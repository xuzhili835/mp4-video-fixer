# MP4视频智能修复工具

一个MP4视频修复工具，自动检测并修复静止画面、画面抽搐、音画不同步等问题。（仅测试于Android的Turmux）

## 能解决什么问题？

### 核心问题诊断
1. **在线vs本地差异** = 容器格式/时间戳兼容性问题
2. **静止画面** = 编码器异常或时间戳重置错误
3. **画面抽搐** = GOP结构损坏 + 时间戳不连续
4. **FFmpeg截断** = moov atom位置错误或时间戳溢出

### 适用症状
- 在线播放正常，下载后本地抽搐
- 画面长时间静止，但音频继续
- 音画不同步
- FFmpeg处理时莫名截断
- 时间戳异常导致播放器卡死

---

## 适用案例

**问题举例：** 收到一个15分钟的视频文件

### 在线观看表现
- 0:00 - 0:30：正常
- 0:28开始：画面静止，音频继续
- 7:20：画面恢复，音画不同步
- 11:00后：音频继续，但声音消失

### 本地播放表现
- 上述问题全部存在
- 画面恢复时（7:20）开始抽搐：画面跳动、撕裂、运动不连贯

### 尝试过的解决方法
- 换多个播放器：无效
- FFmpeg转码：中途截断

---

## 功能特性

✨ **智能检测**
- 自动检测静止画面片段
- 分析容器结构和时间戳问题
- 评估音视频兼容性

🔧 **精准修复**
- 删除静止画面，保留完整音频
- 修复GOP结构，消除画面抽搐
- 标准化编码参数，提升兼容性
- 优化moov atom位置，改善在线播放

📊 **详细报告**
- 实时显示处理进度
- 完整的数据完整性验证
- 音视频时长对比分析

---

## 使用前必读

### 环境要求
- **FFmpeg**: 必须安装 [FFmpeg](https://ffmpeg.org/)
- **Python 3**: 需要 Python 3.6+
- **支持平台**:
  - Linux
  - macOS
  - Windows WSL2 / Git Bash
  - Android Termux

### 快速安装

**Termux (Android):**
```bash
pkg update && pkg upgrade -y
pkg install ffmpeg python -y
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg python3 -y
```

**macOS:**
```bash
brew install ffmpeg python3
```

---

## 快速开始

### 基本用法

```bash
# 最简单用法（自动生成 xxx_fixed.mp4）
python3 fix_video.py input_video.mp4

# 指定输出文件名
python3 fix_video.py input_video.mp4 output_fixed.mp4

# 批量修复当前目录所有视频
for f in *.mp4; do python3 fix_video.py "$f"; done
```

### 修复过程示例

```
============================================================
🔍 完整分析
============================================================
📋 获取信息...
  视频时长: 922.1秒 (15.4分钟)
  音频时长: 522.2秒 (8.7分钟)
  音频编码: aac
  视频编码: h264 (High)
  像素格式: yuv420p
❄️  检测静止段...
  ⚠️ 发现 1 个静止段
    片段1: 0:32-7:12 (400.0秒)
📦 检查容器...
  🔴 moov位置不当（影响在线播放）
  🔴 时间戳异常
🎯 检查兼容性...

🤖 制定方案...
  策略: full_fix

  📊 计算出的有效片段 (2段):
    片段1: 0:00-0:32 (时长: 32.3秒)
    片段2: 7:12-15:22 (时长: 489.8秒)
    总时长: 522.1秒 (8.7分钟)

============================================================
🔧 开始修复
============================================================
  📊 步骤 1/4: 提取完整音频
     ✅ 音频提取成功: 522.2秒 (8.7分钟)

  📊 步骤 2/4: 处理视频片段
     ✅ 片段 1 完成
     ✅ 片段 2 完成

  📊 步骤 3/4: 合并视频片段
     ✅ 视频合并成功

  📊 步骤 4/4: 合并音视频
     📤 处理后视频: 522.2秒 (8.7分钟)
     📤 完整音频:   522.2秒 (8.7分钟)
     📊 音视频对比: ✅ 长度一致

  ✅ 完整修复成功！

============================================================
✅ 完成
============================================================
📊 最终文件时长:
  视频流: 522.2秒 (8.7分钟)
  音频流: 522.2秒 (8.7分钟)
  ✅ 音视频时长一致，应该完美同步

📊 数据完整性检查:
  原始视频: 15.4分钟
  删除静止: 6.7分钟
  预期时长: 8.7分钟
  实际时长: 8.7分钟
  ✅ 数据完整，时长符合预期

💡 建议:
  • 在不同设备/播放器测试播放效果
  • 检查是否还有抽搐或卡顿
  • 验证音画是否同步
```

---

## 技术细节

### 修复策略

脚本会根据检测到的问题自动选择修复策略：

| 策略 | 适用场景 | 处理方式 |
|------|----------|----------|
| `full_fix` | 静止段 + 兼容性问题 | 删除静止段 + 重编码 |
| `remove_freeze` | 只有静止段 | 删除静止段 + 流复制 |
| `fix_compatibility` | 只有兼容性问题 | 重编码修复 |
| `light` | 轻度问题 | 快速优化 |

### 静止检测算法
```python
'-vf', 'freezedetect=n=-60dB:d=2.5'
# n=-60dB: 噪声阈值
# d=2.5: 最小静止时长（秒）
```

### 抽搐修复关键参数
```python
'-vsync', 'cfr'          # 强制恒定帧率
'-g', '30'               # 固定GOP长度
'-sc_threshold', '0'     # 禁用场景检测
'-keyint_min', '15'      # 最小关键帧间隔
'-bf', '2'               # 限制B帧数量
```

### 兼容性优化
```python
'-movflags', '+faststart'  # moov前置
'-pix_fmt', 'yuv420p'      # 标准化像素格式
'-profile:v', 'high'       # 兼容Profile
'-level', '4.0'            # 标准Level
```

---

## 常见问题

### Q1: 找不到ffmpeg错误
确保FFmpeg已正确安装并在PATH中：
```bash
ffmpeg -version  # 检查是否安装
```

### Q2: 找不到python3
```bash
# Termux/Debian
pkg install python -y

# macOS
brew install python3
```

### Q3: 权限被拒绝（Termux）
```bash
termux-setup-storage
```

### Q4: 修复后文件很大
正常现象，重编码会损失压缩效率。可修改脚本中 `-crf 23` 为 `-crf 28` 提高压缩率（数值越大文件越小，质量越低）。

### Q5: 处理速度慢
- 使用 `-preset ultrafast` 可加快速度（文件会变大）
- Termux 可考虑硬件编码（需修改代码）

### Q6: 音频还是不同步
检查输出日志中的"音视频对比"部分：
- 如果显示"长度一致"应该完美同步
- 如果有差异，说明音频或视频被截断

---

## 依赖说明

本项目使用以下外部工具：

- **FFmpeg**: 视频/音频处理引擎
  - 许可证: GPL/LGPL
  - 官网: https://ffmpeg.org
- **Python 3**: 脚本运行环境

本项目代码采用 MIT 许可证发布。

---

## 项目结构

```
mp4-video-fixer/
├── fix_video.py          # 主修复脚本
├── README.md             # 说明文档
├── LICENSE               # MIT许可证
├── requirements.txt      # 依赖说明
└── .gitignore           # Git忽略配置
```

---

## 许可证

MIT License

Copyright (c) 2025 xuzhili835

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## 贡献

欢迎提交 Issue 和 Pull Request！

### 开发者指南
修改代码后请确保：
1. 保持输出格式的一致性
2. 添加适当的验证和错误处理
3. 更新相关文档

---

## 免责声明

本工具仅供学习和个人使用。使用本工具处理视频文件时，请确保你有相关文件的使用权限。作者不对使用本工具造成的任何数据丢失或损坏负责。

建议在处理重要文件前先备份原文件。
