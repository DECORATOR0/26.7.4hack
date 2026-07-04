# Version 1 基础配置

## 结论

Version 1 当前已经跑通，但它是粗糙可用版，不是最终推荐参数。

当前实际配置是：

- 抽帧：`2 秒/帧`
- 不是 `5 秒/帧`
- 每分钟输入图片：约 `30 张`
- 不是 `12 张`
- RPM limit：`20`
- temperature：`0.1`
- 路线：先全场转视觉文本，再从文本中定位事项，必要时回看图片

## 输入

- 视频：`德国_库拉索.mp4`
- 比赛：德国 vs 库拉索
- 目标：根据比赛视频定位关键事项，后续生成中文解说脚本

## Stage 1: 视频转文字

输出位置：

- 人工阅读版：`outputs_frame_narration_full/match_observation_timeline.md`
- 程序读取版：`outputs_frame_narration_full/segment_descriptions.json`
- 原始模型返回：`outputs_frame_narration_full/raw_segments/`
- 运行统计：`outputs_frame_narration_full/narration_runtime_summary.json`

基础配置：

| 参数 | Version 1 |
|---|---:|
| 抽帧间隔 | `2 秒/帧` |
| 每段时长 | `60 秒` |
| 每段图片数 | 最多 `30 张` |
| 全场段数 | `111` |
| 总帧数 | `3327` |
| 并发 | `4` |
| RPM limit | `20` |
| temperature | `0.1` |
| max_tokens | `1800` |

运行结果：

| 指标 | 数值 |
|---|---:|
| 成功段数 | `111 / 111` |
| finish_reason=length 段数 | `33` |
| finish_reason=stop 段数 | `78` |
| prompt tokens | `1,381,806` |
| completion tokens | `161,426` |
| total tokens | `1,543,232` |
| 平均每分钟 token | `13,903` |

注意：这里的“成功段数”只代表 API 有返回，不代表每段 JSON 都完整。当前实际有 `33` 个一分钟段因为 `max_tokens=1800` 被截断。

每分钟输出结构：

- `segment_summary`
- `observations`
- `event_candidates`

每条 observation 包含：

- `timestamp`
- `frame_index`
- `scene_type`
- `description`
- `visible_text`
- `scoreboard`
- `possible_events`
- `confidence`

## Stage 2: 文字转候选事项

输入：

- `outputs_frame_narration_full/segment_descriptions.json`

输入方式：

- 不是整场一次性丢进去
- 每 `12` 个一分钟段合成一个 text chunk
- 每个 chunk 约覆盖 `12 分钟`
- 全场共 `10` 个 text chunks

输出位置：

- `outputs_event_agent_full/text_chunk_plan.json`
- `outputs_event_agent_full/text_agent_events.json`
- `outputs_event_agent_full/text_agent_results.json`

基础配置：

| 参数 | Version 1 |
|---|---:|
| chunk_segments | `12` |
| text chunks | `10` |
| 并发 | `3` |
| RPM limit | `20` |
| temperature | `0.1` |
| max_tokens | `5000` |

运行结果：

| 指标 | 数值 |
|---|---:|
| text chunk 成功 | `10 / 10` |
| 候选事件 | `48` |

候选事件字段：

- `timestamp`
- `event_type`
- `title`
- `confidence`
- `certainty`
- `commentary_value`
- `needs_image_review`
- `text_evidence`
- `script_hint`

## Stage 3: 图片复核

触发方式：

- 由文本 Agent 自己判断 `needs_image_review=true`
- 代码只负责按时间戳取附近图片，不直接判断事件

输出位置：

- `outputs_event_agent_full/image_review_requests.json`
- `outputs_event_agent_full/image_review_results.json`
- `outputs_event_agent_full/raw_image_reviews/`

基础配置：

| 参数 | Version 1 |
|---|---:|
| 复核窗口 | `±8 秒` |
| 每次最多图片 | `9 张` |
| 并发 | `3` |
| RPM limit | `20` |
| temperature | `0.1` |
| max_tokens | `2600` |

运行结果：

| 指标 | 数值 |
|---|---:|
| 需要图片复核事件 | `20` |
| 图片复核成功 | `20 / 20` |

## Stage 4: 最终事项合并

输入：

- `48` 个文本候选事件
- `20` 个图片复核结果

输出位置：

- `outputs_event_agent_full/final_events.json`
- `outputs_event_agent_full/event_agent_report.md`
- `outputs_event_agent_full/event_agent_runtime_summary.json`

基础配置：

| 参数 | Version 1 |
|---|---:|
| final max events | `30` |
| temperature | `0.1` |
| 当前 max_tokens | `9000` |

运行结果：

| 指标 | 数值 |
|---|---:|
| 最终事件 | `30` |
| prompt tokens | `210,477` |
| completion tokens | `29,291` |
| total tokens | `239,768` |

## Output 截断问题

Version 1 有两类 output 截断问题。

### 1. 视频转文字阶段截断

这是当前更重要的问题。

视频转文字阶段每个请求输入约 `12k` prompt tokens，因为包含 30 张图片；但输出上限只有 `max_tokens=1800`。模型被要求“尽量详尽”描述一分钟 30 帧画面时，容易写不完。

具体例子：

- 文件：`outputs_frame_narration_full/raw_segments/S0085.json`
- 时间段：`01:24:00 - 01:24:59`
- prompt tokens：`12,465`
- completion tokens：`1,800`
- finish_reason：`length`
- 结果：输出在 JSON 中途被截断，结尾停在 `"description": "VAR回放`

还有类似段：

- `S0001`
- `S0005`
- `S0008`
- `S0009`
- `S0011`
- `S0014`
- `S0022`
- `S0027`
- `S0030`
- `S0031`
- `S0032`
- `S0034`

这说明：不是“几千 token 怎么会截断”，而是视频转文字阶段实际 completion 上限只有 `1800`，而且 30 帧逐条 JSON 描述很容易超过这个上限。

#### 视频转文字 output 峰值估算

对 `raw_segments` 做了一次粗略统计：

- `finish_reason=stop` 的正常段共有 `78` 段。
- 正常段 completion tokens：p50 约 `1308`，p75 约 `1467`，p90 约 `1598`，p95 约 `1656`，最大 `1783`。
- 这说明 `1800` 对普通段已经接近贴边，不是宽裕参数。
- `finish_reason=length` 的截断段共有 `33` 段，全部打满 `1800`。

以截图里的 `S0085` 为例：

- 时间段：`01:24:00 - 01:24:59`
- completion tokens：`1800`
- 实际只写到约 `01:24:30`
- 已生成 observations：约 `16` 条
- 按时间和 observation 数线性估算，完整写完大概需要 `3300 - 3500` output tokens。

对所有截断段做同样估算：

| 估算方式 | p50 | p75 | p90 | 最大 |
|---|---:|---:|---:|---:|
| 按已覆盖时间线性估算 | `3857` | `4154` | `4154` | `4909` |
| 按已生成 observation 数线性估算 | `3857` | `4154` | `4154` | `4500` |

结论：

- 如果保持 Version 1 这种“尽量详尽、接近逐帧描述”的输出风格，视频转文字阶段 `max_tokens` 应该设到 `4500` 左右，极端保守可以设 `5000`。
- 如果不追求逐帧详写，而是让每分钟只输出 `6 - 10` 条关键观察，`max_tokens=2500 - 3000` 应该更合适。
- 后续更推荐第二种：保留 `2 秒/帧` 或改成 `5 秒/帧` 作为视觉证据输入，但 prompt 明确要求压缩输出，不要每帧都写。

### 2. 最终合并阶段截断

Version 1 还曾经出现过一次最终输出为空的问题。

原因：

- 最终合并 Agent 原来 `max_tokens=7000`
- 模型实际输出正好打满输出上限
- 返回 `finish_reason=length`
- JSON 被截断
- 解析失败后 `final_events` 变成空
- 所以这不是 API 真的返回空内容，而是“有输出，但 JSON 不完整，程序没有拿到合法 final_events”

当前处理：

- 最终合并 `max_tokens` 改为 `9000`
- prompt 要求紧凑 JSON
- final events 限制为 `30`
- 候选证据压缩成短证据

当前状态：

- 已能正常输出 `30` 个最终事件
- 当前最终合并返回 `finish_reason=stop`
- 当前最终合并 completion tokens：`5,674`
- 但这个问题需要后续继续留意，特别是事件数变多时

## Token 压力位置

Version 1 的 token 压力主要不在最终可见的 Markdown 表格，而在模型请求的输入和结构化 JSON 输出。

最大成本阶段：

1. 视频转文字阶段。

   这是总成本最大的位置。111 个一分钟请求，每个请求最多 30 张图片，平均每分钟约 `13,903` tokens，总计 `1,543,232` tokens。

2. 最终合并阶段。

   这是单次请求里上下文压力最大的位置之一。它要同时吃：

   - `48` 个文本候选事件
   - `20` 个图片复核结果
   - 每个事件的证据、标题、confidence、script_hint

   旧版最终合并输入约 `28,499` prompt tokens，输出打满 `7,000` completion tokens 后被截断。

3. 文本转事项阶段。

   每次不是整场输入，而是每 `12` 分钟视觉文本作为一个 chunk。全场 `10` 个 chunks，因此单次压力可控，但总体仍有 `210,477` prompt tokens。

人工看起来“就一点点输出”的原因：

- 人看到的是压缩后的事件表。
- 模型实际输出是完整 JSON，每个事件都有多个字段。
- 截断发生在 JSON 字符串末尾，哪怕肉眼看前面已经生成了很多内容，程序也无法把不完整 JSON 当成最终结果。

## 当前已知问题

1. 队名约束不足。

本场实际是德国 vs 库拉索，但视觉观察阶段有时把库拉索误写成哥伦比亚。

后续 prompt 必须显式加入：

```text
本场比赛固定为：德国 vs 库拉索。
白/黑球衣为德国，蓝/黄球衣为库拉索。
CURAÇAO / CURACAO / 库拉索 都指库拉索。
禁止输出哥伦比亚、委内瑞拉等非本场球队名。
如果画面看不清队名，只能写“德国球员/库拉索球员/unknown”，不要猜第三方国家队。
```

2. 抽帧成本偏高。

当前是 `2 秒/帧`，每分钟约 `30 张`。后续实用版建议改成：

- `5 秒/帧`
- 每分钟约 `12 张`

3. temperature 需要调参。

当前全链路都是 `0.1`。后续可以测试：

- 视觉转文字：`0.0 - 0.1`
- 事件定位：`0.0`
- 最终合并/脚本润色：可稍高，但需要严格结构化输出时仍建议低温

4. 进球和回放仍需比分链校验。

当前已经加了“比分不变时优先判回放”的约束，但还需要单独的比分链校验 Agent，专门复核所有 `goal_or_celebration`。

## Version 1 -> Version 2 改进方案

这次先不重构流程，只解决当前最明确的三个问题：

1. 视觉转文字阶段队名/国籍容易误判。
2. 视觉转文字阶段 `max_tokens=1800` 不够，导致一分钟描述 JSON 被截断。
3. 当前链路只输出结构化事项，缺少可直接阅读的解说脚本/report。

同时给文字转关键事项阶段预留更多输出空间，便于后续纳入更多事件类型。

### 当前固定推荐参数

代码默认参数已按这个方案调整，但还没有用新参数全量重跑。

| 阶段 | 参数 | Version 1 | Version 2 固定参数 |
|---|---:|---:|---:|
| 视频转文字 | 抽帧间隔 | `2 秒/帧` | `2 秒/帧` |
| 视频转文字 | 每段时长 | `60 秒` | `60 秒` |
| 视频转文字 | 每段图片数 | 最多 `30 张` | 最多 `30 张` |
| 视频转文字 | max_tokens | `1800` | `6000` |
| 视频转文字 | concurrency | `4` | `3` |
| 视频转文字 | rpm_limit | `20` | `15` |
| 文字转事项 | chunk_segments | `12` | `12` |
| 文字转事项 | text max_tokens | `5000` | `10000` |
| 文字转事项 | concurrency | `3` | `3` |
| 文字转事项 | rpm_limit | `20` | `12` |
| 事项转脚本/report | max_tokens | 无 | `10000` |
| 事项转脚本/report | temperature | 无 | `0.2` |

### TPM/RPM 极限估算

视频转文字阶段：

- 已有全量运行中，单请求最大 prompt tokens 为 `12,487`。
- 新参数 output 上限为 `6,000`。
- 单请求极限 total tokens 约为 `12,487 + 6,000 = 18,487`。
- `15 RPM` 持续打满时，理论 TPM 约为 `18,487 * 15 = 277,305`。
- 低于当前 `300,000 TPM`，并且 RPM 也低于 `30 RPM`。

文字转关键事项阶段：

- 已有全量运行中，单请求最大 prompt tokens 为 `11,133`。
- 新参数 output 上限为 `10,000`。
- 单请求极限 total tokens 约为 `11,133 + 10,000 = 21,133`。
- `12 RPM` 持续打满时，理论 TPM 约为 `21,133 * 12 = 253,596`。
- 低于当前 `300,000 TPM`，并且 RPM 也低于 `30 RPM`。

图片复核阶段：

- 已有全量运行中，单请求最大 prompt tokens 为 `5,918`。
- 当前图片复核 output 上限为 `2,600`。
- 单请求极限 total tokens 约为 `5,918 + 2,600 = 8,518`。
- `12 RPM` 持续打满时，理论 TPM 约为 `8,518 * 12 = 102,216`。

最终合并阶段：

- 当前是单次请求，不形成 RPM 压力。
- 已有运行中 prompt tokens 为 `25,500`，completion tokens 为 `5,674`，total tokens 为 `31,174`。
- 当前最终合并 `max_tokens=9000` 暂时够用。

事项转脚本/report 阶段：

- 新增单次请求，不形成 RPM 压力。
- 输入为 `outputs_event_agent_full/final_events.json`。
- 输出上限为 `10000`，用于生成可直接阅读的 Markdown 交付稿。
- 该阶段只负责润色、分段和格式化，不允许新增没有事项证据的进球、球员或判罚。

结论：三个会批量请求的阶段，在当前固定参数下按极限 output 估算均低于 `300,000 TPM` 和 `30 RPM`。后续如果改变抽帧密度、chunk 大小或 max_tokens，需要重新计算。

### 缓存复用规则

为了加快迭代，代码支持 `--resume`，但 Version 1 的旧缓存有一个风险：只要 raw 文件存在就复用，可能误用已经被 `finish_reason=length` 截断的旧结果。

现在已改成带指纹缓存：

- 缓存必须 `ok=true`。
- 缓存不能是 `finish_reason=length`。
- 缓存里的 `request_fingerprint` 必须和当前输入、prompt 版本、temperature、max_tokens 等参数一致。
- 不一致就自动重跑该请求。
- 新结果也按同一口径计数：只要 `finish_reason=length`，即使 API 有返回，也不算 `ok=true`。

这意味着后续可以安全使用 `--resume` 做增量迭代；调过 prompt 或 max_tokens 后，旧结果不会被错误复用。

### 队名/国籍约束

视觉转文字 prompt 已加入强约束：

```text
本场比赛固定为：德国 vs 库拉索。
德国队通常为白/黑球衣，库拉索队通常为蓝/黄元素球衣。
CURAÇAO / CURACAO / Curaçao / 库拉索 都指库拉索。
禁止把库拉索误写成哥伦比亚、委内瑞拉或其他第三方国家队。
如果画面或比分牌看不清队名，只能写“德国球员”“库拉索球员”或 unknown，不要猜新队名。
```

### 事项转脚本/report 阶段

新增入口：

```bash
python run_script_report.py --events outputs_event_agent_full/final_events.json --match-info examples/match_info.germany_curacao.json --out outputs_script_report_full
```

输出文件：

- `outputs_script_report_full/commentary_report.md`
- `outputs_script_report_full/script_report_raw.json`
- `outputs_script_report_full/script_report_runtime_summary.json`

输出结构参考附件 4，但更克制：

1. 文档说明。
2. 完整版中文解说脚本。
3. 关键事件时间轴。
4. 60-90 秒短视频口播版。
5. 分镜与制作提示。
6. 内部复核备注。

核心约束：

- 只基于 `final_events` 写稿。
- replay/celebration 要和主进球合并叙事，不能写成重复进球。
- 没有证据的球员名、助攻、射门方式、牌色、判罚原因不写。
- 队名固定为德国 vs 库拉索。

## 后续 Version 2 目标

- 用新参数全量重跑视频转文字，确认 `finish_reason=length` 是否降为 `0`。
- 检查德国 vs 库拉索队名是否仍出现哥伦比亚、委内瑞拉等错误。
- 用 `run_script_report.py` 生成最终 Markdown 交付稿，检查口播风格和重复进球问题。
- 如果 token 成本过高，再测试 `5 秒/帧` 或“每分钟只输出 6-10 条关键观察”的压缩 prompt。
- 加入比分链校验 Agent，专门复核所有 `goal_or_celebration`。
- 对 temperature、max_tokens、rpm_limit 做系统化调参。

## Version 3 Improvement Draft

Version 3 的目标不是扩大事件类型，而是把下游事项收敛到最终要交付的固定集合。上游仍然走 `视频抽帧 -> narrative 文本 -> 事项抽取 -> 必要时图片回看 -> clean events -> report/web`，但事项定义、时间字段和下游接口要重新整理。

### 1. V3 只识别这 10 类事项

下游事项只对齐当前确认的事项集合，不再输出 `replay`、`attack_highlight`、`dead_ball`、`crowd` 这类泛化标签。

| event_type | 中文名 | 记录边界 |
|---|---|---|
| `goal` | 进球 | 明确出现进球、破门、比分变化、进球庆祝或 narrative 明确描述进球。比分牌可作为证据，但不是唯一硬条件。 |
| `penalty` | 点球 | 点球判罚、点球主罚、点球射入/射失都记录。点球进球可以同时生成 `goal`，但要用同一组证据关联，不能写成两个独立进球。 |
| `shot_chance` | 射门机会 | 只记录有解说价值的射门、门将扑救、明显威胁球。普通推进、普通传中不记。 |
| `corner` | 角球 | 明确角球判罚、角球准备或角球开出。 |
| `free_kick` | 任意球 | 明确任意球判罚、定位球准备或任意球开出。 |
| `foul_card_dispute` | 犯规/黄牌/红牌/裁判争议 | 只记录明确犯规、出牌、裁判介入、球员抗议、判罚争议。普通身体接触、不影响比赛的对抗不记录。 |
| `offside` | 越位判罚 | 只在画面、字幕或 narrative 明确提到越位时记录。例如边裁举旗、字幕写 `ONSIDE/OFFSIDE`、进球因越位确认有效/无效。 |
| `substitution` | 换人 | 明确出现换人牌、上下场球员、换人字幕或 narrative 明确换人。 |
| `celebration` | 庆祝 | 进球后或重大节点后的庆祝场景。能关联进球时必须关联到主事件，不能当成新进球。 |
| `half_full_time` | 半场/全场 | 半场结束、全场结束、哨响、球员退场、比分牌确认等。 |

明确不做：

- 不单独输出 `replay`。回放只能作为某个事项的证据，例如进球回放、点球回放、越位回放。
- 不单独输出泛泛的 `attack_highlight`。如果值得记录，归到 `shot_chance`。
- 不记录普通身体接触、普通传控、普通推进、无明确判罚的死球。
- 不为了凑数量编造球速、旋转率、射门距离、概率等没有证据的指标。

### 2. V3 不追踪球员身份、姓名、号码和场上位置

V1/V2 里模型经常尝试识别球员名、号码、前锋/后卫等身份信息，但这些信息对当前交付目标帮助不大，且很容易错。V3 应主动降级这一层信息：

- narrative 阶段不要主动识别或输出球员姓名、号码、前锋/后卫/门将等身份标签。
- 事项抽取阶段最多保留球队层级，例如“德国队球员”“库拉索球员”。
- 即使字幕或阵容图里出现人名，除非任务专门要求球员维度，否则也不要把人名传到最终事项。
- 换人事项只记录“某队换人/出现换人”，不追踪上下场球员姓名。
- 射门、犯规、争议、庆祝等事项不写“前锋”“后卫”“队长”等身份判断；这些不是当前下游需要的事实。
- report/web 层也不新增球员名、号码、位置或身份，只围绕球队、事项类型、比赛时间、视频时间和证据写稿。

### 3. 识别策略：narrative prompt 为主，图片回看为辅

V3 不把规则写得过死。核心思路是：先让模型基于 narrative 文本判断事项，再在必要时召回图片。比分牌、字幕、球员动作、庆祝、裁判手势都可以作为证据，但不要把某一个证据写成所有事件的硬条件。

当前保持的上游参数：

| 参数 | V3 初始值 |
|---|---:|
| 抽帧间隔 | `2 秒/帧` |
| narrative 分段 | `60 秒/段` |
| 每段图片 | 最多 `30 张` |
| 事项抽取 chunk | `12` 个 narrative 段，约 `12 分钟` |
| 图片回看窗口 | `review_timestamp ±8 秒` |
| 图片回看上限 | 最多 `9 张` |

`confidence` 继续由模型给出，但不作为硬阈值直接删事件。更重要的是让模型同时输出：

```json
{
  "confidence": 0.82,
  "certainty": "confirmed|probable|uncertain",
  "evidence_level": "direct_visual|text_clear|text_probable|weak",
  "needs_image_review": true
}
```

解释：

- `confidence` 用于排序、展示和后续整合参考。
- `certainty` 用于表达确定性。
- `evidence_level` 用于说明证据强度。
- `needs_image_review` 仍由模型判断，不设置机械阈值。
- 高价值事项如果 narrative 已经足够明确，可以不回看；如果描述含糊、前后矛盾、时间点不稳，则回看 `±8 秒`。

### 4. 文本转事项 prompt 要轻约束

V3 的事项抽取 prompt 不要要求“必须看到比分变化才算进球”这类过硬条件。它应该让模型基于 narrative 里已经出现的描述做综合判断。

建议 prompt 核心约束：

```text
你将看到连续 12 分钟左右的足球比赛视觉 narrative。
请只抽取以下事项：进球、点球、射门机会、角球、任意球、犯规/黄牌/红牌/裁判争议、越位判罚、换人、庆祝、半场/全场。

不要输出 replay、attack_highlight、dead_ball、crowd 等其他类型。
回放、字幕、比分牌、庆祝、裁判手势只能作为证据写入 evidence，不作为独立事项。

不要识别、保留或输出球员姓名、号码、前锋/后卫/门将等身份标签。
最多写到球队层级，例如“德国队球员”“库拉索球员”。
换人也只记录某队出现换人，不记录上下场球员姓名。

如果事项明显但细节不完整，可以输出 probable，并说明缺失信息。
不要因为缺少某一种证据就直接否定事项。
如果同一事项在 narrative 中被多次提到，请合并为一个事项，并保留最接近实际发生的时间点。
```

每个事项输出结构：

```json
{
  "event_id": "T0001",
  "event_type": "goal",
  "title": "德国队禁区内破门",
  "video_timestamp": "00:14:12",
  "match_time": "6'",
  "period": "first_half",
  "confidence": 0.86,
  "certainty": "probable",
  "evidence_level": "text_clear",
  "needs_image_review": true,
  "review_timestamp": "00:14:12",
  "evidence": [
    "narrative 中提到德国队禁区内射门得分",
    "后续出现庆祝或比分相关描述"
  ],
  "commentary_hint": "可以写成一次打破僵局的关键进球"
}
```

### 5. 图片回看保持 `±8 秒`

V3 暂时不做动态长窗口。图片回看仍然取 `review_timestamp ±8 秒`，2 秒一帧时通常最多 9 张：

```text
t-8, t-6, t-4, t-2, t, t+2, t+4, t+6, t+8
```

图片回看的定位：

- 它是补证据，不是唯一裁判。
- 如果图片明确支持事项，返回 `confirmed`。
- 如果图片没有看到但 narrative 明确，不要轻易 `rejected`，优先返回 `not_visible_in_window` 或 `uncertain`。
- 只有图片和 narrative 明确冲突时，才返回 `rejected`。

图片回看输出建议：

```json
{
  "event_id": "T0001",
  "verdict": "confirmed|probable|uncertain|not_visible_in_window|rejected",
  "event_type": "goal",
  "confidence": 0.78,
  "visual_evidence": ["看到德国队庆祝", "看到防守方门前倒地"],
  "missing_evidence": ["未直接看到球过门线"],
  "corrected_video_timestamp": "00:14:10",
  "notes": "窗口内能支持进球后状态，但不能单独确认破门瞬间"
}
```

### 6. V3 时间必须输出比赛时间

V1/V2 的主要时间是视频时间，例如 `01:42:08`。V3 下游展示和 report 需要改成比赛时间，例如 `第68分钟`、`45+5'`、`90+2'`。

V3 事件里同时保留两套时间：

```json
{
  "video_timestamp": "01:24:12",
  "match_time": "78'",
  "period": "second_half",
  "match_minute": 78,
  "stoppage_minute": 0
}
```

规则：

- `video_timestamp` 用于切视频、回看图片、定位素材。
- `match_time` 用于最终脚本、web 菜单、口播展示。
- 不能把 `01:42:08` 直接写成“第142分钟”。
- 比赛时间优先从比分牌、转播字幕、narrative 中的分钟信息提取。
- 如果没有明确比赛时间，用同半场锚点估算，并标注 `match_time_source=estimated`。

需要新增一个中间产物：

```json
{
  "match_time_anchors": [
    {
      "video_timestamp": "00:09:30",
      "match_time": "1'",
      "period": "first_half",
      "source": "scoreboard"
    }
  ]
}
```

### 7. 最终合并输出 `final_events_clean_v3.json`

V3 不让 report 直接消费粗糙 `final_events`，而是新增清洗后的事项文件。

输出文件建议：

- `outputs_event_agent_v3/text_agent_events_v3.json`
- `outputs_event_agent_v3/image_review_requests_v3.json`
- `outputs_event_agent_v3/image_review_results_v3.json`
- `outputs_event_agent_v3/match_time_anchors.json`
- `outputs_event_agent_v3/final_events_clean_v3.json`

`final_events_clean_v3.json` 要做到：

- 只包含 10 类目标事项。
- 合并重复事件。
- 庆祝、回放证据要挂到主事项，不要生成额外进球。
- 同一个点球进球可以同时体现 `penalty` 和 `goal`，但必须有关联字段，例如 `linked_event_id`。
- 每条事件必须有 `video_timestamp` 和 `match_time`。
- 每条事件必须有 evidence，不能只给结论。
- 所有 review 结果都要在这一层消化完。进入 report 生成之前，事项层必须已经完成确认、合并、去重、时间对齐和证据归档。

生成前检查门槛：

- `event_type` 必须属于 10 类目标事项。
- `match_time` 必须可展示，优先使用比赛时间；不能把视频时间误写成比赛分钟。
- `video_timestamp` 必须可用于切片和图片回看。
- `evidence` 不能为空。
- `needs_image_review=true` 的事项必须已经有 review 结果。
- `not_visible_in_window` 或 `uncertain` 可以保留，但要在 `certainty` 中体现，不允许在 report 阶段再假装确认。
- 点球进球、庆祝、回放证据必须和主事项关联，不能在最终输出里变成重复事件。
- 事件顺序按 `period -> match_minute -> stoppage_minute -> video_timestamp` 排序。

### 8. 最终 Report 生成层

Report 生成层只读取 `final_events_clean_v3.json`。这一层不再做事实检查、不再回看图片、不再新增事件，也不根据解说风格改动事实。它只负责把已经检查完的事项改写成最终可读产物。

最终产物只保留两个部分：

1. 事项事件表格。
2. 激情版解说文稿。

推荐输出文件：

- `outputs_script_report_v3/final_report_v3.md`
- `outputs_script_report_v3/final_report_v3.json`

Markdown 结构固定为：

```md
# 事项事件表格

| 序号 | 比赛时间 | 视频时间戳 | 事项类型 | 事件标题 | 确定性 | 证据摘要 |
|---:|---|---|---|---|---|---|
| 1 | 6' | 00:14:12 | 进球 | 德国队首开记录 | probable | narrative 明确描述破门和庆祝 |

# 激情版解说文稿

第6分钟，德国队终于撕开局面！禁区内这一脚处理果断直接，比赛的节奏瞬间被点燃……
```

JSON 结构固定为：

```json
{
  "event_table": [
    {
      "index": 1,
      "match_time": "6'",
      "video_timestamp": "00:14:12",
      "event_type": "goal",
      "title": "德国队首开记录",
      "certainty": "probable",
      "evidence_summary": "narrative 明确描述破门和庆祝"
    }
  ],
  "passionate_commentary": "第6分钟，德国队终于撕开局面！禁区内这一脚处理果断直接，比赛的节奏瞬间被点燃……"
}
```

事项事件表格的作用是让人快速核对：事件是否全、顺序是否对、时间是否对、类型是否符合 V3 的 10 类事项。激情版解说文稿的作用是模拟附件 4 的高燃解说风格，但必须覆盖表格里的全部事项，而不是只写进球。

生成 prompt 约束：

- 必须覆盖 `event_table` 里的每一条事项。
- 解说文稿按比赛时间自上而下推进。
- 可以有激情表达，但不能新增球员名、号码、场上位置/身份、比分、技术指标、判罚原因。
- 表格事实优先于文风；如果某条事项是 `probable` 或 `uncertain`，解说里要用更稳妥的措辞。
- 不输出额外章节，例如短视频口播、分镜、制作提示、内部复核备注。

### 9. Web Demo 后续对接

Web demo 不改变最终 report 的两个部分结构。后续如果要做交互页面，可以直接消费 `final_events_clean_v3.json` 和 `final_report_v3.json`：

- 一级菜单：事项类型，例如进球、点球、射门机会、角球、任意球、判罚、越位、换人、庆祝、半场/全场。
- 二级菜单：该类型下的事件序号或展示标签，例如 `6' 德国进球`、`45+5' 点球`。
- 点击事件后展示对应视频切片、比赛时间、解说词和 evidence 摘要。

## Version 4 Improvement Draft

Version 4 的目标是在 V3 的固定事项集合之上增加“事实拦截层”。V4 不扩大事项类型，不重新追踪球员身份，而是把容易下沉到 final report 的错误提前拦住：射门/进球误判、定位球时间点漂移、人名/号码/位置污染、非法事件类型、report 编造细节、比分链矛盾、以及 JSON 结构被错误接收。

### 1. 射门相关事项必须联合画面 narrative 和比分牌

所有射门相关事项都不能只看“球像不像进了”或“回放里像不像被扑”。`goal`、`shot_chance`、点球射门、任意球直接射门、角球后射门都必须综合：

- 画面 narrative：是否描述射门、入网、扑出、偏出、挡出、门框、庆祝、重新开球。
- 比分牌/字幕：射门前后比分是否变化，是否出现进球信息条，是否有全场进球名单反向确认。
- 时间关系：比分牌可能在进球后几十秒才出现，不能因为 `±8s` 内没看到比分牌就否定进球。
- 回放关系：回放只作为证据，不能单独推出新进球；同一比分下反复出现入网、庆祝或进球字幕，默认挂到同一主进球。

V4 给射门相关候选事项新增字段：

```json
{
  "shot_outcome": "goal|saved|missed|blocked|woodwork|unknown",
  "scoreboard_relation": "score_changed|score_unchanged|score_not_visible|score_conflicting",
  "score_before": "0-0",
  "score_after": "1-0",
  "score_evidence_timestamp": "00:15:42",
  "score_evidence_source": "scoreboard|subtitle|fulltime_scorer_list|narrative",
  "requires_score_chain_check": true
}
```

判定规则：

- 如果 narrative 写“球入网/破门/庆祝”，且后续比分牌或进球字幕确认比分变化，可以判为 `goal`。
- 如果看到射门但后续比分不变，优先判为 `shot_chance`，不能写“打破僵局”“扩大比分”。
- 如果看到球入网但比分不变，优先判为同一进球的回放/庆祝证据，不能新增 `goal`。
- 如果射门被扑、射偏、挡出、击中门框，只有在比分链确认没有变化时才能稳定写成 `shot_chance`；否则保留 `unknown/probable` 并交给拦截层。
- `goal` 的证据里必须至少有一个比分相关证据或明确进球字幕；纯视觉入网但无比分证据时不能自动升级为 confirmed。

### 2. 定位球只记录“获得判罚/准备执行”的时间点

角球、任意球、点球这三类判罚类事项，V4 默认只记录获得判罚或准备执行的时间点，不把后续传中、射门、进球混进同一事项。

| event_type | V4 记录点 | 不默认记录 |
|---|---|---|
| `corner` | 获得角球、角球区准备开球、字幕/裁判确认角球 | 角球开出后的每一次争顶、解围、混战 |
| `free_kick` | 获得任意球、定点摆球、人墙准备、裁判示意 | 任意球开出后的普通传球、普通争抢 |
| `penalty` | 获得点球判罚、裁判指向点球点、点球准备 | 点球射门结果本身 |

如果定位球之后直接产生射门或进球，则创建独立的 `shot_chance` 或 `goal`，并用 `linked_event_id` 关联原定位球事项。例如：

```json
{
  "event_id": "F0010",
  "event_type": "penalty",
  "title": "德国队获得点球判罚"
}
```

```json
{
  "event_id": "F0011",
  "event_type": "goal",
  "title": "德国队点球破门",
  "linked_event_id": "F0010"
}
```

这样可以避免“获得任意球”“任意球开出”“任意球进球”被混成一个时间点，也可以避免 report 把定位球机会当成已经射门得分。

### 3. 新增 V4 拦截层

V4 在模型 review 和 report 之间增加 deterministic guardrail。它不负责写稿，不负责补脑，只负责拦截违规信号、降级不稳定结论、生成可审计的拦截报告。

新增流程：

```text
narrative -> text event agent -> image/model review -> final consolidation
-> V4 guardrail interceptor -> final_events_guarded_v4.json
-> report generator
```

推荐输出文件：

- `outputs_event_agent_v4/final_events_clean_v4.json`
- `outputs_event_agent_v4/final_events_guarded_v4.json`
- `outputs_event_agent_v4/guardrail_findings.json`
- `outputs_event_agent_v4/guardrail_report.md`
- `outputs_script_report_v4/final_report_v4.md`

拦截层原则：

- 不凭空新增事实。
- 不把 uncertain 改成 confirmed。
- 不直接写最终解说文稿。
- 能确定违规则拦截或降级；不能确定则标记 `needs_more_review=true`。
- 所有拦截必须记录原因、命中的规则、原字段、新字段。

### 4. V4 必须拦截的违规信号

#### 4.1 人名、号码、位置、身份污染

V4 继续不追踪球员身份。最终事项和 report 中不允许出现：

- 球员姓名，例如从字幕 OCR 或模型猜测来的姓名。
- 球衣号码，例如 `10号`、`23号`、`#7`。
- 场上位置/身份，例如前锋、后卫、中场、队长、主罚手等。
- 未经任务要求的教练姓名、裁判姓名、个人身份介绍。

如果为了表达射门被化解，需要避免把身份写死；优先写：

- “射门被防守方扑出”
- “射门被化解”
- “防守方完成扑救”

而不是在最终稿里继续保留具体人名或号码。

#### 4.2 非 V4 事项集合的事件类型

最终事项只允许 V3/V4 的 10 类：

```text
goal, penalty, shot_chance, corner, free_kick,
foul_card_dispute, offside, substitution, celebration, half_full_time
```

下列类型必须被拦截或合并：

- `replay`
- `attack_highlight`
- `dead_ball`
- `crowd`
- `bench`
- `close_up`
- `live_play`
- `scoreboard`
- `lineup`
- `hydration_break`
- 任何模型临时编造的新 event_type

其中 `replay`、`scoreboard`、`close_up` 可以作为 evidence，但不能作为最终事项。

#### 4.3 非动作表动作或过度细节

report 不能凭空把事件写成动作表外的细节。尤其拦截：

- 未在 evidence 中出现的“远射、头球、凌空、单刀、弧线球、鱼跃、倒钩、补射、助攻、传中”等具体动作。
- 未在 evidence 中出现的“速度、旋转率、距离、角度、概率、xG、百分比”等技术指标。
- 未经证据支持的“故意犯规、战术犯规、情绪失控、绝杀、世界波”等解释性标签。

如果 evidence 只支持“射门”，最终稿只能写“射门”；如果 evidence 只支持“进球”，不能自动扩写成“远射破门”或“头球破门”。

#### 4.4 比分链矛盾

所有 `goal` 必须进入比分链检查：

- goal 数量必须能解释最终比分。
- `score_after` 不能跳跃、倒退或重复新增。
- 同一比分下的入网/庆祝/字幕只能作为同一主进球的证据。
- 如果 fulltime scoreboard/进球名单里没有支撑某个进球，该进球必须降级为 `shot_chance`、`celebration` 或 `needs_more_review`。
- 如果比分链显示缺少进球，允许生成 `scoreboard_backfill` 候选，但必须标明来源，不允许 report 直接当作画面已确认。

#### 4.5 射门结果和比分状态冲突

拦截层需要专门扫 `goal` 和 `shot_chance`：

- 标题写“打破僵局/扩大比分”，但 `scoreboard_relation != score_changed`，拦截。
- 标题写“被扑出/射偏/射飞”，但后续比分牌确认比分变化，拦截并要求重审。
- evidence 写“球入网”，但同一事项 event_type 是 `shot_chance`，标记冲突。
- evidence 写“被扑出”，但 event_type 是 `goal`，标记冲突。

#### 4.6 定位球时间点漂移

`corner/free_kick/penalty` 必须检查 `set_piece_phase`：

```json
{
  "set_piece_phase": "awarded|preparation|taken|result"
}
```

V4 final 只保留 `awarded` 或 `preparation` 作为定位球事项主时间点。`taken/result` 如果产生射门或进球，应改为 linked `shot_chance/goal`，否则不单列。

#### 4.7 视频时间和比赛时间混淆

拦截层必须禁止：

- 把 `01:42:08` 写成“第142分钟”。
- 把 `00:14:12` 写成“第14分钟”，除非 scoreboard/match_time 也支持。
- report 自行从视频时间推导比赛时间。

report 只能使用事件里的 `match_time` 展示比赛分钟。

#### 4.8 report 新增事实

report 只能消费 `final_events_guarded_v4.json`。如果 report 中出现表格没有的内容，必须标记：

- 新比分。
- 新进球。
- 新球员/号码/位置。
- 新判罚原因。
- 新动作细节。
- 新技术指标。

report 的激情表达可以增强语气，但不能增加事实。

#### 4.9 JSON/schema 异常

V4 继承 JSON repair 和 strict schema 验收：

- text agent 顶层必须有 `events`。
- review 顶层必须有 `event_id/verdict`。
- final 顶层必须有 `final_events`。
- 不能接受内部 JSON fragment 当成功结果。
- `finish_reason=length` 必须失败重试。
- repair 后仍不满足 schema 的结果必须进入失败队列，不进入后续事项池。

### 5. 从 V2/V3 回忆出的额外拦截项

根据 V2/V3 已经出现的问题，V4 还应该拦截：

1. 第三方队名污染：哥伦比亚、委内瑞拉、美国、巴拉圭等非本场队名不能进入 final/report。
2. replay 误升新进球：回放、庆祝、进球信息条复现不能自动变成新进球。
3. 首球误杀：如果后续 scoreboard 明确确认 `1-0` 和进球信息，不能因为短窗口图片 review 看不见入网瞬间就 reject。
4. 缺失进球链：最终比分是 `7-1` 时，进球链必须解释 8 个进球；少球要标红。
5. 点球链断裂：点球判罚和点球进球要能 linked，不能只保留判罚或只保留结果。
6. report 编造技术指标：速度、旋转、距离、概率、百分比全部需要 evidence 白名单。
7. 不确定事项被写实：`probable/uncertain` 在 report 中不能写成已经确定发生。
8. 换人细节污染：换人只写某队换人，不写上下场姓名、号码或位置。
9. 低价值庆祝单列过多：庆祝默认挂到主进球，除非确实是独立高价值镜头。
10. 证据和标题冲突：title、event_type、evidence、script_angle 互相矛盾时，必须拦截。

### 6. V4 最小实现建议

第一版 V4 不需要重写全链路，先做三个补丁即可：

1. 在 text event/final schema 里增加 `shot_outcome`、`scoreboard_relation`、`score_before`、`score_after`、`set_piece_phase`。
2. 在 final consolidation 后新增 `guardrail_interceptor.py`，输出 guarded final 和 guardrail report。
3. 让 report 只读取 `final_events_guarded_v4.json`，并在生成后再跑一次 report fact scan。

这三个补丁能先解决当前最明显的错误：射门和进球混淆、定位球时间点混乱、人名/非法动作下沉、report 自行编造事实。
