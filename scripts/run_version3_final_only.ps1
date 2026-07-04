$ErrorActionPreference = "Stop"

$Root = "C:\Users\HP\Desktop\26.7.4hack"
Set-Location -LiteralPath $Root

$StatusPath = Join-Path $Root "version3_test_status.json"

function Write-Status {
    param(
        [string]$Stage,
        [string]$Status
    )
    [ordered]@{
        stage = $Stage
        status = $Status
        updated_at = (Get-Date).ToString("o")
        source_text_events = "outputs_event_agent_v3\text_agent_events.json"
        source_image_reviews = "outputs_event_agent_v3\image_review_results.json"
        event_output = "outputs_event_agent_v3"
        script_report_output = "outputs_script_report_v3"
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

Write-Status -Stage "version3_final_only" -Status "started"

$FinalFiles = @(
    "outputs_event_agent_v3\final_consolidation_raw.json",
    "outputs_event_agent_v3\final_events.json",
    "outputs_event_agent_v3\final_events_clean_v3.json",
    "outputs_event_agent_v3\match_time_anchors.json",
    "outputs_event_agent_v3\event_agent_runtime_summary.json",
    "outputs_script_report_v3\script_report_raw.json",
    "outputs_script_report_v3\script_report_runtime_summary.json",
    "outputs_script_report_v3\final_report_v3.json",
    "outputs_script_report_v3\final_report_v3.md"
)
foreach ($RelativePath in $FinalFiles) {
    $Path = Join-Path $Root $RelativePath
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}

Run-Step "event_agent_v3_final_only" @(
    "run_event_agent.py",
    "--descriptions", "outputs_frame_narration_v2\segment_descriptions.json",
    "--frame-index", "outputs_visual_full_safe\frame_index_2s.json",
    "--out", "outputs_event_agent_v3",
    "--chunk-segments", "12",
    "--concurrency", "3",
    "--rpm-limit", "12",
    "--temperature", "0.1",
    "--text-max-tokens", "10000",
    "--final-max-events", "30",
    "--final-consolidation-max-tokens", "20000",
    "--schema-version", "v3",
    "--final-only"
)

Run-Step "script_report_v3" @(
    "run_script_report.py",
    "--events", "outputs_event_agent_v3\final_events_clean_v3.json",
    "--match-info", "examples\match_info.germany_curacao.json",
    "--out", "outputs_script_report_v3",
    "--temperature", "0.2",
    "--max-tokens", "10000",
    "--report-version", "v3"
)

Write-Status -Stage "version3_final_only" -Status "done"
Write-Output "[$((Get-Date).ToString("o"))] VERSION3 FINAL ONLY DONE"
