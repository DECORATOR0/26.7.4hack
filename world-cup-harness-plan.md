# 世界杯视频解说 Harness 实施说明

## 1. 题目目标

本项目选择赛道 B 的「世界杯视频解说 Harness」方向。

目标是围绕题面指定视频「2026 年美加墨世界杯 E 组第 1 轮德国 7:1 大胜库拉索」，构建一个可运行的 Agentic Harness，完成：

- 解说脚本生成
- 关键事件识别
- 风格化激情解说
- 可用于配音、字幕、集锦讲解的结构化输出

注意：评审重点不是单纯写出一篇解说稿，而是展示一套可执行、可反馈、可验证、可复现的任务完成系统。

## 2. 必须交付

基础交付物：

- 可运行源码
- `README.md`，说明安装、配置、运行方式
- 标准 API 配置入口：
  - `INTERN_S2_API_BASE`
  - `INTERN_S2_API_KEY`
- Harness 输出结果：
  - `outputs/transcript.txt`
  - `outputs/events.json`
  - `outputs/commentary.md`
  - `outputs/subtitles.srt`
  - `outputs/run_log.md`
- Presentation 材料：
  - Harness 设计思路
  - 实现方案
  - 运行结果
  - 结果分析
  - 团队分工和贡献比例
  - Intern-S2-Preview 能力不足与提升空间分析

加分交付物：

- 可现场演示 Demo
- 演示录屏或快进回放模式
- Skill / Memory / Sandbox 中至少一个高级机制
- 精彩片段剪辑清单或自动剪辑结果

## 3. 最小可行版本

先做一个能完整跑通的 MVP，命令形式如下：

```bash
python run.py --video data/match.mp4 --out outputs/
```

MVP 流程：

```text
输入比赛视频
-> 提取音频
-> ASR 转写
-> 视频抽帧和切片
-> 识别关键事件
-> 生成比赛事件时间线
-> 调用 Intern-S2-Preview 生成解说
-> 自检比分、队名、事件顺序
-> 输出 markdown/json/srt
```

第一版不追求复杂 UI，先保证命令行稳定可跑。

## 4. 推荐目录结构

```text
.
├── README.md
├── run.py
├── requirements.txt
├── .env.example
├── data/
│   └── match.mp4
├── src/
│   ├── config.py
│   ├── intern_client.py
│   ├── harness.py
│   ├── tools/
│   │   ├── video_tools.py
│   │   ├── audio_tools.py
│   │   ├── asr_tools.py
│   │   └── subtitle_tools.py
│   ├── agents/
│   │   ├── event_extractor.py
│   │   ├── timeline_builder.py
│   │   ├── commentary_writer.py
│   │   ├── fact_checker.py
│   │   └── formatter.py
│   └── schemas/
│       └── outputs.py
├── skills/
│   └── football_commentary.md
├── memory/
│   └── match_style_notes.md
└── outputs/
    ├── transcript.txt
    ├── events.json
    ├── commentary.md
    ├── subtitles.srt
    └── run_log.md
```

## 5. Harness 架构

核心是一个 Agent Loop，不是一次性调用模型。

```text
User Task
  |
  v
Harness Orchestrator
  |
  +-- Video Tool: 抽帧、切片、音频提取
  +-- ASR Tool: 语音转写
  +-- EventExtractor Agent: 候选事件识别
  +-- TimelineBuilder Agent: 时间线合并和排序
  +-- CommentaryWriter Agent: 生成激情解说
  +-- FactChecker Agent: 事实一致性检查
  +-- Formatter Agent: 输出 markdown/json/srt
  |
  v
Final Outputs
```

每一步都要写入中间产物，避免 Demo 时因为某一步失败导致全链路不可展示。

## 6. Agent 拆分

### EventExtractor

职责：

- 从转写文本、抽帧结果、片段时间戳中提取关键事件
- 输出候选事件列表

输出字段建议：

```json
{
  "minute": "12'",
  "timestamp": "00:12:35",
  "team": "Germany",
  "player": "unknown",
  "event_type": "goal",
  "description": "德国队完成一次进球",
  "confidence": 0.82,
  "evidence": ["transcript line 45", "frame 00:12:35"]
}
```

### TimelineBuilder

职责：

- 合并重复事件
- 按时间排序
- 校准比分变化
- 标记不确定事件

必须保证最终比分和题面一致：德国 7:1 库拉索。

### CommentaryWriter

职责：

- 根据事件时间线生成完整解说稿
- 支持不同风格：
  - 央视式专业解说
  - 激情现场解说
  - 短视频集锦解说

第一版建议默认使用「激情但不胡编」的风格。

### FactChecker

职责：

- 检查球队名称是否一致
- 检查比分是否从 0:0 推进到 7:1
- 检查进球数是否匹配
- 检查事件顺序是否倒置
- 对高风险幻觉打标

### Formatter

职责：

- 生成 `commentary.md`
- 生成 `events.json`
- 生成 `subtitles.srt`
- 生成 `run_log.md`

## 7. 工具设计

第一版工具够用即可：

- `extract_audio(video) -> audio.wav`
- `transcribe(audio) -> transcript.txt`
- `sample_frames(video, interval=5) -> frames/`
- `split_video(video, segment_seconds=60) -> clips/`
- `write_json(data, path)`
- `write_srt(segments, path)`

工具调用要有：

- 超时控制
- 错误返回
- 日志记录
- 中间文件缓存

## 8. Intern-S2-Preview 接入要求

最终演示和提交版本的核心大模型调用必须使用 Intern-S2-Preview。

配置方式：

```bash
INTERN_S2_API_BASE=https://chat.intern-ai.org.cn
INTERN_S2_API_KEY=your_api_key_here
INTERN_S2_MODEL=intern-s2-preview
```

代码中不要写死 API Key。主办方会用新的 API Key 替换运行。

真实 API Key 只允许放在本机 `.env` 或系统环境变量里，不能写入 `README.md`、项目说明文档、演示文稿或任何需要提交/共享的文件。`.env` 已在 `.gitignore` 中忽略。

建议封装一个 `intern_client.py`，对外只暴露：

```python
client.chat(messages, tools=None, temperature=0.3)
```

这样后续替换接口格式时，业务代码不用大改。

## 9. Demo 策略

现场演示不要依赖完整长视频实时跑完。

建议支持两种模式：

```bash
python run.py --video data/match.mp4 --out outputs/
python run.py --video data/match.mp4 --out outputs/ --fast-demo
```

普通模式完整跑流程。

`--fast-demo` 使用已缓存的：

- 音频转写
- 抽帧结果
- 候选事件

只现场展示「事件整理 -> 生成解说 -> 自检 -> 输出」这几步，稳定性更高。

## 10. 团队分工

建议分工：

- 成员 A：视频处理和 ASR
  - `ffmpeg`
  - 抽帧
  - 音频提取
  - 字幕生成

- 成员 B：事件识别和时间线
  - `events.json` schema
  - 关键事件识别
  - 比分校验

- 成员 C：Intern-S2 接入和 Agent Loop
  - API client
  - prompt 设计
  - tool call 流程
  - retry 和日志

- 成员 D：Demo、README、Presentation
  - Web/CLI 展示
  - 运行说明
  - 结果展示
  - 评审答辩材料

如果成员少，就优先合并 D 到 C，A 和 B 保持独立。

## 11. 时间安排

### T + 2 小时

- 视频下载完成
- 项目目录建好
- `run.py` 能跑通空流程
- API Key 配置方式确定
- 输出目录结构确定

### T + 6 小时

- 完成音频提取、抽帧、ASR
- 得到 `transcript.txt`
- 人工或半自动整理第一版 `events.json`

### T + 10 小时

- Intern-S2 生成第一版 `commentary.md`
- FactChecker 能检查比分和事件顺序
- 输出 `subtitles.srt`

### T + 16 小时

- 做 Demo 模式
- 优化解说风格
- 补齐日志和 README

### T + 20 小时

- 准备 Presentation
- 录制一版演示视频
- 整理 Intern-S2 能力分析

### 最后 2 小时

- 冻结代码
- 清理 API Key
- 按提交要求打包
- 全流程重跑一次

## 12. 评分点对应策略

可运行 Harness：

- 用 `run.py` 和 `README.md` 证明。

API 可替换：

- 用 `.env.example` 和环境变量读取证明。

完整输出结果：

- 用 `events.json`、`commentary.md`、`subtitles.srt` 证明。

Harness 设计能力：

- 展示 Agent Loop、工具调用、中间产物、自检重试。

结果质量：

- 解说要连贯、有现场感，但不能虚构关键事实。

加分项：

- `--fast-demo`
- `skills/football_commentary.md`
- `memory/match_style_notes.md`
- 自动生成精彩片段清单

## 13. 风险和兜底

视频下载失败：

- 立即联系志愿者或出题人。
- 同时先用 baseline 附件和人工事件表开发 Harness。

ASR 质量差：

- 允许人工修正 `transcript.txt`。
- 重点展示 Harness 能消费转写文本和视频证据。

长视频处理太慢：

- 使用切片处理。
- Demo 使用缓存。

Intern-S2 输出不稳定：

- 降低 temperature。
- 拆小任务。
- 加 FactChecker。
- 对失败步骤做 retry。

关键事件识别不准：

- 第一版可以半自动：模型给候选，人工校对一次。
- 交付时强调 Harness 支持人机协同校验。

## 14. 立即执行清单

- 下载题面视频
- 创建项目骨架
- 准备 `.env.example`
- 写 `intern_client.py`
- 写 `run.py` 空流程
- 用 `ffmpeg` 跑通音频提取和抽帧
- 生成第一版 `transcript.txt`
- 整理第一版 `events.json`
- 调 Intern-S2 生成 `commentary.md`
- 加 FactChecker
- 生成 `subtitles.srt`
- 写 README 和 Presentation 提纲

## 15. Presentation 必讲内容

建议讲 5 页：

1. 任务和目标：世界杯视频到结构化解说输出。
2. Harness 架构：Agent Loop、工具、中间产物、自检。
3. 关键实现：视频处理、事件识别、Intern-S2 解说生成。
4. 结果展示：事件时间线、解说稿、字幕、Demo。
5. 反思分析：Intern-S2 的优势、不足、改进空间、团队分工。

Intern-S2 能力分析可以从这些角度写：

- 优势：长文本组织能力、中文解说风格生成、结构化输出能力。
- 不足：长视频原生理解不足、细粒度时间戳依赖外部工具、事实一致性需要校验器约束。
- 提升空间：更强多模态视频理解、更稳定 tool calling、更好的长上下文事件追踪。

## 16. 资料优先级

当前任务只做「世界杯视频解说 Harness」，资料不需要全看，按下面顺序处理。

### 16.1 附件优先级

必须下载和阅读：

- 题面提供的整场比赛视频：这是主输入，没有视频就无法做真实 Harness。
- 附件4：世界杯解说脚本 baseline。它是同类输出参考，用来学习结构、颗粒度、语气和交付格式。

可以跳过或只快速扫一眼：

- 附件1：代码漏洞检测 baseline，和世界杯题无关。
- 附件2：PPT 生成 baseline，和世界杯题无关。
- 附件3：世界模型综述 baseline，和世界杯题无关。

结论：附件侧先只拿「视频 + 附件4」。附件1、2、3 不进入当前开发主线。

### 16.2 附录优先级

必须看：

- 附录1：Harness 设计介绍。用于 Presentation 里解释你们不是简单调用模型，而是做了 Agent Loop、工具调用、上下文管理、结果检查。
- 附录2：Intern-S2-Preview API 使用说明。用于确认 API base、鉴权方式、模型名、请求格式。
- 附录4：Intern-S2-Preview 工具调用接口示例。用于决定要不要把视频处理、ASR、事件提取等工具注册成 tool call。
- 附录7：参考 baseline。它会指向附件4，证明你们知道 baseline 是什么，并能说明你们比 baseline 强在哪里。

建议看：

- 附录3：Intern-S2-Preview 接入 Claude Code 示例。它不是最终项目必需，但可以帮助理解 API 接入方式、环境变量配置和调用格式。如果时间紧，放在附录2之后看。

可以跳过：

- 附录5：MinerU API 使用说明。主要给 PPT 和论文综述方向用，世界杯视频题基本不用。
- 附录6：Sciverse API 使用说明。主要给 PPT 和论文综述方向用，世界杯视频题基本不用。

### 16.3 当前阅读顺序

建议现在按这个顺序：

1. 下载比赛视频。
2. 下载并阅读附件4 baseline。
3. 阅读附录2，确认 Intern-S2-Preview API 怎么调。
4. 阅读附录4，确认 tool calling 怎么接。
5. 快速阅读附录3，参考接入示例。
6. 回头扫附录1，把 Harness 设计语言补进 README 和 Presentation。
7. 最后看附录7，明确 baseline 对比口径。

不要在附件1、附件2、附件3、附录5、附录6 上消耗时间。

### 16.4 附件4 baseline 怎么用

附件4不是硬性提交模板，而是世界杯解说方向的输出参考。不要照抄它的内容，也不需要逐项复刻它的所有章节。

附件4里真正值得保留的核心结构：

- 第一部分：完整解说脚本。对应题目要求的「解说脚本生成」和「风格化激情解说」。
- 第二部分：详细关键事件识别。对应题目要求的「关键事件识别」。
- 第五部分：字幕脚本。对应题目中提到的「可用于配音、字幕的结构化输出」。
- 第六部分：集锦讲解脚本。对应题目中提到的「可用于集锦讲解的结构化输出」。

可以作为加分但不必第一版实现：

- 第三部分：多语言解说。题面没有强制要求，适合作为展示 Intern-S2 风格迁移和多语言能力的加分项。
- 第四部分：配音脚本。可以用字幕或精简版解说替代，后续再单独生成。
- 第七部分：技术统计分析。如果没有可靠视频识别或人工统计依据，不要硬编详细数据。
- 第八部分：制作使用说明。可以放到 README，而不是塞进最终解说结果里。

我们自己的第一版输出建议是：

```text
outputs/
├── commentary.md       # 完整激情解说脚本，必须有
├── events.json         # 关键事件时间线，必须有
├── subtitles.srt       # 字幕/配音可用，建议有
├── highlights.json     # 集锦片段清单，建议有
└── run_log.md          # Harness 运行日志，必须有
```

如果时间充足，再额外生成：

```text
outputs/
├── commentary_short.md     # 60 秒/90 秒短视频解说
├── commentary_multi.md     # 英文或多语言版本
└── analysis.md             # Intern-S2 结果分析和不足
```

关键原则：附件4是「参考它的组织方式」，不是「必须做成同样的大而全文档」。评审更关心你们的 Harness 能不能从视频输入稳定产出这些内容，并能解释每个中间结果是怎么来的。

## 17. 底层框架选择：是否使用 LangChain

结论：可以用，但不要把整个项目强绑定在 LangChain 上。对本题更稳的方案是「自研轻量 Harness + 可选 LangGraph 编排 + 自己封装 Intern-S2 Client」。

推荐架构：

```text
run.py
  |
  v
Harness Orchestrator
  |
  +-- 可选：LangGraph 管状态流转
  +-- 自研 tools：ffmpeg / ASR / 抽帧 / 文件读写
  +-- 自研 intern_client.py：直接调用 Intern-S2 API
  |
  v
outputs/
```

### 17.1 为什么不建议全量依赖 LangChain

本题流程相对确定：

```text
视频 -> 音频/抽帧 -> 转写 -> 事件识别 -> 时间线 -> 解说生成 -> 校验 -> 输出
```

这更像一个可控工作流，而不是完全开放式 Agent。全量使用 LangChain Agent 可能带来：

- 调试链路变长，出错时不容易定位是框架、prompt、tool schema 还是 Intern-S2 接口问题。
- Intern-S2 API 虽然兼容 OpenAI SDK 的部分方法，但仍在适配中，直接走 `requests` 或 `openai` SDK 更可控。
- 黑客松时间短，框架抽象越重，Demo 风险越高。

### 17.2 什么时候可以用 LangChain

如果队友熟 LangChain，可以把它用在局部：

- Prompt 模板管理
- Tool schema 描述
- 结构化输出校验
- 简单 agent loop 原型

但核心 API 调用仍建议保留 `intern_client.py` 自己封装，避免后续 LangChain provider 适配不一致。

### 17.3 什么时候用 LangGraph

如果想展示更像「Harness 工程」的能力，LangGraph 比纯 LangChain Agent 更适合本题。

可以把每个节点写成固定步骤：

```text
extract_media
-> transcribe_audio
-> extract_events
-> build_timeline
-> write_commentary
-> fact_check
-> format_outputs
```

这样 Presentation 里可以清楚展示：

- 状态如何流转
- 哪一步调用工具
- 哪一步调用 Intern-S2
- 哪一步失败可以重试
- 哪些中间结果被缓存

### 17.4 最终建议

第一版不要引入 LangChain，先用 Python 函数把完整流程跑通。

第二版如果时间够：

- 引入 LangGraph 做流程编排。
- 保留自研 `intern_client.py`。
- 不强依赖 LangChain Agent 自动决策。

一句话：LangChain 可以作为辅助库，LangGraph 可以作为编排层，但 Intern-S2 调用和关键流程控制要掌握在自己代码里。

## 18. 视频模态处理细节

视频、音频、抽帧、OCR、关键事件定义和 Intern-S2 多模态输入实测结果，见：

```text
video-modality-pipeline-notes.md
```

## 17. 视频输入策略

根据当前 Intern Chat API 文档，多模态 `messages.content` 支持的是：

- `text`
- `image_url`

`image_url` 可以是公网可访问图片 URL，也可以是图片的 base64 编码。文档没有给出 `video_url`、`video_file` 或直接上传 `.mp4` 的请求格式。

因此本项目不要把整场 `.mp4` 直接传给 Intern-S2-Preview。正确策略是：

```text
本地视频
-> ffmpeg / OpenCV 抽帧
-> 音频提取
-> ASR 转写
-> 构造关键片段图片帧 + 转写文本 + 候选事件
-> 交给 Intern-S2-Preview 做事件整理、解说生成、自检
```

也就是说，Intern-S2-Preview 在本项目中的输入应主要是：

- 关键帧图片
- 音频转写文本
- 候选事件列表
- 比赛元信息
- 已整理的时间线

视频理解能力由 Harness 的工具层完成，不依赖模型 API 直接读取完整视频。
