$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $Root

$StatusPath = Join-Path $Root "version4_5_status.json"

function Write-Status {
    param(
        [string]$Stage,
        [string]$Status
    )
    [ordered]@{
        stage = $Stage
        status = $Status
        updated_at = (Get-Date).ToString("o")
        branch_profile = "prune"
        event_input = "outputs_event_agent_v4_5\final_events_guarded_v4_5.json"
        report_output = "outputs_script_report_v4_5"
        web_data_output = "web_demo\data\events.json"
        note = "Prune verification rebuilds deterministic V4.5 report and web data from retained V4.5 artifacts."
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

Write-Status -Stage "version4_5_prune_verify" -Status "started"

Run-Step "compile_v4_5_code" @(
    "-m", "compileall",
    "src",
    "scripts\build_web_demo_from_report.py",
    "run_script_report.py"
)

Run-Step "script_report_v4_5" @(
    "run_script_report.py",
    "--events", "outputs_event_agent_v4_5\final_events_guarded_v4_5.json",
    "--match-info", "examples\match_info.germany_curacao.json",
    "--out", "outputs_script_report_v4_5",
    "--report-version", "v4_5_markdown"
)

Run-Step "web_demo_data_v4_5" @(
    "scripts\build_web_demo_from_report.py",
    "--skip-clips",
    "--skip-montage"
)

$EventsPath = Join-Path $Root "web_demo\data\events.json"
if (-not (Test-Path -LiteralPath $EventsPath)) {
    Write-Status -Stage "validate_web_demo_data" -Status "failed"
    throw "Missing generated web data: $EventsPath"
}

$Data = Get-Content -LiteralPath $EventsPath -Encoding UTF8 | ConvertFrom-Json
$Types = @($Data.events | ForEach-Object { $_.type } | Sort-Object -Unique)
$ExpectedTypes = @("corner", "foul_card_dispute", "free_kick", "goal", "shot_chance", "substitution")

if ($Data.version -ne "v4.5") {
    throw "Unexpected web data version: $($Data.version)"
}
if (@($Data.events).Count -ne 43) {
    throw "Unexpected event count: $(@($Data.events).Count)"
}
if ($Data.scoreboardGoalCount -ne 8) {
    throw "Unexpected goal count: $($Data.scoreboardGoalCount)"
}
if (($Types -join ",") -ne ($ExpectedTypes -join ",")) {
    throw "Unexpected event types: $($Types -join ',')"
}

Write-Status -Stage "version4_5_prune_verify" -Status "done"
Write-Output "[$((Get-Date).ToString("o"))] VERSION4.5 PRUNE VERIFY DONE"
