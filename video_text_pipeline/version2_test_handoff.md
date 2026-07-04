# Version 2 Test Handoff

## 当前状态

- 状态：已完成
- 启动时间：`2026-07-04 22:45:53 +08:00`
- 结束时间：`2026-07-04 23:10:22 +08:00`
- 后台进程 PID：`9092`，已结束
- 日志：`logs/version2_test.stdout.log`、`logs/version2_test.stderr.log`
- 状态文件：`version2_test_status.json`

## Version 2 运行结果

### Stage 1: 视频转文字

- 输出目录：`outputs_frame_narration_v2`
- segments：`111`
- success：`111`
- failures：`0`
- `finish_reason=length`：`0`
- 最大 completion tokens：`4737`
- total tokens：`1,688,471`
- 队名误识别快速检查：未在 timeline 中搜到 `哥伦比亚`、`委内瑞拉`、`美国`、`巴拉圭`

### Stage 2: 文字转关键事项

- 输出目录：`outputs_event_agent_v2`
- text chunks：`10`
- text candidate events：`39`
- image review calls：`16`
- final events：`35`
- total tokens：`324,455`

### Stage 3: 事项转解说脚本/report

- 输出目录：`outputs_script_report_v2`
- input events：`35`
- status：`ok=true`
- finish_reason：`stop`
- total tokens：`14,084`
- Markdown 字符数：`11,106`

## 测试目标

本轮是 Version 2 小步迭代测试，不改抽帧密度，仍然使用 `2 秒/帧` 的全场帧索引。

输入：

- 帧索引：`outputs_visual_full_safe/frame_index_2s.json`
- 比赛信息：`examples/match_info.germany_curacao.json`
- 比赛：德国 vs 库拉索

本轮重点验证三项改进：

1. 视频转文字阶段加入队名/国籍约束，避免把库拉索误写成哥伦比亚、委内瑞拉等第三方国家队。
2. 视频转文字 `max_tokens` 从 `1800` 提升到 `6000`，文字转事项 `text_max_tokens` 从 `5000` 提升到 `10000`。
3. 端到端补上 `final_events -> commentary_report.md` 的脚本/report 生成阶段。

## 固定参数

### Stage 1: 视频转文字

```bash
python run_frame_narration.py \
  --frame-index outputs_visual_full_safe/frame_index_2s.json \
  --out outputs_frame_narration_v2 \
  --segment-seconds 60 \
  --max-images 30 \
  --concurrency 3 \
  --rpm-limit 15 \
  --temperature 0.1 \
  --max-tokens 6000 \
  --resume
```

输出：

- `outputs_frame_narration_v2/segment_descriptions.json`
- `outputs_frame_narration_v2/match_observation_timeline.md`
- `outputs_frame_narration_v2/raw_segments/`
- `outputs_frame_narration_v2/narration_runtime_summary.json`

### Stage 2: 文字转关键事项

```bash
python run_event_agent.py \
  --descriptions outputs_frame_narration_v2/segment_descriptions.json \
  --frame-index outputs_visual_full_safe/frame_index_2s.json \
  --out outputs_event_agent_v2 \
  --chunk-segments 12 \
  --concurrency 3 \
  --rpm-limit 12 \
  --temperature 0.1 \
  --text-max-tokens 10000 \
  --final-max-events 30 \
  --resume
```

输出：

- `outputs_event_agent_v2/text_agent_events.json`
- `outputs_event_agent_v2/image_review_results.json`
- `outputs_event_agent_v2/final_events.json`
- `outputs_event_agent_v2/event_agent_report.md`
- `outputs_event_agent_v2/event_agent_runtime_summary.json`

### Stage 3: 事项转解说脚本/report

```bash
python run_script_report.py \
  --events outputs_event_agent_v2/final_events.json \
  --match-info examples/match_info.germany_curacao.json \
  --out outputs_script_report_v2 \
  --temperature 0.2 \
  --max-tokens 10000
```

输出：

- `outputs_script_report_v2/commentary_report.md`
- `outputs_script_report_v2/script_report_raw.json`
- `outputs_script_report_v2/script_report_runtime_summary.json`

## 一键启动脚本

```bash
powershell -ExecutionPolicy Bypass -File scripts/run_version2_test.ps1
```

后台启动后看日志：

```powershell
Get-Content logs/version2_test.stdout.log -Tail 50
Get-Content logs/version2_test.stderr.log -Tail 50
Get-Content version2_test_status.json
```

## TPM/RPM 口径

当前 API 限制：

- RPM：`30`
- TPM：`300000`

本轮参数极限估算：

- 视频转文字：最大约 `18,487 tokens/request * 15 RPM = 277,305 TPM`
- 文字转事项：最大约 `21,133 tokens/request * 12 RPM = 253,596 TPM`
- 图片复核：最大约 `8,518 tokens/request * 12 RPM = 102,216 TPM`
- report 阶段是单次请求，不形成持续 RPM 压力。

## 接手后优先检查

1. `outputs_frame_narration_v2/narration_runtime_summary.json`
   - 看 `failures` 是否为 `0`
   - 看 raw segments 是否还有 `finish_reason=length`

2. `outputs_frame_narration_v2/match_observation_timeline.md`
   - 搜索是否还有 `哥伦比亚`、`委内瑞拉`、`美国`、`巴拉圭`
   - 检查库拉索是否被稳定识别

3. `outputs_event_agent_v2/event_agent_report.md`
   - 看最终事件时间线是否明显重复
   - 重点看进球和 replay 是否被混淆

4. `outputs_script_report_v2/commentary_report.md`
   - 看是否像可交付文稿
   - 看是否编造了未在 `final_events` 里的球员、助攻、牌色、判罚原因

## 后续 Web Demo 交互方案

初步方案是做一个菜单式事件浏览器，用于展示“模型识别到的关键事项 + 对应视频片段 + 解说文本”。

页面结构：

- 主区域：播放对应比赛片段。
- 下方或侧边：显示该片段对应的解说文字，可以做逐句动态字幕。
- 事件导航：大菜单叠小菜单。

菜单设计：

1. 大菜单按高光事项类型分组。
   - 例如：进球、回放、任意球、角球、换人、争议判罚、攻势高光、半场/全场。
   - 数据来源：`final_events[].event_type`。

2. 小菜单显示该事项类型下的具体事件。
   - 暂定使用序号，例如 `进球 1`、`进球 2`。
   - 也可以用更有信息量的标识，例如 `1-0`、`2-1`、`57:22 任意球破门`。
   - 数据来源：`final_events[].timestamp`、`title`、`script_angle`，后续如果有比分链，也可以用比分作为标签。

3. 点击“大菜单 -> 小菜单”后，弹出或切换到对应事件详情。
   - 播放该事件前后的视频片段。
   - 显示事件标题、时间戳、可信度、证据摘要。
   - 显示对应解说文字。
   - 可选显示模型证据：关键帧、`visual_evidence`、`text_evidence`。

视频片段规则：

- 默认以事件 `timestamp` 为中心切片。
- 进球/高光类：前 `10-15s`，后 `15-25s`。
- replay 类：前 `5-8s`，后 `8-12s`。
- 换人/争议/定位球：前后各 `8-12s`。
- 后续可以按事件类型在前端或预处理脚本中配置。

展示重点：

- 让评委看到：系统不是只生成一篇文字，而是能把“关键事项 -> 视频证据 -> 解说稿”对应起来。
- replay/celebration 要标识清楚，避免看起来像重复进球。
- 解说词不需要全部一次性铺开，优先做动态字幕或逐句浮现。

## 备注

- Version 2 仍然使用 `2 秒/帧`，不是 `5 秒/帧`。
- 本轮不是最终质量版，主要验证新参数、新队名约束和端到端 report 形态。
- 缓存现在带 `request_fingerprint`，旧 Version 1 截断结果不会被误复用。
