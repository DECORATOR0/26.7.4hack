$ErrorActionPreference = "Stop"

$Root = "C:\Users\HP\Desktop\26.7.4hack"
Set-Location -LiteralPath $Root

$StatusPath = Join-Path $Root "version3_pure_status.json"

function Write-Status {
    param(
        [string]$Stage,
        [string]$Status
    )
    [ordered]@{
        stage = $Stage
        status = $Status
        updated_at = (Get-Date).ToString("o")
        narrative_input = "outputs_frame_narration_v2\segment_descriptions.json"
        event_output = "outputs_event_agent_v3_pure"
        script_report_output = "outputs_script_report_v3_pure"
        model = "Intern S2"
        postprocess_policy = "pure_model_output"
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

Write-Status -Stage "version3_pure_model" -Status "started"

Run-Step "event_agent_v3_pure" @(
    "run_event_agent.py",
    "--descriptions", "outputs_frame_narration_v2\segment_descriptions.json",
    "--frame-index", "outputs_visual_full_safe\frame_index_2s.json",
    "--out", "outputs_event_agent_v3_pure",
    "--chunk-segments", "12",
    "--concurrency", "3",
    "--rpm-limit", "12",
    "--temperature", "0.1",
    "--text-max-tokens", "10000",
    "--final-max-events", "30",
    "--final-consolidation-max-tokens", "20000",
    "--schema-version", "v3",
    "--pure-model-output",
    "--resume"
)

Run-Step "script_report_v3_pure" @(
    "run_script_report.py",
    "--events", "outputs_event_agent_v3_pure\final_events.json",
    "--match-info", "examples\match_info.germany_curacao.json",
    "--out", "outputs_script_report_v3_pure",
    "--temperature", "0.2",
    "--max-tokens", "12000",
    "--report-version", "v3_markdown",
    "--pure-model-output"
)

Write-Status -Stage "version3_pure_model" -Status "done"
Write-Output "[$((Get-Date).ToString("o"))] VERSION3 PURE MODEL DONE"
