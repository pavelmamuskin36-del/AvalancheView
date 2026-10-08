param([switch]$WithGeo)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory

if (-not (Test-Path -LiteralPath '.venv\Scripts\Activate.ps1')) {
    $pythonVersion = py -c 'import sys; print(int(sys.version_info >= (3, 11)))'
    if ($LASTEXITCODE -ne 0) { throw 'Python launcher py is required' }
    if ($pythonVersion -eq '1') {
        py -m venv .venv
    } else {
        Write-Host 'Preparing portable Python 3.13.12 inside the project…'
        py -m pip install --target .runtime\bootstrap uv
        if ($LASTEXITCODE -ne 0) { throw 'Cannot install uv bootstrap' }
        $previousPythonPath = $env:PYTHONPATH
        $previousInstallDirectory = $env:UV_PYTHON_INSTALL_DIR
        $previousCacheDirectory = $env:UV_CACHE_DIR
        try {
            $env:PYTHONPATH = Join-Path $projectDirectory '.runtime\bootstrap'
            $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectDirectory '.runtime\interpreters'
            $env:UV_CACHE_DIR = Join-Path $projectDirectory '.runtime\cache'
            py -m uv python install 3.13.12 --no-bin
            if ($LASTEXITCODE -ne 0) { throw 'Cannot download portable Python' }
            py -m uv venv --python 3.13.12 --managed-python --seed .venv
        } finally {
            $env:PYTHONPATH = $previousPythonPath
            $env:UV_PYTHON_INSTALL_DIR = $previousInstallDirectory
            $env:UV_CACHE_DIR = $previousCacheDirectory
        }
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the project environment' }
}
. .\.venv\Scripts\Activate.ps1
py -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
if ($WithGeo) {
    py -m pip install 'cartopy>=0.23,<1'
    if ($LASTEXITCODE -ne 0) { throw 'Cartopy installation failed' }
    py tools/cache_map_data.py
    if ($LASTEXITCODE -ne 0) { throw 'Map data download failed' }
}
py tools/create_demo_dataset.py
if ($LASTEXITCODE -ne 0) { throw 'Demo generation failed' }
Write-Host 'Ready. Start AvalancheView with: py main.py --demo'
