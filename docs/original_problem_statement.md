# 原题与 Harness 理解备忘

来源：赛题页面粘贴文本，附件路径：

```text
C:\Users\HP\.codex\attachments\e47622a2-9d51-4049-93aa-9183051cd5f1\pasted-text.txt
```

记录日期：2026-07-04

关联设计决策：`docs/harness_design_decision.md`

## 1. 赛题名称

基于 Intern-S2-Preview 的 Agentic Harness 开发挑战。

题面强调：Harness 不只是简单调用大模型 API，而是围绕模型构建一套可执行、可反馈、可验证的任务完成系统，包括：

- 任务拆解
- 工具调用
- 上下文管理
- 结果检查
- 迭代优化

## 2. 可选任务方向

参赛队伍需要在以下方向中任选一个：

- 代码漏洞检测 Harness
- PPT 生成与美化 Harness
- 世界杯视频解说 Harness
- 学术论文综述生成 Harness

当前项目选择第三项：世界杯视频解说 Harness。

## 3. 世界杯视频解说 Harness 原题要求

构建一个世界杯视频解说 Harness，针对：

```text
2026 年美加墨世界杯 E 组第 1 轮德国 7:1 大胜库拉索
```

需要完成：

- 解说脚本生成
- 关键事件识别
- 风格化激情解说
- 根据视频内容生成连贯、准确、有现场感的比赛解说文本
- 可进一步辅助生成用于配音、字幕、集锦讲解的结构化输出

出题人提供整场比赛视频文件。题面中提到下载地址需要访问密码：

```text
D&742518
```

## 4. 模型使用限制

开发 Harness 时可以使用任意大模型或开发工具辅助系统设计与代码实现。

但最终任务运行、现场演示和评审测试环节中，Harness 的核心大模型调用必须使用主办方提供的 Intern-S2-Preview API。

因此本项目必须保留标准配置接口：

- API Base URL
- API Key
- 支持环境变量读取

评审时主办方会填入新的 Intern-S2-Preview API 进行运行测试。

## 5. 配套资源与链接

题面明确给出的链接：

| 资源 | 链接 | 当前项目是否必需 |
| --- | --- | --- |
| Intern-S2-Preview 官网/API 入口 | https://chat.intern-ai.org.cn | 必需 |
| MinerU 官网 | https://mineru.net/ | 不必需，偏 PPT/论文方向 |
| MinerU API 文档 | https://mineru.net/apiManage/docs | 不必需 |
| Sciverse 官网 | https://sciverse.space/ | 不必需，偏论文方向 |
| Sciverse API 文档 | https://sciverse.space/docs#sciverse/api | 不必需 |

题面提到但页面粘贴文本没有直接给 URL 的 Harness 参考资料，已检索到候选链接：

| 题面名称 | 检索到的候选链接 | 用途 |
| --- | --- | --- |
| The Anatomy of an Agent Harness | https://www.langchain.com/blog/the-anatomy-of-an-agent-harness | 理解 Harness 的基本组成 |
| Harness design for long-running application development | https://www.anthropic.com/engineering/harness-design-long-running-apps | 理解长程任务、多智能体、工具编排 |
| 智能体 Harness 工程指南 | https://yeasy.gitbook.io/harness_engineering_guide | 中文 Harness 工程参考 |
| harness-engineering-guide | https://github.com/nexu-io/harness-engineering-guide | 开源 Harness 设计资料 |
| Pi agent | https://pi.dev/ 和 https://github.com/earendil-works/pi | 可参考的最小 Agent Harness |
| oh-my-openagent | https://github.com/code-yeongyu/oh-my-openagent | 可参考的 Agent Harness 项目 |

补充参考：

| 资料 | 链接 | 说明 |
| --- | --- | --- |
| OpenAI Harness Engineering | https://openai.com/index/harness-engineering/ | 解释为什么上下文、约束、工具、可读性比单纯 prompt 更重要 |

## 6. 附录一对 Harness 的定义

题面给出的核心定义：

```text
Harness 可以定义为，模型之外，能让 agent 稳定完成任务的一整套工程外壳。
```

题面示例的 Agent Loop：

```text
用户发起请求
-> 构建上下文
-> 调用模型
-> 判断是否要调用工具
-> 执行工具
-> 把结果返回给模型
-> 继续下一轮工具调用
-> 最终得到回答
```

题面同时指出，如果工具较多，可以考虑使用 MCP 协议管理全部工具。

## 7. 题面要求考虑的问题

工具调用相关：

- 任务需要哪些工具？
- 每个工具的调用说明如何写入提示词？
- 每个工具能访问哪些路径？
- 如何控制读取权限？
- 工具调用失败怎么办？
- 工具调用超时怎么办？
- 工具调用结果过长如何截断？

可选高级能力：

- Skill 系统
- Memory 系统
- Sandbox 架构
- Prompt cache 优化
- 长程任务上下文压缩
- Sub-agent 机制
- 多智能体协作
- Plan 模式

## 8. 交付要求

基础要求：

- 完成一个可运行的 Harness 原型，能够围绕所选任务方向执行完整流程。
- 提供源代码，并包含必要运行说明。
- 代码或配置中留出标准 API Base URL 和 API Key 接口。
- 展示所选方向的输出结果。世界杯方向对应解说文本或精彩片段剪辑成片。
- 提交表格，给出 Intern-S2-Preview 的能力不足与提升空间分析。
- Presentation 环节清晰介绍 Harness 设计思路、实现方案、运行结果、结果分析。
- 团队成员超过 1 人时，需要说明每位成员职责和贡献占比。

加分项：

- 提供可现场演示的 Demo，展示从输入任务到输出结果的完整过程。
- 如果运行时间较长，可以快进播放提前录制的结果。
- 支持 Skill、Memory、Sandbox 等高级能力。

## 9. 附件与 baseline

题面附件：

- 附件1：`transformers_optimization_report.md`
- 附件2：`GPT发展历程.html`
- 附件3：`game_craft_agent_world_model_research.md`
- 附件4：`美国VS巴拉圭_2026世界杯解说脚本.md`

附件4是世界杯解说方向的 baseline 输出参考，不是必须照抄的输入格式。它说明最终结果可以包含：

- 解说脚本文稿
- 详细事件
- 多语言解说

我们当前项目可以输出更结构化的版本：

- `visual_events.json`
- `merged_events.json`
- `commentary.md`
- `subtitles.srt`
- `highlights.json`
- `run_log.md`
- `report.md`

## 10. 对当前方案的判断

当前理解基本正确：世界杯视频解说不是最适合做“完全自由路由 Agent”的任务。它的输入和目标都很明确，合理做法是一个固定主流程，加少量受控条件路由。

推荐定义为：

```text
固定主流程 + 工具注册表 + 条件路由 + 证据链 + 校验回路
```

也就是说，主流程可以固定：

```text
视频输入
-> 视频预处理/抽帧
-> 多模态证据提取
-> 视觉事件识别
-> 事件合并与时间线构建
-> 解说脚本生成
-> 事实校验
-> 结构化输出
```

但中间要体现 Harness 能力：

- 每个阶段有明确输入输出。
- 工具不是隐含在代码里，而是以 tool registry 的形式声明。
- Intern-S2-Preview 不是一次性写稿，而是在事件识别、合并、生成、校验阶段多次被调用。
- 每次调用产生可追踪的中间产物。
- 低置信度事件不直接进入最终解说。
- replay 自动关联前序事件。
- 如果事件太少或校验失败，可以触发局部重扫或修正。
- 最终输出要能回溯到视频时间戳和证据帧。

## 11. “没有太多自由路由”是否有问题

没有明显问题。题面要求的是 Harness，而不是必须实现一个任意工具自由调用的通用 Agent。

对世界杯视频解说这个任务来说，完全自由路由反而有几个风险：

- 成本不可控：模型可能反复扫描视频或重复调用视觉模型。
- 稳定性差：不同运行可能走出不同路径，现场演示风险高。
- 难校验：自由生成容易编造球员、动作、时间。
- 难复现：评审用新 API key 运行时不一定得到一致结果。

因此更适合的答辩说法是：

```text
我们没有把世界杯解说做成无约束的自由 Agent，而是把 Agent 能力收敛在一个可验证的状态机里。
系统通过工具组合完成确定性工作，通过 Intern-S2-Preview 完成语义判断、事件归纳和解说生成，通过校验器保证输出能回溯到视频证据。
```

## 12. 当前项目需要补强的点

为了更贴合题面，建议代码层面补强三件事：

1. 工具注册表

   明确声明每个工具的名称、输入、输出、失败策略，例如：

   - `FrameExtractor`
   - `MultiEventJudge`
   - `EventMerger`
   - `ScriptWriter`
   - `FactChecker`
   - `ReportWriter`

2. 受控路由

   不做任意自由路由，但做条件分支：

   - `need_rescan`
   - `need_verify`
   - `need_fact_fix`
   - `skip_low_confidence`
   - `link_replay_to_previous_event`

3. 运行报告

   每次运行保存：

   - 工具调用次数
   - 输入帧数量
   - API 请求数
   - token 用量估算或真实 usage
   - 失败和重试记录
   - 最终事件数量
   - 置信度分布

这三件事比强行引入复杂多智能体更能贴合当前任务。
