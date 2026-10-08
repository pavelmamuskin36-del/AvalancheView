param(
    [ValidateSet('onefile', 'onedir')][string]$Mode = 'onefile',
    [string]$WorkPath = 'build/pyinstaller'
)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$interpreter = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $interpreter)) {
    throw 'Create the project .venv and install requirements-dev.txt and requirements-build.txt first.'
}
$previousMode = $env:AVALANCHEVIEW_BUILD_MODE
Push-Location -LiteralPath $projectDirectory
try {
    $env:AVALANCHEVIEW_BUILD_MODE = $Mode
    & $interpreter tools/make_windows_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not render the application icon.' }
    $logDirectory = Join-Path $projectDirectory 'build\logs'
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $errorLog = Join-Path $logDirectory "$Mode.log"
    $buildProcess = Start-Process -FilePath $interpreter -WindowStyle Hidden -Wait -PassThru `
        -WorkingDirectory $projectDirectory `
        -ArgumentList @('-m', 'PyInstaller', '--noconfirm', '--workpath', "`"$WorkPath`"", 'AvalancheView.spec') `
        -RedirectStandardOutput (Join-Path $logDirectory "$Mode.stdout.log") `
        -RedirectStandardError $errorLog
    if ($buildProcess.ExitCode -ne 0) {
        Get-Content -LiteralPath $errorLog -Tail 30
        throw "PyInstaller failed with exit code $($buildProcess.ExitCode)"
    }
    if ($Mode -eq 'onefile') {
        $fileHash = Get-FileHash -LiteralPath 'dist\AvalancheView.exe' -Algorithm SHA256
        ('{0}  AvalancheView.exe' -f $fileHash.Hash.ToLowerInvariant()) |
            Set-Content -LiteralPath 'dist\AvalancheView.sha256' -Encoding ASCII
        Get-Item -LiteralPath 'dist\AvalancheView.exe' | Select-Object FullName, Length
    } else {
        Get-Item -LiteralPath 'dist\AvalancheView\AvalancheView.exe' | Select-Object FullName, Length
    }
} finally {
    $env:AVALANCHEVIEW_BUILD_MODE = $previousMode
    Pop-Location
}
