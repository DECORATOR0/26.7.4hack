# Video Text Pipeline

这个目录用于沉淀“比赛视频 -> 视觉观察文本 -> 关键事件 -> 解说脚本”的迭代版本。

当前版本：

- `outputs_script_report_v4/final_report_v4.md`：当前 V4 交付报告。事项列表全量列出，解说文案按关联事项合并成分段。
- `outputs_event_agent_v4/final_events_guarded_v4.json`：当前 V4 guardrail 后的事项 JSON。
- `version3_current_markdown.md`：当前 V3 交付报告。打开后先看到事项表格，下面是解说台词。
- `version1_text_first.md`：已跑通的 Version 1，采用 2 秒抽帧、每分钟视觉转文字、再由文本 Agent 抽取事件。

后续建议每次重要改动新增一个版本文档，例如：

- `version2_5s_team_constrained.md`
- `version3_score_chain_verified.md`
