#!/usr/bin/env python3
"""
MP4视频完整修复 - 融合版
解决：在线正常/本地抽搐 + 静止画面 + 兼容性问题
策略：最小化重编码，精准修复
"""

import subprocess
import json
import sys
import tempfile
import shutil
import re
from pathlib import Path

class ComprehensiveFixer:
    def __init__(self, input_video, output_video=None):
        self.input_path = Path(input_video)
        if not self.input_path.exists():
            raise FileNotFoundError(f"文件不存在: {input_video}")
        
        if output_video:
            self.output_path = Path(output_video)
        else:
            self.output_path = self.input_path.parent / f"{self.input_path.stem}_fixed{self.input_path.suffix}"
        
        self.temp_dir = Path(tempfile.mkdtemp(prefix="vfix_"))
        print(f"📁 临时: {self.temp_dir}")
        
        self.issues = {
            'freezes': [],           # 静止段
            'moov_late': False,      # moov位置
            'edit_list': False,      # 编辑列表
            'timestamp_bad': False,  # 时间戳
            'need_reencode': False   # 是否需重编码
        }
        
        self.info = {}
    
    # ==================== 分析 ====================
    
    def analyze(self):
        """完整分析"""
        print("\n" + "="*60)
        print("🔍 完整分析")
        print("="*60)
        
        self._get_info()
        self._check_freezes()
        self._check_container()
        self._check_compatibility()
        self._decide()
        self._show_plan()
    
    def _get_info(self):
        """基本信息"""
        print("📋 获取信息...")
        
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams',
                str(self.input_path)
            ], capture_output=True, text=True, check=True)
            
            data = json.loads(result.stdout)
            v = next((s for s in data['streams'] if s['codec_type'] == 'video'), {})
            
            self.info = {
                'duration': float(data['format'].get('duration', 0)),
                'size_mb': int(data['format'].get('size', 0)) / 1024**2,
                'fps': self._fps(v.get('r_frame_rate', '30/1')),
                'codec': v.get('codec_name', 'unknown'),
                'profile': v.get('profile', 'unknown'),
                'pix_fmt': v.get('pix_fmt', 'unknown')
            }
            
            print(f"  时长: {self.info['duration']:.1f}秒")
            print(f"  编码: {self.info['codec']} ({self.info['profile']})")
            print(f"  像素: {self.info['pix_fmt']}")
            
        except Exception as e:
            print(f"  ⚠️ 失败: {e}")
            self.info = {'duration': 900, 'fps': 30}
    
    def _fps(self, fps_str):
        try:
            n, d = map(int, fps_str.split('/'))
            return n/d if d else 30
        except:
            return 30
    
    def _check_freezes(self):
        """检测静止段（FFmpeg原生）"""
        print("❄️  检测静止段...")
        
        try:
            result = subprocess.run([
                'ffmpeg', '-i', str(self.input_path),
                '-vf', 'freezedetect=n=-60dB:d=2.5',
                '-f', 'null', '-'
            ], capture_output=True, text=True, timeout=60)
            
            freeze = None
            for line in result.stderr.split('\n'):
                if 'freeze_start:' in line:
                    try:
                        t = float(line.split('freeze_start:')[1].strip())
                        freeze = {'start': t}
                    except:
                        pass
                
                elif 'freeze_end:' in line and freeze:
                    try:
                        t = float(line.split('freeze_end:')[1].split()[0])
                        dur = t - freeze['start']
                        if dur >= 3.0:  # 至少3秒
                            self.issues['freezes'].append((freeze['start'], t, dur))
                        freeze = None
                    except:
                        pass
            
            if self.issues['freezes']:
                print(f"  ⚠️ 发现 {len(self.issues['freezes'])} 个静止段")
                for s, e, d in self.issues['freezes'][:2]:
                    print(f"    {self._t(s)}-{self._t(e)} ({d:.1f}秒)")
            else:
                print("  ✅ 无静止段")
                
        except Exception as e:
            print(f"  ⚠️ 检测失败: {e}")
    
    def _check_container(self):
        """检查容器结构"""
        print("📦 检查容器...")
        
        try:
            # 检查moov位置
            with open(self.input_path, 'rb') as f:
                head = f.read(1024*1024)
                moov_pos = head.find(b'moov')
                mdat_pos = head.find(b'mdat')
                
                if moov_pos == -1 or (mdat_pos != -1 and moov_pos > mdat_pos):
                    print("  🔴 moov位置不当（影响在线播放）")
                    self.issues['moov_late'] = True
                else:
                    print("  ✅ moov位置正常")
        except:
            pass
        
        # 检查时间戳
        try:
            result = subprocess.run([
                'ffmpeg', '-v', 'error',
                '-i', str(self.input_path),
                '-f', 'null', '-'
            ], capture_output=True, text=True, timeout=30)
            
            errors = result.stderr.lower()
            if any(x in errors for x in ['timestamp', 'dts', 'pts', 'non-monotonic']):
                print("  🔴 时间戳异常")
                self.issues['timestamp_bad'] = True
            else:
                print("  ✅ 时间戳正常")
        except:
            pass
    
    def _check_compatibility(self):
        """检查播放器兼容性"""
        print("🎯 检查兼容性...")
        
        # 检查像素格式
        if self.info['pix_fmt'] != 'yuv420p':
            print(f"  ⚠️ 像素格式非标准: {self.info['pix_fmt']}")
            self.issues['need_reencode'] = True
        
        # 检查profile
        if self.info['profile'] not in ['High', 'Main', 'Baseline']:
            print(f"  ⚠️ Profile可能不兼容: {self.info['profile']}")
            self.issues['need_reencode'] = True
    
    def _decide(self):
        """决策修复策略"""
        print("\n🤖 制定方案...")
        
        # 评估严重程度
        has_freezes = len(self.issues['freezes']) > 0
        has_container_issue = self.issues['moov_late'] or self.issues['timestamp_bad']
        need_reencode = self.issues['need_reencode']
        
        if has_freezes and (has_container_issue or need_reencode):
            self.strategy = 'full_fix'
            self.steps = [
                '1. 删除静止段',
                '2. 修复容器结构',
                '3. 标准化编码（修复抽搐）'
            ]
        
        elif has_freezes:
            self.strategy = 'remove_freeze'
            self.steps = [
                '1. 删除静止段',
                '2. 优化容器'
            ]
        
        elif has_container_issue or need_reencode:
            self.strategy = 'fix_compatibility'
            self.steps = [
                '1. 修复容器结构',
                '2. 标准化编码（修复抽搐）'
            ]
        
        else:
            self.strategy = 'light'
            self.steps = ['1. 轻度优化']
        
        print(f"  策略: {self.strategy}")
    
    def _show_plan(self):
        """显示计划"""
        print("\n" + "="*60)
        print("📋 修复计划")
        print("="*60)
        
        for step in self.steps:
            print(f"  {step}")
    
    # ==================== 修复 ====================
    
    def repair(self):
        """执行修复"""
        print("\n" + "="*60)
        print("🔧 开始修复")
        print("="*60)
        
        try:
            if self.strategy == 'full_fix':
                return self._full_fix()
            elif self.strategy == 'remove_freeze':
                return self._remove_freeze()
            elif self.strategy == 'fix_compatibility':
                return self._fix_compat()
            else:
                return self._light_fix()
        except Exception as e:
            print(f"\n❌ 失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _full_fix(self):
        """完整修复：删除静止段 + 标准化编码"""
        print("\n🔨 完整修复...")
        
        # 计算有效段
        segments = self._calc_segments()
        
        if not segments:
            print("  ❌ 无有效片段")
            return False
        
        # 如果只有一段且是全部，直接重编码
        if len(segments) == 1 and segments[0]['start'] == 0:
            print("  单段重编码（修复抽搐）...")
            return self._reencode_for_compatibility(
                str(self.input_path),
                str(self.output_path)
            )
        
        # 多段：提取、编码、合并
        print(f"  多段处理 ({len(segments)}段)...")
        
        seg_files = []
        for i, seg in enumerate(segments, 1):
            print(f"  处理 {i}/{len(segments)}...")
            
            seg_file = self.temp_dir / f"s{i}.mp4"
            
            # 提取并重编码（确保一致性）
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(seg['start']),
                '-i', str(self.input_path),
                '-t', str(seg['end'] - seg['start']),
                
                # 标准化编码（修复抽搐）
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-profile:v', 'high',
                '-pix_fmt', 'yuv420p',
                
                # 关键：防止抽搐
                '-g', '30',              # 固定GOP
                '-keyint_min', '15',
                '-sc_threshold', '0',    # 无场景检测
                '-bf', '2',              # 适度B帧
                '-vsync', 'cfr',         # 恒定帧率
                
                # 音频
                '-c:a', 'aac',
                '-b:a', '128k',
                
                str(seg_file)
            ]
            
            self._run(cmd)
            
            if seg_file.exists():
                seg_files.append(seg_file)
        
        if not seg_files:
            return False
        
        # 合并
        print("  🔗 合并...")
        return self._concat(seg_files)
    
    def _remove_freeze(self):
        """只删除静止段"""
        print("\n✂️ 删除静止段...")
        
        segments = self._calc_segments()
        
        if len(segments) == 1:
            # 只有一段，copy即可
            cmd = [
                'ffmpeg', '-y',
                '-i', str(self.input_path),
                '-c', 'copy',
                '-movflags', '+faststart',
                str(self.output_path)
            ]
            self._run(cmd)
            return self.output_path.exists()
        
        # 多段提取合并
        seg_files = []
        for i, seg in enumerate(segments, 1):
            seg_file = self.temp_dir / f"s{i}.mp4"
            
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(seg['start']),
                '-i', str(self.input_path),
                '-t', str(seg['end'] - seg['start']),
                '-c', 'copy',
                str(seg_file)
            ]
            
            self._run(cmd)
            if seg_file.exists():
                seg_files.append(seg_file)
        
        return self._concat(seg_files)
    
    def _fix_compat(self):
        """修复兼容性（不删除静止段）"""
        print("\n🔧 修复兼容性...")
        
        # 分步修复
        temp1 = self.temp_dir / "step1.mp4"
        temp2 = self.temp_dir / "step2.mp4"
        
        # 步骤1：修复容器
        if self.issues['moov_late'] or self.issues['timestamp_bad']:
            print("  1. 修复容器...")
            
            cmd = [
                'ffmpeg', '-y',
                '-i', str(self.input_path),
                '-c', 'copy',
                '-movflags', '+faststart',
                '-avoid_negative_ts', 'make_zero',
                str(temp1)
            ]
            
            self._run(cmd)
            current = temp1 if temp1.exists() else self.input_path
        else:
            current = self.input_path
        
        # 步骤2：标准化编码（修复抽搐）
        print("  2. 标准化编码...")
        return self._reencode_for_compatibility(str(current), str(self.output_path))
    
    def _light_fix(self):
        """轻度优化"""
        print("\n⚡ 轻度优化...")
        
        cmd = [
            'ffmpeg', '-y',
            '-i', str(self.input_path),
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'copy',
            '-movflags', '+faststart',
            str(self.output_path)
        ]
        
        self._run(cmd)
        return self.output_path.exists()
    
    def _reencode_for_compatibility(self, input_file, output_file):
        """针对抽搐问题的重编码（关键函数）"""
        cmd = [
            'ffmpeg', '-y',
            '-i', input_file,
            
            # 视频：标准化 + 防抽搐
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-profile:v', 'high',
            '-level', '4.0',
            '-pix_fmt', 'yuv420p',
            
            # 关键参数：修复抽搐
            '-g', '30',              # 每30帧一个I帧
            '-keyint_min', '15',     # 最小关键帧间隔
            '-sc_threshold', '0',    # 禁用场景检测
            '-bf', '2',              # B帧数量
            '-refs', '3',            # 参考帧
            '-vsync', 'cfr',         # 恒定帧率（重要！）
            '-r', str(int(self.info['fps'])),  # 明确帧率
            
            # 音频
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            
            # 容器
            '-movflags', '+faststart',
            '-f', 'mp4',
            
            output_file
        ]
        
        self._run(cmd)
        return Path(output_file).exists()
    
    def _calc_segments(self):
        """计算有效段（排除静止段）"""
        if not self.issues['freezes']:
            return [{'start': 0, 'end': self.info['duration']}]
        
        segments = []
        pos = 0.0
        
        for s, e, _ in sorted(self.issues['freezes']):
            if s > pos + 0.5:
                segments.append({'start': pos, 'end': s})
            pos = max(pos, e)
        
        if pos < self.info['duration'] - 0.5:
            segments.append({'start': pos, 'end': self.info['duration']})
        
        return segments
    
    def _concat(self, seg_files):
        """合并片段"""
        list_file = self.temp_dir / "list.txt"
        
        with open(list_file, 'w') as f:
            for seg in seg_files:
                f.write(f"file '{seg.absolute()}'\n")
        
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file),
            '-c', 'copy',
            '-movflags', '+faststart',
            str(self.output_path)
        ]
        
        self._run(cmd)
        return self.output_path.exists()
    
    def _run(self, cmd):
        """运行命令"""
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        
        for line in p.stdout:
            if 'time=' in line:
                m = re.search(r'time=(\d+:\d+:\d+)', line)
                if m:
                    print(f"\r    {m.group(1)}", end='', flush=True)
        
        p.wait()
        print()
    
    def _t(self, sec):
        """时间格式"""
        m, s = divmod(int(sec), 60)
        return f"{m}:{s:02d}"
    
    def cleanup(self):
        """清理"""
        try:
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
                print("🧹 清理完成")
        except:
            pass
    
    def verify(self):
        """验证"""
        print("\n" + "="*60)
        print("✅ 完成")
        print("="*60)
        
        if not self.output_path.exists():
            print("❌ 文件不存在")
            return False
        
        size = self.output_path.stat().st_size / 1024**2
        print(f"输出: {self.output_path}")
        print(f"大小: {size:.2f} MB")
        
        # 检查参数
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'stream=codec_name,profile,pix_fmt',
                '-of', 'json',
                str(self.output_path)
            ], capture_output=True, text=True)
            
            info = json.loads(result.stdout)
            
            for s in info.get('streams', []):
                if s.get('codec_type') == 'video':
                    print(f"\n参数:")
                    print(f"  编码: {s.get('codec_name')}")
                    print(f"  Profile: {s.get('profile')}")
                    print(f"  像素: {s.get('pix_fmt')}")
                    
                    if s.get('pix_fmt') == 'yuv420p':
                        print("  ✅ 标准化成功")
        except:
            pass
        
        print("\n建议:")
        print("• 上传到Telegram测试在线播放")
        print("• 下载后本地测试是否还抽搐")
        
        return True

# ==================== 主程序 ====================

def main():
    print("="*60)
    print("🎬 MP4完整修复工具")
    print("   解决: 静止画面 + 在线正常/本地抽搐")
    print("="*60)
    
    if len(sys.argv) < 2:
        print("\n用法: python3 script.py <输入> [输出]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not Path(input_file).exists():
        print(f"❌ 不存在: {input_file}")
        sys.exit(1)
    
    fixer = ComprehensiveFixer(input_file, output_file)
    
    try:
        fixer.analyze()
        
        print("\n" + "="*60)
        resp = input("继续? (Y/n): ").strip().lower()
        if resp and resp not in ['y', 'yes', '']:
            print("取消")
            return
        
        success = fixer.repair()
        
        if success:
            fixer.verify()
        
    except KeyboardInterrupt:
        print("\n\n中断")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
    finally:
        fixer.cleanup()

if __name__ == "__main__":
    main()