# 足球事件识别规格草案

## 1. 总体策略

事件识别阶段不是只跑一个大 prompt，而是多个目标并行识别，最后汇总。

原则：

```text
硬信号能确定的事件，优先用规则/OCR/图像工具。
硬信号不能稳定确定的事件，再交给 Intern-S2 视觉判断。
所有事件最后汇总到 visual_events.json。
```

事件识别分三层：

```text
1. Hard Detectors
   用 OCR、图像差分、转播图层、颜色块、时间轴变化直接识别。

2. VLM Judges
   对候选片段的多张关键帧做语义判断。

3. Merger
   合并重复事件，关联 replay 和前序事件，输出统一时间线。
```

## 2. 输出格式

所有 detector / judge 最终输出统一结构：

```json
{
  "event_id": "V012",
  "timestamp": "00:31:25",
  "start": "00:31:05",
  "end": "00:31:50",
  "event_type": "corner",
  "source": "ocr|rule|vlm|hybrid",
  "confidence": 0.82,
  "certainty": "confirmed|probable|uncertain",
  "team": "德国|库拉索|unknown",
  "score_after": "2-1",
  "visual_evidence": [
    "角旗区附近有球员准备开球",
    "禁区内多名球员等待争顶"
  ],
  "frame_paths": [
    "candidate_frames/C012_000.jpg",
    "candidate_frames/C012_001.jpg"
  ],
  "commentary_value": "low|medium|high",
  "notes": ""
}
```

## 3. 事件清单

### 3.1 goal

优先级：最高。

推荐方式：

```text
硬规则优先，VLM 辅助。
```

硬信号：

- 比分牌 OCR 从 `0-0` 变成 `1-0`。
- 转播比分条更新。
- 进球后短时间内出现庆祝和 replay。

硬规则：

```text
如果连续 OCR 分数稳定，且比分发生 +1 变化：
  直接输出 goal，confidence >= 0.9。
```

VLM 辅助：

当 OCR 不稳定，但出现庆祝/回放/球员情绪变化时，用 `GoalCelebrationJudge` 判断。

Prompt 核心：

```text
请判断这个候选片段是否展示进球或进球后庆祝。

进球/庆祝的典型视觉特征：
1. 多名队友拥抱、奔跑、滑跪或冲向同一名球员。
2. 观众席出现大面积欢呼或镜头切到看台。
3. 对方球员低头、摊手，门将回头看球网。
4. 转播画面可能切到慢动作回放。
5. 比分牌或转播图层可能发生变化。

不要误判：
1. 普通犯规后的围人不等于庆祝。
2. 普通进攻后的遗憾反应不等于进球。
3. 如果只看到射门动作但没有庆祝/比分变化，输出 attack_highlight。
```

输出事件：

```text
goal 或 goal_or_celebration
```

### 3.2 replay

优先级：高。

推荐方式：

```text
硬规则 + VLM 辅助。
```

硬信号：

- OCR/图像识别到 `REPLAY`、转播台 LOGO、回放标识。
- 画面出现转播特效、切场动画。
- 同一动作在短时间内多角度重复。
- 画面速度明显变慢。

注意：

Replay 不是独立比赛事件，而是高价值证据。后处理时应关联到前 30-60 秒内最近的：

```text
goal
penalty
card
referee_dispute
attack_highlight
```

Prompt 核心：

```text
请判断这个候选片段是否是转播回放。

Replay 典型视觉特征：
1. 画面上出现 Replay 或转播品牌标识。
2. 画面速度像慢动作。
3. 同一动作以不同角度重复出现。
4. 有转播特效、镜头拉近、慢镜头质感。
5. 画面不是正常比赛连续推进，而像事后重放。

如果只是普通近景或普通转播切镜头，不要判为 replay。
```

### 3.3 substitution

优先级：高。

推荐方式：

```text
硬规则优先，VLM 确认。
```

硬信号：

- OCR 识别换人字幕条。
- 场边第四官员举换人牌。
- 两名球员在边线交接。
- 替补席/技术区画面。

Prompt 核心：

```text
请判断这个片段是否展示换人。

换人的典型视觉特征：
1. 第四官员在场边举电子换人牌。
2. 一名球员从场内走向边线，另一名球员准备上场。
3. 画面出现替补席或技术区。
4. 转播字幕可能显示球员号码和换人图标。

如果只是普通边线球或球员热身，不要判为 substitution。
```

### 3.4 card

优先级：中高。

推荐方式：

```text
VLM 判断为主，OCR/颜色块辅助。
```

硬信号：

- 裁判近景。
- 画面中有黄/红色小矩形。
- 转播字幕有黄牌/红牌图标。

风险：

牌面很小，普通图像工具难稳定识别。第一版建议输出：

```text
card_scene
```

只有模型明确看到颜色时，再输出：

```text
yellow_card / red_card
```

Prompt 核心：

```text
请判断这个片段是否展示出牌或纪律处罚。

出牌场景的典型视觉特征：
1. 裁判出现在画面中心或近景。
2. 裁判手臂举起，手中可能有黄色或红色小矩形牌。
3. 被判罚球员或多名球员围在裁判附近。
4. 转播字幕可能显示球员名、犯规信息或牌的图标。

要求：
1. 如果看不清牌的颜色，只输出 card_scene。
2. 只有明确看到黄色牌面，才输出 yellow_card。
3. 只有明确看到红色牌面，才输出 red_card。
```

### 3.5 referee_dispute

优先级：中。

推荐方式：

```text
VLM 判断。
```

视觉信号：

- 多名球员围住裁判。
- 球员摊手、指向某处、情绪激动。
- 裁判解释手势。
- 裁判指向耳机、屏幕或 VAR 区域。
- 画面出现 VAR 标识。

Prompt 核心：

```text
请判断这个片段是否展示判罚争议。

判罚争议的典型视觉特征：
1. 多名球员围住裁判。
2. 球员有摊手、抗议、指向某处等动作。
3. 裁判做解释或制止手势。
4. 可能出现 VAR 标识，或裁判指向耳机/场边屏幕。

如果只是普通犯规后球员站在一起，不要高置信度判为 referee_dispute。
```

### 3.6 corner

优先级：中高。

推荐方式：

```text
VLM 判断为主，场景规则辅助。
```

硬规则辅助：

- 候选帧中绿色草坪占比高。
- 画面接近球场角落。
- 可能出现角旗、底线、边线。
- 禁区内多人聚集。

Prompt 核心：

```text
请判断这个片段是否展示角球。

角球的典型视觉特征：
1. 画面靠近球场角落，可能看到角旗、底线、边线。
2. 一名进攻球员在角旗附近摆球、后退助跑或准备传中。
3. 禁区内有大量攻防球员集中站位，准备争顶。
4. 镜头常在角旗区和禁区之间切换。
5. 角球开出后，球通常飞向禁区，随后出现争顶或门前混战。

不要误判：
1. 如果只是边线附近控球，没有角旗或禁区争顶准备，不是角球。
2. 如果球员用双手从头顶掷球，那是边线球，不是角球。
3. 如果有明显人墙，更像任意球。
```

### 3.7 free_kick

优先级：中。

推荐方式：

```text
VLM 判断。
```

第一版不强分 direct / indirect，先输出：

```text
free_kick 或 set_piece_unknown
```

Prompt 核心：

```text
请判断这个片段是否展示任意球。

任意球的典型视觉特征：
1. 球静止摆放在犯规地点。
2. 主罚球员站在球后，可能有助跑距离。
3. 防守方多人排成人墙。
4. 裁判可能站在球和人墙之间，指挥距离。
5. 如果位置靠近禁区，镜头通常正对球门、人墙和主罚球员。

不要误判：
1. 角球发生在角旗区，不是任意球。
2. 点球发生在点球点，其他球员站在禁区外，不是普通任意球。
3. 中圈开球或门球也有静止球，但没有人墙。
```

### 3.8 penalty

优先级：中。

推荐方式：

```text
VLM 判断，必须高置信度才进入最终解说。
```

Prompt 核心：

```text
请判断这个片段是否展示点球。

点球的典型视觉特征：
1. 球静止放在点球点。
2. 主罚球员独自站在球后。
3. 门将站在球门线上。
4. 其他球员站在禁区外或禁区弧外。
5. 镜头通常正对球门和主罚球员。

不要误判：
1. 如果有多人排成人墙，更像任意球。
2. 如果球在角旗区，更像角球。
3. 如果是运动战单刀，球不是静止在点球点。
```

### 3.9 attack_highlight

优先级：中。

推荐方式：

```text
VLM 判断，作为兜底类别。
```

用途：

当模型看出这是一个有解说价值的进攻片段，但无法确认是射正、扑救、门框、点球或进球时，输出 `attack_highlight`。

Prompt 核心：

```text
请判断这个片段是否是有解说价值的进攻高光。

进攻高光的视觉特征：
1. 球门附近出现高强度攻防。
2. 多名球员在禁区内聚集。
3. 门将、后卫、进攻球员都集中在门前区域。
4. 可能出现射门、封堵、解围、门前混战。

要求：
1. 如果无法确认扑救、射正、击中门框，不要细分。
2. 只输出 attack_highlight。
3. 解说时只能说“形成威胁攻势”，不要说“神扑”或“击中门框”。
```

### 3.10 halftime / fulltime

优先级：中。

推荐方式：

```text
硬规则 + VLM 辅助。
```

硬信号：

- 视频时间接近 45 分钟或 90 分钟附近。
- 画面出现球员退场、握手、裁判鸣哨后停顿。
- 转播字幕显示半场/全场比分。
- 大范围球员向场边移动。

Prompt 核心：

```text
请判断这个片段是否展示半场结束或全场结束。

典型视觉特征：
1. 球员停止比赛并向场边移动。
2. 裁判结束比赛或半场。
3. 转播画面显示半场/全场比分。
4. 球员握手、退场或镜头切到教练/观众。

如果只是普通死球暂停，不要判为 halftime/fulltime。
```

## 4. Detector 分组

第一版推荐三个 VLM Judge。

### 4.1 OutcomeJudge

处理：

```text
goal_or_celebration
attack_highlight
penalty
unknown
```

用途：

判断比赛结果相关或进攻价值片段。

### 4.2 SetPieceJudge

处理：

```text
corner
free_kick
penalty
set_piece_unknown
unknown
```

用途：

判断定位球。

### 4.3 BroadcastJudge

处理：

```text
replay
substitution
card_scene
referee_dispute
halftime
fulltime
unknown
```

用途：

判断转播画面、裁判场景、场边事件。

## 5. 硬规则优先级

建议硬规则先跑：

```text
1. ScoreboardOCRDetector
   识别比分变化，输出 goal。

2. ReplayDetector
   识别 replay 标识/转播特效，输出 replay 候选。

3. OverlayChangeDetector
   识别字幕条变化，召回 substitution/card/score_change 候选。

4. SceneChangeDetector
   召回镜头切换、近景、庆祝、裁判特写候选。
```

硬规则输出高置信度事件后，可以跳过 VLM；中低置信度候选再交给 VLM。

## 6. 合并规则

### 6.1 时间去重

```text
同一 event_type，时间差 < 30 秒，合并。
保留 confidence 更高的事件。
```

### 6.2 Replay 关联

```text
replay 在 goal/card/penalty/attack_highlight 后 60 秒内出现，
则作为该事件 evidence，不单独进入最终解说主线。
```

### 6.3 进球确认

```text
scoreboard OCR 变化 > goal_or_celebration VLM 判断。
```

如果二者同时存在：

```text
confidence 提升。
```

如果只有庆祝但没有比分变化：

```text
输出 goal_or_celebration，certainty=probable。
```

### 6.4 低置信度处理

```text
confidence < 0.55:
  只保留在 visual_events.json，不进入 commentary.md。

0.55 <= confidence < 0.75:
  可进入 events.json，但 commentary_value 设为 medium。

confidence >= 0.75:
  可进入解说主线。
```

## 7. 第一版事件范围

第一版做：

```text
goal
goal_or_celebration
replay
substitution
card_scene
yellow_card
red_card
referee_dispute
corner
free_kick
penalty
attack_highlight
halftime
fulltime
```

第一版不做：

```text
shot_on_target
shot_off_target
save
woodwork
offside
possession_shift
tactical_change
player_tracking
ball_tracking
```

## 8. 实现顺序

建议先做：

```text
1. candidate_segments.json
2. ReplayDetector / OverlayChangeDetector / SceneChangeDetector
3. VLM 三个 Judge 的 prompt
4. visual_events.json
5. merger 到 events.json
6. commentary.md 生成
```

Scoreboard OCR 很重要，但可能需要调试比分牌位置和 OCR 质量，可以并行做。

