# MultiEventJudge 全视频实验报告

## 1. 运行配置

命令：

```bash
python run_visual_spotting.py ^
  --video "德国_库拉索.mp4" ^
  --out outputs_visual_multi_full ^
  --interval 5 ^
  --batch-sizes 22 ^
  --detectors multi ^
  --concurrency 4 ^
  --rpm-limit 28 ^
  --temperature 0.1
```

说明：

- 每 5 秒抽 1 帧。
- 每批 22 张图，约覆盖 110 秒。
- 每批只调用一次 `MultiEventJudge`，同时识别多个事件。
- 不再对每个事件单独跑 detector。

## 2. 结果文件

```text
outputs_visual_multi_full/frame_index_2s.json
outputs_visual_multi_full/spotting_plan.json
outputs_visual_multi_full/batch_results.json
outputs_visual_multi_full/visual_events.json
outputs_visual_multi_full/merged_events.json
outputs_visual_multi_full/visual_spotting_report.md
outputs_visual_multi_full/token_summary.json
outputs_visual_multi_full/raw_batches/
```

## 3. 运行统计

```text
抽帧数量: 1331
API 请求数: 61
成功请求: 61
失败请求: 0
原始视觉事件: 103
合并后事件: 60
总 tokens: 586414
平均 tokens/request: 9613
```

对比之前 9 detector 全扫方案：

```text
旧方案估计: 约 1200 万 tokens
新方案实际: 约 58.6 万 tokens
成本下降约 20 倍
```

## 4. 识别到的主要事件类型

`outputs_visual_multi_full/merged_events.json` 里合并出了 60 个事件，类型包括：

```text
goal_or_celebration
replay
attack_highlight
corner
free_kick
card_scene
referee_dispute
substitution
halftime
fulltime
```

其中模型能比较稳定识别：

- 进球/庆祝/比分牌变化
- 进球后的 replay
- 部分角球
- 部分争议/裁判场景
- 全场结束

局部片段中表现较好：

```text
00:14:25 - 00:15:15
识别到德国 1-0 进球、庆祝、回放，置信度 0.90-0.95。
```

## 5. 主要问题

### 5.1 赛前仪式误报

模型把赛前入场、球员列队、阵容展示等误判为：

```text
halftime
replay
attack_highlight
```

例如：

```text
00:03:40 -> halftime
00:06:45 -> replay
00:08:15 -> attack_highlight
```

这些显然不是比赛进程事件。

原因：

- MultiEventJudge 一次性判断多类事件，容易把“转播展示画面”误当成 replay。
- Prompt 里没有强制区分赛前仪式、阵容展示和比赛事件。
- 没有比赛开始时间过滤。

### 5.2 换人和出牌存在误报

模型有时会把：

```text
教练手势
场边镜头
字幕人物信息
```

误判为：

```text
substitution
card_scene
```

需要更强约束：

```text
substitution 必须看到换人牌、球员上下场交接或换人字幕。
card_scene 必须看到裁判和明确牌面/处罚图标。
```

### 5.3 事件重复较多

同一个进球可能被识别成多个：

```text
goal_or_celebration
replay
goal_or_celebration
```

当前 merger 能合并一部分，但还需要更明确规则：

```text
replay 跟随 goal_or_celebration 时并入同一事件。
同一比分段内的多个庆祝/回放合并为一个 goal event。
```

## 6. 当前结论

MultiEventJudge 是可用的。

优点：

- 成本大幅下降。
- 能在局部片段中识别进球、庆祝和回放。
- 能一次性输出多类事件，适合作为第一阶段召回。

缺点：

- 误报明显，尤其是赛前/转播展示画面。
- 不适合直接作为最终事件时间线。
- 需要后处理过滤和二次校验。

## 7. 下一步建议

### 7.1 加比赛进行状态过滤

先识别或人工配置：

```text
match_start_time
match_end_time
```

例如从 00:10:00 或开球后开始处理，过滤赛前仪式。

### 7.2 加事件后处理规则

过滤规则：

```text
timestamp < match_start_time:
  不进入最终 events.json

event_type in halftime/fulltime:
  必须接近 45/90 分钟附近，或有明确比分总结/球员退场证据

substitution:
  必须有换人牌/球员上下场/换人字幕证据

card_scene:
  必须有裁判+牌面/处罚图标证据
```

### 7.3 用 MultiEventJudge 召回，专项 verifier 精判

推荐最终流程：

```text
5 秒抽帧
-> MultiEventJudge 全视频召回候选事件
-> 过滤明显误报
-> 对 goal/replay/corner/card/substitution 做局部 verifier
-> 合并成 events.json
-> 生成 commentary.md
```

这样能兼顾成本和质量。

