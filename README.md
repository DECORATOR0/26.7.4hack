# World Cup Commentary Harness

面向足球比赛视频的固定阶段 Agentic Harness。输入一段比赛 MP4，系统自动完成视频预处理、多模态证据提取、关键事件识别、解说脚本生成、事实校验和格式化输出。

本项目当前默认任务是：

```text
2026 年美加墨世界杯 E 组第 1 轮：德国 7:1 库拉索
```

## 快速运行

1. 安装依赖：

```bash
python -m pip install -r requirements.txt
```

2. 准备 `.env`：

```env
INTERN_S2_API_BASE=https://chat.intern-ai.org.cn/api/v1
INTERN_S2_API_KEY=your_api_token_here
INTERN_S2_MODEL=intern-s2-preview
```

3. 运行：

```bash
python run.py --video "德国_库拉索.mp4" --out outputs
```

更快的本地调试：

```bash
python run.py --video "德国_库拉索.mp4" --out outputs --frame-interval 180 --max-frames 24 --vision-frames 6
```

## 输出结果

```text
outputs/
├── audio.wav                 # 如果本机安装 ffmpeg，会自动生成
├── video_metadata.json
├── frame_index.json
├── evidence.json
├── events.json
├── commentary.md
├── subtitles.srt
├── highlights.json
├── fact_check.json
└── run_log.md
```

## Harness 阶段

```text
1. 视频预处理
   - 读取视频元信息
   - 按间隔抽帧
   - 对抽帧做运动评分
   - 使用 imageio-ffmpeg 提取音频

2. 多模态证据提取
   - 汇总视频元信息、抽帧索引、关键帧、音频/ASR/OCR 可用性
   - 如果有 whisper/faster-whisper，尝试 ASR
   - 如果有 tesseract，后续可接 OCR

3. 关键事件识别与时间线构建
   - 调用 Intern-S2-Preview
   - 基于比赛信息、证据摘要和关键帧生成 `events.json`

4. 解说脚本生成
   - 调用 Intern-S2-Preview
   - 基于 `events.json` 生成完整解说、字幕和集锦结构

5. 校验与输出
   - 本地检查比分、进球数、时间顺序
   - 调用 Intern-S2-Preview 生成结果分析
   - 写出最终文件
```

## 设计原则

- 固定阶段骨架，避免端到端黑盒 Agent 不稳定。
- 每阶段都有中间产物，方便评审检查和现场演示。
- 模型只能基于前序证据生成，不允许编造球员姓名和不存在的进球。
- 真实 API Key 只放 `.env` 或系统环境变量，不写进提交文件。

## 可选增强

本项目不强依赖这些工具，但安装后会自动增强：

- `faster-whisper` 或 `openai-whisper`：从音频转写原始解说。
- `tesseract` + `pytesseract`：识别比分牌和比赛时间。
- `LangGraph`：后续可把 5 个阶段包装成状态图节点。
