# 视觉检测实验效果复盘

记录时间：2026-07-04

## 1. 容易混淆的三组输出

### A. 2 秒一帧 + 9 个 detector 分开扫

输出目录：

```text
outputs_visual_full_safe/
```

真实配置和进度：

```text
抽帧间隔: 2 秒
总帧数: 3327
计划请求数: 1368
detectors: goal_celebration, replay, corner, free_kick, penalty,
           substitution, card_scene, referee_dispute, attack_highlight
已完成 raw batch: 108
实际覆盖: 00:00:00 - 00:08:46
已消耗 tokens: 988081
按当前均值推全场 tokens: 约 12515693
```

效果判断：

- 前 11 批基本都正确识别为赛前仪式、阵容展示、裁判介绍，没有乱报角球、任意球、点球、换人、出牌。
- 第 12 批报出两个事件：
  - `00:08:04 replay`，置信度 0.6。
  - `00:08:06 goal_or_celebration`，置信度 0.95。
- 肉眼复核对应帧后，`00:08:06` 是德国队球员围圈抱肩的 huddle，不是进球庆祝；`00:08:04` 也更像全场/大屏镜头，不是明确 replay。

结论：

```text
这个方案召回粒度细，专项 detector 在赛前阶段多数时候比 MultiEventJudge 更克制；
但成本过高，而且仍会把“球员围圈/抱肩”误判成进球庆祝。
不建议全场继续跑 9 detector。
```

## 2. 5 秒一帧 + MultiEventJudge 全场

输出目录：

```text
outputs_visual_multi_full/
```

注意：目录里的文件名仍叫 `frame_index_2s.json`，但这次真实命令使用的是 `--interval 5`。

运行统计：

```text
抽帧间隔: 5 秒
总帧数: 1331
请求数: 61
成功: 61
失败: 0
原始事件: 103
合并事件: 60
总 tokens: 586414
耗时: 132.315 秒
```

效果判断：

- 优点：
  - 成本从约 1200 万 tokens 降到约 58.6 万 tokens。
  - 能快速给出全场候选，适合作为第一阶段召回。
  - 能覆盖进球、回放、角球、换人、争议、全场结束等类型。
- 问题：
  - 赛前仪式误报明显，例如 `00:03:40 halftime`、`00:06:45 replay`。
  - goal_or_celebration 数量过多，合并后仍有 32 个，明显超过真实进球数。
  - replay、substitution、card_scene 都需要证据约束和二次验证。

结论：

```text
MultiEventJudge 可以作为低成本召回器，但不能直接作为最终 events.json。
```

## 3. 2 秒一帧 + 按分钟视觉转文字

输出目录：

```text
outputs_frame_narration_full/
```

运行统计：

```text
抽帧来源: outputs_visual_full_safe/frame_index_2s.json
段数: 111
成功: 111
失败: 0
总 tokens: 1543232
平均 tokens/分钟段: 13903
```

效果判断：

- 它不直接判最终事件，而是把每分钟的画面压缩成文本观察。
- 对 `00:08` 附近更保守：没有把德国队围圈直接写成进球。
- 在 `00:09:16` 看到比分牌 `德国 0-0 库拉索` 和比赛时间 `00:10`，基本能定位真正开球后的 live_play。

结论：

```text
这条链路成本比 9 detector 全扫低很多，比 MultiEventJudge 更适合做事实约束。
推荐后续用它先生成 observation timeline，再从文本里抽事件并做少量图像复核。
```

## 4. 当前推荐路线

不继续跑 1200 万 tokens 的 9 detector 全场方案。

推荐主流程：

```text
2 秒抽帧
-> 按分钟视觉转文字 observation timeline
-> 文本事件抽取
-> 对候选进球/点球/红黄牌/换人做局部图片 verifier
-> 合并 replay 和庆祝镜头
-> 输出最终 events.json 和解说稿
```

这样比 MultiEventJudge 直接出最终结果稳，也比 9 detector 全扫省。

