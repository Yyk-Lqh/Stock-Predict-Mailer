param(
    [string]$ConfigPath = "config/agent-example.toml",
    [int]$Limit = 20
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$interpreter = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $interpreter)) { throw "Run uv sync first" }
& $interpreter -m stock_predict_mailer --config $ConfigPath mail-drain --limit $Limit
# Exit 2 means at least one message is still retry/failed/uncertain; it is reported, not swallowed.
if ($LASTEXITCODE -ne 0) { throw "Mail drain finished with unsettled messages (exit code $LASTEXITCODE)" }
