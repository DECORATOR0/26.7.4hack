# Version 2 Prompt Diagnosis

## 结论

Version 2 的事实偏差主要不是视频转文字阶段造成的，而是 `文字转事项 -> 图片复核 -> 最终合并 -> report` 这几层 prompt 的约束方向不完整。

核心问题：

1. 文本事项 Agent 对 replay 和新进球的规则过硬，但没有明确要求“用后续比分牌/进球字幕回填主进球”。
2. 图片复核 Agent 被要求“必须看图片证据”，但复核窗口只有 `±8s`，导致它看不到进球后几十秒出现的比分牌，从而把真实进球 reject。
3. 最终合并 Agent 被要求“剔除 rejected”，导致图片复核一旦错判，文本证据无法翻案。
4. report Agent 被要求润色，但没有足够硬地禁止从 replay 标题推导新比分、技术指标和比赛分钟。

## 1. 文字转事项 Prompt 问题

位置：`src/event_agent.py` 的 `_build_text_agent_prompt`

当前关键规则：

```text
goal_or_celebration：进球发生、比分变化、进球后庆祝。新进球必须有比分增加、明确“比分更新/扩大优势”的文本，或清楚的 live play 进球上下文；如果同一比分下反复出现球入网、庆祝或进球者字幕，优先判断为同一进球的 replay/celebration，不要写成“再入一球”。
```

问题：

- 这条规则能抑制重复进球，但也会把“先发生进球、后续才出现比分牌”的主进球压成 replay/celebration。
- 它没有要求模型建立 `score_delta_event`，也没有要求把后续比分牌反向关联到前面的入网/庆祝。
- 对进球类事项没有输出 `score_before`、`score_after`、`score_evidence_time`，导致最终合并无法做比分链。

具体表现：

- `Nmecha 1-0` 的视觉文本在 `00:14:14 - 00:14:58` 有庆祝和 `1-0`，`00:15:42` 有 `NMECHA 6' / GERMANY 1-0 CURAÇAO`。
- 文本事项阶段虽然提出了 `T0001 00:14:12 德国队Nmecha首开纪录`，但因为需要图片复核，后面被图片复核错杀。
- `00:23:12 Wirtz` 实际是 replay/误读，但 prompt 允许标题写成“远射破门回放”，后续 report 又把它当真。

建议改法：

```text
对 goal_or_celebration 必须输出：
- goal_status: new_goal|celebration_only|replay_only|possible_goal
- score_before
- score_after
- score_evidence: 哪一条观察文本明确显示比分变化/进球字幕
- score_evidence_timestamp

如果看到球入网但没有比分增加或进球字幕，不能写“扩大比分/再进一球”，只能写 possible_goal 或 replay_only。
如果后续 30-90 秒内出现进球字幕或比分变化，可以回填为 new_goal，并用后续字幕作为 score_evidence。
```

## 2. 图片复核 Prompt 问题

位置：`src/event_agent.py` 的 `_build_image_review_prompt`

当前关键规则：

```text
不要因为候选文本里写了就直接确认，必须看图片证据。
复核新进球时必须看比分牌和上下文：如果附近已经有同比分进球，且当前帧比分没有增加，只能修正为 replay 或同一进球庆祝，不能确认成新的 goal_or_celebration。
```

问题：

- 这条规则本身没错，但配合 `±8s` 复核窗口会出问题。
- 真正确认进球的比分牌/进球字幕经常在进球后 `20-60s` 出现。
- 图片复核只看 `±8s`，看不到后续比分牌，于是把真实进球判成 rejected 或 replay。

具体表现：

- `T0001 00:14:12 Nmecha首球` 被图片复核判为 `rejected`，理由是“比分仍为0-0/进攻被扑出”。
- 但 `00:15:42` 明确显示 `NMECHA 6' / GERMANY 1-0 CURAÇAO`。
- 当前复核窗口抓不到这条后续证据。

建议改法：

```text
进球类复核不要使用对称 ±8s。
使用 asymmetric window：
- goal_or_celebration: -10s / +60s
- replay: -8s / +12s
- substitution/card/set_piece: ±8s

图片复核输出必须包含：
- verdict
- event_type
- goal_status
- score_before
- score_after
- score_evidence_frame
- whether_later_scoreboard_confirms
```

## 3. 最终合并 Prompt 问题

位置：`src/event_agent.py` 的 `_build_final_prompt`

当前关键规则：

```text
剔除被图片复核 rejected 的事件。
不要新增没有候选依据的事件。
新进球必须以比分增加或明确 live play 新进球为依据。
```

问题：

- `剔除 rejected` 太绝对。图片复核窗口不够时，rejected 不一定可靠。
- `不要新增没有候选依据的事件` 会阻止它根据全场比分牌/进球名单补齐缺失进球。
- 没有强制做比分链完整性：最终比分 `7-1` 必须对应德国 7 个进球、库拉索 1 个进球。

具体表现：

- `Nmecha 1-0` 被图片复核 rejected 后，最终合并直接丢掉主进球，只保留 replay。
- `3-1 Havertz 点球` 没有从 `penalty + fulltime scorer list` 合成实际进球。
- `Wirtz replay` 没有被全场进球名单否掉，最终 report 写成 `2-0`。

建议改法：

```text
最终合并前先构建 score chain：
- 从所有 observation 中提取比分变化：0-0 -> 1-0 -> 1-1 -> 2-1 -> 3-1 -> ...
- 从 fulltime scoreboard 中提取 scorer list。
- final_events 的 new_goal 必须能对齐 score chain。

如果图片复核 rejected 但文本证据包含后续明确比分牌/进球字幕，则不能直接剔除，应标记 needs_more_review=true 或用 scoreboard evidence 覆盖。

允许基于 fulltime scorer list 和 penalty/scoreboard evidence 补齐缺失进球，但必须标明 source=scoreboard_backfill。
```

## 4. Report Prompt 问题

位置：`src/script_report.py`

当前 prompt 已经要求“不编造没有证据的球员、比分、判罚或技术指标”，但仍然不够硬。

具体表现：

- report 写出 `球速达到83公里/小时，旋转率10.5 rps`。
- report 把 `01:42:08` 视频时间写成“第142分钟”。
- report 把 replay 标题 `Wirtz远射破门回放` 扩展成“德国队2-0领先”。

建议改法：

```text
禁止输出任何未在 evidence 中逐字出现的数字指标，包括速度、距离、旋转率、百分比。
不要把视频时间戳 HH:MM:SS 转换为比赛分钟。
replay 事件不能改变比分，不能写“扩大优势/再进一球/领先到X-X”，除非 final_events 中 goal_status=new_goal 且有 score_after。
```

## 5. 与 final_common_event_timepoints.md 的关系

`final_common_event_timepoints.md` 里已有人工/半人工整理的较准时间线，包括：

- `00:14:26` Nmecha 1-0
- `00:29:50-00:30:00` Comenencia 1-1
- `00:45:44` 德国 2-1
- `00:57:18-00:57:22` Havertz 点球 3-1
- `01:01:46` 德国 4-1
- `01:23:20-01:24:20` Brown 5-1
- `01:31:30-01:31:40` Undav 6-1
- `01:42:08-01:42:18` Havertz 7-1

Version 2 当前没有消费这个文件，所以不会用它纠错。

后续可以把它作为：

1. 开发调参时的 gold reference。
2. 比分链校验 Agent 的参考输出格式。
3. Web demo 事件菜单的临时可靠数据源。

但正式比赛不能依赖人工文件，应从视觉文本和 scoreboard 自动提取。

## 下一步修改优先级

1. 进球类复核窗口改为 `-10s/+60s`。
2. 给文本事项和最终事件增加 `goal_status / score_before / score_after / score_evidence_timestamp`。
3. 最终合并前加入本地比分链构建，不完全交给 LLM。
4. report 阶段只消费经过比分链清洗后的 `final_events_clean.json`。
