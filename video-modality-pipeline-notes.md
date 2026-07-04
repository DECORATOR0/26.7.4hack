# 视频模态处理与关键事件识别方案

## 1. API 模态能力实测结论

测试时间：2026-07-04

使用模型：`intern-s2-preview`

测试结论：

| 能力 | 结果 | 说明 |
| --- | --- | --- |
| 文本输入 | 可用 | `/chat/completions` 正常返回 |
| 图片 URL 输入 | 可用 | `image_url` + 公网 URL 正常识别 |
| 图片 base64 输入 | 可用 | 本地图片转 `data:image/...;base64,...` 后可识别 |
| 多图输入 | 可用 | 同一轮消息可传多张 `image_url` |
| 音频直接输入 | 不作为主方案 | 测试 `audio_url` 返回 prompt processing error；官方文档也未给音频消息格式 |
| 视频直接输入 | 不作为主方案 | 测试 `video_url` 返回 400；官方文档主要给 `text/image_url` 多模态格式 |

工程结论：

```text
视频不能直接作为主输入喂给 Intern-S2。
音频也不要直接喂给 Intern-S2。

正确方案：
视频 -> 工具抽帧/切片 -> 图片
音频 -> ASR 工具 -> 文本
OCR -> 比分/时间/队名

再把图片 + ASR 文本 + OCR 结果 + 候选时间段交给 Intern-S2 做事件理解和解说生成。
```

## 2. 视频上来先做什么预处理

视频预处理不是为了美化视频，而是为了把整场比赛拆成可处理的证据材料。

输入：

```text
data/match.mp4
```

输出：

```text
outputs/preprocess/
├── metadata.json
├── audio.wav
├── frames_coarse/
├── clips/
├── scoreboard_crops/
└── frame_index.json
```

建议处理项：

1. 读取视频元信息
   - 时长
   - fps
   - 分辨率
   - 编码格式

2. 提取音频
   - 输出 `audio.wav`
   - 后续给 ASR 使用

3. 粗抽帧
   - 每 2 秒或 5 秒抽一帧
   - 用于全局扫描比赛走势和候选片段

4. 视频切片
   - 每 30 秒或 60 秒切一段
   - 方便局部重跑、缓存和 Demo

5. 比分牌区域裁剪
   - 对每个粗抽帧裁剪左上角/上方比分区域
   - 用于 OCR 识别比分、比赛时间、队名

## 3. 是否需要锐化和增强

不建议对整段视频做锐化或美化，收益低、耗时高。

只建议对 OCR 相关区域做局部增强：

```text
scoreboard crop
-> resize 放大 2x 或 3x
-> grayscale 灰度化
-> contrast enhance 增强对比度
-> threshold 二值化，可选
-> OCR
```

增强目标不是让画面更好看，而是提高比分牌、比赛时间、队名的识别率。

如果 OCR 效果已经够用，这一步可以跳过。

## 4. 音频怎么处理

Intern-S2 当前方案里不直接吃音频。音频先走 ASR 工具。

流程：

```text
match.mp4
-> ffmpeg extract audio.wav
-> ASR
-> transcript.json
```

`transcript.json` 建议格式：

```json
[
  {
    "start": "00:12:31",
    "end": "00:12:38",
    "text": "射门！球进了！德国队再次扩大比分！"
  }
]
```

ASR 的作用：

- 找进球、射门、角球、犯规等关键词
- 辅助判断候选精彩片段
- 给解说生成提供语言线索
- 和 OCR 比分变化互相校验

可选工具：

- `faster-whisper`
- `openai-whisper`
- 其他可用 ASR 服务

## 5. 时间戳怎么转换

所有阶段统一使用秒数作为内部表示，再在输出阶段转成人类可读格式。

内部表示：

```json
{
  "start_sec": 751.2,
  "end_sec": 789.6
}
```

展示表示：

```json
{
  "start": "00:12:31",
  "end": "00:13:09"
}
```

比赛分钟表示：

```json
{
  "match_minute": "13'"
}
```

转换规则：

```text
video timestamp: 00:12:31
-> seconds: 751
-> match minute: floor(751 / 60) + 1 = 13'
```

如果视频有片头、广告、入场仪式，需要设置偏移量：

```json
{
  "kickoff_offset_sec": 95.0
}
```

比赛分钟计算：

```text
match_time_sec = video_time_sec - kickoff_offset_sec
match_minute = floor(match_time_sec / 60) + 1
```

## 6. 视频怎么给模型看

不要把整场比赛所有帧都发给模型。

采用两层抽帧：

### 6.1 粗抽帧

目的：低成本扫描全场。

策略：

```text
每 2 秒或 5 秒抽一帧
```

产物：

```text
outputs/preprocess/frames_coarse/
outputs/preprocess/frame_index.json
```

用于：

- 找比分牌变化
- 找庆祝画面
- 找回放画面
- 找画面切换密集区域

### 6.2 细抽帧

目的：只对候选精彩片段做精细理解。

策略：

```text
候选片段前后各扩 5-10 秒
每 0.5 秒或 1 秒抽一帧
```

示例：

```text
候选片段：00:12:31 - 00:12:38
扩展片段：00:12:21 - 00:12:48
细抽帧：每 1 秒 1 帧
```

产物：

```text
outputs/events/candidate_001/frames_fine/
```

再把少量关键帧转成 base64 或图片 URL，连同 ASR/OCR 证据一起交给 Intern-S2。

## 7. 关键事件怎么定义

题面没有严格定义“关键事件”的算法标准，只要求完成「关键事件识别」并基于视频生成解说。因此关键事件需要我们自己定义。

建议定义为：

> 对比赛走势、比分变化、观赛情绪或集锦价值有明显影响的事件。

第一版关键事件类型：

| 类型 | 是否必须 | 说明 |
| --- | --- | --- |
| goal | 必须 | 进球，最核心事件 |
| near_goal | 建议 | 击中门框、门线救险、绝佳机会 |
| shot | 可选 | 有威胁射门 |
| save | 可选 | 门将精彩扑救 |
| foul_card | 可选 | 严重犯规、黄牌、红牌 |
| substitution | 可选 | 换人，若影响比赛走势可记录 |
| kickoff_halftime_final | 建议 | 开场、中场、终场节点 |
| celebration_replay | 辅助 | 庆祝和回放通常用于确认进球，不一定作为独立事件 |

世界杯解说题的第一版应该优先进球事件：

```text
德国 7 个进球
库拉索 1 个进球
开场
半场
终场
若干高光射门/扑救
```

不要为了事件多而硬编。没有证据的球员名、助攻方式、技术统计不要写死。

## 8. 候选精彩片段怎么挖掘

候选片段不应该完全靠大模型盲看。先用工具和规则筛，再让模型理解。

可用信号：

1. OCR 比分变化
   - 最强信号
   - 比如比分从 `2-0` 变成 `3-0`

2. ASR 关键词
   - 进球
   - 射门
   - 漂亮
   - 扑救
   - 黄牌
   - 犯规
   - 绝佳机会
   - goal
   - shoots
   - scores

3. 音频峰值
   - 欢呼声突然升高
   - 解说语速和音量变化

4. 画面模式
   - 球员庆祝
   - 慢动作回放
   - 比分牌特写
   - 教练/观众反应

5. 镜头切换密度
   - 进球后通常出现快速切换、回放、多角度镜头

候选片段格式：

```json
{
  "candidate_id": "C001",
  "start_sec": 741.0,
  "end_sec": 792.0,
  "signals": [
    "scoreboard_changed",
    "asr_goal_keyword",
    "audio_peak",
    "celebration_frames"
  ],
  "confidence": 0.88
}
```

## 9. 事件理解 Agent 输入输出

输入：

```json
{
  "match_info": {
    "home_team": "Germany",
    "away_team": "Curacao",
    "expected_score": "7-1"
  },
  "candidate": {
    "start": "00:12:21",
    "end": "00:12:48"
  },
  "asr_snippets": [],
  "ocr_snapshots": [],
  "frames": []
}
```

输出：

```json
{
  "event_id": "E001",
  "event_type": "goal",
  "team": "Germany",
  "match_minute": "13'",
  "video_timestamp": "00:12:35",
  "score_after": "1-0",
  "description": "德国队完成一次进球，随后出现庆祝和比分牌变化。",
  "evidence": [
    "scoreboard changed from 0-0 to 1-0",
    "ASR contains goal keyword",
    "frames show celebration"
  ],
  "confidence": 0.86,
  "uncertain_fields": ["player_name", "assist_type"]
}
```

## 10. 推荐 5 阶段总流程

```text
1. 视频预处理
   - 提取音频
   - 粗抽帧
   - 切片
   - 裁剪比分牌区域

2. 多模态证据提取
   - ASR 转写
   - OCR 识别比分/时间
   - 音频峰值检测
   - 关键帧描述

3. 关键事件识别与时间线构建
   - 筛候选精彩片段
   - 细抽帧
   - Intern-S2 理解候选片段
   - 合并重复事件
   - 校准比分变化

4. 解说脚本生成
   - 完整解说
   - 精简配音脚本
   - 字幕
   - 集锦讲解脚本

5. 校验与输出
   - 检查最终比分
   - 检查进球数量
   - 检查时间顺序
   - 检查是否编造球员名
   - 输出最终文件
```

## 11. 本机工具状态

当前本机未检测到：

```text
ffmpeg
ffprobe
```

后续要跑真实视频处理，需要先安装 ffmpeg，或把 ffmpeg 可执行文件加入 PATH。

## 12. 对外表述

可以在方案/PPT 中这样写：

> 我们没有将整场视频直接交给大模型端到端生成解说，而是先通过工具将视频拆解为音频、关键帧、比分牌 OCR、ASR 转写和候选片段等结构化证据。Intern-S2-Preview 主要负责候选片段理解、事件归纳、解说生成和事实校验。这样既保留大模型的语义理解与生成能力，又通过阶段化中间产物保证系统稳定、可解释、可验证。

