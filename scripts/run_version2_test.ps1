$ErrorActionPreference = "Stop"

$Root = "C:\Users\HP\Desktop\26.7.4hack"
Set-Location -LiteralPath $Root

$StatusPath = Join-Path $Root "version2_test_status.json"

function Write-Status {
    param(
        [string]$Stage,
        [string]$Status
    )
    [ordered]@{
        stage = $Stage
        status = $Status
        updated_at = (Get-Date).ToString("o")
        frame_output = "outputs_frame_narration_v2"
        event_output = "outputs_event_agent_v2"
        script_report_output = "outputs_script_report_v2"
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

Write-Status -Stage "version2_test" -Status "started"

Run-Step "frame_narration_v2" @(
    "run_frame_narration.py",
    "--frame-index", "outputs_visual_full_safe\frame_index_2s.json",
    "--out", "outputs_frame_narration_v2",
    "--segment-seconds", "60",
    "--max-images", "30",
    "--concurrency", "3",
    "--rpm-limit", "15",
    "--temperature", "0.1",
    "--max-tokens", "6000",
    "--resume"
)

Run-Step "event_agent_v2" @(
    "run_event_agent.py",
    "--descriptions", "outputs_frame_narration_v2\segment_descriptions.json",
    "--frame-index", "outputs_visual_full_safe\frame_index_2s.json",
    "--out", "outputs_event_agent_v2",
    "--chunk-segments", "12",
    "--concurrency", "3",
    "--rpm-limit", "12",
    "--temperature", "0.1",
    "--text-max-tokens", "10000",
    "--final-max-events", "30",
    "--resume"
)

Run-Step "script_report_v2" @(
    "run_script_report.py",
    "--events", "outputs_event_agent_v2\final_events.json",
    "--match-info", "examples\match_info.germany_curacao.json",
    "--out", "outputs_script_report_v2",
    "--temperature", "0.2",
    "--max-tokens", "10000"
)

Write-Status -Stage "version2_test" -Status "done"
Write-Output "[$((Get-Date).ToString("o"))] VERSION2 TEST DONE"
