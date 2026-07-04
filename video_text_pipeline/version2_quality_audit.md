# Version 2 Quality Audit

## 结论

Version 2 的工程链路是通的，且没有上下文截断问题：

- 视频转文字：`111 / 111` 成功。
- 视频转文字 `finish_reason=length`：`0`。
- 文字转事项：`10 / 10` text chunks 成功。
- 图片复核：`16 / 16` 成功。
- 最终合并：`ok=true`，`finish_reason=stop`。
- report 生成：`ok=true`，`finish_reason=stop`。

队名/国籍问题基本解决：

- `final_events.json`、`event_agent_report.md`、`commentary_report.md` 中未发现哥伦比亚、委内瑞拉、美国、巴拉圭等第三方球队名。
- `match_observation_timeline.md` 中命中的 `COL`、`Coca-Cola`、VAR 裁判国籍等不是球队误识别。

但事实线仍有明显问题，尤其是进球链。Version 2 当前可以作为流程 demo，不建议直接作为最终比赛解说结果。

## 上下文与截断检查

### 视频转文字

- 目录：`outputs_frame_narration_v2/raw_segments`
- raw 数量：`111`
- `ok=true, finish_reason=stop`：`111`
- 异常数：`0`
- 最大 completion tokens：`4737`
- 当前 `max_tokens=6000` 足够。

### 文字转事项

- 目录：`outputs_event_agent_v2/raw_text_chunks`
- raw 数量：`10`
- `ok=true, finish_reason=stop`：`10`
- 异常数：`0`
- 当前 `text_max_tokens=10000` 未截断。

### 图片复核

- 目录：`outputs_event_agent_v2/raw_image_reviews`
- raw 数量：`16`
- `ok=true, finish_reason=stop`：`16`
- 异常数：`0`

### 最终合并与 report

- `outputs_event_agent_v2/final_consolidation_raw.json`
  - `ok=true`
  - `finish_reason=stop`
  - `prompt_tokens=20972`
  - `completion_tokens=6578`
- `outputs_script_report_v2/script_report_raw.json`
  - `ok=true`
  - `finish_reason=stop`
  - `prompt_tokens=6678`
  - `completion_tokens=7406`

## 队名/国籍检查

检查范围：

- `outputs_frame_narration_v2/match_observation_timeline.md`
- `outputs_frame_narration_v2/segment_descriptions.json`
- `outputs_event_agent_v2/text_agent_events.json`
- `outputs_event_agent_v2/final_events.json`
- `outputs_event_agent_v2/event_agent_report.md`
- `outputs_script_report_v2/commentary_report.md`

结果：

- 最终事项和最终 report 没有第三方球队名污染。
- 视觉文本中的命中主要是：
  - `Coca-Cola`
  - VAR 裁判信息里的 `COL`
  - 广告、转播字幕、裁判国籍
- 这些不是“把库拉索识别成哥伦比亚”的问题。

## 事实问题

### 1. 首个德国进球被最终合并漏掉

视觉文本中有明确证据：

- `00:14:14 - 00:14:58` 多帧显示德国 `1-0` 库拉索和庆祝。
- `00:15:42` 比分牌显示 `NMECHA 6'`，`GERMANY 1-0 CURAÇAO`。

文字事项阶段也提出了：

- `T0001 00:14:12 德国队Nmecha首开纪录，1-0领先库拉索`

但图片复核把它判成：

- `rejected`
- `德国队进攻被扑出，比分仍为0-0`

最终结果只保留了：

- `F0001 00:15:14 replay Nmecha进球瞬间回放`
- `F0002 00:17:24 replay Nmecha进球慢动作回放`

问题：

- 正式 `goal_or_celebration` 首球缺失。
- report 用 replay 段来讲首球，时间和事件类型不够准确。

建议：

- 图片复核窗口对进球类扩大到 `+30s`，保证能看到后续比分牌。
- 进球事件不能只看入网瞬间，必须结合后续比分牌和进球字幕。
- 如果后续 scoreboard 明确 `NMECHA 6' / 1-0`，不能 reject 首球。

### 2. Wirtz 23 分钟进球是明显误报

最终事项：

- `F0006 00:23:12 replay 德国队Wirtz远射破门回放`
- `script_angle`: `Wirtz在禁区外远射破门，德国队再次扩大优势！`

但视觉文本附近显示：

- `00:23:36 - 00:23:58` 比分仍是德国 `1-0` 库拉索。
- 后续全场进球名单没有 Wirtz。

report 中进一步放大错误：

- 写成“Wirtz 远射破门，德国队 2-0 领先”。
- 随后又写库拉索 `1-1` 扳平，比分链自相矛盾。

建议：

- replay 若没有比分变化或全场进球名单支持，不能生成“破门/扩大比分”叙述。
- 最终 report 阶段需要读取比分链，不允许从 replay 标题推断新比分。

### 3. 3-1 进球缺失

全场结束比分牌显示：

- `HAVERTZ 45+5' (P), 88'`
- `SCHLOTTERBECK 38'`
- `NMECHA 6'`
- `COMENENCIA 21'`
- `BROWN 68'`
- `MUSIALA 47'`
- `UNDAV 78'`

因此德国 3-1 应该是 Havertz 的点球或补时进球。

当前 final_events 有：

- `F0012 00:40:16 penalty 德国队获得点球判罚`
- `F0013 00:45:44 goal_or_celebration 德国队角球头球破门，比分2-1`
- `F0014 01:01:46 goal_or_celebration 穆西亚拉进球，德国队4-1领先`

问题：

- 从 `2-1` 直接跳到 `4-1`。
- `3-1` 进球缺失。
- 点球判罚和 Havertz `45+5' (P)` 没有合成一个实际进球事件。

建议：

- 用比分牌/全场进球名单反推缺失进球。
- 最终合并阶段加入“比分链完整性检查”：7-1 必须对应 8 个进球事件，其中德国 7 个、库拉索 1 个。

### 4. 穆西亚拉 4-1 后存在重复或不安全进球

当前 final_events：

- `F0014 01:01:46 穆西亚拉进球，德国队4-1领先`
- `F0017 01:06:06 穆西亚拉再进球，德国队庆祝`
- `F0020 01:12:00 穆西亚拉进球后庆祝，比分4-1，个人第10球`

问题：

- `F0017` 标题写“再进球”，但没有明确比分变为 `5-1`。
- `F0020` 仍显示比分 `4-1`，更像庆祝/字幕/回放，不应该当新进球。

建议：

- 如果比分没有增加，统一降级为 `replay` 或 `celebration`。
- `goal_or_celebration` 里要拆分 `new_goal` 和 `celebration_only`，避免 report 当成新进球写。

### 5. report 生成阶段有编造技术指标

`outputs_script_report_v2/commentary_report.md` 中出现：

- `球速达到 83 公里/小时`
- `旋转率 10.5 rps`

这些不在原始 evidence 中，虽然 report 自己加了风险提示，但正文仍然写进了解说稿。

建议：

- report prompt 增加硬约束：禁止输出任何未在 evidence 中出现的数值指标。
- 生成后做正则扫描：`km/h`、`rps`、`%`、`米` 等指标如果不在 evidence 里，直接标红或删除。

### 6. report 把视频时间戳误写成比赛分钟

`commentary_report.md` 中出现：

- `第 142 分钟，德国队 Havertz...`

来源是把 `01:42:08` 的视频时间误当比赛分钟。

建议：

- report 阶段不要把 `HH:MM:SS` 自动改成“第 X 分钟”。
- 如果需要比赛分钟，只能从比分牌时间或事件 evidence 中读取，例如 Havertz 第二球应对应 `88'`。

## 当前可用性判断

可以用于：

- 展示端到端架构。
- 展示视频转文字完整性。
- 展示文本事项、图片复核、report 生成流程。
- Web demo 的菜单/事件浏览原型。

暂不适合直接作为最终结果：

- 进球链不完整。
- replay 与正式进球仍有混淆。
- report 会放大 final_events 中的错误。

## 下一步优先级

1. 加比分链校验 Agent 或本地规则。
   - 从视觉文本中提取所有比分变化。
   - 从全场结束比分牌提取进球名单。
   - 校验 `final_events` 是否覆盖全部进球。

2. 进球类图片复核扩大窗口。
   - 当前 `±8s` 对进球不够。
   - 建议新进球复核用 `-8s/+35s`，必须看到比分牌或进球字幕。

3. report 前先做事件清洗。
   - 删除或降级比分不变的“新进球”。
   - 删除未证实的 Wirtz 进球。
   - 补回 Nmecha 1-0 和 Havertz 3-1。

4. report 生成后做事实后处理。
   - 禁止未证据支持的技术指标。
   - 禁止把视频时间戳转成错误比赛分钟。
   - 禁止从 replay 自动推断新比分。
