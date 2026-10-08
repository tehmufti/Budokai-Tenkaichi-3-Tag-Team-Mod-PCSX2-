<# Install native workbench packages into a project-local virtual environment. #>
[CmdletBinding()]
param()
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
try {
    $guiVenv = Join-Path $PSScriptRoot '.gui-venv'
    $guiPython = Join-Path $guiVenv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $guiPython -PathType Leaf)) {
        $basePython = (Get-Command python -CommandType Application -ErrorAction Stop).Source
        & $basePython -m venv $guiVenv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the GUI virtual environment.' }
    }
    & $guiPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-gui.txt')
    if ($LASTEXITCODE -ne 0) { throw 'GUI dependency installation failed.' }
    & $guiPython (Join-Path $PSScriptRoot 'tools\modder_gui.py') --check
    if ($LASTEXITCODE -ne 0) { throw 'GUI validation failed.' }
    Write-Host 'Ready. Open BT3 Workbench.cmd.'
}
catch { Write-Error $_; exit 1 }
