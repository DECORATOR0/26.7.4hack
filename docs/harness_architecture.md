# 世界杯视频解说 Harness 架构说明

## 场景定义

输入一场足球比赛视频，Harness 自动提取证据、识别关键事件、构建事件时间线，并调用 Intern-S2-Preview 生成中文激情解说脚本、字幕和集锦片段清单。

当前默认比赛：

```text
2026 年美加墨世界杯 E 组第 1 轮：德国 7:1 库拉索
```

## 固定 5 阶段

### 1. 视频预处理

目标：把大视频转换成后续阶段可处理的基础材料。

工具：

- OpenCV：读取视频元信息、按时间间隔抽帧、计算运动评分。
- ffmpeg：如果本机安装，则提取音频。

输入：

```text
match.mp4
```

输出：

```text
video_metadata.json
frame_index.json
selected_frames.json
frames/raw/
frames/selected/
audio.wav
audio_peaks.json
```

### 2. 多模态证据提取

目标：汇总后续模型可使用的证据。

工具：

- faster-whisper / whisper：如果安装，则对 `audio.wav` 做 ASR。
- 预留 OCR 工具：后续可接 tesseract 或 PaddleOCR 识别比分牌。

输出：

```text
transcript.json
transcript.txt
evidence.json
```

### 3. 关键事件识别与时间线构建

目标：调用 Intern-S2-Preview，根据比赛信息、关键帧、证据摘要生成结构化事件。

输入：

```text
match_info.json
evidence.json
frames/selected/
```

输出：

```text
events.json
```

约束：

- 不编造球员姓名。
- 最终比分必须是德国 7:1 库拉索。
- 如果模型事件数量和比分不一致，Harness 自动回退到比分一致的兜底时间线。

### 4. 解说脚本生成

目标：调用 Intern-S2-Preview，根据 `events.json` 生成解说脚本。

输出：

```text
commentary.md
```

内容包括：

- 文档说明
- 完整激情解说
- 关键事件时间线
- 60 秒集锦解说
- 字幕/配音使用建议

### 5. 校验与输出

目标：检查事实一致性，并输出可交付文件。

检查项：

- 德国进球数是否为 7。
- 库拉索进球数是否为 1。
- 时间线是否递增。
- 解说稿是否出现最终比分。
- 模型是否遗漏关键事件。

输出：

```text
fact_check.json
subtitles.srt
highlights.json
run_log.md
```

## 为什么这是 Harness

本系统不是一次性 prompt 生成解说，而是阶段化自动流程：

```text
视频 -> 证据 -> 事件 -> 解说 -> 校验 -> 输出
```

每个阶段都有明确输入、输出和失败兜底：

- 工具负责产生证据。
- Intern-S2 负责事件归纳、解说生成和一致性审查。
- Harness 负责调度、缓存、解析、校验和回退。

这符合题面强调的任务拆解、工具调用、上下文管理、结果检查和迭代优化。

