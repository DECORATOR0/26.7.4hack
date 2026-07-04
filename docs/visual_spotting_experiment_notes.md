# 视觉事件识别实验记录

## 1. 当前实验代码

入口：

```bash
python run_visual_spotting.py --video "德国_库拉索.mp4" --out outputs_visual_probe
```

核心能力：

```text
视频 -> 每 2 秒抽帧 -> 按 batch 分组 -> 每个 detector 单独调用 Intern-S2 -> visual_events.json
```

已实现 detector：

```text
goal_celebration
replay
corner
free_kick
penalty
substitution
card_scene
referee_dispute
attack_highlight
```

## 2. 图片 batch 边界

### 2.1 单张图成本

之前测过一张 768x432 JPEG：

```text
压缩后 JPG: 约 76 KB
API prompt_tokens: 约 364
```

这是单图粗估，不同画面会波动。

### 2.2 单请求图片数量硬上限

用最小 prompt 做二分探测：

```text
30 张：通过
45 张：通过
48 张：通过
50 张：通过
51 张：失败
52 张：失败
60 张：失败
```

51 张及以上返回：

```text
HTTP 400
code: -20102
message: 图片数量达到上限，请开启新对话后再试
```

结论：

```text
Intern-S2 当前单请求最多可带 50 张图片。
```

但这只是接口硬上限，不代表推荐 batch size。实测 30 张已经会稀释短事件，15 张更适合事件定位。

探测结果文件：

```text
outputs_visual_image_limit_summary.json
outputs_visual_image_limit_probe.json
```

### 2.3 15 / 30 / 60 张事件识别测试

测试命令：

```bash
python run_visual_spotting.py ^
  --video "德国_库拉索.mp4" ^
  --out outputs_visual_probe ^
  --interval 2 ^
  --batch-sizes 15,30,60 ^
  --max-frames 60 ^
  --max-batches-per-size 1 ^
  --detectors goal_celebration,replay,corner ^
  --concurrency 1
```

结果：

```text
15 张 batch:
  可用
  单请求约 6.3k tokens
  对 30 秒窗口内的短事件更敏感

30 张 batch:
  可用
  单请求约 12.1k tokens
  覆盖约 60 秒窗口
  容易稀释短事件，模型可能忽略其中一两个关键帧

60 张 batch:
  不可用
  Intern-S2 返回 HTTP 400:
  “图片数量达到上限，请开启新对话后再试”
```

结论：

```text
不要用 60 张一批。
30 张是接口可接受上限附近，但不一定识别最好。
15 张更适合作为当前默认 batch size。
```

## 3. 具体片段表现

测试 10:00-12:00 左右片段：

```bash
python run_visual_spotting.py ^
  --video "德国_库拉索.mp4" ^
  --out outputs_visual_goal_probe ^
  --interval 2 ^
  --start-second 600 ^
  --batch-sizes 15,30 ^
  --max-frames 60 ^
  --max-batches-per-size 2 ^
  --detectors goal_celebration,replay,corner ^
  --concurrency 1
```

结果：

```text
replay 在 00:10:50 / 00:11:08 附近被识别为高置信事件。
goal_celebration 没有直接识别出进球。
corner 没有误报。
```

这说明：

```text
Replay 是强候选信号。
进球不一定能靠 goal_celebration detector 直接抓到。
后续整合阶段应利用 replay 反推前 30-60 秒存在高价值事件。
```

15 张 vs 30 张对照：

```text
15 张 batch 覆盖 10:30-10:58:
  replay 成功识别 00:10:50，confidence=0.85

30 张 batch 覆盖 10:00-10:58:
  replay 未识别
```

结论：

```text
batch 太大可能让模型忽略短事件。
当前默认应使用 15 张一批。
```

## 4. 并发测试

已知当前账号限流：

```text
RPM: 30
TPM: 300000
Input Tokens per Month: 90000000
Output Tokens per Month: 90000000
```

对视觉识别来说，TPM 暂时不是主要瓶颈。20 张图请求约 6900 tokens，10 个并发请求约 69000 tokens，低于 300000 TPM。真正要注意的是 RPM=30。

测试片段：

```text
10:00-10:58 附近，15 张 batch，3 个 detector。
```

结果：

```text
concurrency=1:
  9 requests 用时约 27.9s（不同测试批次）

concurrency=2:
  6 requests 用时约 8.8s
  0 失败

concurrency=4:
  6 requests 用时约 5.7s
  0 失败
```

结论：

```text
小规模 concurrency=4 可用。
不建议直接上 concurrency=10，容易触发限流或浪费 token。
当前推荐默认 concurrency=2 或 4。
```

### 4.1 50 图请求并发 10 测试

为了确认“每个请求 50 张图时，整体能否并发”，做了 10 个请求的对比实验。

每个请求：

```text
50 张图片
max_tokens=60
简单 JSON 输出
```

结果文件：

```text
outputs_visual_concurrency50_compare.json
outputs_visual_concurrency50_c1.json
outputs_visual_concurrency50_c10.json
```

结果：

```text
concurrency=1:
  requests: 10
  success: 10
  failures: 0
  total elapsed: 47.76s
  avg request elapsed: 4.78s
  total tokens: 171805

concurrency=10:
  requests: 10
  success: 10
  failures: 0
  total elapsed: 13.96s
  avg request elapsed: 11.01s
  total tokens: 171842
```

结论：

```text
并发 10 不会直接爆。
总耗时明显下降：47.76s -> 13.96s。
但单请求平均耗时变慢：4.78s -> 11.01s，说明服务端存在排队或资源竞争。
```

当前建议：

```text
如果只是少量压力测试，并发 10 可用。
如果要稳定跑完整流程，推荐 concurrency=4。
如果时间紧且请求数不多，可以尝试 concurrency=8-10。
```

### 4.2 20 图请求并发 10 测试

每个请求：

```text
20 张图片
max_tokens=60
简单 JSON 输出
```

结果文件：

```text
outputs_visual_concurrency20_c10.json
```

结果：

```text
concurrency=10:
  requests: 10
  success: 10
  failures: 0
  total elapsed: 6.213s
  avg request elapsed: 5.306s
  min/max request elapsed: 4.105s / 6.203s
  total tokens: 69020
  avg tokens per request: 6902
```

结论：

```text
20 张图 + 10 并发非常快，10 个请求约 6.2 秒完成。
如果后续做事件识别，20 张一组是比 15 张更省 RPM 的候选配置。
```

但是：

```text
20 张覆盖 40 秒窗口。
如果事件很短，仍然可能比 15 张更容易稀释。
建议后续比较 15 vs 20 的真实 detector 召回质量。
```

## 5. 当前推荐参数

### 5.1 推荐固定参数：留安全余量

已知限制：

```text
RPM = 30
TPM = 300000
```

根据实测，事件 detector 的 token 消耗大致是：

```text
15 张图: 约 6300 tokens / request
22 张图: 约 9159 tokens / request
24 张图: 约 9927 tokens / request
30 张图: 约 12100 tokens / request
50 张图: 约 17184 tokens / request
```

如果每分钟跑满 30 个请求：

```text
15 张图: 6300 * 30  = 189000 TPM
22 张图: 9159 * 30  = 274757 TPM
24 张图: 9927 * 30  = 297817 TPM
30 张图: 12100 * 30 = 363000 TPM
50 张图: 17184 * 30 = 515520 TPM
```

24 张图在 30 RPM 下非常贴近 300000 TPM，但没有安全余量。为了避免 prompt 变长、图片 token 波动或计费口径变化，默认参数改成：

```text
batch size = 22
rpm limit = 28
concurrency = 4
```

验证命令：

```bash
python run_visual_spotting.py ^
  --video "德国_库拉索.mp4" ^
  --out outputs_visual_safe_param_probe ^
  --interval 2 ^
  --start-second 600 ^
  --batch-sizes 22 ^
  --max-frames 66 ^
  --max-batches-per-size 3 ^
  --detectors goal_celebration,replay,corner ^
  --concurrency 4 ^
  --rpm-limit 28 ^
  --temperature 0.1
```

实测结果：

```text
requests: 9
success: 9
failures: 0
elapsed: 19.814s
avg tokens/request: 9158.6
projected TPM at 28 RPM: 256439.6
projected TPM at 30 RPM: 274756.7
TPM margin at 28 RPM: 43560.4
```

输出：

```text
outputs_visual_safe_param_probe/visual_events.json
```

识别到：

```text
00:10:50 replay confidence=0.85
00:11:08 goal_or_celebration confidence=0.60
```

结论：

```text
固定推荐参数：22 张图一批，concurrency=4，rpm_limit=28。
这组参数留出了 RPM 和 TPM 安全区间，更适合后续默认实验。
```

注意：

```text
如果只是短时压力测试，可以用 batch size = 24, rpm_limit = 30。
如果要长时间稳定跑，使用 batch size = 22, rpm_limit = 28。
```

### 5.2 常用命令

调试：

```bash
python run_visual_spotting.py ^
  --video "德国_库拉索.mp4" ^
  --out outputs_visual_debug ^
  --interval 2 ^
  --batch-sizes 15 ^
  --max-frames 60 ^
  --detectors all ^
  --concurrency 4
```

局部片段测试：

```bash
python run_visual_spotting.py ^
  --video "德国_库拉索.mp4" ^
  --out outputs_visual_segment ^
  --interval 2 ^
  --start-second 600 ^
  --batch-sizes 15 ^
  --max-frames 60 ^
  --detectors all ^
  --concurrency 4
```

全视频第一版建议：

```bash
python run_visual_spotting.py ^
  --video "德国_库拉索.mp4" ^
  --out outputs_visual_full ^
  --interval 2 ^
  --batch-sizes 15 ^
  --detectors replay,goal_celebration,corner,free_kick,penalty,substitution,card_scene,referee_dispute ^
  --concurrency 2
```

全视频不要一次性跑 15/30/60 全组合，否则请求数会膨胀。

## 6. 请求量估算

视频约 110 分钟，2 秒一帧：

```text
约 3300 张图
```

如果 batch size = 15：

```text
约 220 batches
```

如果 detector = 8：

```text
约 1760 API requests
```

这太多。

所以实际全视频要么：

```text
先用本地规则筛 candidate segments
```

要么减少 detector：

```text
先只跑 replay + goal_celebration + corner
```

当前阶段如果只是看能力边界，建议跑局部片段，不建议全视频所有 detector 直接扫。

## 7. 对下一步的建议

短期：

```text
默认 batch size = 15
concurrency = 2 或 4
先跑局部片段验证 detector 能力
```

下一步必须加候选筛选，否则全量调用成本太高：

```text
2 秒抽帧
-> 本地 motion/overlay/scoreboard/replay 规则筛 Top candidates
-> 只对候选片段跑 Intern-S2 detector
```
