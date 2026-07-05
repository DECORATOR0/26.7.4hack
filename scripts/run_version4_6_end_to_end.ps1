$ErrorActionPreference = "Stop"

$Root = "C:\Users\HP\Desktop\26.7.4hack"
Set-Location -LiteralPath $Root

$StatusPath = Join-Path $Root "version4_6_status.json"
$FrameIndex = "cache_frames\1s\frame_index.json"
$ScoreboardReadings = "outputs_event_agent_v4_3\scoreboard_readings_merged.json"
$GoalFacts = "outputs_event_agent_v4_6_seed\scoreboard_goal_events.json"

function Write-Status {
    param(
        [string]$Stage,
        [string]$Status
    )
    [ordered]@{
        stage = $Stage
        status = $Status
        updated_at = (Get-Date).ToString("o")
        frame_index = $FrameIndex
        frame_policy = "1_second_frames"
        frame_narration_unit = "30_seconds_per_segment"
        event_agent_unit = "12_segments_per_chunk_6_minutes"
        base_event_input = "outputs_event_agent_v4_2\final_events_guarded_v4.json"
        scoreboard_readings = $ScoreboardReadings
        goal_facts = $GoalFacts
        frame_narration_output = "outputs_frame_narration_v4_6"
        memory_event_output = "outputs_event_agent_v4_6_text"
        scoreboard_goal_output = "outputs_event_agent_v4_6"
        script_report_output = "outputs_script_report_v4_6"
        model = "Intern S2"
        goal_policy = "scoreboard_ocr_score_jump_goals_last_before_jump_as_pre_narration_memory"
        time_policy = "event_table_match_time_10_second_granularity_only"
        report_policy = "v4_6_split_items_markdown_and_delivery_markdown_deterministic"
    } | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -LiteralPath $StatusPath
}

function Run-Step {
    param(
        [string]$Name,
        [string[]]$ArgsList
    )
    Write-Output "[$((Get-Date).ToString("o"))] START $Name"
    Write-Status -Stage $Name -Status "running"
    & python -u @ArgsList
    if ($LASTEXITCODE -ne 0) {
        Write-Status -Stage $Name -Status "failed"
        throw "$Name failed with exit code $LASTEXITCODE"
    }
    Write-Output "[$((Get-Date).ToString("o"))] END $Name"
    Write-Status -Stage $Name -Status "done"
}

Write-Status -Stage "version4_6_end_to_end" -Status "started"

Run-Step "scoreboard_goals_v4_6_seed_last_before_jump" @(
    "run_scoreboard_goals.py",
    "--source-events", "outputs_event_agent_v4_2\final_events_guarded_v4.json",
    "--frame-index", $FrameIndex,
    "--out", "outputs_event_agent_v4_6_seed",
    "--precomputed-readings", $ScoreboardReadings,
    "--output-version", "v4_6_seed",
    "--goal-timestamp-policy", "last_before_jump",
    "--min-confidence", "0.5"
)

Run-Step "frame_narration_v4_6_1s_30s_goal_memory" @(
    "run_frame_narration.py",
    "--frame-index", $FrameIndex,
    "--goal-memory", $GoalFacts,
    "--out", "outputs_frame_narration_v4_6",
    "--segment-seconds", "30",
    "--max-images", "30",
    "--concurrency", "10",
    "--rpm-limit", "20",
    "--temperature", "0.1",
    "--max-tokens", "6000",
    "--resume"
)

Run-Step "event_agent_v4_6_6min_from_regenerated_narrative" @(
    "run_event_agent.py",
    "--descriptions", "outputs_frame_narration_v4_6\segment_descriptions.json",
    "--frame-index", $FrameIndex,
    "--out", "outputs_event_agent_v4_6_text",
    "--chunk-segments", "12",
    "--concurrency", "4",
    "--rpm-limit", "12",
    "--temperature", "0.1",
    "--text-max-tokens", "10000",
    "--final-max-events", "60",
    "--final-consolidation-max-tokens", "24000",
    "--schema-version", "v4",
    "--pure-model-output",
    "--resume"
)

Run-Step "guardrail_v4_6_text" @(
    "run_guardrail.py",
    "--events", "outputs_event_agent_v4_6_text\final_events.json",
    "--out", "outputs_event_agent_v4_6_text",
    "--temperature", "0",
    "--max-tokens", "6000"
)

Run-Step "scoreboard_goal_merge_v4_6_final" @(
    "run_scoreboard_goals.py",
    "--source-events", "outputs_event_agent_v4_6_text\final_events_guarded_v4.json",
    "--frame-index", $FrameIndex,
    "--out", "outputs_event_agent_v4_6",
    "--precomputed-goals", $GoalFacts,
    "--output-version", "v4_6",
    "--goal-timestamp-policy", "last_before_jump",
    "--min-confidence", "0.5"
)

Run-Step "script_report_v4_6" @(
    "run_script_report.py",
    "--events", "outputs_event_agent_v4_6\final_events_guarded_v4_6.json",
    "--match-info", "examples\match_info.germany_curacao.json",
    "--out", "outputs_script_report_v4_6",
    "--report-version", "v4_6_markdown"
)

Write-Status -Stage "version4_6_end_to_end" -Status "done"
Write-Output "[$((Get-Date).ToString("o"))] VERSION4.6 END TO END DONE"
