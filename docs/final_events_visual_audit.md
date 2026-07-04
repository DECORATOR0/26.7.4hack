# Final Events Visual Audit

Input: `outputs_event_agent_full/final_events.json`

Audit evidence:

- `outputs_event_agent_audit/contact_sheet_01.jpg` ... `contact_sheet_06.jpg`
- `outputs_event_agent_audit/contact_sheet_suspects_wide.jpg`

Legend:

- OK: visual frames support the event.
- ADJUST: event is broadly useful, but type/time/title/confidence should be changed.
- WRONG: visual frames do not support the event as written.

## One-by-One Result

| Event | Verdict | Visual audit note |
|---|---|---|
| F0001 00:14:26 goal | OK | Ball/score transition and celebration are visible. Goal is valid. Scorer name should be subtitle/OCR-confirmed, not trusted from visual alone. |
| F0002 00:15:14 replay | OK | Clearly a replay of the first Germany goal. |
| F0003 00:17:24 replay | OK | Multi-angle replay of the same earlier goal; not a new goal. |
| F0004 00:19:26 attack_highlight | OK | Sané chance/shot sequence and follow-up close-up are visible. |
| F0005 00:20:46 goal | WRONG | Wider window shows attack/shot sequence but score remains 1-0; no new-goal evidence. Reclassify as attack_highlight or remove. |
| F0006 00:22:50 attack_highlight | OK | Attack and likely save/clearance sequence are visible. |
| F0007 00:23:16 replay | ADJUST | Replay-like goalmouth sequence is visible, but player/title attribution is not visually reliable. Keep as replay, avoid naming scorer unless OCR confirms. |
| F0008 00:32:00 goal | WRONG | Frames show hydration break/team huddle, not a goal. Remove from final events; at most record as break/score state. |
| F0009 00:34:36 referee_dispute | ADJUST | Foul/no-call dispute is plausible, but player name is wrong/unreliable. Keep as low-confidence referee dispute/foul review. |
| F0010 00:35:00 free_kick | OK | Ball placed and set-piece setup are visible. |
| F0011 00:36:00 referee_dispute | ADJUST | Referee-player communication is visible, but dispute strength is weak. Downgrade confidence or remove from highlights. |
| F0012 00:40:16 free_kick | ADJUST | Foul leading to a free kick is visible; timestamp is closer to foul/award than the actual kick. |
| F0013 00:41:46 replay | OK | Goalkeeper save replay is visible. |
| F0014 00:44:58 corner | OK | Corner-flag setup is clear. |
| F0015 00:45:44 goal | OK | Goal and celebration are visible; score becomes 2-1. |
| F0016 00:51:24 corner | OK | Corner setup and delivery are visible. |
| F0017 00:57:22 goal | OK | Direct free-kick goal and 3-1 score context are visible. |
| F0018 00:58:44 halftime | OK | Half-time graphic shows Germany 3-1 Curacao. |
| F0019 01:01:46 goal | OK | Goal sequence and 4-1 score context are visible. |
| F0020 01:02:28 replay | OK | Replay of the 4-1 goal is visible. |
| F0021 01:18:14 goal | WRONG | Single frames and wider window show Sané close-up/attack continuation; score stays 4-1. No goal evidence. Remove or downgrade to attack_highlight. |
| F0022 01:23:20 goal | OK | Ball enters net and Brown/18 celebration is visible. Scoreboard appears delayed, but event itself is supported. |
| F0023 01:26:44 substitution | OK | Germany substitution board is clear: 15 off, 8 Goretzka on. |
| F0024 01:36:20 substitution | OK | Curacao substitution board is clear: 21 Chong / 19 Kastaneer. |
| F0025 01:37:04 substitution | OK | Germany substitution graphic is clear: Kimmich off, Anton on. |
| F0026 01:38:30 goal | ADJUST | Ball-in-net frame is visible, but overlay/angle indicates replay/referee-view context and score already shows 6-1. Do not treat as live new goal; merge with the missing 6-1 goal sequence or reclassify as replay/review. |
| F0027 01:39:42 replay | OK | Replay/golemouth sequence is visible; likely belongs to the same 6-1 goal phase. |
| F0028 01:42:18 goal | OK | 7-1 celebration/score state is visible. Timestamp is celebration/confirmation, not exact shot moment. |
| F0029 01:43:04 goal | WRONG | This is a replay/duplicate of the 7-1 goal phase, not another new goal. Reclassify as replay or merge into F0028. |
| F0030 01:50:00 fulltime | OK | Wider window shows full-time graphic Germany 7-1 Curacao around 01:50:30. Shift timestamp later if precision matters. |

## Important Missing/Incorrect Chain

- A Germany 6-1 goal/celebration is visible around `01:33:40` with a `DENIZ UNDAV` lower-third and score already `6-1`. The final event list does not preserve it as a clean goal event.
- The later F0026/F0027 entries appear to be replay/review material connected to that 6-1 phase, not a clean live goal at `01:38:30`.

## Recommended Fixes

1. Remove F0005, F0008, F0021.
2. Reclassify F0029 as replay and merge it into F0028.
3. Rework F0026/F0027 into a single 6-1 goal/replay cluster, using the `01:33:40` Undav lower-third as the main confirmation.
4. Downgrade F0009/F0011/F0012 from high-confidence event material; keep only if the script needs referee/foul flavor.
5. For all scorer names, prefer scoreboard/lower-third OCR over visual-language inference.
