# InternCast V4.5 Prune

This branch is the cleaned V4.5 delivery branch. It keeps the current football commentary pipeline, the V4.5 retained event outputs, the static web demo code, and the self-contained product guide. Older experiments, old version reports, and deprecated run scripts have been removed.

## Public Demo

<http://39.105.210.249/>

The web demo shows the Germany vs Curacao match review with retained V4.5 event types, event clips, multilingual copy, and Chinese style switching.

## What V4.5 Does

Input: a full football match video plus match metadata.

Output:

- retained event list for web/demo consumption
- OCR-confirmed goal timeline
- Chinese commentary scripts in passionate and steady styles
- English, Spanish, and French commentary snippets
- subtitle and voiceover scripts
- static web demo data

V4.5 keeps these external event types:

- goal
- shot_chance
- corner
- free_kick
- foul_card_dispute
- substitution

It excludes penalty, offside, half/full-time markers, and celebration-only events from the external event list.

## Key Paths

```text
docs/interncast_v4_5_product_guide.md       # self-contained uploadable product guide
outputs_event_agent_v4_5/                   # final V4.5 guarded events and scoreboard goals
outputs_script_report_v4_5/                 # V4.5 items markdown and delivery markdown
scripts/build_web_demo_from_report.py       # builds web_demo/data/events.json and optional clips
scripts/run_version4_5_end_to_end.ps1       # prune verification runner
web_demo/                                   # static web frontend
```

Large media files are intentionally not tracked. To generate clips or montage locally, place the source video at:

```text
web_demo/assets/source_match.mp4
```

## Quick Verification

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Regenerate the V4.5 markdown report from the retained guarded event file:

```bash
python run_script_report.py --events outputs_event_agent_v4_5/final_events_guarded_v4_5.json --match-info examples/match_info.germany_curacao.json --out outputs_script_report_v4_5 --report-version v4_5_markdown
```

Build web demo data without requiring the large source video:

```bash
python scripts/build_web_demo_from_report.py --skip-clips --skip-montage
```

Or run the PowerShell verification script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_version4_5_end_to_end.ps1
```

Expected web data:

```text
version = v4.5
events = 43
goal events = 8
event types = corner, foul_card_dispute, free_kick, goal, shot_chance, substitution
```

## Local Web Build With Media

If `web_demo/assets/source_match.mp4` exists, generate event clips and montage:

```bash
python scripts/build_web_demo_from_report.py
```

Then serve locally:

```bash
cd web_demo
python -m http.server 8105
```

Open:

```text
http://127.0.0.1:8105/
```

## Notes

- Goal timing uses scoreboard OCR score jumps.
- The item markdown uses 10-second match-time granularity for web/demo generation.
- The delivery markdown uses minute-level narrative text for readability.
- Commentary must stay evidence-grounded and avoid unsupported player names, numbers, assists, VAR, or card claims.
