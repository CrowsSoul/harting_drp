[CmdletBinding()]
param(
    [string]$PythonExe = 'python',
    [string]$PnpmExe = 'pnpm.cmd',
    [string]$NxRoot = '',
    [switch]$SkipInstall,
    [switch]$Verify
)
$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$deliveryDir = Join-Path $projectDir 'release'
$frontendDir = Join-Path $projectDir 'nxdrp\checkers\platform_web\frontend'
$envDir = Join-Path $projectDir '.desktop-venv'
$venvPython = Join-Path $envDir 'Scripts\python.exe'
function Assert-Exit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}
$previousDir = Get-Location
try {
    Set-Location -LiteralPath $projectDir
    if ($NxRoot) {
        & (Join-Path $projectDir 'tools\build_nx_plugin.ps1') -NxRoot $NxRoot
        Assert-Exit 'NX plugin build'
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $PythonExe -c 'import sys; assert sys.version_info[:2] == (3,12), "Use Python 3.12 for this locked build"'
        Assert-Exit 'Python version check'
        & $PythonExe -m venv $envDir
        Assert-Exit 'Create environment'
    }
    Get-Command $PnpmExe -ErrorAction Stop | Out-Null
    $pnpmVersion = (& $PnpmExe --version | Select-Object -Last 1).Trim()
    Assert-Exit 'pnpm version check'
    if ($pnpmVersion -ne '10.20.0') { throw 'Use pnpm 10.20.0 (npm install --global pnpm@10.20.0).' }
    if (-not $SkipInstall) {
        & $venvPython -m pip install -r requirements-desktop.lock.txt
        Assert-Exit 'Install Python dependencies'
        & $venvPython -m pip install -r (Join-Path $projectDir 'nxdrp\checkers\report\requirements.txt')
        Assert-Exit 'Install report dependencies'
        if ($Verify) {
            & $venvPython -m pip install -r (Join-Path $projectDir 'nxdrp\checkers\report\requirements-test.txt')
            Assert-Exit 'Install report verification dependencies'
        }
        Set-Location -LiteralPath $frontendDir
        & $PnpmExe install --frozen-lockfile --ignore-scripts
        Assert-Exit 'Install frontend dependencies'
    }
    # PDF/Word 报告是可选能力，但桌面交付要求可用；缺依赖时在构建前就报清楚。
    & $venvPython -c "import reportlab, docx" 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Report dependencies missing: re-run without -SkipInstall (PDF/Word needs reportlab and python-docx).' }
    Set-Location -LiteralPath $frontendDir
    & $venvPython '..\generate_types.py'
    Assert-Exit 'Generate contracts'
    & $PnpmExe exec vue-tsc --noEmit
    Assert-Exit 'Type check'
    if ($Verify) {
        & $PnpmExe exec vitest run
        Assert-Exit 'Frontend tests'
    }
    & $PnpmExe exec vite build
    Assert-Exit 'Frontend build'
    Set-Location -LiteralPath $projectDir
    if ($Verify) {
        & $venvPython -m pytest tests nxdrp/checkers/platform_web/tests -q
        Assert-Exit 'Backend tests'
    }
    & $venvPython -m PyInstaller --noconfirm --distpath $deliveryDir HartingDRP.spec
    Assert-Exit 'EXE build'
    Copy-Item -Path (Join-Path $projectDir 'packaging\desktop\*') -Destination $deliveryDir -Recurse -Force
    & $venvPython tools/update_checksums.py
    Assert-Exit 'Update checksums'
    Write-Host "Ready: $(Join-Path $deliveryDir 'HartingDRP_NX.exe')"
} finally {
    Set-Location -LiteralPath $previousDir
}
