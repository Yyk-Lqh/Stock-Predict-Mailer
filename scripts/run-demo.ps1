param(
    [string]$ConfigPath = "config/agent-example.toml"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$interpreter = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $interpreter)) { throw "Run uv sync first" }
& $interpreter -m stock_predict_mailer --config $ConfigPath run --send
if ($LASTEXITCODE -ne 0) { throw "Demo pipeline failed with exit code $LASTEXITCODE" }
