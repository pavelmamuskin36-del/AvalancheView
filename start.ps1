param([Parameter(ValueFromRemainingArguments = $true)][string[]]$AppArguments)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath '.venv\Scripts\Activate.ps1') {
    . .\.venv\Scripts\Activate.ps1
}
py main.py @AppArguments
exit $LASTEXITCODE
