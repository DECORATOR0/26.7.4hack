$ErrorActionPreference = "Stop"

$Root = "C:\Users\HP\Desktop\26.7.4hack"
Set-Location -LiteralPath $Root

$StatusPath = Join-Path $Root "version4_status.json"

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
        event_output = "outputs_event_agent_v4"
        script_report_output = "outputs_script_report_v4"
        model = "Intern S2"
        guardrail_policy = "single_pass_identity_and_event_type_cleanup"
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

Write-Status -Stage "version4_end_to_end" -Status "started"

Run-Step "event_agent_v4" @(
    "run_event_agent.py",
    "--descriptions", "outputs_frame_narration_v2\segment_descriptions.json",
    "--frame-index", "outputs_visual_full_safe\frame_index_2s.json",
    "--out", "outputs_event_agent_v4",
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

Run-Step "guardrail_v4" @(
    "run_guardrail.py",
    "--events", "outputs_event_agent_v4\final_events.json",
    "--out", "outputs_event_agent_v4",
    "--temperature", "0",
    "--max-tokens", "6000"
)

Run-Step "script_report_v4" @(
    "run_script_report.py",
    "--events", "outputs_event_agent_v4\final_events_guarded_v4.json",
    "--match-info", "examples\match_info.germany_curacao.json",
    "--out", "outputs_script_report_v4",
    "--temperature", "0.2",
    "--max-tokens", "12000",
    "--report-version", "v4_markdown",
    "--pure-model-output"
)

Write-Status -Stage "version4_end_to_end" -Status "done"
Write-Output "[$((Get-Date).ToString("o"))] VERSION4 END TO END DONE"
