# Harness 设计决策：固定主流程 + Intern-S2 局部智能

记录日期：2026-07-04

关联文档：

- `docs/original_problem_statement.md`
- `docs/harness_architecture.md`
- `docs/event_detection_spec.md`

## 1. 当前结论

世界杯视频解说任务的目标是端到端自动完成：

```text
输入比赛视频 -> 输出解说脚本和结构化事件结果
```

中间过程包括视频预处理、抽帧、视觉事件识别、事件合并、脚本生成、事实校验和导出。这个流程本身已经足够复杂，不需要为了“Agent 感”强行让 Intern-S2-Preview 决定所有步骤。

当前设计原则：

```text
该自动化的确定性步骤，由 Harness 自动执行。
该由 Intern-S2 判断的语义步骤，交给 Intern-S2。
整体目标优先保证稳健性、可复现性、端到端打通。
```

## 2. 为什么不让模型决定所有工具调用

抽帧、读取视频元信息、生成批次、写入文件、导出字幕这类操作是确定性工程步骤。它们在世界杯视频解说任务里是必经流程，让模型判断“是否需要抽帧”没有实际收益，反而会带来：

- 运行路径不稳定
- 成本不可控
- 失败点增多
- 现场演示风险变高
- 难以复现和调试

因此，固定主流程不是问题。题面要求的是一个可执行、可反馈、可验证的 Harness，而不是一个无约束自由路由 Agent。

## 3. 推荐架构

采用双层控制：

```text
第一层：确定性 Workflow
负责视频处理、批处理、文件产物、输出导出。

第二层：Intern-S2 Agent Loop
负责语义判断、事件归纳、低置信度处理、事实校验和解说生成。
```

端到端流程：

```text
输入视频
-> Harness 自动 inspect_video
-> Harness 自动 extract_frames
-> Harness 自动 build_batches
-> Intern-S2 执行 multi_event_judge
-> Harness 自动 merge_events
-> Intern-S2 执行 verify_or_repair
-> Intern-S2 执行 commentary_writer
-> Harness 自动 export_outputs
```

## 4. 哪些事情由 Harness 自动做

这些步骤应当由代码稳定执行，不交给模型自由决定：

- 检查输入视频是否存在
- 读取视频时长、FPS、分辨率
- 按固定间隔抽帧
- 压缩图片到 API 可接受大小
- 将图片切成 batch
- 控制 RPM、并发数和重试
- 保存原始模型响应
- 解析 JSON
- 合并重复事件
- 按时间排序
- 根据置信度过滤事件
- 导出 `visual_events.json`
- 导出 `merged_events.json`
- 导出 `commentary.md`
- 导出 `subtitles.srt`
- 导出 `run_log.md`
- 导出 `report.md`

这些内容体现的是 Harness 的工程外壳，而不是简单 prompt。

## 5. 哪些事情交给 Intern-S2

这些步骤需要视觉语义理解、文本归纳或风格化生成，适合交给 Intern-S2：

- 判断一批帧中是否存在有解说价值的事件
- 判断事件类型，例如进球、回放、角球、任意球、换人、出牌、争议、进攻高光
- 给出事件置信度和视觉证据
- 判断 replay 应该关联到哪个前序事件
- 对低置信度事件做复核
- 检查时间线是否自洽
- 在事实约束下生成中文激情解说
- 根据结构化事件生成字幕和集锦讲解文案
- 输出 Intern-S2 能力不足与提升空间分析

## 6. 受控路由，而不是完全自由路由

当前 Harness 不做任意自由路由，但需要保留受控条件分支：

```text
low_confidence_event -> event_verifier
too_few_events -> rescan_selected_windows
replay_detected -> link_replay_to_previous_event
fact_check_failed -> repair_timeline
api_error -> retry_or_backoff
batch_too_large -> split_batch
```

这些条件分支足够体现工具编排与 Agentic Harness 思路，同时不会破坏稳定性。

## 7. 答辩表述

推荐答辩说法：

```text
我们没有把世界杯解说做成无约束的自由 Agent，因为长视频多模态任务成本高、错误传播强、现场演示需要稳定复现。

我们的 Harness 采用双层控制：确定性 workflow 负责视频处理、批处理和文件产物；Intern-S2 Agent Loop 负责视觉语义识别、事件归纳、事实校验和解说生成。

系统每一步都有明确输入输出、失败策略、运行日志和中间产物，因此不是一次性 prompt，而是一个可执行、可反馈、可验证的端到端 Harness。
```

## 8. 对当前实现的要求

短期目标是先端到端打通，优先级如下：

1. 稳定输入视频，自动抽帧。
2. 低成本调用 Intern-S2 做多事件合并识别。
3. 生成结构化事件时间线。
4. 生成解说脚本。
5. 输出可检查的运行报告。
6. 再补充工具注册表和受控路由日志。

不是当前优先级：

- 不强行引入完全自由的工具调用。
- 不强行让 Intern-S2 决定抽帧、写文件、导出字幕等确定性步骤。
- 不为了 LangGraph 而 LangGraph。
- 不做过多复杂多智能体，除非端到端主流程已经稳定。

## 9. 当前架构一句话

```text
以稳健端到端为第一目标，用确定性工具处理视频和产物，用 Intern-S2 处理语义判断和文本生成，用受控路由处理异常和低置信度情况。
```
