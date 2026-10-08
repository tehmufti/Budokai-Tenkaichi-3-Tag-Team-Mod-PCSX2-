<# Native workbench only; does not start or connect to PCSX2. #>
[CmdletBinding()]
param([switch]$ValidateOnly)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$guiPython = Join-Path $PSScriptRoot '.gui-venv\Scripts\python.exe'
$guiScript = Join-Path $PSScriptRoot 'tools\modder_gui.py'
try {
    if (-not (Test-Path -LiteralPath $guiPython -PathType Leaf)) {
        throw 'The GUI dependencies are missing. Run Install modder tools.cmd once, then reopen BT3 Workbench.cmd.'
    }
    $probe = & $guiPython $guiScript --check 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Workbench dependency check failed. Run Install modder tools.cmd. $($probe -join ' ')" }
    if ($ValidateOnly) { Write-Output ($probe -join [Environment]::NewLine); return }
    $logs = Join-Path $PSScriptRoot 'analysis\modder-gui'
    [void](New-Item -ItemType Directory -Path $logs -Force)
    $token = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $app = Start-Process -FilePath $guiPython -ArgumentList @('-u', ('"' + $guiScript + '"')) `
        -PassThru -Wait -WindowStyle Hidden -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput (Join-Path $logs ($token + '.log')) `
        -RedirectStandardError (Join-Path $logs ($token + '-errors.log'))
    if ($app.ExitCode -ne 0) { throw "The workbench stopped. Details: $logs" }
}
catch {
    if ($ValidateOnly) { throw }
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'BT3 Workbench', 'OK', 'Error')
    exit 1
}
