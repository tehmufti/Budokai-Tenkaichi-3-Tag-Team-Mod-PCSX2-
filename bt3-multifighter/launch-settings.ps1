<# Open the visible settings window without a persistent console or emulator. #>
[CmdletBinding()]
param([switch]$ValidateOnly)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
# Python writes UTF-8 and this script reads UTF-8 (accented folder names, Spanish text).
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$settingsScript = Join-Path $PSScriptRoot 'tools\mod_settings.py'
$language = 'en'
try {
    . (Join-Path $PSScriptRoot 'launcher-lifecycle.ps1')
    $language = Get-Bt3Language -ProjectRoot $PSScriptRoot
    # Square brackets break Start-Process and its log redirection below: refuse first (exit 2), with the fix.
    if (Test-Bt3BracketPath -ProjectRoot $PSScriptRoot) {
        throw (New-Bt3Failure -Code 'TTM-PLAY-45' -What (Get-Bt3Text 'brackets.what' $language) -Why (Get-Bt3Text 'brackets.why' $language) `
            -Fix (Get-Bt3Text 'brackets.fix' $language) -File $PSScriptRoot -ExitCode 2 -NothingChanged `
            -Message "The installation path contains square brackets: $PSScriptRoot")
    }
    # A player installation runs only its own private Python (.venv); a developer tree may use any.
    $isPlayer = Test-Bt3PlayerInstall -ProjectRoot $PSScriptRoot
    if (-not (Test-Path -LiteralPath $settingsScript -PathType Leaf)) {
        $fixKey = 'missing.fix.dev'
        if ($isPlayer) { $fixKey = 'missing.fix' }
        throw (New-Bt3Failure -Code 'TTM-PLAY-24' -What (Get-Bt3Text 'missing.what' $language) -Why (Get-Bt3Text 'missing.why' $language) `
            -Fix (Get-Bt3Text $fixKey $language) -File $settingsScript -ExitCode 2 -Message "Missing settings application: $settingsScript")
    }
    $venvPython = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'))
    if ($isPlayer) { $pythonCandidates = @($venvPython) }
    else {
        $pythonCandidates = @(
            $venvPython
            Get-Command python, python.exe -All -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandType -eq 'Application' } | ForEach-Object { $_.Source }
            Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
        ) | Select-Object -Unique
    }
    $pythonPath = $null
    $failures = @()
    $probe = $null
    foreach ($candidate in $pythonCandidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            if ($isPlayer) { $failures += "$candidate`: not found" }
            continue
        }
        # Judged by the exit code only: a warning on stderr must not reject a working Python.
        $probe = Invoke-Bt3Probe -PythonPath $candidate -Arguments @($settingsScript, '--check')
        if ($probe.Code -eq 0) { $pythonPath = $candidate; break }
        $failures += "$candidate (exit $($probe.Code)):"
        $failures += @($probe.Lines | Where-Object { $_ -and $_.Trim() } | Select-Object -Last 6)
    }
    if (-not $pythonPath) {
        $message = 'Could not find Python 3.11 or later with Tk. ' + ($failures -join ' ')
        if ($isPlayer) {
            # It started but its Tk (or another package) is missing, or its base Python is gone.
            $startedKey = 'venv.packages'
            if ($probe -and @($probe.Lines | Where-Object { ([string]$_) -match 'tkinter|_tkinter|Tcl|\bTk\b' }).Count) { $startedKey = 'venv.tk' }
            $venvWhy = Get-Bt3VenvWhy -VenvRoot (Join-Path $PSScriptRoot '..\.venv') -Language $language -Probe $probe -StartedKey $startedKey
            $venvDetails = @(Get-Bt3VenvDetails -VenvRoot (Join-Path $PSScriptRoot '..\.venv') -Language $language) + $failures
            throw (New-Bt3Failure -Code 'TTM-PLAY-25' -What (Get-Bt3Text 'venv.what' $language) -Why $venvWhy `
                -Fix (Get-Bt3Text 'venv.fix' $language) -File $venvPython -DetailLines $venvDetails -ExitCode 2 -Message $message)
        }
        throw (New-Bt3Failure -Code 'TTM-PLAY-43' -What (Get-Bt3Text 'notk.what' $language) -Fix (Get-Bt3Text 'notk.fix' $language) `
            -DetailLines $failures -Message $message)
    }
    if ($ValidateOnly) {
        Write-Host "Settings validation passed: $pythonPath. No window was opened."
        exit 0
    }
    $logs = Join-Path $PSScriptRoot 'analysis\settings'
    [void](New-Item -ItemType Directory -Path $logs -Force)
    $token = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $errorLog = Join-Path $logs ($token + '-errors.log')
    $application = Start-Process -FilePath $pythonPath -ArgumentList @('-u', ('"' + $settingsScript + '"'), '--ui') `
        -PassThru -Wait -WindowStyle Hidden -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput (Join-Path $logs ($token + '.log')) `
        -RedirectStandardError $errorLog
    if ($application.ExitCode -ne 0) {
        # The last line of a Python error names what went wrong.
        $lastLine = @()
        if (Test-Path -LiteralPath $errorLog) {
            $lastLine = @(Get-Content -LiteralPath $errorLog -Encoding UTF8 | Where-Object { $_ -and $_.Trim() } | Select-Object -Last 1)
        }
        throw (New-Bt3Failure -Code 'TTM-PLAY-42' -What (Get-Bt3Text 'settingsfail.what' $language) -Fix (Get-Bt3Text 'unexpected.fix' $language) `
            -File $errorLog -DetailLines $lastLine -Message "The settings window could not finish. Check $logs for details.")
    }
}
catch {
    $failure = $_.Exception
    $exitCode = 1
    try { if ($failure.Data.Contains('bt3')) { $exitCode = [int]$failure.Data['bt3']['ExitCode'] } } catch { $exitCode = 1 }
    if ($ValidateOnly) {
        # A console check (no window, no dialog): an explained failure is printed as its block.
        $explained = $false
        try { $explained = [bool]$failure.Data.Contains('bt3') } catch { }
        if (-not $explained -or -not (Get-Command Format-Bt3Block -ErrorAction SilentlyContinue)) { throw }
        $data = $failure.Data['bt3']
        Write-Bt3Block -Color Yellow -Lines (Format-Bt3Block -Code $data['Code'] -What $data['What'] -Why $data['Why'] -Fix $data['Fix'] `
            -File $data['File'] -Details $data['Details'] -DetailLines $data['DetailLines'] -NothingChanged:([bool]$data['NothingChanged']) -Language $language)
        exit $exitCode
    }
    # A dialog, not a console block: this launcher runs without a visible window.
    $text = [string]$failure.Message
    try {
        if ($failure.Data.Contains('bt3')) {
            $data = $failure.Data['bt3']
            $labels = $Bt3Labels['en']
            if ($language -eq 'es') { $labels = $Bt3Labels['es'] }
            $parts = @('[' + $data['Code'] + '] ' + $data['What'])
            if ($data['Why']) { $parts += ($labels['why'] + ': ' + $data['Why']) }
            if ($data['Fix']) { $parts += ($labels['fix'] + ': ' + $data['Fix']) }
            if ($data['File']) { $parts += ($labels['file'] + ': ' + $data['File']) }
            $raw = @($data['DetailLines'] | Where-Object { $_ })
            if ($raw.Count) { $parts += ($labels['details'] + ': ' + (@($raw | Select-Object -Last 4) -join [Environment]::NewLine)) }
            $text = $parts -join ([Environment]::NewLine + [Environment]::NewLine)
        }
    }
    catch { $text = [string]$failure.Message }
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show($text, 'Tag Team Mod settings', 'OK', 'Error')
    exit $exitCode
}
