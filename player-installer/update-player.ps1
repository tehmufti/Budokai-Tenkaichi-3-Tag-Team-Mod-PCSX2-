param([string]$Installation, [switch]$Restore)
$ErrorActionPreference = 'Stop'
try {
    if (-not $Installation) {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = 'Choose your installed Tag Team Mod folder / Elige la carpeta donde instalaste el mod'
        $dialog.ShowNewFolderButton = $false
        if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 1 }
        $Installation = $dialog.SelectedPath
        $dialog.Dispose()
    }
    $python = Join-Path $Installation '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'Choose the installed mod folder containing Play.cmd. This updater requires an existing player installation.'
    }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONNOUSERSITE = '1'
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    $script = Join-Path $PSScriptRoot 'update_player.py'
    if ($Restore) { & $python -B $script $Installation --restore }
    else { & $python -B $script $Installation }
    exit $LASTEXITCODE
} catch {
    Write-Host ('UPDATE STOPPED / ACTUALIZACION DETENIDA: ' + $_.Exception.Message)
    exit 2
}
