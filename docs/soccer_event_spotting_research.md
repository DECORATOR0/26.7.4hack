# 足球长视频事件定位调研

## 1. 问题定义

我们要做的不是普通图像分类，也不是识别单个短 clip 的动作，而是：

```text
输入一整场足球转播长视频
-> 找到值得解说的事件发生时间
-> 给出事件类别和证据
-> 生成解说脚本
```

在论文和比赛里，这类问题通常叫：

```text
Action Spotting
```

它和普通 Action Recognition 的区别：

- Action Recognition：给一段短视频，判断里面是什么动作。
- Temporal Action Localization：找一段动作的开始和结束。
- Action Spotting：在长视频里找某个事件发生的单点时间戳。

足球事件很多是瞬间事件，例如进球、黄牌、换人、角球、任意球。用单点时间戳比用完整起止区间更符合转播解说需求。

## 2. 核心数据集和 benchmark

### 2.1 SoccerNet

资料：

- Paper: [SoccerNet: A Scalable Dataset for Action Spotting in Soccer Videos](https://arxiv.org/abs/1804.04527)
- Project: [SoccerNet official page](https://silviogiancola.github.io/SoccerNet/)
- Code: [SilvioGiancola/SoccerNet-code](https://github.com/SilvioGiancola/SoccerNet-code)

关键信息：

- 数据包含 500 场完整足球转播比赛。
- 总时长约 764 小时。
- 早期标注三类事件：
  - Goal
  - Yellow/Red Card
  - Substitution
- 目标是在长视频中定位稀疏事件。

对我们的启发：

```text
第一版最稳的事件类别就是 goal / card / substitution。
```

这不是随便选的，而是 SoccerNet 最早就把这三类作为核心 action spotting 类别。

### 2.2 SoccerNet-v2

资料：

- Paper: [SoccerNet-v2: A Dataset and Benchmarks for Holistic Understanding of Broadcast Soccer Videos](https://arxiv.org/abs/2011.13367)
- Project: [SoccerNet-v2 page](https://silviogiancola.github.io/SoccerNetv2/)

关键信息：

- 在原 SoccerNet 基础上扩展到约 30 万条标注。
- 不只做 action spotting，还包括：
  - Camera shot segmentation
  - Camera shot boundary detection
  - Replay grounding
- Action spotting 类别扩展到 17 类。

SoccerNet 官方 Action Spotting 任务列出的 17 类包括：

```text
Penalty
Kick-off
Goal
Substitution
Offside
Shots on target
Shots off target
Clearance
Ball out of play
Throw-in
Foul
Indirect free-kick
Direct free-kick
Corner
Yellow card
Red card
Yellow->red card
```

资料页：

- [SoccerNet Action Spotting task](https://www.soccer-net.org/tasks/action-spotting)

对我们的启发：

我们不需要全做 17 类。第一版可以从其中选视觉特征更明显、对解说价值更高的类别：

```text
Goal
Penalty
Corner
Direct/Indirect free-kick
Yellow card
Red card
Substitution
Replay
Foul / Referee dispute
```

不建议第一版强做：

```text
Shots on target
Shots off target
Clearance
Ball out of play
Throw-in
Offside
```

这些对视觉时序和规则理解要求更高，容易误判。

### 2.3 SoccerNet Ball Action Spotting

资料：

- Task: [SoccerNet Ball Action Spotting](https://www.soccer-net.org/tasks/ball-action-spotting)
- Code: [SoccerNet/sn-spotting](https://github.com/SoccerNet/sn-spotting)

关键信息：

Ball Action Spotting 更细，关注 12 类与球相关的动作：

```text
Pass
Drive
Header
High Pass
Out
Cross
Throw In
Shot
Ball Player Block
Player Successful Tackle
Free Kick
Goal
```

它比 SoccerNet Action Spotting 更难，因为事件密度更高，时间定位要求更严格，通常要到 1 秒级。

对我们的启发：

```text
不要第一版做 pass / drive / tackle / cross 这种细粒度动作。
```

我们现在的目标是生成解说主线，不是做专业技战术统计。可以把难分类的进攻片段统一归为：

```text
attack_highlight
```

## 3. 代表性论文和方法

### 3.1 CALF: Context-Aware Loss Function

资料：

- Paper: [A Context-Aware Loss Function for Action Spotting in Soccer Videos](https://arxiv.org/abs/1912.01326)
- Code: [cioppaanthony/context-aware-loss](https://github.com/cioppaanthony/context-aware-loss)

核心思想：

足球事件不是只看一个帧。事件前后有上下文，例如：

```text
进球前：进攻推进、射门
进球点：球入网或庆祝开始
进球后：庆祝、回放、比分变化
```

CALF 的重点是利用事件周围的 temporal context，而不是只盯单帧。

对我们的启发：

候选事件不要只给一张图。每个候选片段至少给：

```text
center - 10s
center - 5s
center
center + 5s
center + 10s
```

也就是“事件前、中、后”一起交给模型判断。

### 3.2 NetVLAD++ / Temporally-aware pooling

资料：

- SoccerNet-v2 page 上列出：[Temporally-Aware Feature Pooling for Action Spotting in Video Broadcasts](https://silviogiancola.github.io/SoccerNetv2/)

核心思想：

普通 pooling 把事件前后上下文混在一起，容易丢失时间方向。NetVLAD++ 把动作发生前和发生后的上下文分开建模。

对我们的启发：

给 Intern-S2 的候选片段不应该是无序图片堆，而要明确标注：

```text
before frames
center frames
after frames
```

Prompt 里也要写清：

```text
请比较事件前后画面变化，判断是否发生了 goal / card / substitution / replay 等事件。
```

### 3.3 Dense Detection Anchors / Spivak

资料：

- Code: [yahoo/spivak](https://github.com/yahoo/spivak)
- Model page: [yahoo-inc/spivak-action-spotting-soccernet](https://huggingface.co/yahoo-inc/spivak-action-spotting-soccernet)

关键信息：

Spivak 是一个运动视频分析工具包，包含 SoccerNet action spotting 和 camera shot segmentation。它实现的 Dense Detection Anchors 方法在 SoccerNet Challenge 2022 中表现很好，并且有预训练模型。

对我们的启发：

如果要更像标准 CV 方案，可以参考它的工程结构：

```text
视频 -> 特征提取 -> 时间序列模型 -> action timestamps
```

但它依赖 TensorFlow 和 SoccerNet 特征/模型，黑客松里直接接入成本可能偏高。

适合用途：

- 作为调研和 Presentation 背书。
- 后续如果有时间，可尝试跑预训练模型或复用它的结果格式。

### 3.4 E2E-Spot / MBS

资料：

- Code: [ZJLAB-AMMI/E2E-Spot-MBS](https://github.com/ZJLAB-AMMI/E2E-Spot-MBS)

关键信息：

这是 SoccerNet 2023 Ball Action Spotting 的方案，基于 E2E-Spot 做模型集成，报告里提到在测试阶段达到较高 mAP@1。

它的流程大致是：

```text
视频帧化
-> 训练多个 E2E-Spot 变体
-> 模型集成
-> 输出高精度 ball action spotting
```

对我们的启发：

这类方法适合训练型比赛，不适合我们 24 小时内直接上。

但它再次证明一件事：

```text
足球事件定位的主流路线是先把长视频变成帧序列，再用时间模型定位事件。
```

### 3.5 T-DEED

资料：

- Challenge report: [SoccerNet 2024 Challenges Results](https://arxiv.org/html/2409.10587v1)
- DevKit: [SoccerNet/sn-teamspotting](https://github.com/SoccerNet/sn-teamspotting)

关键信息：

T-DEED 是 2024 Ball Action Spotting 相关任务里的强 baseline。报告里描述它使用 2D backbone 提取局部时空特征，再用 temporal encoder-decoder 做时间建模和高分辨率预测。

对我们的启发：

如果不训练模型，我们可以借鉴它的思想，而不是复刻它：

```text
不要只看单帧；
把候选片段作为短时间窗口；
用前后帧判断事件；
保留时间分辨率；
最后输出 timestamp。
```

### 3.6 SoccerNet-Caption

资料：

- Paper: [SoccerNet-Caption: Dense Video Captioning for Soccer Broadcasts Commentaries](https://arxiv.org/abs/2304.04565)
- Code: [SoccerNet/sn-caption](https://github.com/SoccerNet/sn-caption)
- Task: [SoccerNet Dense Video Captioning](https://www.soccer-net.org/tasks/dense-video-captioning)

关键信息：

这个方向和我们最像。它不是只定位事件，而是：

```text
定位足球动作时间戳
-> 生成对应的自然语言解说/评论
```

论文公开了约 3.7 万条带时间戳的足球文字解说，覆盖 715.9 小时比赛。它的 baseline 是两阶段：

```text
action spotting module -> captioning module
```

对我们的启发：

我们的 Harness 应该明确采用两阶段：

```text
事件定位/结构化 -> 解说生成
```

这比“直接给视频生成整篇解说”更符合已有研究路线。

### 3.7 Replay Grounding

资料：

- Task: [SoccerNet Replay Grounding](https://www.soccer-net.org/tasks/replay-grounding)
- Code: [SoccerNet/sn-grounding](https://github.com/SoccerNet/sn-grounding)

关键信息：

Replay Grounding 是找到回放镜头对应的真实比赛时间点。官方任务说明里强调，回放通常对应更重要的动作，因此可以用于自动集锦生产。

对我们的启发：

回放是非常强的视觉信号。即使我们不识别球轨迹，只要检测到：

```text
Replay 画面 / 慢动作 / 多角度重复
```

就可以把它作为高优先级候选片段。回放前后通常就是进球、犯规、争议或绝佳机会。

## 4. 开源项目清单

### 4.1 SoccerNet/sn-spotting

链接：

- [SoccerNet/sn-spotting](https://github.com/SoccerNet/sn-spotting)

用途：

- SoccerNet Action Spotting / Ball Action Spotting 官方 DevKit。
- 包含 benchmark 方法。
- 包含数据格式、评测格式和 baseline 代码。

我们怎么用：

- 参考输出 JSON 组织方式。
- 参考 action spotting 的类别定义。
- 不建议当前直接大规模训练。

### 4.2 yahoo/spivak

链接：

- [yahoo/spivak](https://github.com/yahoo/spivak)

用途：

- 运动视频分析工具包。
- 支持 SoccerNet action spotting 和 camera shot segmentation。
- 有 SoccerNet 2022 强方法和预训练模型。

我们怎么用：

- 可作为“标准 CV action spotting 路线”的参考。
- 如果后续时间足够，可尝试加载预训练模型做事件候选。

### 4.3 SoccerNet/sn-teamspotting

链接：

- [SoccerNet/sn-teamspotting](https://github.com/SoccerNet/sn-teamspotting)

用途：

- 2025 Team Ball Action Spotting DevKit。
- 任务不只识别动作，还要识别是哪一队执行动作。

我们怎么用：

- 参考“team/action 组合标签”的思路。
- 当前不建议实现队伍归属细分类，除非 OCR/比分牌/球衣颜色稳定。

### 4.4 ZJLAB-AMMI/E2E-Spot-MBS

链接：

- [ZJLAB-AMMI/E2E-Spot-MBS](https://github.com/ZJLAB-AMMI/E2E-Spot-MBS)

用途：

- SoccerNet 2023 Ball Action Spotting 方案。
- 强调帧化、端到端模型、模型集成。

我们怎么用：

- 作为后续训练型方案参考。
- 当前不建议直接接入，因为依赖和训练成本偏高。

### 4.5 SoccerNet/sn-caption

链接：

- [SoccerNet/sn-caption](https://github.com/SoccerNet/sn-caption)

用途：

- 足球转播 dense video captioning 官方代码。
- 目标是生成带时间戳的足球解说文本。

我们怎么用：

- 参考“先定位事件，再生成文本”的两阶段结构。
- 参考 caption 输出格式。

### 4.6 SoccerNet/sn-grounding

链接：

- [SoccerNet/sn-grounding](https://github.com/SoccerNet/sn-grounding)

用途：

- Replay grounding 官方代码。
- 包含回放任务的评估和可视化工具。

我们怎么用：

- 把 replay 作为关键事件候选信号。
- 对自动集锦生成有用。

### 4.7 Baidu Soccernet Features

链接：

- [baidu-research/Soccernet-features](https://github.com/baidu-research/Soccernet-features)

用途：

- 提供 SoccerNet 下游任务使用的视频特征提取/微调代码。
- SoccerNet action spotting/replay grounding 里常用预提取特征路线。

我们怎么用：

- 当前不直接接。
- 作为“提特征再做时间模型”的参考。

## 5. 这些研究怎么指导我们的实现

### 5.1 不要全视频喂 VLM

论文和 benchmark 的共同路线都是：

```text
长视频 -> 帧/特征序列 -> 时间模型/候选片段 -> 事件时间戳
```

不是：

```text
整场视频所有帧 -> 大模型直接看完
```

因此我们应该坚持：

```text
本地粗筛候选片段
-> 只把候选片段给 Intern-S2
```

### 5.2 第一版事件类别要克制

建议第一版事件集合：

```text
goal_or_celebration
replay
corner
free_kick
penalty
card
substitution
referee_dispute
attack_highlight
halftime
fulltime
unknown
```

原因：

- SoccerNet 早期核心类就是 goal / card / substitution。
- SoccerNet-v2 扩展类里 penalty / free-kick / corner 对解说有价值。
- Replay grounding 证明 replay 对集锦和重要事件非常关键。
- attack_highlight 作为兜底，避免硬判射正、扑救、门框。

### 5.3 候选片段要带前后文

借鉴 CALF / NetVLAD++ / T-DEED：

```text
不要单帧识别事件。
每个候选片段至少给 before / center / after。
```

推荐：

```text
每个候选片段 4-8 张图
每批 3-5 个候选片段
每批总图数控制在 20-30 张以内
```

### 5.4 回放是强信号

SoccerNet-v2 单独定义 replay grounding，说明回放本身很有价值。

我们的候选筛选应该提高这些片段权重：

```text
慢动作
多角度
Replay 标识
转播特效
同一动作重复出现
```

即使不能准确判断动作类型，也可以标成：

```text
replay 或 high_value_highlight
```

### 5.5 输出应该分两层

借鉴 SoccerNet-Caption：

```text
visual_events.json      # 事件定位和分类
commentary.md           # 基于事件生成解说
```

不要让模型直接从图片生成整篇解说。先有事件结构，再生成文本。

## 6. 推荐给我们项目的落地方案

### 6.1 阶段 1：粗抽帧

```text
每 5 秒抽 1 帧
生成 frame_index.json
```

只在本地使用，不进模型。

### 6.2 阶段 2：候选筛选

计算：

```text
motion_score
scene_change_score
grass_ratio_change
overlay_change
closeup_score
```

选 Top N：

```text
Top 30-60 候选中心帧
```

合并相邻候选：

```text
center - 15s 到 center + 20s
相近片段合并
```

输出：

```text
candidate_segments.json
```

### 6.3 阶段 3：候选片段密抽帧

每个候选片段抽：

```text
start
center - 5s
center
center + 5s
end
```

输出：

```text
candidate_frames/
```

### 6.4 阶段 4：Intern-S2 视觉分类

统一分类器：

```text
EventClassifier
```

输入：

```text
候选片段元数据
候选片段 4-8 张图
固定事件标签定义
```

输出：

```json
{
  "segment_id": "C012",
  "event_type": "goal_or_celebration",
  "timestamp": "00:31:25",
  "confidence": 0.78,
  "visual_evidence": [
    "多名球员拥抱",
    "画面切到近景",
    "疑似进球后庆祝"
  ],
  "commentary_value": "high"
}
```

### 6.5 阶段 5：事件合并和脚本生成

相近事件合并：

```text
同类事件，间隔 < 30s，合并成一个
replay 紧跟 goal_or_celebration，则作为该事件证据
```

再输出：

```text
events.json
commentary.md
subtitles.srt
highlights.json
```

## 7. 对 Presentation 的说法

可以这样讲：

> 我们参考 SoccerNet 系列中 Action Spotting 的定义，将足球长视频中的关键事件定位建模为单时间戳事件检测问题。不同于直接把整场视频喂给大模型，我们采用两阶段方案：先通过本地视觉规则从全视频中筛选候选片段，再调用 Intern-S2 对候选片段进行事件分类和解说生成。这个设计借鉴了 CALF 和 SoccerNet-Caption 的思想，即事件判断必须依赖前后文，并且解说生成应建立在结构化事件时间线之上。

## 8. 当前最值得借鉴的结论

1. SoccerNet 证明足球长视频事件定位是成熟 benchmark，核心任务叫 Action Spotting。
2. 早期最稳类别是 goal / card / substitution。
3. SoccerNet-v2 扩展到 17 类，但我们第一版不应该全做。
4. Ball Action Spotting 对球动作很细，难度高，不适合第一版直接追。
5. CALF、NetVLAD++、T-DEED 都说明事件必须看前后文，不能只看单帧。
6. Replay 是自动集锦的重要信号，应该作为候选筛选的高权重特征。
7. SoccerNet-Caption 的两阶段结构正好对应我们的 Harness：先定位事件，再生成解说。

## 9. 识别精度和方法细节

### 9.1 SoccerNet-v2 17 类 Action Spotting 的精度

SoccerNet-v2 论文 Table 2 给了公开代码方法在 17 类 action spotting 上的 Average-mAP。

其中 CALF 是论文里整体最好的公开 baseline：

```text
SoccerNet-v2 overall Average-mAP: 40.7
Shown actions Average-mAP:       42.1
Unshown actions Average-mAP:     29.0
```

重点类别的 CALF Average-mAP：

```text
Goal:              72.2
Corner:            71.8
Ball out of play:  63.9
Throw-in:          56.4
Foul:              53.0
Clearance:         51.6
Substitution:      47.3
Direct free-kick:  43.5
Yellow card:       41.7
Indirect free-kick:41.5
Penalty:           30.6
Shots on target:   26.6
Shots off target:  27.3
Offside:           25.7
Yellow->red card:   0.7
Red card:           0.7
```

这个结果对我们很关键：

- 角球和进球确实比较好抓。
- 出界、边线球、犯规、解围也能抓，但对解说价值不一定高。
- 射正、射偏、越位的识别分数明显低，不适合作为第一版核心事件。
- 点球分数不高，可能因为样本少且形态不稳定。
- 红牌、黄转红几乎不可用，主要是测试集中样本极少。

AudioVid 在部分事件上更强，因为它加入了同步音频特征：

```text
AudioVid overall SoccerNet-v2 Average-mAP: 39.9
AudioVid Corner:                         66.0
AudioVid Substitution:                   54.0
AudioVid Goal:                           69.7
AudioVid Penalty:                        52.1
```

论文也明确提到，音频对 shown instances 和一些带哨声前后文的动作有帮助。

### 9.2 它们是 AI 识别，还是图像规则识别

Action spotting 主流不是简单图像规则，而是深度学习时序模型。

典型流程：

```text
视频
-> 按 fps 抽帧
-> 用 CNN/视频模型提取每帧特征，比如 ResNet / I3D / C3D
-> 将一段时间窗口的特征输入时序模型
-> 输出每个时间点/窗口属于某类 action 的置信度
-> NMS 后得到事件 timestamp
```

SoccerNet-v2 论文里的几个 baseline：

```text
MaxPool / NetVLAD:
  对 20 秒 ResNet 特征做 temporal pooling，
  分类窗口内是否包含动作，
  测试时用滑窗 + NMS 变成 action timestamp。

AudioVid:
  使用 20 秒 ResNet 视频特征 + VGGish 音频特征，
  两种特征拼接后分类。

CALF:
  处理 2 分钟 ResNet 特征 chunk，
  包含时空特征提取、temporal segmentation、action spotting 模块，
  用 context-aware loss 学习事件前后文。
```

这些都是 AI/深度学习方法，不是“看到角旗就规则判断角球”的简单 CV。

但它们也不是现在这种大语言模型直接看图生成答案，而是：

```text
训练好的足球事件时序检测模型
```

### 9.3 角球是怎么定义和识别的

SoccerNet-v2 对事件标注是单时间戳，不是一个时间段。

论文里对 corner 的标注定义很具体：

```text
corner 标注为最后一帧射门/开球动作，也就是球员脚和球最后接触的那一帧。
```

模型本身不会显式写规则：

```text
如果画面里有角旗 -> corner
```

它是从大量标注数据中学习角球前后文：

```text
角旗区画面
禁区内球员站位
转播镜头切换
球员助跑
球被开出后禁区争顶
```

然后在时间线上输出一个 corner 置信度峰值。

对我们的 Harness，可以借鉴成更工程化的混合方案：

```text
本地规则先筛：
  是否有角旗/底线区域/禁区多人站位/镜头切到角球区

Intern-S2 再确认：
  给候选片段前后 5-8 张图，
  让模型判断是不是 corner，
  如果不确定就输出 unknown。
```

### 9.4 任意球、点球、牌、换人的难度判断

结合 SoccerNet-v2 数字和视觉形态：

```text
corner:
  论文分数高，视觉形态明确，第一版值得做。

goal_or_celebration:
  论文 goal 分数高，且对解说最重要，必须做。

substitution:
  分数中等，视觉上可能有场边牌/字幕条，值得做。

yellow_card:
  分数中等，牌本身小，但裁判特写和球员围裁判可做候选。

direct/indirect free-kick:
  分数中等，有人墙/定点球信号，值得尝试。

penalty:
  视觉上看似好抓，但论文里 CALF 分数不高；如果没有 OCR/字幕/音频，容易和单刀、任意球混淆。

red_card / yellow->red:
  论文分数极低，主要样本太少；第一版不要单独承诺高精度。

shots on/off target:
  论文分数低，且需要球轨迹和连续动作理解；第一版不要细分。
```

### 9.5 Ball Action Spotting 的精度

Ball Action Spotting 和 SoccerNet-v2 17 类 action spotting 不一样。

它更细，关注球相关动作：

```text
2023: Pass, Drive
2024: Pass, Drive, Header, High Pass, Out, Cross, Throw In, Shot,
      Ball Player Block, Player Successful Tackle, Free Kick, Goal
```

2023 年 Ball Action Spotting leaderboard：

```text
1st Ruslan Baikulov:
  mAP@1 = 86.47
  tight Average-mAP = 87.91

Baseline PTS:
  mAP@1 = 62.72
  tight Average-mAP = 71.21
```

2024 年扩展到 12 类后更难：

```text
T-DEED:
  mAP@1 = 73.39
  tight Average-mAP = 77.25

Baseline:
  mAP@1 = 56.15
  tight Average-mAP = 60.60
```

这说明：

- 如果只做少数球动作，并且有专门训练数据，精度可以很高。
- 类别扩到 12 类后，难度明显上升。
- 这些方案是训练型深度学习模型，不是几条规则能达到的。

### 9.6 对我们当前项目的直接建议

第一版事件集合应该按精度和可解释性排序：

```text
必须:
  goal_or_celebration
  replay

优先:
  corner
  substitution
  free_kick
  yellow_card
  penalty

只做候选，不做精细判断:
  attack_highlight

暂不承诺:
  shots_on_target
  shots_off_target
  save
  woodwork
  red_card
  offside
```

理由：

```text
论文数据支持 goal/corner 相对好抓。
substitution/card/free-kick 中等可做。
shot/save/woodwork 需要连续动作和球轨迹，风险高。
red card 样本少，论文分数极低。
```
