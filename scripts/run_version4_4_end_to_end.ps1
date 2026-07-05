$ErrorActionPreference = "Stop"

$Root = "C:\Users\HP\Desktop\26.7.4hack"
Set-Location -LiteralPath $Root

$StatusPath = Join-Path $Root "version4_4_status.json"
$ScoreboardReadings = "outputs_event_agent_v4_3\scoreboard_readings_merged.json"
$GoalFacts = "outputs_event_agent_v4_4_seed\scoreboard_goal_events.json"

function Write-Status {
    param(
        [string]$Stage,
        [string]$Status
    )
    [ordered]@{
        stage = $Stage
        status = $Status
        updated_at = (Get-Date).ToString("o")
        base_event_input = "outputs_event_agent_v4_2\final_events_guarded_v4.json"
        scoreboard_readings = $ScoreboardReadings
        goal_facts = $GoalFacts
        frame_narration_output = "outputs_frame_narration_v4_4"
        memory_event_output = "outputs_event_agent_v4_4_text"
        scoreboard_goal_output = "outputs_event_agent_v4_4"
        script_report_output = "outputs_script_report_v4_4"
        model = "Intern S2"
        goal_policy = "scoreboard_ocr_score_jump_goals_last_before_jump_as_pre_narration_memory"
        report_policy = "v4_4_fused_markdown"
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

Write-Status -Stage "version4_4_end_to_end" -Status "started"

Run-Step "scoreboard_goals_v4_4_seed_last_before_jump" @(
    "run_scoreboard_goals.py",
    "--source-events", "outputs_event_agent_v4_2\final_events_guarded_v4.json",
    "--frame-index", "outputs_visual_full_safe\frame_index_2s.json",
    "--out", "outputs_event_agent_v4_4_seed",
    "--precomputed-readings", $ScoreboardReadings,
    "--output-version", "v4_4_seed",
    "--goal-timestamp-policy", "last_before_jump",
    "--min-confidence", "0.5"
)

Run-Step "frame_narration_v4_4_goal_memory" @(
    "run_frame_narration.py",
    "--frame-index", "outputs_visual_full_safe\frame_index_2s.json",
    "--goal-memory", $GoalFacts,
    "--out", "outputs_frame_narration_v4_4",
    "--segment-seconds", "60",
    "--max-images", "30",
    "--concurrency", "8",
    "--rpm-limit", "15",
    "--temperature", "0.1",
    "--max-tokens", "6000",
    "--resume"
)

Run-Step "event_agent_v4_4_from_regenerated_narrative" @(
    "run_event_agent.py",
    "--descriptions", "outputs_frame_narration_v4_4\segment_descriptions.json",
    "--frame-index", "outputs_visual_full_safe\frame_index_2s.json",
    "--out", "outputs_event_agent_v4_4_text",
    "--chunk-segments", "12",
    "--concurrency", "3",
    "--rpm-limit", "12",
    "--temperature", "0.1",
    "--text-max-tokens", "10000",
    "--final-max-events", "50",
    "--final-consolidation-max-tokens", "20000",
    "--schema-version", "v4",
    "--pure-model-output",
    "--resume"
)

Run-Step "guardrail_v4_4_text" @(
    "run_guardrail.py",
    "--events", "outputs_event_agent_v4_4_text\final_events.json",
    "--out", "outputs_event_agent_v4_4_text",
    "--temperature", "0",
    "--max-tokens", "6000"
)

Run-Step "script_report_v4_4" @(
    "run_script_report.py",
    "--events", "outputs_event_agent_v4_4_text\final_events_guarded_v4.json",
    "--match-info", "examples\match_info.germany_curacao.json",
    "--out", "outputs_script_report_v4_4",
    "--report-version", "v4_4_markdown"
)

Write-Status -Stage "version4_4_end_to_end" -Status "done"
Write-Output "[$((Get-Date).ToString("o"))] VERSION4.4 END TO END DONE"
