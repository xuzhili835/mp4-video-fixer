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
            a = next((s for s in data['streams'] if s['codec_type'] == 'audio'), {})

            self.info = {
                'duration': float(data['format'].get('duration', 0)),
                'audio_duration': float(a.get('duration', data['format'].get('duration', 0))) if a else float(data['format'].get('duration', 0)),
                'size_mb': int(data['format'].get('size', 0)) / 1024**2,
                'fps': self._fps(v.get('r_frame_rate', '30/1')),
                'codec': v.get('codec_name', 'unknown'),
                'profile': v.get('profile', 'unknown'),
                'pix_fmt': v.get('pix_fmt', 'unknown'),
                'audio_codec': a.get('codec_name', 'unknown') if a else 'none'
            }

            print(f"  视频时长: {self.info['duration']:.1f}秒 ({self.info['duration']/60:.1f}分钟)")
            if a:
                print(f"  音频时长: {self.info['audio_duration']:.1f}秒 ({self.info['audio_duration']/60:.1f}分钟)")
                print(f"  音频编码: {self.info['audio_codec']}")
            else:
                print(f"  ⚠️ 未检测到音频流")
            print(f"  视频编码: {self.info['codec']} ({self.info['profile']})")
            print(f"  像素格式: {self.info['pix_fmt']}")

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
                for i, (s, e, d) in enumerate(self.issues['freezes'][:3], 1):
                    print(f"    片段{i}: {self._t(s)}-{self._t(e)} ({d:.1f}秒)")
                if len(self.issues['freezes']) > 3:
                    print(f"    ... 共{len(self.issues['freezes'])}个")
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

        # 第一步：提取完整音频（不删除静止段对应的音频）
        print(f"\n  📊 步骤 1/4: 提取完整音频")
        print(f"     从原始视频提取完整音频流...")
        audio_file = self.temp_dir / "audio.aac"

        # 显示音频时长信息
        audio_dur = self.info.get('audio_duration', self.info['duration'])
        print(f"     预期音频时长: {audio_dur:.1f}秒 ({audio_dur/60:.1f}分钟)")

        cmd = [
            'ffmpeg', '-y',
            '-i', str(self.input_path),
            '-vn',  # 不处理视频
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            str(audio_file)
        ]
        self._run(cmd)

        if not audio_file.exists():
            print(f"     ❌ 音频提取失败")
            return False

        # 检查提取的音频时长
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'json',
                str(audio_file)
            ], capture_output=True, text=True)
            dur = float(json.loads(result.stdout)['format']['duration'])
            print(f"     ✅ 音频提取成功: {dur:.1f}秒 ({dur/60:.1f}分钟)")
        except:
            print(f"     ✅ 音频提取成功（无法验证时长）")

        # 第二步：提取并重编码视频片段（删除静止画面）
        print(f"\n  📊 步骤 2/4: 处理视频片段 ({len(segments)}段)")
        print(f"     删除静止画面，保留有效视频内容...")

        seg_files = []
        for i, seg in enumerate(segments, 1):
            start_t = self._t(seg['start'])
            end_t = self._t(seg['end'])
            dur = seg['end'] - seg['start']
            print(f"\n     片段 {i}/{len(segments)}: {start_t}-{end_t} (时长{dur:.1f}秒)")

            seg_file = self.temp_dir / f"s{i}.mp4"

            # 使用 -to 而不是 -t，避免截断音频
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(seg['start']),
                '-i', str(self.input_path),
                '-to', str(seg['end']),  # 使用 -to 指定结束时间

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

                '-an',  # 不提取音频（后面单独合并）

                str(seg_file)
            ]

            self._run(cmd)

            if seg_file.exists():
                seg_files.append(seg_file)
                print(f"     ✅ 片段 {i} 完成")
            else:
                print(f"     ❌ 片段 {i} 失败")

        if not seg_files:
            print(f"\n     ❌ 没有成功提取任何片段")
            return False

        # 第三步：合并视频片段
        print(f"\n  📊 步骤 3/4: 合并视频片段")
        print(f"     将{len(seg_files)}个视频片段合并...")
        video_merged = self.temp_dir / "video_merged.mp4"

        list_file = self.temp_dir / "list.txt"
        with open(list_file, 'w') as f:
            for seg in seg_files:
                f.write(f"file '{seg.absolute()}'\n")

        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file),
            '-c', 'copy',  # 视频直接复制
            str(video_merged)
        ]

        self._run(cmd)

        if not video_merged.exists():
            print(f"     ❌ 视频合并失败")
            return False

        print(f"     ✅ 视频合并成功")

        # 第四步：合并视频和完整音频
        print(f"\n  📊 步骤 4/4: 合并音视频")
        print(f"     将处理后的视频与完整音频合并...")

        # 检查视频时长
        video_dur = 0
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'json',
                str(video_merged)
            ], capture_output=True, text=True)
            video_dur = float(json.loads(result.stdout)['format']['duration'])
        except:
            pass

        print(f"     📤 处理后视频: {video_dur:.1f}秒 ({video_dur/60:.1f}分钟)")
        print(f"     📤 完整音频:   {audio_dur:.1f}秒 ({audio_dur/60:.1f}分钟)")
        print(f"     📊 音视频对比: {'✅ 长度一致' if abs(video_dur - audio_dur) < 1 else f'⚠️ 差异{abs(video_dur - audio_dur):.1f}秒'}")
        print(f"     📌 合并策略: -shortest (以最短的流为准)")

        # 计算原始删除的静止段时长
        removed_duration = 0
        for s, e, _ in self.issues['freezes']:
            removed_duration += (e - s)

        print(f"\n  📊 处理总结:")
        print(f"     原始视频: {self.info['duration']:.1f}秒 ({self.info['duration']/60:.1f}分钟)")
        print(f"     删除静止: {removed_duration:.1f}秒 ({removed_duration/60:.1f}分钟)")
        print(f"     保留视频: {self.info['duration'] - removed_duration:.1f}秒 ({(self.info['duration'] - removed_duration)/60:.1f}分钟)")
        print(f"     最终输出: {min(video_dur, audio_dur):.1f}秒 ({min(video_dur, audio_dur)/60:.1f}分钟)")

        if abs(video_dur - audio_dur) < 1:
            print(f"\n     ✅ 音视频时长匹配，应该完美同步")
        elif video_dur > audio_dur:
            print(f"\n     ⚠️ 视频比音频长{video_dur - audio_dur:.1f}秒，尾部将无声音")
        else:
            print(f"\n     ⚠️ 音频比视频长{audio_dur - video_dur:.1f}秒，部分音频被截断")

        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_merged),
            '-i', str(audio_file),
            '-c:v', 'copy',  # 视频直接复制
            '-c:a', 'aac',   # 音频直接复制
            '-b:a', '128k',
            '-ar', '44100',
            '-map', '0:v:0',  # 使用视频文件的视频流
            '-map', '1:a:0',  # 使用音频文件的音频流
            '-shortest',     # 以最短的流为准
            '-movflags', '+faststart',
            str(self.output_path)
        ]

        self._run(cmd)

        if self.output_path.exists():
            print(f"\n  ✅ 完整修复成功！")
        else:
            print(f"\n  ❌ 完整修复失败")

        return self.output_path.exists()
    
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
                '-c:v', 'copy',         # 视频直接复制
                '-c:a', 'aac',          # 音频重编码并重置时间戳
                '-b:a', '128k',
                '-ar', '44100',
                '-af', 'asetpts=PTS-STARTPTS',  # 重置音频时间戳到0
                '-fflags', '+genpts',           # 生成新的PTS
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

        # 调试信息：显示计算出的片段
        print(f"\n  📊 计算出的有效片段 ({len(segments)}段):")
        total_duration = 0
        for i, seg in enumerate(segments, 1):
            dur = seg['end'] - seg['start']
            total_duration += dur
            print(f"    片段{i}: {self._t(seg['start'])}-{self._t(seg['end'])} (时长: {dur:.1f}秒)")
        print(f"    总时长: {total_duration:.1f}秒 ({total_duration/60:.1f}分钟)")

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
            '-c:v', 'copy',         # 视频直接复制
            '-c:a', 'aac',          # 音频重编码以确保时间戳连续
            '-b:a', '128k',
            '-ar', '44100',
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
        print(f"输出文件: {self.output_path.name}")
        print(f"文件大小: {size:.2f} MB")

        # 检查最终文件的音视频时长
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format=duration:stream=codec_type,duration',
                '-of', 'json',
                str(self.output_path)
            ], capture_output=True, text=True)

            info = json.loads(result.stdout)
            format_dur = float(info['format'].get('duration', 0))

            print(f"\n📊 最终文件时长:")

            video_dur = 0
            audio_dur = 0

            for s in info.get('streams', []):
                if s.get('codec_type') == 'video':
                    video_dur = float(s.get('duration', format_dur))
                    print(f"  视频流: {video_dur:.1f}秒 ({video_dur/60:.1f}分钟)")
                elif s.get('codec_type') == 'audio':
                    audio_dur = float(s.get('duration', format_dur))
                    print(f"  音频流: {audio_dur:.1f}秒 ({audio_dur/60:.1f}分钟)")

            if video_dur > 0 and audio_dur > 0:
                if abs(video_dur - audio_dur) < 0.5:
                    print(f"\n  ✅ 音视频时长一致，应该完美同步")
                elif video_dur > audio_dur:
                    print(f"\n  ⚠️ 视频比音频长 {video_dur - audio_dur:.1f}秒")
                else:
                    print(f"\n  ⚠️ 音频比视频长 {audio_dur - video_dur:.1f}秒")

        except Exception as e:
            print(f"  ⚠️ 无法获取时长信息: {e}")

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
                    print(f"\n📊 视频参数:")
                    print(f"  编码: {s.get('codec_name')}")
                    print(f"  Profile: {s.get('profile')}")
                    print(f"  像素: {s.get('pix_fmt')}")

                    if s.get('pix_fmt') == 'yuv420p':
                        print(f"  ✅ 像素格式标准化成功")
        except:
            pass

        # 数据完整性检查
        print(f"\n📊 数据完整性检查:")
        original_video = self.info['duration']
        removed_duration = sum((e - s) for s, e, _ in self.issues['freezes'])
        expected_duration = original_video - removed_duration

        print(f"  原始视频: {original_video/60:.1f}分钟")
        print(f"  删除静止: {removed_duration/60:.1f}分钟")
        print(f"  预期时长: {expected_duration/60:.1f}分钟")

        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'json',
                str(self.output_path)
            ], capture_output=True, text=True)
            actual_duration = float(json.loads(result.stdout)['format']['duration'])

            print(f"  实际时长: {actual_duration/60:.1f}分钟")

            if abs(actual_duration - expected_duration) < 5:
                print(f"  ✅ 数据完整，时长符合预期")
            elif abs(actual_duration - expected_duration) < 30:
                print(f"  ⚠️ 时长略有差异，可能正常")
            else:
                print(f"  ❌ 时长差异较大，请检查")
        except:
            pass

        print("\n💡 建议:")
        print("  • 在不同设备/播放器测试播放效果")
        print("  • 检查是否还有抽搐或卡顿")
        print("  • 验证音画是否同步")

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