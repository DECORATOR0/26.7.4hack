# API / VLM 辅助的足球事件识别方案

## 1. 我们真正关心的问题

传统 SoccerNet / CALF / T-DEED 路线通常是：

```text
视频 -> CNN/视频模型提特征 -> 时间模型训练 -> action timestamp
```

这条路线精度高，但需要训练或加载专用模型，和我们当前黑客松目标不完全一致。

我们更现实的路线是：

```text
视频 -> 本地图像工具粗筛候选片段 -> Intern-S2 / VLM API 判断事件类型 -> 解说生成
```

也就是：

- 不训练专用 ResNet/CNN。
- 不全量喂 1000+ 张图。
- 用 OpenCV/OCR/规则先把候选片段找出来。
- 再用 Intern-S2 这类多模态 API 判断“这几张图像像不像角球/点球/庆祝/换人/牌”。

## 2. 有没有相关论文

有，但它们通常不是“直接调商业 API”的工程论文，而是更泛化的 Vision-Language / Zero-shot Action Localization 思路。

### 2.1 Soccer-CLIP

资料：

- Paper: [Soccer-CLIP: Vision Language Model for Soccer Action Spotting](https://ieeexplore.ieee.org/document/10916659/)
- Full text mirror: [ResearchGate page](https://www.researchgate.net/publication/389643658_Soccer-CLIP_Vision_Language_model_for_Soccer_Action_Spotting)

它做什么：

```text
视频片段 + 文本 prompt
-> 视觉语言模型对齐
-> 输出 soccer action spotting confidence
```

和我们最相关的点：

- 它不是纯 CNN 分类，而是把足球动作的文本描述和视频特征对齐。
- 它用 LLM 做 domain-specific prompt engineering，让标签不是简单的 `corner`，而是更丰富的足球语义描述。
- 它报告 SoccerNet Action Spotting 上 t-AmAP 75.7%，高于 COMEDIAN 73.1、ASTRA 66.8、Spivak 65.1。
- 它提到 `corner kick` 单类结果很高，约 96.6%，说明角球这种空间上下文明确的事件非常适合 VLM/语义对齐方法。

对我们的启发：

不要只给模型标签：

```text
corner
```

而是给 domain prompt：

```text
角球通常表现为：球员站在角旗附近准备开球，角旗和底线可见，
禁区内有多名攻防球员等待争顶，转播镜头可能从角旗区切到禁区。
```

然后让 Intern-S2 判断候选片段和这些描述的匹配程度。

### 2.2 ZEAL: Zero-shot Action Localization via LVLM Confidence

资料：

- Paper: [Zero-shot Action Localization via the Confidence of Large Vision-Language Models](https://arxiv.org/abs/2410.14340)

它做什么：

```text
不用训练数据
LLM 把动作扩写成“开始/结束/典型视觉表现”的详细描述
LVLM 对每帧或每个片段打置信度
聚合置信度得到 action localization
```

这条线和我们非常接近，因为它的核心就是：

```text
不给模型训练，只靠动作文本描述 + VLM 置信度做定位
```

对我们的启发：

可以把每个事件写成一个 detector prompt。

例如 `corner_detector`：

```text
请判断这组足球转播帧是否展示角球事件。
角球的典型视觉表现：
1. 球员在角旗附近摆球或助跑；
2. 角旗、底线、边线至少部分可见；
3. 禁区内多名球员聚集准备争顶；
4. 镜头可能在角旗区和禁区之间切换。

请输出 0-1 confidence，并列出你看到的视觉证据。
```

再把多个 detector 的置信度合起来：

```text
corner_confidence
free_kick_confidence
penalty_confidence
card_confidence
substitution_confidence
celebration_confidence
```

最高且超过阈值的就是事件类型。

### 2.3 Do We Need Large VLMs for Spotting Soccer Actions?

资料：

- Paper: [Do We Need Large VLMs for Spotting Soccer Actions?](https://arxiv.org/html/2506.17144v1/)

它做什么：

```text
不用视觉，改用专家解说文本做 action spotting
设计 3 个 LLM judge：
  Outcome Judge: goals, penalties, cards
  Excitement Judge: crowd eruptions, near-misses, controversies
  Tactical Judge: substitutions, formation changes, momentum swings
```

虽然我们当前暂时不考虑音频/ASR，但它的 judge 设计有价值。

对我们的启发：

我们也可以做视觉版多 judge：

```text
Outcome Visual Judge:
  goal_or_celebration, penalty, card

Set-piece Visual Judge:
  corner, free_kick, penalty

Broadcast Visual Judge:
  replay, substitution, referee_dispute, halftime/fulltime
```

不要一次让一个 prompt 判断十几个类别。

### 2.4 SoccerComment: MLLM + RAG for Soccer Commentary

资料：

- Paper: [Multi-Modal Large Language Model with RAG Strategies in Soccer Commentary Generation](https://openaccess.thecvf.com/content/WACV2025/papers/Li_Multi-Modal_Large_Language_Model_with_RAG_Strategies_in_Soccer_Commentary_WACV_2025_paper.pdf)

它做什么：

```text
输入多模态 soccer clip
构造多模态特征和检索记忆
用 MLLM 做 commentary generation
```

和我们相关：

- 它承认长上下文是瓶颈。
- 它不是整场长视频端到端生成，而是基于片段和检索上下文生成。
- 它证明 MLLM 可以用于足球解说生成，但需要先组织好片段信息。

对我们的启发：

我们的 Harness 应该先输出：

```text
visual_events.json
```

再让 Intern-S2 生成：

```text
commentary.md
```

而不是直接从整场视频生成解说。

## 3. 对我们最适合的方案

推荐做成三层。

### 3.1 本地图像工具层：便宜粗筛

不用 AI，负责从全视频里找候选。

工具：

```text
OpenCV
OCR 可选
图像差分
绿色草坪比例
转播 overlay 区域变化
镜头切换检测
```

输出：

```text
candidate_segments.json
```

候选筛选逻辑：

```text
每 5 秒抽一帧
计算帧间差异
计算草坪比例变化
计算上下转播字幕区域变化
检测近景/非球场画面
合并高分帧为候选片段
```

这一层只回答：

```text
这里可能有事。
```

不负责最终判断：

```text
这里一定是角球。
```

### 3.2 VLM/API 事件 detector 层：语义判断

对候选片段密抽 4-8 张图，交给 Intern-S2。

不要一个 prompt 判断 17 类。建议分成 3 个 judge：

```text
SetPieceJudge:
  corner
  free_kick
  penalty
  unknown

BroadcastJudge:
  replay
  substitution
  halftime
  fulltime
  unknown

IncidentJudge:
  goal_or_celebration
  card
  referee_dispute
  attack_highlight
  unknown
```

每个 judge 输出：

```json
{
  "segment_id": "C012",
  "judge": "SetPieceJudge",
  "event_type": "corner",
  "confidence": 0.82,
  "visual_evidence": [
    "角旗区附近有球员准备开球",
    "禁区内多名球员等待争顶",
    "画面从角旗区切向禁区"
  ],
  "uncertainty": "未看到球离脚瞬间，因此不是 confirmed"
}
```

### 3.3 Harness 合并层：时序去重和校验

规则：

```text
同一类事件，时间差 < 30 秒，合并。
replay 紧跟 goal_or_celebration，则 replay 作为该事件证据。
corner/free_kick/penalty 如果前后 30 秒出现 goal_or_celebration，则提升解说价值。
confidence < 0.55 的事件只保留在 visual_events.json，不进最终解说。
```

输出：

```text
visual_events.json
events.json
commentary.md
```

## 4. 每类事件怎么用 API 判断

### 4.1 Corner

判断难度：适合第一版。

API 输入：

```text
候选片段 5 张图：
start, center-5s, center, center+5s, end
```

Prompt 标准：

```text
角球视觉标准：
1. 角旗或球场角落区域可见；
2. 球员在角旗附近摆球、助跑或开球；
3. 禁区内多名球员集中等待争顶；
4. 镜头可能在角旗和禁区之间切换；
5. 如果只是边线附近控球，不能判为角球。
```

输出：

```json
{
  "event_type": "corner",
  "confidence": 0.0,
  "evidence": [],
  "reject_reason": "如果不是角球，说明为什么"
}
```

### 4.2 Free Kick

判断难度：中等。

标准：

```text
人墙
定点球
裁判指挥站位
禁区前多人固定站位
球员助跑主罚
```

风险：

```text
普通犯规后暂停、开球、边线定位球可能混淆。
```

所以输出可以分：

```text
direct_free_kick
indirect_free_kick
set_piece_unknown
```

第一版不强分 direct/indirect。

### 4.3 Penalty

判断难度：中高。

标准：

```text
点球点
门将站门线
主罚球员独自面对球门
其他球员站禁区外
镜头正对球门/主罚球员
```

风险：

```text
单刀、普通禁区内射门、任意球镜头可能误判。
```

所以要求模型必须列出：

```text
是否看到点球点？
是否看到门将站门线？
是否看到其他球员在禁区外等待？
```

### 4.4 Card

判断难度：中等。

标准：

```text
裁判近景
裁判手中黄/红色牌
球员围裁判
转播字幕条显示犯规球员
```

风险：

```text
牌很小，单帧看不清。
```

所以第一版可以不强分黄/红：

```text
card_or_disciplinary_scene
```

如果模型能明确看到颜色，再输出：

```text
yellow_card / red_card
```

### 4.5 Substitution

判断难度：适合第一版。

标准：

```text
第四官员举换人牌
两名球员在边线交接
替补席/技术区画面
转播换人字幕条
```

这个可以单独做 `SubstitutionDetector`，因为视觉标准很清楚。

### 4.6 Replay

判断难度：适合第一版。

标准：

```text
Replay 标识
慢动作
多角度重复
转播特效/LOGO 转场
画面速度和正常比赛不同
```

Replay 本身不是比赛事件，但它是高价值候选。

规则：

```text
如果 replay 前 30 秒内有 goal_or_celebration / penalty / referee_dispute，
则把 replay 合并为该事件证据。
```

### 4.7 Goal or Celebration

判断难度：适合第一版，但最好不要只靠一张图。

标准：

```text
多名队友拥抱/奔跑/滑跪
观众席大面积欢呼
对方球员低头或门将回头看球网
比分牌变化
随后出现 replay
```

第一版不要强行判断“球入网瞬间”，因为球很小。

更稳的标签是：

```text
goal_or_celebration
```

再由比分牌/OCR 或题面比分做二次确认。

## 5. 推荐 Prompt 结构

每个 judge 都用这个格式。

```text
你是足球转播视频事件识别器。
你会看到同一个候选片段的 5 张按时间排序的关键帧。

任务：
只判断该片段是否属于以下事件之一：
{候选事件列表}

判断要求：
1. 只能根据画面证据判断。
2. 不要猜球员姓名。
3. 如果证据不足，输出 unknown。
4. 必须列出视觉证据。
5. 输出严格 JSON。

事件定义：
{每个事件的视觉标准}

输出 JSON：
{
  "segment_id": "...",
  "event_type": "...",
  "confidence": 0.0,
  "visual_evidence": [],
  "uncertainty": "",
  "commentary_value": "low|medium|high"
}
```

## 6. 和论文路线的关系

我们的方案不是要复刻 SoccerNet 模型。

更准确地说：

```text
借鉴 SoccerNet 的任务定义；
借鉴 Soccer-CLIP 的“文本描述 + 视觉片段”对齐思想；
借鉴 ZEAL 的“用动作描述让 VLM 打置信度”；
借鉴 SoccerComment 的“先结构化片段，再生成解说”；
用 Intern-S2 API 替代训练好的专业 VLM。
```

这在 Presentation 里可以讲成：

> 我们没有训练专用 action spotting 模型，而是采用 API-assisted spotting。系统先用本地视觉规则从长视频中召回候选片段，再用 Intern-S2 作为视觉语言事件判别器，对每个候选片段进行多 judge 分类，最终由 Harness 做合并、校验和解说生成。

## 7. 现实风险

### 7.1 VLM 单帧判断不稳定

解决：

```text
每个候选片段给 5-8 张图，不给单帧。
```

### 7.2 类别太多会混淆

解决：

```text
拆成 SetPieceJudge / BroadcastJudge / IncidentJudge。
```

### 7.3 模型可能过度猜测

解决：

```text
强制 unknown；
强制 visual_evidence；
低置信度不进最终解说。
```

### 7.4 候选召回漏掉事件

解决：

```text
本地筛选宁可多召回；
Top 30-60 候选；
近似事件合并去重。
```

## 8. 当前最建议落地的版本

第一版实现：

```text
1. 每 5 秒抽一帧。
2. 本地计算 scene_change / grass_ratio / overlay_change。
3. 选 Top 40 候选片段。
4. 每段抽 5 张图。
5. 分批调用 Intern-S2：
   - SetPieceJudge
   - BroadcastJudge
   - IncidentJudge
6. 合并事件。
7. 输出 visual_events.json。
8. 基于 visual_events.json 生成 commentary.md。
```

不做：

```text
球轨迹检测
射正/射偏/扑救/门框精细分类
全 17 类 SoccerNet 复刻
端到端一次性长视频理解
```

