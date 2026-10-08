<# Start the clean game with the autopilot: pick teams in Versus and play.
   Exit codes (the generated Play launcher pauses on any other code than 0): 0 the session ended normally;
   1 an unexpected launch failure or a PCSX2 crash; 2 refused (PCSX2 already running, a missing or moved
   ISO, a broken private Python, a missing file); 3 the session ended after an error (status.json
   last_error, not recovered) or the mod's helper died while PCSX2 was running. #>
[CmdletBinding()]
param(
    [ValidateSet('Original', 'Player', 'Cpu', 'TwoPlayer')]
    [string]$Mode = 'Original',
    [switch]$ManualPause,
    [switch]$NoLoadingScreen,
    [ValidateSet('runtime128','runtime28')]
    [string]$RuntimeProfile = 'runtime128'
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$language = 'en'
# Python writes UTF-8 and this window reads UTF-8: accented folder names and Spanish text survive.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
. (Join-Path $PSScriptRoot 'launcher-lifecycle.ps1')
$language = Get-Bt3Language -ProjectRoot $PSScriptRoot
# Every startup failure is shown as one explained block and also written to disk: the console showing
# it closes on a key press. The exit code comes from the failure (2 for a refusal).
trap {
    $failureDirectory = Join-Path $PSScriptRoot 'analysis\autopilot'
    $known = Get-Variable -Name logDirectory -Scope Script -ErrorAction SilentlyContinue
    if ($known -and $known.Value) { $failureDirectory = $known.Value }
    $saved = $null
    if (Get-Command Write-Bt3LaunchFailure -ErrorAction SilentlyContinue) {
        $saved = Write-Bt3LaunchFailure -ErrorRecord $_ -Directory $failureDirectory
    }
    $exitCode = 1
    $data = $null
    try { if ($_.Exception.Data.Contains('bt3')) { $data = $_.Exception.Data['bt3'] } } catch { $data = $null }
    if (Get-Command Format-Bt3Block -ErrorAction SilentlyContinue) {
        if ($data) {
            $exitCode = [int]$data['ExitCode']
            $lines = Format-Bt3Block -Code $data['Code'] -What $data['What'] -Why $data['Why'] -Fix $data['Fix'] `
                -File $data['File'] -Details $data['Details'] -DetailLines $data['DetailLines'] -Log $saved `
                -NothingChanged:([bool]$data['NothingChanged']) -Language $language
        }
        else {
            $lines = Format-Bt3Block -Code 'TTM-PLAY-40' -What (Get-Bt3Text 'unexpected.what' $language) `
                -Fix (Get-Bt3Text 'unexpected.fix' $language) -DetailLines @([string]$_.Exception.Message) -Log $saved -Language $language
        }
        $color = 'Red'
        if ($exitCode -eq 2) { $color = 'Yellow' }
        Write-Bt3Block -Lines $lines -Color $color   # the block names the saved log under LOG
    }
    else {
        Write-Host ([string]$_.Exception.Message) -ForegroundColor Red
        if ($saved) { Write-Host "The full error is saved in $saved" -ForegroundColor Red }
    }
    # Every refusal after the launcher lease releases it here (Windows would also release it when this process ends).
    $heldLease = Get-Variable -Name launcherLease -Scope Script -ErrorAction SilentlyContinue
    if ($heldLease -and $heldLease.Value) { try { $heldLease.Value.Dispose() } catch { } }
    exit $exitCode
}
# Square brackets in the folder path break Start-Process and the log redirection below (PowerShell reads them as
# wildcards): refuse first, with the fix, instead of an unexpected error later (IF-06; setup refuses too).
if (Test-Bt3BracketPath -ProjectRoot $PSScriptRoot) {
    throw (New-Bt3Failure -Code 'TTM-PLAY-45' -What (Get-Bt3Text 'brackets.what' $language) -Why (Get-Bt3Text 'brackets.why' $language) `
        -Fix (Get-Bt3Text 'brackets.fix' $language) -File $PSScriptRoot -ExitCode 2 -NothingChanged `
        -Message "The installation path contains square brackets: $PSScriptRoot")
}
$env:BT3_RUNTIME_PROFILE = $RuntimeProfile
$runtimeDirectory = Join-Path $PSScriptRoot $RuntimeProfile
$emulatorPath = Join-Path $runtimeDirectory 'pcsx2-qt.exe'
$configPath = Join-Path $runtimeDirectory 'inis\PCSX2.ini'
$pineSlot = 28011
$isPlayer = Test-Bt3PlayerInstall -ProjectRoot $PSScriptRoot
# The developer tree's disc. An installation's disc (the one chosen in Mod settings > Game disc) is resolved by
# game_profile.py --where under the launcher lease, below.
$gamePath = Join-Path (Split-Path -Parent $PSScriptRoot) 'games\Dragon Ball Z - Budokai Tenkaichi 3 (USA) (En,Ja).iso'
$installedIso = $false
$discTitle = ''
$autopilot = Join-Path $PSScriptRoot 'tools\autopilot.py'
$presentationSettings = Join-Path $PSScriptRoot 'tools\presentation_settings.py'
$versionPolicyPath = Join-Path $PSScriptRoot 'tools\pcsx2_versions.json'
# The game ISO is checked after the Python probe, where a moved ISO can be found again.
foreach ($requiredPath in @($emulatorPath, $configPath, $autopilot, $presentationSettings, $versionPolicyPath, (Join-Path $runtimeDirectory 'portable.ini'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        $fixKey = 'missing.fix.dev'
        if ($isPlayer) { $fixKey = 'missing.fix' }
        throw (New-Bt3Failure -Code 'TTM-PLAY-24' -What (Get-Bt3Text 'missing.what' $language) -Why (Get-Bt3Text 'missing.why' $language) `
            -Fix (Get-Bt3Text $fixKey $language) -File $requiredPath -ExitCode 2 -NothingChanged -Message "Missing file: $requiredPath")
    }
}
# tools\pcsx2_versions.json is the single source of the accepted versions (Python reads it too).
# runtime28 is only the player folder's name: any PCSX2 2.x from player_minimum on is accepted,
# nightlies included; runtime128 is the developer runtime on one audited build.
function Test-Bt3Pcsx2Version([string]$FileVersion, [string]$RuntimeName, $Policy) {
    $found = [regex]::Match([string]$FileVersion, '(?i)^\s*(?:PCSX2\s+)?v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})(?!\d)')
    if (-not $found.Success) { return [pscustomobject]@{ Version = ''; Accepted = $false; Tested = $false } }
    $current = New-Object -TypeName System.Version -ArgumentList ([int]$found.Groups[1].Value), ([int]$found.Groups[2].Value), ([int]$found.Groups[3].Value)
    $text = '{0}.{1}.{2}' -f $current.Major, $current.Minor, $current.Build
    if ($RuntimeName -eq 'runtime28') {
        $minimum = [System.Version][string]$Policy.player_minimum
        $accepted = ($current.Major -eq $minimum.Major -and $current -ge $minimum)
    } else { $accepted = ($text -eq [string]$Policy.developer) }
    return [pscustomobject]@{ Version = $text; Accepted = $accepted; Tested = (@($Policy.tested) -contains $text) }
}
$emulatorVersion = [string][System.Diagnostics.FileVersionInfo]::GetVersionInfo($emulatorPath).FileVersion
if (-not $emulatorVersion) { $emulatorVersion = 'unknown' }
$versionPolicy = Get-Content -LiteralPath $versionPolicyPath -Raw -Encoding UTF8 | ConvertFrom-Json
$emulatorSupport = Test-Bt3Pcsx2Version -FileVersion $emulatorVersion -RuntimeName $RuntimeProfile -Policy $versionPolicy
if (-not $emulatorSupport.Accepted) {
    if ($RuntimeProfile -eq 'runtime28') { $versionDetail = "This runtime needs PCSX2 $($versionPolicy.player_minimum) or newer (2.x); it contains PCSX2 $emulatorVersion." }
    else { $versionDetail = "The developer runtime needs PCSX2 $($versionPolicy.developer); it contains PCSX2 $emulatorVersion." }
    throw (New-Bt3Failure -Code 'TTM-PLAY-29' -What (Get-Bt3Text 'version.what' $language) -Fix (Get-Bt3Text 'version.fix' $language) `
        -File $emulatorPath -DetailLines @($versionDetail) -ExitCode 2 -NothingChanged -Message $versionDetail)
}
if ($RuntimeProfile -eq 'runtime28' -and -not $emulatorSupport.Tested) {
    Write-Host (Get-Bt3Text 'version.untested' $language @{ version = $emulatorSupport.Version; tested = (@($versionPolicy.tested) -join ', ') }) -ForegroundColor Yellow
}
$configurationText = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
$profileProblem = $null
$cpuSection = [regex]::Match($configurationText, '(?ms)^\[EmuCore/CPU\]\s*\r?\n(?<body>.*?)(?=^\[|\z)')
if (-not $cpuSection.Success -or $cpuSection.Groups['body'].Value -notmatch '(?m)^ExtraMemory\s*=\s*true\s*$') {
    $profileProblem = 'The isolated profile must have ExtraMemory = true in [EmuCore/CPU].'
}
elseif ($configurationText -notmatch '(?m)^EnablePINE\s*=\s*true\s*$' -or
        $configurationText -notmatch ('(?m)^PINESlot\s*=\s*' + $pineSlot + '\s*$')) {
    $profileProblem = "Automatic preparation requires EnablePINE = true and PINESlot = $pineSlot in the isolated profile."
}
elseif ($configurationText -notmatch '(?m)^EnableCheats\s*=\s*true\s*$') {
    $profileProblem = 'The isolated profile needs EnableCheats = true for its in-game loading hook.'
}
if ($profileProblem) {
    $fixKey = 'missing.fix.dev'
    if ($isPlayer) { $fixKey = 'missing.fix' }
    throw (New-Bt3Failure -Code 'TTM-PLAY-30' -What (Get-Bt3Text 'profile.what' $language) -Fix (Get-Bt3Text $fixKey $language) `
        -File $configPath -DetailLines @($profileProblem) -ExitCode 2 -NothingChanged -Message $profileProblem)
}
# Refuse while any PCSX2 runs or anything serves the PINE port, and say which program it is. This
# installation's own PCSX2 gets a few seconds to finish closing (Play right after closing PCSX2).
$blockers = @(Resolve-Bt3Blockers -EmulatorPath $emulatorPath -Port $pineSlot -Language $language)
if ($blockers.Count) {
    $found = @($blockers | ForEach-Object { Format-Bt3Blocker $_ $pineSlot })
    $whyKey = 'running.why'
    if (@($blockers | Where-Object { -not ($_.Own -and $_.Windowless) }).Count -eq 0) { $whyKey = 'hung.why' }
    if (@($blockers | Where-Object { $_.Pcsx2 }).Count) {
        throw (New-Bt3Failure -Code 'TTM-PLAY-20' -What (Get-Bt3Text 'running.what' $language) -Why (Get-Bt3Text $whyKey $language) `
            -Fix (Get-Bt3Text 'running.fix' $language) -DetailLines $found -ExitCode 2 -NothingChanged `
            -Message ('Close the current emulator, then run this launcher again. Found: ' + ($found -join '; ')))
    }
    throw (New-Bt3Failure -Code 'TTM-PLAY-21' -What (Get-Bt3Text 'port.what' $language) -Fix (Get-Bt3Text 'port.fix' $language) `
        -DetailLines $found -ExitCode 2 -NothingChanged -Message ('Another program listens on the PINE port. Found: ' + ($found -join '; ')))
}
# Resolve and probe an actual interpreter. Start-Process must not silently use
# a different PATH Python, or leave a normal game after an import failure. A player
# installation runs only its own private Python (.venv).
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
# Serialize the entire launch from here on: the choice of the game disc (Mod settings > Game disc switches only while
# no Play window holds this lease), the probe, the ISO check and the interval before PINE listens. Windows releases
# the stream if this console is closed abruptly; the trap and the finally below dispose of it.
$launcherLease = Enter-Bt3LauncherLease -ProjectRoot $PSScriptRoot
# The game disc this session starts (game_profile.py --where), resolved once and pinned for every Python child
# (TAGTEAM_DISC). Exit 2 with TTM-PLAY-46 is a damaged choice, explained by Python. A developer tree without
# game_profile.py keeps its games folder ISO; a Python that cannot answer is diagnosed by the probe below.
Remove-Item Env:TAGTEAM_DISC -ErrorAction SilentlyContinue
$whereFailure = $null
$whereScript = Join-Path $PSScriptRoot 'tools\game_profile.py'
function Invoke-Bt3Where([string]$Python) {
    # One answer of game_profile.py --where --json: TTM-PLAY-46 ends the launch here (Python explained it), a JSON
    # line sets the disc and its pin; anything else comes back as the failure text (a Python that cannot answer).
    $where = Invoke-Bt3Probe -PythonPath $Python -Arguments @($whereScript, '--where', '--json')
    if ($where.Code -eq 2 -and @($where.Lines | Where-Object { ([string]$_) -match '\[TTM-PLAY-46\]' }).Count) {
        Write-Bt3Block -Color Yellow -Lines @($where.Lines | Where-Object { $_ -and -not ([string]$_).StartsWith('{') })
        $script:launcherLease.Dispose()
        exit 2
    }
    $whereLine = @($where.Lines | Where-Object { ([string]$_).StartsWith('{') } | Select-Object -Last 1)
    if ($where.Code -eq 0 -and $whereLine.Count) {
        $disc = [string]$whereLine[0] | ConvertFrom-Json
        if ($disc.player) {
            $script:gamePath = [string]$disc.iso
            $script:installedIso = $true
            $script:discTitle = [string]$disc.title
            Remove-Item Env:TAGTEAM_ADAPTER -ErrorAction SilentlyContinue
            $env:TAGTEAM_DISC = [string]$disc.key
        }
        return $null
    }
    return ("game_profile.py --where ended with exit status $($where.Code): " + (@($where.Lines | Where-Object { $_ }) -join ' '))
}
$wherePython = @($pythonCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1)
if ((Test-Path -LiteralPath $whereScript -PathType Leaf) -and $wherePython.Count) {
    $whereFailure = Invoke-Bt3Where -Python $wherePython[0]
}
$pythonPath = $null
$probeFailures = @()
$probe = $null
foreach ($candidate in $pythonCandidates) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        if ($isPlayer) { $probeFailures += "$candidate`: not found" }
        continue
    }
    $probe = Invoke-Bt3Probe -PythonPath $candidate -Arguments @($autopilot, '--check')
    if ($probe.Code -eq 0) { $pythonPath = $candidate; break }
    $tail = @($probe.Lines | Where-Object { $_ -and $_.Trim() } | Select-Object -Last 8)
    # 3 and 4: this Python works; the mod settings file or a game file is the problem (autopilot.py --check).
    if ($probe.Code -eq 3) {
        throw (New-Bt3Failure -Code 'TTM-PLAY-27' -What (Get-Bt3Text 'settings.what' $language) -Why (Get-Bt3Text 'settings.why' $language) `
            -Fix (Get-Bt3Text 'settings.fix' $language) -File (Join-Path $PSScriptRoot 'mod-settings.json') -DetailLines $tail -ExitCode 2 `
            -NothingChanged -Message ('Mod settings cannot be read. ' + ($tail -join ' ')))
    }
    if ($probe.Code -eq 4) {
        $fixKey = 'missing.fix.dev'
        if ($isPlayer) { $fixKey = 'missing.fix' }
        throw (New-Bt3Failure -Code 'TTM-PLAY-28' -What (Get-Bt3Text 'gamefiles.what' $language) -Fix (Get-Bt3Text $fixKey $language) `
            -DetailLines $tail -ExitCode 2 -NothingChanged -Message ('A game file of the mod is missing or does not match. ' + ($tail -join ' ')))
    }
    $probeFailures += "$candidate (exit $($probe.Code)):"
    $probeFailures += $tail
}
if (-not $pythonPath) {
    $message = 'No Python 3.11+ with the trainer dependencies could start. ' + ($probeFailures -join ' ')
    if ($isPlayer) {
        # It started but misses a package (autopilot.py --check exit 2), or its base Python is gone.
        $venvWhy = Get-Bt3VenvWhy -VenvRoot (Join-Path $PSScriptRoot '..\.venv') -Language $language -Probe $probe
        $venvDetails = @(Get-Bt3VenvDetails -VenvRoot (Join-Path $PSScriptRoot '..\.venv') -Language $language) + $probeFailures
        throw (New-Bt3Failure -Code 'TTM-PLAY-25' -What (Get-Bt3Text 'venv.what' $language) -Why $venvWhy `
            -Fix (Get-Bt3Text 'venv.fix' $language) -File $venvPython -DetailLines $venvDetails -ExitCode 2 -NothingChanged -Message $message)
    }
    throw (New-Bt3Failure -Code 'TTM-PLAY-26' -What (Get-Bt3Text 'nopython.what' $language) -Fix (Get-Bt3Text 'nopython.fix' $language) `
        -DetailLines $probeFailures -ExitCode 2 -NothingChanged -Message $message)
}
if ($whereFailure -and $pythonPath -ne $wherePython[0]) {
    # A developer tree: the first interpreter found could not answer, but the probe chose a later one that works.
    $whereFailure = Invoke-Bt3Where -Python $pythonPath
}
if ($whereFailure) {
    # This Python works (the probe passed), yet it could not name the game disc: never start a guessed disc.
    throw (New-Bt3Failure -Code 'TTM-PLAY-40' -What (Get-Bt3Text 'unexpected.what' $language) -Fix (Get-Bt3Text 'unexpected.fix' $language) `
        -DetailLines @($whereFailure) -NothingChanged -Message $whereFailure)
}
# The ISO blocks name this installation's launchers, as the Python blocks do (play_launcher.py entry: localization.entry);
# plain 'Play' and 'Mod settings' when that cannot run.
function Get-Bt3EntryName([string]$Name, [string]$Default) {
    $entry = Invoke-Bt3Probe -PythonPath $pythonPath -Arguments @((Join-Path $PSScriptRoot 'tools\play_launcher.py'), 'entry', $Name)
    $named = @($entry.Lines | Where-Object { $_ -and ([string]$_).Trim() })
    if ($entry.Code -eq 0 -and $named.Count) { return ([string]$named[$named.Count - 1]).Trim() }
    return $Default
}
function Get-Bt3IsoFix {
    $name = Get-Bt3EntryName 'play' 'Play'
    return (Get-Bt3Text 'iso.fix' $language @{ play = $name })
}
# A moved or deleted game ISO: explain, then offer to find it again (only the same file is accepted).
if (-not (Test-Path -LiteralPath $gamePath -PathType Leaf)) {
    $isoFix = Get-Bt3IsoFix
    $isoFailure = New-Bt3Failure -Code 'TTM-PLAY-22' -What (Get-Bt3Text 'iso.what' $language) -Why (Get-Bt3Text 'iso.why' $language) `
        -Fix $isoFix -File $gamePath -ExitCode 2 -NothingChanged -Message "Missing file: $gamePath"
    if (-not $installedIso -or -not (Test-Bt3Interactive)) { throw $isoFailure }
    Write-Bt3Block -Color Yellow -Lines (Format-Bt3Block -Code 'TTM-PLAY-22' -What (Get-Bt3Text 'iso.what' $language) `
        -Why (Get-Bt3Text 'iso.why' $language) -Fix $isoFix -File $gamePath -Language $language)
    if (-not (Read-Bt3YesNo (Get-Bt3Text 'iso.prompt' $language))) { throw $isoFailure }
    Add-Type -AssemblyName System.Windows.Forms
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = Get-Bt3Text 'iso.title' $language @{ disc = $discTitle }
    $picker.Filter = 'PlayStation 2 ISO (*.iso)|*.iso|All files (*.*)|*.*'
    $picker.InitialDirectory = Split-Path -Parent $gamePath
    if ($picker.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw $isoFailure }
    # game_profile.py hashes the file (with progress), accepts only the installed ISO and saves iso-location.json.
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $pythonPath (Join-Path $PSScriptRoot 'tools\game_profile.py') '--relink' $picker.FileName 2>&1 | ForEach-Object { Write-Host "$_" }
        $relinkCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $savedPreference }
    if ($relinkCode -ne 0) { $launcherLease.Dispose(); exit 2 }   # game_profile.py has explained why the file was refused
}
# The ISO check can hash the whole ISO (after a relink or a changed file): its progress is shown as it
# comes (stderr), and the selected path is the JSON string line on stdout.
$mapNotes = New-Object System.Collections.Generic.List[string]
$mapPath = New-Object System.Collections.Generic.List[string]
$mapCode = -1
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & $pythonPath (Join-Path $PSScriptRoot 'tools\map_scale_launch.py') '--json' 2>&1 | ForEach-Object {
        $mapLine = "$_"
        if ($mapLine -match '^\s*"') { $mapPath.Add($mapLine) }
        elseif ($mapLine.Trim()) {
            Write-Host $mapLine
            # Progress was just shown; the failure block keeps the messages only.
            if ($mapLine -notmatch '^(?:Fingerprinting ISO: \d+%|Using unchanged ISO compatibility profile|Checking the game ISO: \d+%|Comprobando la ISO del juego: \d+%|Checking (?:fighter|stage) resources: \d+/\d+|Comprobando los recursos de los (?:luchadores|escenarios): \d+/\d+)') { $mapNotes.Add($mapLine) }
        }
    }
    $mapCode = $LASTEXITCODE
    if ($null -eq $mapCode) { $mapCode = -1 }
}
catch { $mapNotes.Add([string]$_.Exception.Message); $mapCode = -1 }
finally { $ErrorActionPreference = $savedPreference }
# 4: the chosen game disc's files failed their check; map_scale_launch.py has shown its TTM-PLAY-46 block above.
if ($mapCode -eq 4) { $launcherLease.Dispose(); exit 2 }
if ($mapCode -eq 2) {
    $isoCheckFix = Get-Bt3Text 'isocheck.fix' $language @{ mod_settings = (Get-Bt3EntryName 'mod_settings' 'Mod settings') }
    throw (New-Bt3Failure -Code 'TTM-PLAY-23' -What (Get-Bt3Text 'isocheck.what' $language) -Fix $isoCheckFix `
        -File $gamePath -DetailLines $mapNotes.ToArray() -ExitCode 2 -NothingChanged -Message ('Game ISO check failed. ' + ($mapNotes.ToArray() -join ' ')))
}
if ($mapCode -ne 0 -or -not $mapPath.Count) {
    throw (New-Bt3Failure -Code 'TTM-PLAY-39' -What (Get-Bt3Text 'maps.what' $language) -Fix (Get-Bt3Text 'maps.fix' $language) `
        -DetailLines $mapNotes.ToArray() -NothingChanged -Message ('Expanded-map selection failed. ' + ($mapNotes.ToArray() -join ' ')))
}
$gamePath = [string]($mapPath[$mapPath.Count - 1] | ConvertFrom-Json)
if (-not (Test-Path -LiteralPath $gamePath -PathType Leaf)) {
    throw (New-Bt3Failure -Code 'TTM-PLAY-22' -What (Get-Bt3Text 'iso.what' $language) -Why (Get-Bt3Text 'iso.why' $language) `
        -Fix (Get-Bt3IsoFix) -File $gamePath -ExitCode 2 -NothingChanged -Message "Selected game ISO is missing: $gamePath")
}
$logDirectory = Join-Path $PSScriptRoot ('analysis\autopilot\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
[void](New-Item -ItemType Directory -Path $logDirectory -Force)
$stdoutPath = Join-Path $logDirectory 'watcher.log'
$stderrPath = Join-Path $logDirectory 'errors.log'
$statusPath = Join-Path $logDirectory 'status.json'
# The hints come from play_launcher.py in the player's language (the same lines as on Linux).
$hintArguments = @((Join-Path $PSScriptRoot 'tools\play_launcher.py'), 'hints', '--logs', $logDirectory)
if ($ManualPause) { $hintArguments += '--manual-pause' }
# The disc this session starts (resolved above under the lease), so the window names it.
if ($discTitle) { $hintArguments += @('--disc', $discTitle) }
$hints = Invoke-Bt3Probe -PythonPath $pythonPath -Arguments $hintArguments
if ($hints.Code -eq 0 -and $hints.Lines.Count) { $hints.Lines | ForEach-Object { Write-Host $_ } }
else { Write-Host "Preparation status and errors remain in this window. Logs: $logDirectory" }
$watcher = $null
$watcherWorker = $null
$launcherToken = [guid]::NewGuid().ToString('N')
$emulatorProcess = $null
$settingsWatcher = $null
$watcherFailed = $false
$watcherExit = $null
$earlyExit = $false
$emulatorExit = $null
$logState = @{ Offset = 0 }
$startupComplete = $false
function Restore-Bt3Display {
    # A warning on stderr must not turn the clean-up into a failure (Invoke-Bt3Probe judges by exit code).
    $restore = Invoke-Bt3Probe -PythonPath $pythonPath -Arguments @($presentationSettings, 'restore')
    $restore.Lines | Where-Object { $_ } | ForEach-Object { Write-Host $_ }
    if ($restore.Code -ne 0) { Write-Host "Restoring the display settings failed (exit $($restore.Code))." -ForegroundColor Yellow }
}
# The launcher lease taken before the game disc was resolved is held until PCSX2 closes (finally below).
try {
    if (@(Get-Process -Name 'pcsx2*' -ErrorAction SilentlyContinue).Count) {
        throw (New-Bt3Failure -Code 'TTM-PLAY-41' -What (Get-Bt3Text 'appeared.what' $language) -Fix (Get-Bt3Text 'appeared.fix' $language) `
            -ExitCode 2 -NothingChanged -Message 'An emulator opened while this launcher was starting. Close it before launching again.')
    }
    Invoke-Bt3LaunchStep -PythonPath $pythonPath -LogDirectory $logDirectory -Name 'storage' -Language $language `
        -Description 'Could not check generated-file retention.' `
        -Arguments ('"' + (Join-Path $PSScriptRoot 'tools\player_storage.py') + '"')
    Invoke-Bt3LaunchStep -PythonPath $pythonPath -LogDirectory $logDirectory -Name 'boot-hooks' -Language $language `
        -Description 'Could not install the isolated in-game loading screen.' `
        -Arguments ('"' + (Join-Path $PSScriptRoot 'tools\install_boot_hooks.py') + '"')
    Invoke-Bt3LaunchStep -PythonPath $pythonPath -LogDirectory $logDirectory -Name 'display' -Language $language `
        -Description 'Could not prepare the isolated display settings.' `
        -Arguments ('"' + $presentationSettings + '" apply')
    # A GUI executable can return from PowerShell invocation while still open.
    # Follow the actual process, so finally cannot immediately kill its watcher.
    $emulatorProcess = Start-Process -FilePath $emulatorPath -ArgumentList @('-portable', '-fastboot', '--', ('"' + $gamePath + '"')) `
        -PassThru -WorkingDirectory $runtimeDirectory
    # This independent watchdog survives a closed launcher and restores the
    # temporary display/startup keys after PCSX2 has written its settings.
    # Its output is kept (a failed restore must leave a trace).
    $settingsWatcher = Start-Process -FilePath $pythonPath -ArgumentList @(('"' + $presentationSettings + '"'),
        'watch', '--pid', $emulatorProcess.Id) -PassThru -WindowStyle Hidden -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput (Join-Path $logDirectory 'settings-watchdog.log') -RedirectStandardError (Join-Path $logDirectory 'settings-watchdog.err.log')
    try { $null = $settingsWatcher.Handle } catch { }   # a redirected process keeps its exit code only with a handle
    # Bind the controller to this exact process. A watcher must never discover
    # and attach to a later emulator after its original one has closed.
    $watcherArguments = @('-u', ('"' + $autopilot + '"'), '--mode', $Mode,
        '--status-file', ('"' + $statusPath + '"'), '--emulator-pid', $emulatorProcess.Id, '--launcher-token', $launcherToken)
    if ($ManualPause) { $watcherArguments += '--manual-pause' }
    if ($NoLoadingScreen) { $watcherArguments += '--no-loading-screen' }
    $watcher = Start-Process -FilePath $pythonPath -ArgumentList $watcherArguments -PassThru -WindowStyle Hidden -WorkingDirectory $PSScriptRoot `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    try { $null = $watcher.Handle } catch { }   # keeps ExitCode readable after exit on Windows PowerShell 5.1
    $readyDeadline = (Get-Date).AddSeconds(10)
    $controllerReady = $false
    do {
        if ($emulatorProcess.HasExited) { break }
        if ($watcher.HasExited) {
            $helperTail = @()
            if (Test-Path -LiteralPath $stderrPath) { $helperTail = @(Get-Content -LiteralPath $stderrPath -Tail 12 -Encoding UTF8) }
            throw (New-Bt3Failure -Code 'TTM-PLAY-33' -What (Get-Bt3Text 'helper.what' $language) -Fix (Get-Bt3Text 'helper.fix' $language) `
                -File $stderrPath -DetailLines $helperTail -Message "Automatic preparation could not start. Read $stderrPath")
        }
        if (Test-Path -LiteralPath $statusPath) {
            try {
                $controllerStatus = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $controllerReady = Test-Bt3ControllerStatus -Status $controllerStatus -Token $launcherToken -EmulatorId $emulatorProcess.Id
                if ($controllerReady) {
                    # Retain the authenticated worker's process object too, so
                    # forced cleanup cannot orphan a venv redirector child.
                    $watcherWorker = Get-Process -Id $controllerStatus.pid -ErrorAction Stop
                    $null = $watcherWorker.Handle
                    $controllerReady = -not $watcherWorker.HasExited
                }
            }
            catch { $controllerReady = $false }
        }
        if (-not $controllerReady) { Start-Sleep -Milliseconds 100 }
    } while (-not $controllerReady -and (Get-Date) -lt $readyDeadline)
    if (-not $controllerReady -and -not $emulatorProcess.HasExited) {
        $helperTail = @()
        if (Test-Path -LiteralPath $stderrPath) { $helperTail = @(Get-Content -LiteralPath $stderrPath -Tail 12 -Encoding UTF8) }
        throw (New-Bt3Failure -Code 'TTM-PLAY-34' -What (Get-Bt3Text 'confirm.what' $language) -Why (Get-Bt3Text 'confirm.why' $language) `
            -Fix (Get-Bt3Text 'confirm.fix' $language) -File $stderrPath -DetailLines $helperTail `
            -Message 'The controller did not confirm ownership of this emulator.')
    }
    # PCSX2 closed before the helper confirmed it: a crash unless it ended normally (checked after clean-up).
    if (-not $controllerReady) { $earlyExit = $true }
    $startupComplete = $true
    while (-not $emulatorProcess.HasExited) {
        foreach ($line in @(Read-Bt3LogLines -Path $stdoutPath -State $logState)) { Write-Bt3LogLine -Line $line }
        if ($watcher.HasExited -and -not $watcherFailed) {
            $emulatorProcess.Refresh()
            if ($emulatorProcess.HasExited) { break }
            $watcherFailed = $true
            try { $watcherExit = $watcher.ExitCode } catch { $watcherExit = $null }
            Write-Host (Get-Bt3Text 'helperstop.line' $language @{ code = [string]$watcherExit; logs = $logDirectory }) -ForegroundColor Red
            if (Test-Path -LiteralPath $stderrPath) {
                Get-Content -LiteralPath $stderrPath -Tail 24 -Encoding UTF8 | ForEach-Object { Write-Host $_ -ForegroundColor Red }
            }
        }
        Start-Sleep -Milliseconds 500
        $emulatorProcess.Refresh()
        $watcher.Refresh()
    }
    try { $emulatorProcess.Refresh(); $emulatorExit = $emulatorProcess.ExitCode } catch { $emulatorExit = $null }
}
catch {
    # An explained failure is shown once, by the trap's block (with its own details); only an unexpected
    # one gets the raw message and the helper's error tail here.
    $explained = $false
    try { $explained = [bool]$_.Exception.Data.Contains('bt3') } catch { }
    if (-not $explained) {
        Write-Host "AUTOMATIC PREPARATION ERROR: $($_.Exception.Message)" -ForegroundColor Red
        if (Test-Path -LiteralPath $stderrPath) {
            Get-Content -LiteralPath $stderrPath -Tail 24 -Encoding UTF8 | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        }
    }
    throw
}
finally {
    try {
    if (-not $startupComplete -and $emulatorProcess -and -not $emulatorProcess.HasExited) {
        Stop-Bt3OwnedHelper -Process $emulatorProcess -GraceMilliseconds 0
    }
    Stop-Bt3OwnedHelper -Process $watcherWorker
    Stop-Bt3OwnedHelper -Process $watcher
    # The watcher's last lines (it reports the close after PCSX2 exits); shutdown noise stays in the log.
    foreach ($line in @(Read-Bt3LogLines -Path $stdoutPath -State $logState -Final)) { Write-Bt3LogLine -Line $line -Closing }
    if (-not $emulatorProcess) { Restore-Bt3Display }
    elseif (-not $settingsWatcher) {
        Write-Host 'Waiting for the emulator to close before restoring display settings.'
        $emulatorProcess.WaitForExit()
        Restore-Bt3Display
    }
    elseif ($emulatorProcess.HasExited) {
        Stop-Bt3OwnedHelper -Process $settingsWatcher
        Restore-Bt3Display
    }
    }
    finally { if ($launcherLease) { $launcherLease.Dispose() } }
}
# The outcome. Closing PCSX2 after a normal session ends with 0 and the window closes; after an error
# the window stays open (the Play launcher pauses on any other code) with the explanation on screen.
# An exception code (0xC0000005 and the like) is a PCSX2 crash, not a close.
$crashed = ($null -ne $emulatorExit -and ([int]$emulatorExit -band 0xF0000000) -eq 0xC0000000)
$exitText = 'unknown'
if ($null -ne $emulatorExit) { $exitText = [string]$emulatorExit + ' (0x' + ([int]$emulatorExit).ToString('X8') + ')' }
if ($earlyExit -and $crashed) {
    Write-Bt3Block -Color Red -Lines (Format-Bt3Block -Code 'TTM-PLAY-36' -What (Get-Bt3Text 'crash.what' $language) `
        -Why (Get-Bt3Text 'crash.why' $language) -Fix (Get-Bt3Text 'crash.fix' $language) `
        -Details ('PCSX2 exit code: 0x' + ([int]$emulatorExit).ToString('X8')) -Log $logDirectory -Language $language)
    exit 1
}
if ($earlyExit -and $emulatorExit -ne 0) {
    Write-Bt3Block -Color Red -Lines (Format-Bt3Block -Code 'TTM-PLAY-35' -What (Get-Bt3Text 'early.what' $language) `
        -Fix (Get-Bt3Text 'early.fix' $language) -Details ('PCSX2 exit code: ' + $exitText) -Log $logDirectory -Language $language)
    exit 1
}
$lastError = Read-Bt3LastError -StatusPath $statusPath
$lastErrorRecovered = $false
if ($lastError -and $lastError.PSObject.Properties['recovered']) { $lastErrorRecovered = [bool]$lastError.recovered }
if ($lastError -and -not $lastErrorRecovered) {
    Write-Host (Get-Bt3Text 'session.what' $language) -ForegroundColor Red
    Write-Bt3Block -Color Red -Lines (Format-Bt3Block -Code (Get-Bt3Field $lastError 'code') -What (Get-Bt3Field $lastError 'what') `
        -Why (Get-Bt3Field $lastError 'cause') -Fix (Get-Bt3Field $lastError 'action') -Report (Get-Bt3Field $lastError 'report') `
        -Log $logDirectory -Details (Get-Bt3Field $lastError 'detail') -Language $language)
    exit 3
}
if ($watcherFailed -and $watcherExit -ne 0) {
    Write-Bt3Block -Color Red -Lines (Format-Bt3Block -Code 'TTM-PLAY-37' -What (Get-Bt3Text 'stopped.what' $language) `
        -Fix (Get-Bt3Text 'stopped.fix' $language) -Details ('Helper exit code: ' + $watcherExit) -File $stderrPath -Log $logDirectory -Language $language)
    exit 3
}
if ($lastError) {
    Write-Host (Get-Bt3Text 'recovered.what' $language) -ForegroundColor Yellow
    $recoveredReport = Get-Bt3Field $lastError 'report'
    if ($recoveredReport) { Write-Host $recoveredReport -ForegroundColor Yellow }
}
if ($crashed) {
    Write-Bt3Block -Color Red -Lines (Format-Bt3Block -Code 'TTM-PLAY-36' -What (Get-Bt3Text 'crash.what' $language) `
        -Why (Get-Bt3Text 'crash.why' $language) -Fix (Get-Bt3Text 'crash.fix' $language) `
        -Details ('PCSX2 exit code: 0x' + ([int]$emulatorExit).ToString('X8')) -Log $logDirectory -Language $language)
    exit 1
}
exit 0
