param(
    [string]$ConfigPath = "config/example.toml"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$interpreter = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $interpreter)) { throw "Run uv sync first" }
$cutoff = [DateTimeOffset]::UtcNow.ToString("o")
& $interpreter -m stock_predict_mailer --config $ConfigPath demo-run --cutoff $cutoff
if ($LASTEXITCODE -ne 0) { throw "Demo pipeline failed with exit code $LASTEXITCODE" }
