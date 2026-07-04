# Text-First Event Agent Report

## Purpose

本轮实现的是“先把全场抽帧转成视觉观察文本，再让模型基于观察文本定位事件；模型自己认为不确定时，再回看对应图片证据”的流程。

这里没有用代码规则直接抽事件。代码只做调度：

1. 切分上一阶段的 `segment_descriptions.json`。
2. 调用 Intern-S2 读取观察文本，输出候选事件和 `needs_image_review`。
3. 对模型要求回看的事件，自动取对应时间附近帧，再调用 Intern-S2 做图片复核。
4. 调用 Intern-S2 总编 Agent 合并候选和复核结果，输出最终关键事件表。

## Implementation

新增文件：

- `run_event_agent.py`
- `src/event_agent.py`

核心输入：

- `outputs_frame_narration_full/segment_descriptions.json`
- `outputs_visual_full_safe/frame_index_2s.json`

全场运行命令：

```powershell
python run_event_agent.py --descriptions outputs_frame_narration_full\segment_descriptions.json --frame-index outputs_visual_full_safe\frame_index_2s.json --out outputs_event_agent_full --chunk-segments 12 --concurrency 3 --rpm-limit 20 --temperature 0.1 --resume --final-max-events 30
```

## Run Result

- 文本 chunk：10
- 文本定位成功：10
- 文本候选事件：48
- 模型主动要求图片复核：20
- 图片复核成功：20
- 最终关键事件：30
- 总 token：239,768

主要输出：

- `outputs_event_agent_full/text_agent_events.json`
- `outputs_event_agent_full/image_review_requests.json`
- `outputs_event_agent_full/image_review_results.json`
- `outputs_event_agent_full/final_events.json`
- `outputs_event_agent_full/event_agent_report.md`
- `outputs_event_agent_full/event_agent_runtime_summary.json`

## Notes

这个版本已经能避免一类明显问题：例如 `00:17:14` 文本层误判成“Nmecha 再入一球”，图片复核看到比分仍为 1-0 后，将它修正为同一进球的回放/庆祝。

仍有风险：上游视觉观察文本偶尔会误读球员名、队名或比分；如果文本 Agent 没有要求回看图片，最终合并可能继承这些错误。下一步建议加一个“比分链校验 Agent”，专门复核所有进球事件的比分变化，保证最终脚本的主线稳定。

## Team Name Constraint To Fix

当前发现一个明确问题：本场实际是德国 vs 库拉索，但视觉观察阶段在部分片段里把库拉索误写成哥伦比亚。典型例子：

- `outputs_frame_narration_full/raw_segments/S0033.json`：画面 `visible_text` 已经出现 `CURACAO`，但 `description` 写成“哥伦比亚球迷看台”。
- `outputs_frame_narration_full/raw_segments/S0043.json`：比分牌文字是“德国 1-1 库拉索”，但描述写成“德国队与哥伦比亚队”。

判断原因：模型被库拉索球衣和球迷区的蓝黄视觉元素带偏；如果 prompt 没有明确给出本场双方，它会按视觉先验猜第三方球队。

后续重跑前需要在 `frame_narration` 和 `event_agent` 的 prompt 顶部加入强约束：

```text
本场比赛固定为：德国 vs 库拉索。
白/黑球衣为德国，蓝/黄球衣为库拉索。
CURAÇAO / CURACAO / 库拉索 都指库拉索。
禁止输出哥伦比亚、委内瑞拉等非本场球队名。
如果画面看不清队名，只能写“德国球员/库拉索球员/unknown”，不要猜第三方国家队。
```
