[CmdletBinding()]
param([string]$Destination, [string]$Iso, [string]$PCSX2, [string]$Bios, [ValidateSet('en','es','')][string]$Language = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
# A 32-bit PowerShell (opened from a 32-bit program) sees Program Files (x86) and a redirected System32, so it would
# miss a machine-wide Python and check the 32-bit Visual C++ files: run the 64-bit PowerShell instead.
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    $native = Join-Path $env:WINDIR 'Sysnative\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $native -PathType Leaf) {
        $forward = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
        foreach ($name in @('Destination','Iso','PCSX2','Bios','Language')) {
            $value = [string](Get-Variable -Name $name -ValueOnly)
            if ($value) { $forward += @("-$name", $value) }
        }
        & $native @forward
        exit $LASTEXITCODE
    }
}
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONPATH = ''
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ownedDestination = $false
$transcriptStarted = $false
$stage = 'Checking installer files'
$exitCode = 1
$script:setupFolder = $PSScriptRoot
$script:translations = $null
$script:messages = $null
# Failure blocks are shown in English, then Spanish, until the language is chosen.
$script:blockLanguage = 'both'
$script:failure = $null
$script:cancelled = ''
$script:systemChanged = $false
$script:beside = ''
$script:installed = $false
$script:interactive = -not [bool]$Destination
# -Destination, -Iso and -PCSX2 given: no dialog opens, so a BIOS the PCSX2 settings do not give is a coded failure.
$script:unattended = [bool]($Destination -and $Iso -and $PCSX2)

#region setup functions
function L([string]$Text) {
    if ($Language -eq 'es' -and $script:translations -and $script:translations.PSObject.Properties[$Text]) { return $script:translations.$Text }
    return $Text
}
function Get-Messages {
    if ($null -eq $script:messages) {
        $path = Join-Path $script:setupFolder 'messages.json'
        if (Test-Path -LiteralPath $path -PathType Leaf) { $script:messages = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json }
    }
    return $script:messages
}
function ConvertTo-Table($Value) {
    # install-status.json details (PSCustomObject) and hashtables alike; PowerShell 5.1 has no -AsHashtable.
    $table = [ordered]@{}
    if ($null -eq $Value) { return $table }
    if ($Value -is [System.Collections.IDictionary]) { foreach ($key in $Value.Keys) { $table[[string]$key] = $Value[$key] }; return $table }
    foreach ($property in $Value.PSObject.Properties) { $table[$property.Name] = $property.Value }
    return $table
}
function Get-PlaceholderText($Value, [string]$Lang) {
    # A value is plain text, or @{en=...; es=...} for text that is itself translated (setup_messages.pick).
    if ($null -eq $Value) { return '' }
    if ($Value -is [System.Collections.IDictionary]) {
        if ($Value.Contains($Lang) -and $Value[$Lang]) { return [string]$Value[$Lang] }
        if ($Value.Contains('en')) { return [string]$Value['en'] }
        return ''
    }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $property = $Value.PSObject.Properties[$Lang]
        if ($property -and $property.Value) { return [string]$property.Value }
        $property = $Value.PSObject.Properties['en']
        if ($property) { return [string]$property.Value }
        return ''
    }
    return [string]$Value
}
function Get-PlatformValues {
    $profileFolder = $env:USERPROFILE
    if (-not $profileFolder) { $profileFolder = [Environment]::GetFolderPath('UserProfile') }
    return [ordered]@{ install = 'Install.cmd'; play = 'Play.cmd'; check = 'Check installation.cmd'; settings = 'Mod settings.cmd';
        recommended = (Join-Path (Join-Path $profileFolder 'Games') 'Tag Team Mod'); platform = 'Windows x64'; cards = 'game/runtime28/memcards';
        bios_option = '-Bios' }
}
function Format-MessageText([string]$Template, [string]$Lang, $Values) {
    # Named placeholders are replaced with .Replace('{name}', value): -f is positional. An unknown one becomes '?'.
    $merged = Get-PlatformValues
    $table = ConvertTo-Table $Values
    foreach ($key in $table.Keys) { $merged[$key] = $table[$key] }
    $text = $Template
    foreach ($key in $merged.Keys) { $text = $text.Replace('{' + $key + '}', (Get-PlaceholderText $merged[$key] $Lang)) }
    return [regex]::Replace($text, '\{\w+\}', '?')
}
function Get-MessageText([string]$Code, [string]$Part, [string]$Lang, $Values) {
    $catalog = Get-Messages
    if ($Lang -ne 'es') { $Lang = 'en' }
    if ($null -eq $catalog -or -not $catalog.codes.PSObject.Properties[$Code]) {
        if ($Part -eq 'what') { return (Get-PlaceholderText ((ConvertTo-Table $Values)['reason']) $Lang) }
        return ''
    }
    $row = $catalog.codes.$Code
    return (Format-MessageText ([string]$row.$Lang.$Part) $Lang $Values)
}
function Get-Label([string]$Key, [string]$Lang) {
    $fallback = @{ en = @{ what='WHAT HAPPENED'; why='WHY'; fix='HOW TO FIX'; file='FILE'; details='DETAILS'; log='LOG';
        unchanged='Nothing was changed.'; copy='Copy this block when asking for help.'; setup='SETUP STOPPED';
        check='INSTALLATION CHECK FAILED'; launcher='CANNOT START'; warning='WARNING'; notice='NOTE'; ok='OK'; warn='WARN'; fail='FAIL' } }
    $catalog = Get-Messages
    if ($Lang -ne 'es') { $Lang = 'en' }
    if ($catalog -and $catalog.labels.PSObject.Properties[$Lang] -and $catalog.labels.$Lang.PSObject.Properties[$Key]) { return [string]$catalog.labels.$Lang.$Key }
    return [string]$fallback['en'][$Key]
}
function Format-Wrapped([string]$Text) {
    # Greedy word wrap at 78 columns on single spaces; continuation lines indented (setup_messages.wrap).
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($paragraph in ($Text -split "`n")) {
        $line = ''
        foreach ($word in ($paragraph -split ' ')) {
            if ($word -eq '') { continue }
            if ($line -eq '') { if ($lines.Count -eq 0) { $line = $word } else { $line = '  ' + $word } }
            elseif (($line.Length + 1 + $word.Length) -le 78) { $line = $line + ' ' + $word }
            else { $lines.Add($line); $line = '  ' + $word }
        }
        if ($line -ne '') { $lines.Add($line) }
    }
    return ,$lines.ToArray()
}
function Get-CodeFamily([string]$Code) {
    $match = [regex]::Match($Code, '^TTM-([A-Z0-9]+)-\d\d$')
    if ($match.Success) { return $match.Groups[1].Value }
    return 'PAYLOAD'
}
function Get-FailureExitCode([string]$Code) {
    $catalog = Get-Messages
    $family = Get-CodeFamily $Code
    if ($catalog -and $catalog.families.PSObject.Properties[$family]) { return [int]$catalog.families.$family }
    return 80
}
function Format-SetupFailure([string]$Code, $Values, [string]$Lang, $Unchanged, $File, [string]$Detail, [string]$Log) {
    # The same block as setup_messages.render (a test compares both).
    if ($Lang -eq 'both') { $languages = @('en','es') } elseif ($Lang -eq 'es') { $languages = @('es') } else { $languages = @('en') }
    $catalog = Get-Messages
    $row = $null
    if ($catalog -and $catalog.codes.PSObject.Properties[$Code]) { $row = $catalog.codes.$Code }
    if ($null -eq $Unchanged) { $Unchanged = [bool]($row -and $row.unchanged) }
    $family = Get-CodeFamily $Code
    $kind = 'setup'
    if ($family -eq 'CHECK') { $kind = 'check' } elseif ($family -eq 'PLAY') { $kind = 'launcher' }
    if ($row -and $row.PSObject.Properties['kind']) { $kind = [string]$row.kind }
    $rule = '=' * 78; $thin = '-' * 78
    $both = { param($Key) (($languages | ForEach-Object { Get-Label $Key $_ }) -join ' / ') }
    $out = New-Object System.Collections.Generic.List[string]
    $out.Add($rule); $out.Add('[' + $Code + '] ' + (& $both $kind)); $out.Add($thin)
    for ($index = 0; $index -lt $languages.Count; $index++) {
        $language = $languages[$index]
        if ($index -gt 0) { $out.Add($thin) }
        foreach ($part in @('what','why','fix')) {
            $body = Get-MessageText $Code $part $language $Values
            if ($body) { foreach ($line in (Format-Wrapped ((Get-Label $part $language) + ': ' + $body))) { $out.Add($line) } }
        }
        if ($Unchanged) { $out.Add((Get-Label 'unchanged' $language)) }
    }
    if ($languages.Count -gt 1) { $out.Add($thin) }
    $paths = @($File | Where-Object { $null -ne $_ -and [string]$_ -ne '' })
    if ($paths.Count -gt 0) { $out.Add((& $both 'file') + ':'); foreach ($path in $paths) { $out.Add('  ' + [string]$path) } }
    if ($Detail) { foreach ($line in (Format-Wrapped ((& $both 'details') + ': ' + $Detail))) { $out.Add($line) } }
    if ($Log) { $out.Add((& $both 'log') + ':'); $out.Add('  ' + $Log) }
    foreach ($line in (Format-Wrapped (& $both 'copy'))) { $out.Add($line) }
    $out.Add($rule)
    return ($out.ToArray() -join "`n")
}
function Format-SetupLine([string]$Code, [string]$Lang, $Values) {
    $parts = @($Code, (Get-MessageText $Code 'what' $Lang $Values), (Get-MessageText $Code 'fix' $Lang $Values)) | Where-Object { $_ }
    return ($parts -join ' ')
}
function Stop-Setup([string]$Code, $Values = @{}, $File = $null, [string]$Detail = '', $Unchanged = $null) {
    $script:failure = @{ Code = $Code; Values = $Values; File = $File; Detail = $Detail; Unchanged = $Unchanged }
    throw ('Setup stopped: ' + $Code)
}
function Stop-Cancelled([string]$Text) {
    $script:cancelled = $Text
    throw 'Setup cancelled'
}
function Format-Size([long]$Size) {
    # setup_messages / install_player.size_text: floor to one decimal with integer arithmetic.
    foreach ($unit in @(@(1073741824,'GiB'), @(1048576,'MiB'), @(1024,'KiB'))) {
        $base = [long]$unit[0]
        if ($Size -ge $base) {
            $tenths = [long](($Size * 10 - (($Size * 10) % $base)) / $base)
            $whole = [long](($tenths - ($tenths % 10)) / 10)
            $text = [string]$whole
            if ($tenths % 10) { $text += '.' + [string]($tenths % 10) }
            return $text + ' ' + $unit[1]
        }
    }
    return ([string]$Size + ' bytes')
}
function Read-Head([string]$Path, [int]$Count) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    try {
        $buffer = New-Object byte[] $Count
        $read = 0
        while ($read -lt $Count) { $n = $stream.Read($buffer, $read, $Count - $read); if ($n -le 0) { break }; $read += $n }
        if ($read -lt $Count) { $short = New-Object byte[] $read; [Array]::Copy($buffer, $short, $read); return ,$short }
        return ,$buffer
    } finally { $stream.Dispose() }
}
function Test-Bytes([byte[]]$Data, [byte[]]$Magic, [int]$Offset = 0) {
    if ($Data.Length -lt ($Offset + $Magic.Length)) { return $false }
    for ($i = 0; $i -lt $Magic.Length; $i++) { if ($Data[$Offset + $i] -ne $Magic[$i]) { return $false } }
    return $true
}
function Get-ArchiveName([byte[]]$Head) {
    foreach ($row in @(@([byte[]](0x37,0x7A,0xBC,0xAF,0x27,0x1C), '7z'), @([byte[]](0x50,0x4B,0x03,0x04), 'ZIP'),
                       @([byte[]](0x50,0x4B,0x05,0x06), 'ZIP'), @([byte[]](0x52,0x61,0x72,0x21,0x1A,0x07), 'RAR'),
                       @([byte[]](0x1F,0x8B), 'gzip (.gz)'))) {
        if (Test-Bytes $Head $row[0]) { return $row[1] }
    }
    return ''
}
function Get-IsoProblem([string]$Path) {
    # install_player.iso_problem and iso_compatibility.disc.image_problem sniff the same bytes (a test compares them).
    $size = (Get-Item -LiteralPath $Path).Length
    $head = Read-Head $Path 65536
    $ascii = [Text.Encoding]::ASCII
    if (Test-Bytes $head $ascii.GetBytes('MComprHD')) { return @{ Code = 'TTM-ISO-02'; Values = @{ format = 'CHD' } } }
    if ((Test-Bytes $head $ascii.GetBytes('CISO')) -or (Test-Bytes $head $ascii.GetBytes('ZISO'))) {
        $kind = [string][char]$head[0] + 'SO'
        return @{ Code = 'TTM-ISO-03'; Values = @{ format = $kind; extension = $kind.ToLowerInvariant() } }
    }
    $archive = Get-ArchiveName $head
    if ($archive) { return @{ Code = 'TTM-ISO-01'; Values = @{ format = $archive } } }
    $sync = [byte[]](@(0x00) + @(0xFF) * 10 + @(0x00))
    $start = ''
    if ($head.Length -gt 0) { $start = [Text.Encoding]::GetEncoding(28591).GetString($head, 0, [Math]::Min(64, $head.Length)) }
    $cue = [regex]::IsMatch($start, '^(?:\xEF\xBB\xBF)?[ \t\r\n\f\v]*(?:FILE|REM|TRACK|CATALOG|PERFORMER|TITLE)[ \t\r\n\f\v]',
        [Text.RegularExpressions.RegexOptions]::IgnoreCase -bor [Text.RegularExpressions.RegexOptions]::CultureInvariant)
    if ((Test-Bytes $head $sync) -or $cue) { return @{ Code = 'TTM-ISO-04'; Values = @{} } }
    $pvd = [byte[]](0x01,0x43,0x44,0x30,0x30,0x31)
    if ($size -lt 0x8800 -or $head.Length -lt 0x8058 -or -not (Test-Bytes $head $pvd 0x8000)) { return @{ Code = 'TTM-ISO-05'; Values = @{ size = $size } } }
    $expected = [long][BitConverter]::ToUInt32($head, 0x8050) * 2048
    if ($size -lt $expected) { return @{ Code = 'TTM-ISO-06'; Values = @{ size = $size; expected = $expected } } }
    return $null
}
function Get-BiosProblem([string]$Path) {
    $size = (Get-Item -LiteralPath $Path -Force).Length
    $head = Read-Head $Path 16
    $archive = Get-ArchiveName $head
    if ($archive) { return @{ Code = 'TTM-BIOS-04'; Values = @{ format = $archive } } }
    if ((Test-Bytes $head ([Text.Encoding]::ASCII.GetBytes('SCEUF'))) -or $size -gt 8388608) { return @{ Code = 'TTM-BIOS-03'; Values = @{ size = (Format-Size $size) } } }
    # install_player.bios_problem: a BIOS names ROMVER in its ROMDIR table; the .ROM1/.ROM2 parts of a dump (512 KiB,
    # ROMDIR without ROMVER) and the other companion files are TTM-BIOS-06, not a PS1 BIOS.
    $romdir = $false; $romver = $false
    if (@(524288, 2097152, 4194304, 8388608) -contains $size) {
        $text = [Text.Encoding]::GetEncoding(28591).GetString([IO.File]::ReadAllBytes($Path))
        $romdir = $text.IndexOf('ROMDIR', [StringComparison]::Ordinal) -ge 0
        $romver = $text.IndexOf('ROMVER', [StringComparison]::Ordinal) -ge 0
    }
    if ($size -eq 524288) {
        if ($romdir) { return @{ Code = 'TTM-BIOS-06'; Values = @{ size = (Format-Size $size) } } }
        return @{ Code = 'TTM-BIOS-02'; Values = @{} }
    }
    if ($romdir -and $romver) { return $null }
    if ($romdir -or (@('.rom1', '.rom2', '.erom', '.nvm', '.mec') -contains [IO.Path]::GetExtension($Path).ToLowerInvariant())) {
        return @{ Code = 'TTM-BIOS-06'; Values = @{ size = (Format-Size $size) } }
    }
    return @{ Code = 'TTM-BIOS-01'; Values = @{ size = (Format-Size $size) } }
}
# Without -Bios, setup copies the BIOS the selected PCSX2 is set up with (install_player.configured_bios; a test
# compares both). PCSX2 keeps its settings in <data folder>\inis\PCSX2.ini: when portable.ini or portable.txt is beside
# pcsx2-qt.exe, the program folder joined with the text of portable.txt (usually empty), else Documents\PCSX2.
# Settings that name no BIOS, or a missing one, make PCSX2 start with the first PS2 BIOS its BIOS folder lists; on an
# NTFS drive that is the first by name, so setup takes it too (Get-FirstBios), elsewhere it asks.
function Get-DocumentsFolder {
    # install_player.documents_folder: the Documents Known Folder, so a Documents folder moved to OneDrive or another
    # drive is followed. TAGTEAM_SETUP_DOCUMENTS overrides it (the installer's own tests).
    if ($env:TAGTEAM_SETUP_DOCUMENTS) { return [string]$env:TAGTEAM_SETUP_DOCUMENTS }
    $documents = [Environment]::GetFolderPath('MyDocuments')
    if ($documents) { return $documents }
    $profileFolder = $env:USERPROFILE
    if (-not $profileFolder) { $profileFolder = [Environment]::GetFolderPath('UserProfile') }
    return [IO.Path]::Combine($profileFolder, 'Documents')
}
function Get-FullPath([string]$Path) {
    # os.path.abspath: the full path without a trailing separator (a drive root keeps its own).
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.Length -gt 3) { $full = $full.TrimEnd([char[]]@('\', '/')) }
    return $full
}
function Get-PortableDataFolder([string]$Program) {
    # install_player.portable_data_folder: the program folder joined with the text of portable.txt, blanks trimmed, the
    # way PCSX2's Path::Combine joins it; the program folder when that file is missing, empty or unreadable; $null when
    # the text cannot be part of a folder path (a drive letter, a character Windows refuses in names, too long).
    $buffer = New-Object byte[] 32768; $count = 0
    try {
        $stream = [IO.File]::OpenRead([IO.Path]::Combine($Program, 'portable.txt'))
        try {
            while ($count -lt $buffer.Length) { $read = $stream.Read($buffer, $count, $buffer.Length - $count); if ($read -le 0) { break }; $count += $read }
        } finally { $stream.Dispose() }
    } catch { return $Program }
    if ($count -gt 32767) { return $null }
    $text = (New-Object Text.UTF8Encoding($false)).GetString($buffer, 0, $count).Trim([char[]]@(' ', "`t", "`n", [char]11, [char]12, "`r"))
    if (-not $text) { return $Program }
    foreach ($char in $text.ToCharArray()) { if ([int]$char -lt 32 -or ':<>"|?*'.IndexOf($char) -ge 0) { return $null } }
    return (Get-FullPath ($Program.TrimEnd([char[]]@('\', '/')) + '\' + $text))
}
function Get-Pcsx2DataFolders([string]$Pcsx2) {
    # install_player.pcsx2_data_folders (Windows): rows @{ Folder; Own }, each folder once, the selected PCSX2's own
    # first (when portable, Get-PortableDataFolder, none when portable.txt names no usable folder; else
    # Documents\PCSX2), then %USERPROFILE%\Documents\PCSX2 and the program folder.
    $program = [IO.Path]::GetDirectoryName((Get-FullPath $Pcsx2))
    $portable = $false
    foreach ($marker in @('portable.ini', 'portable.txt')) { if (Test-Path -LiteralPath ([IO.Path]::Combine($program, $marker)) -PathType Leaf) { $portable = $true } }
    $user = @([IO.Path]::Combine((Get-DocumentsFolder), 'PCSX2'))
    if ($env:USERPROFILE) { $user += [IO.Path]::Combine([IO.Path]::Combine($env:USERPROFILE, 'Documents'), 'PCSX2') }
    $rows = @()
    if ($portable) {
        $own = Get-PortableDataFolder $program
        if ($null -ne $own) { $rows += @{ Folder = $own; Own = $true } }
        foreach ($folder in $user) { $rows += @{ Folder = $folder; Own = $false } }
    } else {
        $rows += @{ Folder = $user[0]; Own = $true }
        for ($index = 1; $index -lt $user.Count; $index++) { $rows += @{ Folder = $user[$index]; Own = $false } }
    }
    $rows += @{ Folder = $program; Own = $false }
    $seen = @{}
    foreach ($row in $rows) {
        $folder = Get-FullPath ([string]$row.Folder)
        $key = $folder.ToLowerInvariant()
        if (-not $seen.ContainsKey($key)) { $seen[$key] = $true; Write-Output @{ Folder = $folder; Own = [bool]$row.Own } }
    }
}
function Read-Pcsx2Settings([string]$Path) {
    # install_player.read_pcsx2_settings: @{ folders; filenames } with lower-case names, the first value of a repeated
    # key; ; and # lines are comments. $null when unreadable or too large to be PCSX2's settings.
    try {
        if ((Get-Item -LiteralPath $Path -Force).Length -gt 4194304) { return $null }
        $text = [IO.File]::ReadAllText($Path, (New-Object Text.UTF8Encoding($false)))
    } catch { return $null }
    $found = @{ folders = @{}; filenames = @{} }
    $section = ''
    $blank = [char[]]@(' ', "`t")
    foreach ($raw in [regex]::Split($text, '\r\n|\n|\r')) {
        $line = $raw.Trim($blank)
        if (-not $line -or $line[0] -eq ';' -or $line[0] -eq '#') { continue }
        if ($line[0] -eq '[') {
            $end = $line.IndexOf(']')
            if ($end -gt 0) { $section = $line.Substring(1, $end - 1).Trim($blank).ToLowerInvariant() } else { $section = '' }
            continue
        }
        $equals = $line.IndexOf('=')
        if ($section -and $found.ContainsKey($section) -and $equals -ge 0) {
            $key = $line.Substring(0, $equals).Trim($blank).ToLowerInvariant()
            if (-not $found[$section].ContainsKey($key)) { $found[$section][$key] = $line.Substring($equals + 1).Trim($blank) }
        }
    }
    return $found
}
function Test-Pcsx2Absolute([string]$Value) {
    # PCSX2's Path::IsAbsolute on Windows: a drive with a separator, or \\; anything else is relative to the data folder.
    return [regex]::IsMatch($Value, '^(?:[A-Za-z]:[\\/]|\\\\)')
}
function Get-Pcsx2Path([string]$Base, [string]$Value) {
    # install_player.pcsx2_path: as it is when absolute, else Base, one separator and Value (PCSX2's Path::Combine).
    if (Test-Pcsx2Absolute $Value) { return (Get-FullPath $Value) }
    return (Get-FullPath ($Base.TrimEnd([char[]]@('\', '/')) + '\' + $Value))
}
function Get-BiosChoices([string]$Folder) {
    # install_player.bios_choices: the usable PS2 BIOS files directly in a folder, by name (ordinal, ignoring case); a
    # copy with the same bytes as an earlier file is the same BIOS and is left out.
    try { $names = [string[]]@([IO.Directory]::GetFiles($Folder) | ForEach-Object { [IO.Path]::GetFileName($_) }) } catch { return }
    [Array]::Sort($names, [StringComparer]::OrdinalIgnoreCase)
    $read = 0; $seen = @{}
    foreach ($name in $names) {
        $path = [IO.Path]::Combine($Folder, $name)
        try {
            if (@(2097152, 4194304, 8388608) -notcontains (New-Object IO.FileInfo($path)).Length) { continue }
            $read++
            if ($read -gt 64) { break }
            if (Get-BiosProblem $path) { continue }
            $digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash
            if ($seen.ContainsKey($digest)) { continue }
            $seen[$digest] = $true; Write-Output $path
        } catch {}
    }
}
function Test-ListedInNameOrder([string]$Folder) {
    # install_player.listed_in_name_order: Windows lists a folder of a local NTFS drive by name, ignoring case; FAT32,
    # exFAT and network drives list files in another order. $false for a network path and through a junction or
    # symbolic link. TAGTEAM_SETUP_FILE_SYSTEM stands for the drive's file system (the installer's own tests).
    try {
        $full = Get-FullPath $Folder
        $root = [IO.Path]::GetPathRoot($full)
        if (-not $root -or $root.StartsWith('\\') -or $root.StartsWith('//')) { return $false }
        for ($item = New-Object IO.DirectoryInfo($full); $null -ne $item; $item = $item.Parent) {
            if ($item.Exists -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return $false }
        }
        if ($env:TAGTEAM_SETUP_FILE_SYSTEM) { return ($env:TAGTEAM_SETUP_FILE_SYSTEM -ceq 'NTFS') }
        $drive = New-Object IO.DriveInfo($root)
        if ($drive.DriveType -eq [IO.DriveType]::Network) { return $false }
        return ($drive.DriveFormat -ceq 'NTFS')
    } catch { return $false }
}
function Get-FirstBios([string]$Folder) {
    # install_player.pcsx2_first_bios: the BIOS PCSX2 starts with when its settings name none, or a missing one: the
    # first file of its BIOS folder by name (ordinal, ignoring case) that is 4 to 8 MiB, not hidden and a PS2 BIOS.
    try { $names = [string[]]@([IO.Directory]::GetFiles($Folder) | ForEach-Object { [IO.Path]::GetFileName($_) }) } catch { return '' }
    [Array]::Sort($names, [StringComparer]::OrdinalIgnoreCase)
    $read = 0
    foreach ($name in $names) {
        $path = [IO.Path]::Combine($Folder, $name)
        try {
            $info = New-Object IO.FileInfo($path)
            if (@(2097152, 4194304, 8388608) -notcontains $info.Length) { continue }
            $read++
            if ($read -gt 64) { break }
            if ($info.Attributes -band [IO.FileAttributes]::Hidden) { continue }
            if ($info.Length -ge 4194304 -and -not (Get-BiosProblem $path)) { return $path }
        } catch {}
    }
    return ''
}
function New-BiosResult($Checked, [hashtable]$Values) {
    $result = @{ Bios = ''; Own = $false; Settings = ''; How = ''; Folder = ''; Choices = @(); Rejected = ''; RejectedCode = ''; RejectedValues = @{}; Checked = @($Checked); Error = '' }
    foreach ($key in @($Values.Keys)) { $result[$key] = $Values[$key] }
    return $result
}
function Find-ConfiguredBios([string]$Pcsx2) {
    # install_player.configured_bios: Filenames/BIOS inside Folders/Bios (default 'bios', both relative to the data folder
    # unless absolute) when it passes Get-BiosProblem, else the only PS2 BIOS in that folder, else, when the settings
    # name no BIOS or a missing one and Test-ListedInNameOrder, the one PCSX2 starts with (Get-FirstBios). The selected
    # PCSX2's own settings with several BIOS files and none usable selected otherwise end the search: setup must ask.
    # Own: the result comes from the selected PCSX2's own settings, not another PCSX2's.
    $checked = @(); $fallback = $null
    foreach ($row in @(Get-Pcsx2DataFolders $Pcsx2)) {
        $data = [string]$row.Folder; $own = [bool]$row.Own
        $ini = [IO.Path]::Combine([IO.Path]::Combine($data, 'inis'), 'PCSX2.ini')
        $checked += $ini
        if (-not (Test-Path -LiteralPath $ini -PathType Leaf)) { continue }
        $settings = Read-Pcsx2Settings $ini
        if ($null -eq $settings) { continue }
        try {
            $value = 'bios'
            if ($settings.folders.ContainsKey('bios')) { $value = [string]$settings.folders['bios'] }
            $folder = Get-Pcsx2Path $data $value
            $name = ''
            if ($settings.filenames.ContainsKey('bios')) { $name = [string]$settings.filenames['bios'] }
            $rejected = ''; $code = ''; $values = @{}
            if ($name) {
                $path = Get-Pcsx2Path $folder $name
                if (Test-Path -LiteralPath $path -PathType Leaf) {
                    $problem = Get-BiosProblem $path
                    if (-not $problem) { return (New-BiosResult $checked @{ Bios = $path; Own = $own; Settings = $ini; How = 'configured'; Folder = $folder }) }
                    $rejected = $path; $code = [string]$problem.Code; $values = $problem.Values
                } else { $rejected = $path }
            }
            $choices = @(Get-BiosChoices $folder)
            if ($choices.Count -eq 1) {
                return (New-BiosResult $checked @{ Bios = [string]$choices[0]; Own = $own; Settings = $ini; How = 'only'; Folder = $folder;
                    Rejected = $rejected; RejectedCode = $code; RejectedValues = $values })
            }
            # PCSX2 replaces a BIOS setting that is empty or names a missing file, not a file that is not a PS2 BIOS.
            if ($choices.Count -gt 1 -and -not $code -and (Test-ListedInNameOrder $folder)) {
                $first = Get-FirstBios $folder
                if ($first) { return (New-BiosResult $checked @{ Bios = $first; Own = $own; Settings = $ini; How = 'first'; Folder = $folder; Rejected = $rejected }) }
            }
            $shown = ''
            if (Test-Path -LiteralPath $folder -PathType Container) { $shown = $folder }
            $found = New-BiosResult $checked @{ Own = $own; Settings = $ini; Folder = $shown; Choices = $choices; Rejected = $rejected; RejectedCode = $code; RejectedValues = $values }
        } catch { continue }
        if ($own -and $choices.Count -gt 1) { return $found }
        if ($null -eq $fallback -and ($choices.Count -gt 0 -or $rejected)) { $fallback = $found }
    }
    if ($fallback) { $fallback.Checked = @($checked); return $fallback }
    return (New-BiosResult $checked @{})
}
function Get-BiosOrigin($Found) {
    # install_player.bios_origin: where a BIOS setup found by itself comes from (saying so when it is another PCSX2's
    # settings; the BIOS folder for the one PCSX2 starts with); '' for a selected one.
    if ($null -eq $Found -or -not $Found.Bios) { return '' }
    if ($Found.How -eq 'first') {
        if ($Found.Own) { $text = L 'the BIOS your PCSX2 starts with, from' } else { $text = L 'the BIOS another PCSX2 on this PC starts with, from' }
        return (' (' + $text + ' ' + $Found.Folder + ')')
    }
    if ($Found.How -eq 'configured') {
        if ($Found.Own) { $text = L 'the BIOS your PCSX2 uses, from' } else { $text = L 'a PS2 BIOS set up in another PCSX2 on this PC, from' }
    } elseif ($Found.Own) { $text = L 'the only PS2 BIOS in the BIOS folder of your PCSX2, from' }
    else { $text = L 'the only PS2 BIOS in the BIOS folder of another PCSX2 on this PC, from' }
    return (' (' + $text + ' ' + $Found.Settings + ')')
}
function Get-BiosNotes($Found) {
    # install_player.bios_notes: a configured BIOS setup cannot use (it then took the only PS2 BIOS of that folder or the
    # one PCSX2 starts with, or asks) and, when it found no BIOS, why it asks. None when there is nothing to say.
    $lines = @()
    if ($Found.Rejected -and $Found.RejectedCode) {
        if ($Found.Own) { $text = L 'The BIOS set up in your PCSX2 cannot be used:' } else { $text = L 'The BIOS set up in another PCSX2 on this PC cannot be used:' }
        $lines += ($text + ' ' + $Found.Rejected)
        $lines += (Format-SetupLine $Found.RejectedCode $Language $Found.RejectedValues)
    } elseif ($Found.Rejected) {
        if ($Found.Own) { $text = L 'The BIOS set up in your PCSX2 is missing:' } else { $text = L 'The BIOS set up in another PCSX2 on this PC is missing:' }
        $lines += ($text + ' ' + $Found.Rejected)
    }
    if ($Found.Bios) { return $lines }
    if (@($Found.Choices).Count -gt 1) {
        if ($Found.Own) { $lines += (L 'Your PCSX2 has several PS2 BIOS files and none is selected in its settings: choose the one to use.') }
        else { $lines += (L 'Another PCSX2 on this PC has several PS2 BIOS files and none is selected in its settings: choose the one to use.') }
    }
    elseif ($Found.Rejected) { $lines += (L 'Choose your PS2 BIOS file.') }
    else { $lines += (L 'Your PCSX2 has no PS2 BIOS set up yet: choose your BIOS file.') }
    return $lines
}
function Get-ConfiguredBiosFailure($Found) {
    # install_player.configured_bios_failure: @{ Code; Values; File; Detail } of an unattended setup (no dialogs) whose
    # PCSX2 settings give no BIOS it can use. The details say when the settings are another PCSX2's.
    $settings = ''
    if ($Found.Settings) {
        if ($Found.Own) { $settings = 'PCSX2 settings: ' + $Found.Settings } else { $settings = 'settings of another PCSX2 on this PC: ' + $Found.Settings }
    }
    $rejected = ''
    if ($Found.Rejected) {
        $state = 'missing'
        if ($Found.RejectedCode) { $state = 'not usable (' + $Found.RejectedCode + ')' }
        $rejected = 'selected BIOS ' + $state + ': ' + $Found.Rejected
    }
    $detail = (@($rejected, $settings) | Where-Object { $_ }) -join '; '
    if (@($Found.Choices).Count -gt 1) { return @{ Code = 'TTM-BIOS-08'; Values = @{ count = @($Found.Choices).Count }; File = $Found.Folder; Detail = $detail } }
    if ($Found.Rejected -and $Found.RejectedCode) { return @{ Code = $Found.RejectedCode; Values = $Found.RejectedValues; File = $Found.Rejected; Detail = $settings } }
    if ($Found.Rejected) { return @{ Code = 'TTM-BIOS-07'; Values = @{}; File = $Found.Rejected; Detail = $detail } }
    return @{ Code = 'TTM-BIOS-07'; Values = @{}; File = @($Found.Checked); Detail = [string]$Found.Error }
}
# release.json is the installer's policy: any PCSX2 2.x from pcsx2_minimum on is accepted (nightlies
# included); pcsx2_supported lists the tested releases. game\tools\pcsx2_versions.json must agree.
function Get-Pcsx2Support([string]$FileVersion, [string]$Minimum, [string[]]$Tested) {
    $found = [regex]::Match([string]$FileVersion, '(?i)^\s*(?:PCSX2\s+)?v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})(?!\d)')
    if (-not $found.Success) { return [pscustomobject]@{ Version = ''; Accepted = $false; Tested = $false } }
    $current = New-Object -TypeName System.Version -ArgumentList ([int]$found.Groups[1].Value), ([int]$found.Groups[2].Value), ([int]$found.Groups[3].Value)
    $lowest = [System.Version]$Minimum
    $text = '{0}.{1}.{2}' -f $current.Major, $current.Minor, $current.Build
    return [pscustomobject]@{ Version = $text; Accepted = ($current.Major -eq $lowest.Major -and $current -ge $lowest); Tested = (@($Tested) -contains $text) }
}
function Get-Pcsx2Problem([string]$Path, $Release) {
    # install_player.pcsx2_version and runtime_copy decide the same, later; this runs before anything is changed.
    $head = Read-Head $Path 4096
    $machines = @{ 0x014c = '32-bit x86'; 0xaa64 = 'ARM64'; 0x01c4 = 'ARM' }
    if (-not (Test-Bytes $head ([byte[]](0x4D,0x5A)))) { return @{ Code = 'TTM-PCSX2-01'; Values = @{} } }
    $offset = 0
    if ($head.Length -ge 0x40) { $offset = [BitConverter]::ToInt32($head, 0x3C) }
    if ($offset -le 0 -or ($offset + 6) -gt $head.Length) {
        $all = Read-Head $Path ([Math]::Max(4096, $offset + 6))
        if ($offset -le 0 -or ($offset + 6) -gt $all.Length) { return @{ Code = 'TTM-PCSX2-01'; Values = @{} } }
        $head = $all
    }
    if (-not (Test-Bytes $head ([byte[]](0x50,0x45,0x00,0x00)) $offset)) { return @{ Code = 'TTM-PCSX2-01'; Values = @{} } }
    $machine = [int][BitConverter]::ToUInt16($head, $offset + 4)
    if ($machine -ne 0x8664) {
        $name = 'machine 0x{0:x4}' -f $machine
        if ($machines.ContainsKey($machine)) { $name = $machines[$machine] }
        return @{ Code = 'TTM-PCSX2-04'; Values = @{ machine = $name } }
    }
    $check = Get-Pcsx2VersionProblem ([string][Diagnostics.FileVersionInfo]::GetVersionInfo($Path).FileVersion) $Release
    if ($check.Code) { return $check }
    $folder = Split-Path -Parent $Path
    $missing = ''
    if (-not ((Test-Path -LiteralPath (Join-Path $folder 'QtPlugins\platforms\qwindows.dll') -PathType Leaf) -or
              (Test-Path -LiteralPath (Join-Path $folder 'platforms\qwindows.dll') -PathType Leaf))) { $missing = 'QtPlugins\platforms\qwindows.dll' }
    elseif (-not (Test-Path -LiteralPath (Join-Path $folder 'resources') -PathType Container)) { $missing = 'resources' }
    if ($missing) { return @{ Code = 'TTM-PCSX2-05'; Values = @{ missing = $missing } } }
    return $check
}
function Get-Pcsx2VersionProblem([string]$FileVersion, $Release) {
    # install_player.pcsx2_refusal: unreadable (TTM-PCSX2-06), too old (-02) or a later major version such as 3.x (-03).
    $support = Get-Pcsx2Support $FileVersion ([string]$Release.pcsx2_minimum) @($Release.pcsx2_supported)
    if (-not $support.Version) { return @{ Code = 'TTM-PCSX2-06'; Values = @{}; Detail = ('version ' + $FileVersion) } }
    if (-not $support.Accepted) {
        $code = 'TTM-PCSX2-02'
        if ([int]($support.Version.Split('.')[0]) -gt ([System.Version][string]$Release.pcsx2_minimum).Major) { $code = 'TTM-PCSX2-03' }
        return @{ Code = $code; Values = @{ version = $support.Version; minimum = [string]$Release.pcsx2_minimum; platform = 'Windows x64' } }
    }
    return @{ Code = ''; Values = @{}; Version = $support.Version; Tested = $support.Tested }
}
function Get-FolderState([string]$Path) {
    # install_player.folder_state: 'missing', 'failed' (an unfinished setup attempt), 'complete' or 'other'.
    if (-not (Test-Path -LiteralPath $Path)) { return 'missing' }
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer -or ($item.PSObject.Properties['LinkType'] -and $item.LinkType)) { return 'other' }
    $play = (Test-Path -LiteralPath (Join-Path $Path 'Play.cmd')) -or (Test-Path -LiteralPath (Join-Path $Path 'Play.sh'))
    if ((Test-Path -LiteralPath (Join-Path $Path 'install-bootstrap.json') -PathType Leaf) -and -not $play) {
        $ready = $false
        try {
            $status = Get-Content -LiteralPath (Join-Path $Path 'install-status.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($status.PSObject.Properties['ready'] -and $status.ready -eq $true) { $ready = $true }
        } catch {}
        if ($ready) { return 'other' }
        return 'failed'
    }
    if ($play -and (Test-Path -LiteralPath (Join-Path $Path 'installed-files.json') -PathType Leaf)) { return 'complete' }
    return 'other'
}
function Get-DestinationPlan([string]$Path, [bool]$Explicit, [string]$Version) {
    # install_player.plan_destination: never write into or delete an existing folder.
    $state = Get-FolderState $Path
    if ($state -eq 'missing') { return @{ Destination = $Path; Aside = ''; Beside = '' } }
    if ($state -eq 'failed') { return @{ Destination = $Path; Aside = $Path; Beside = '' } }
    if ($Explicit) { Stop-Setup 'TTM-DEST-06' @{} $Path }
    $beside = ''
    if ($state -eq 'complete') { $beside = $Path }
    for ($number = 1; $number -lt 100; $number++) {
        $candidate = $Path + ' ' + $Version
        if ($number -gt 1) { $candidate += ' (' + $number + ')' }
        $found = Get-FolderState $candidate
        if ($found -eq 'missing') { return @{ Destination = $candidate; Aside = ''; Beside = $beside } }
        if ($found -eq 'failed') { return @{ Destination = $candidate; Aside = $candidate; Beside = $beside } }
    }
    Stop-Setup 'TTM-DEST-06' @{} $Path
}
function Get-ChosenInstallation([string]$Folder) {
    # The folder chosen in the dialog is the parent of the new installation, unless it is itself a complete
    # installation (TTM-PLAY-51 says to choose it for a repair): then the plan treats it as the existing one.
    if ((Get-FolderState $Folder) -eq 'complete') { return $Folder }
    return (Join-Path $Folder 'Tag Team Mod')
}
function Get-GameFamily([string]$Installation) {
    # install_player.game_family: 'bt3' or 'bt4' from game\player-install.json, else installed-files.json; '' unknown.
    foreach ($name in @('game\player-install.json', 'installed-files.json')) {
        try {
            $data = Get-Content -LiteralPath (Join-Path $Installation $name) -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($data.PSObject.Properties['adapter'] -and $data.adapter) { return ([string]$data.adapter).Split('-')[0] }
        } catch {}
    }
    return ''
}
function Import-PreviousInstallation([string]$Private, [string]$Old, [string]$New, [string]$Log) {
    # Optional, after a complete installation: the memory cards, and the mod settings of the same game only
    # (install_player.import_previous enforces that too). A failure is one warning line, never a setup failure.
    $family = Get-GameFamily $Old
    $question = 'Copy your memory cards and mod settings from the existing installation?'
    if (-not $family -or $family -ne (Get-GameFamily $New)) { $question = 'Copy your memory cards from the existing installation? (Its mod settings are for the other game and are not copied.)' }
    if (-not (Ask-YesNo ((L $question) + "`n`n" + $Old))) { return $false }
    $result = Invoke-Probe $Private @((Join-Path $script:setupFolder 'install_player.py'), '--destination', $New, '--import-from', $Old,
        '--language', $Language, '--log', $Log, '--quiet-failure')
    if ($result.Output) { Write-Host $result.Output }
    if ($result.Code -ne 0) { Write-Check 'warn' (Format-SetupLine 'TTM-DEST-27' $Language @{}) 'Yellow'; return $false }
    return $true
}
function Complete-OptionalSteps([string]$Private, [string]$Installation, [string]$Version, [string]$Log) {
    # After "Ready": copying from the installation beside this one, and Desktop shortcuts. The installation is complete
    # whatever happens here, so an error is a warning line and the log, never a setup failure.
    if ($script:beside) {
        try { [void](Import-PreviousInstallation $Private $script:beside $Installation $Log) }
        catch {
            try { [IO.File]::AppendAllText($Log, ($_ | Out-String), (New-Object Text.UTF8Encoding($false))) } catch {}
            Write-Check 'warn' (Format-SetupLine 'TTM-DEST-27' $Language @{}) 'Yellow'
        }
    }
    try {
        if (Ask-YesNo (L 'Create desktop shortcuts for Play and Mod settings? (Use shortcuts; a copied .cmd file cannot find the game.)')) {
            foreach ($path in @(New-PlayShortcuts ([Environment]::GetFolderPath('Desktop')) $Installation $Version)) {
                Write-Host ((L 'Shortcut:') + ' ' + $path)
            }
        }
    } catch {
        try { [IO.File]::AppendAllText($Log, ($_ | Out-String), (New-Object Text.UTF8Encoding($false))) } catch {}
        Write-Check 'warn' (Format-SetupLine 'TTM-DEST-28' $Language @{}) 'Yellow'
    }
}
function Get-AsideName([string]$Path) {
    $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss', [Globalization.CultureInfo]::InvariantCulture)
    $candidate = $Path + ' (failed ' + $stamp + ')'
    $number = 2
    while (Test-Path -LiteralPath $candidate) { $candidate = $Path + ' (failed ' + $stamp + '-' + $number + ')'; $number++ }
    return $candidate
}
function Get-ExistingAncestor([string]$Path) {
    $current = $Path
    while ($current -and -not (Test-Path -LiteralPath $current -PathType Container)) { $current = Split-Path -Parent $current }
    return $current
}
function Test-Writable([string]$Folder) {
    # A probe file that deletes itself on close: nothing stays behind.
    try {
        $probe = Join-Path $Folder ('.tagteam-write-test-' + [guid]::NewGuid().ToString('N'))
        $stream = [IO.File]::Create($probe, 1, [IO.FileOptions]::DeleteOnClose)
        $stream.Dispose()
        return $true
    } catch { return $false }
}
function Get-DestinationFindings([string]$Destination) {
    # (failures, warnings) about the installation folder, before it exists.
    $failures = @(); $warnings = @()
    if ($Destination.IndexOf('[') -ge 0 -or $Destination.IndexOf(']') -ge 0) { $failures += ,@{ Code = 'TTM-DEST-04'; Values = @{}; File = $Destination } }
    if ($Destination.Length -gt 140) { $failures += ,@{ Code = 'TTM-DEST-02'; Values = @{ length = $Destination.Length }; File = $Destination } }
    $existing = Get-ExistingAncestor (Split-Path -Parent $Destination)
    if (-not $existing) { $failures += ,@{ Code = 'TTM-DEST-03'; Values = @{}; File = (Split-Path -Parent $Destination) }; return ,@($failures, $warnings) }
    $cursor = $existing
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force
        if ($item.PSObject.Properties['LinkType'] -and ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink')) {
            $failures += ,@{ Code = 'TTM-DEST-07'; Values = @{}; File = $cursor }; break
        }
        $cursor = Split-Path -Parent $cursor
    }
    if (-not (Test-Writable $existing)) { $failures += ,@{ Code = 'TTM-DEST-01'; Values = @{}; File = $existing } }
    $warnings = @(Get-FolderWarnings $Destination (Test-Administrator))
    return ,@($failures, $warnings)
}
function Test-Administrator {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Get-FolderWarnings([string]$Destination, [bool]$Administrator) {
    # Folders that work but cause trouble later: OneDrive, network drives, system folders, running as administrator.
    $warnings = @()
    $full = [IO.Path]::GetFullPath($Destination).TrimEnd('\') + '\'
    $cloud = @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial) | Where-Object { $_ }
    foreach ($root in $cloud) { if ($full.StartsWith(([IO.Path]::GetFullPath($root).TrimEnd('\') + '\'), [StringComparison]::OrdinalIgnoreCase)) { $warnings += 'TTM-DEST-21'; break } }
    $network = $full.StartsWith('\\')
    if (-not $network) { try { $network = ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($full))).DriveType -eq [IO.DriveType]::Network } catch {} }
    if ($network) { $warnings += 'TTM-DEST-22' }
    foreach ($system in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432, $env:WINDIR) | Where-Object { $_ }) {
        if ($full.StartsWith(([IO.Path]::GetFullPath($system).TrimEnd('\') + '\'), [StringComparison]::OrdinalIgnoreCase)) { $warnings += 'TTM-DEST-23'; break }
    }
    if ($Administrator) { $warnings += 'TTM-DEST-24' }
    # Callers wrap the result in @(): no warning is an empty list, never one empty entry.
    return $warnings
}
function Get-FreeSpace([string]$Path) {
    try { return ([IO.DriveInfo]::new([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path)))).AvailableFreeSpace } catch { return -1 }
}
function Invoke-Probe([string]$Program, [string[]]$Arguments) {
    # Native probes under a local 'Continue': a line on stderr must not become a terminating error (exit code decides).
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $global:LASTEXITCODE = 0
        $output = @(& $Program @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } catch { $output = @("$_"); $code = -1 }
    finally { $ErrorActionPreference = $previous }
    return [pscustomobject]@{ Code = $code; Output = ($output -join "`n") }
}
function Get-PythonProblem([string]$Path) {
    # '' when this Python 3.11 x64 has Tk, venv and ensurepip; otherwise the part that is missing ('TK' for Tk).
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return 'not found' }
    $probe = "import sys,struct`nif sys.version_info[:2]!=(3,11): print('it is Python %d.%d, not 3.11' % sys.version_info[:2]); sys.exit(1)`nif struct.calcsize('P')!=8: print('it is a 32-bit Python'); sys.exit(1)`ntry:`n import tkinter`nexcept Exception: print('TK'); sys.exit(1)`ntry:`n import venv, ensurepip; ensurepip.version()`nexcept Exception: print('its venv/ensurepip part is missing'); sys.exit(1)"
    $result = Invoke-Probe $Path @('-I', '-c', $probe)
    if ($result.Code -eq 0) { return '' }
    $lines = @($result.Output -split "`n" | Where-Object { $_.Trim() })
    if ($lines.Count -gt 0) { return $lines[-1].Trim() }
    return ('it does not start (exit ' + $result.Code + ')')
}
function Get-RegisteredPythons {
    # python.org installations: the default per-user and machine folders, and PEP 514 registrations (also custom
    # folders and installs without "Add to PATH"). Their installer can add a missing part (Settings > Apps > Modify).
    $list = New-Object System.Collections.Generic.List[string]
    if ($env:LOCALAPPDATA) { $list.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe')) }
    foreach ($root in @($env:ProgramFiles, $env:ProgramW6432) | Where-Object { $_ }) { $list.Add((Join-Path $root 'Python311\python.exe')) }
    foreach ($hive in @('HKCU:\Software\Python\PythonCore\3.11\InstallPath', 'HKLM:\Software\Python\PythonCore\3.11\InstallPath')) {
        try {
            $key = Get-ItemProperty -LiteralPath $hive -ErrorAction Stop
            if ($key.PSObject.Properties['ExecutablePath'] -and $key.ExecutablePath) { $list.Add([string]$key.ExecutablePath) }
            elseif ($key.PSObject.Properties['(default)'] -and $key.'(default)') { $list.Add((Join-Path ([string]$key.'(default)') 'python.exe')) }
        } catch {}
    }
    return @($list | Select-Object -Unique)
}
function Test-RegisteredPython([string]$Path) {
    # A Python found only on PATH (an embeddable ZIP, a program's bundled interpreter) has no installer to modify.
    if (-not $Path) { return $false }
    try { $full = [IO.Path]::GetFullPath($Path) } catch { return $false }
    foreach ($known in @(Get-RegisteredPythons)) {
        try { if ([string]::Equals([IO.Path]::GetFullPath($known), $full, [StringComparison]::OrdinalIgnoreCase)) { return $true } } catch {}
    }
    return $false
}
function Get-PythonCandidates {
    $list = New-Object System.Collections.Generic.List[string]
    foreach ($path in @(Get-RegisteredPythons)) { $list.Add($path) }
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        $found = Invoke-Probe 'py.exe' @('-3.11-64', '-c', 'import sys;print(sys.executable)')
        if ($found.Code -eq 0) { $line = @($found.Output -split "`n" | Where-Object { $_.Trim() }); if ($line.Count) { $list.Add($line[-1].Trim()) } }
    }
    Get-Command python.exe -All -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*\WindowsApps\*' } | ForEach-Object { $list.Add($_.Source) }
    return @($list | Select-Object -Unique)
}
function Find-PlayerPython {
    # (python, problem) where python is the first usable candidate; problem names the closest miss.
    $closest = ''
    foreach ($candidate in (Get-PythonCandidates)) {
        $problem = Get-PythonProblem $candidate
        if (-not $problem) { return @($candidate, '') }
        if ($problem -eq 'TK' -or $problem -like '*venv*' -or ($problem -like '*32-bit*' -and -not $closest)) { $closest = $problem + '|' + $candidate }
    }
    return @('', $closest)
}
function Get-WingetMeaning([int]$Code) {
    # The WinGet results players actually meet (hex literals are Int32 in PowerShell 5.1, like $LASTEXITCODE).
    $known = @{
        0x8A15002B = @('no newer version is available: the package is already installed', 'no hay una version mas nueva: el paquete ya esta instalado');
        0x8A150061 = @('the package is already installed', 'el paquete ya esta instalado');
        0x80072EE7 = @('no internet connection (the download server could not be found)', 'no hay conexion a internet (no se encontro el servidor de descarga)');
        0x80072EFD = @('no internet connection (the download server did not answer)', 'no hay conexion a internet (el servidor de descarga no respondio)');
        0x80072EE2 = @('the download timed out', 'la descarga ha tardado demasiado');
        0x8A15000F = @('a WinGet source could not be opened (try: winget source reset --force)', 'no se pudo abrir un origen de WinGet (prueba: winget source reset --force)');
        0x8A15005E = @('a WinGet source could not be opened (try: winget source reset --force)', 'no se pudo abrir un origen de WinGet (prueba: winget source reset --force)');
        0x8A150056 = @('the installation was cancelled, for example by declining the Windows permission prompt', 'la instalacion se cancelo, por ejemplo al rechazar el aviso de permisos de Windows');
        1602 = @('the installation was cancelled, for example by declining the Windows permission prompt', 'la instalacion se cancelo, por ejemplo al rechazar el aviso de permisos de Windows');
        1618 = @('another installation is already running; wait for it to finish', 'ya hay otra instalacion en curso; espera a que termine')
    }
    if ($known.ContainsKey($Code)) { return @{ en = $known[$Code][0]; es = $known[$Code][1] } }
    return @{ en = 'WinGet stopped with an error'; es = 'WinGet se detuvo con un error' }
}
function Test-WingetAlreadyInstalled([int]$Code) { return ($Code -eq 0x8A15002B -or $Code -eq 0x8A150061) }
function Get-VcRuntimeProblem([string]$System32) {
    # 'missing', 'old:<version>' (older than 14.40, which PCSX2 2.x needs) or ''.
    foreach ($name in @('vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll')) {
        if (-not (Test-Path -LiteralPath (Join-Path $System32 $name) -PathType Leaf)) { return 'missing' }
    }
    $info = [Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $System32 'msvcp140.dll'))
    $version = New-Object System.Version -ArgumentList $info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart
    if ($version -lt [System.Version]'14.40.0') { return ('old:' + $version.ToString()) }
    return ''
}
function New-PlayShortcuts([string]$Folder, [string]$Installation, [string]$Version) {
    # Shortcuts, not copies, so the launchers keep running from their installation folder. An existing shortcut is
    # never replaced: the second one gets the version in its name, and a third is skipped.
    $made = @()
    $shell = New-Object -ComObject WScript.Shell
    foreach ($row in @(@('Tag Team Mod', 'Play.cmd'), @('Tag Team Mod - Mod settings', 'Mod settings.cmd'))) {
        $path = Join-Path $Folder ($row[0] + '.lnk')
        if (Test-Path -LiteralPath $path) { $path = Join-Path $Folder ($row[0] + ' ' + $Version + '.lnk') }
        if (Test-Path -LiteralPath $path) { continue }
        $link = $shell.CreateShortcut($path)
        $link.TargetPath = Join-Path $Installation $row[1]
        $link.WorkingDirectory = $Installation
        $icon = Join-Path $Installation 'game\runtime28\pcsx2-qt.exe'
        if (Test-Path -LiteralPath $icon -PathType Leaf) { $link.IconLocation = $icon + ',0' }
        $link.Save()
        $made += $path
    }
    return $made
}
function Write-SetupStatus([string]$Path, [hashtable]$Data) {
    # Written without a BOM (Python reads it as UTF-8).
    [IO.File]::WriteAllText($Path, ($Data | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
}
function Write-Check([string]$Kind, [string]$Text, [string]$Color = '') {
    $label = Get-Label $Kind $script:blockLanguage
    $line = '  [' + $label + '] ' + $Text
    if ($Color) { Write-Host $line -ForegroundColor $Color } else { Write-Host $line }
}
function Test-Winget {
    # TAGTEAM_SETUP_NO_WINGET=1: never install system software (offline or managed PCs, and the installer's own tests).
    if ($env:TAGTEAM_SETUP_NO_WINGET -eq '1') { return $false }
    return [bool](Get-Command winget.exe -ErrorAction SilentlyContinue)
}
function Install-PlayerPython {
    # A usable Python 3.11 x64 (with Tk, venv and ensurepip); WinGet installs one when none is found.
    $found = Find-PlayerPython
    $python = [string]$found[0]
    if ($python) { return $python }
    $closest = [string]$found[1]
    $missingPart = ''; $missingAt = $null
    if ($closest) { $missingPart = $closest.Split('|')[0]; $missingAt = $closest.Split('|')[1] }
    # WinGet cannot add Tk or venv to an installed python.org 3.11 (it answers "already installed"): name the part
    # instead. A Python found only on PATH is no such installation: WinGet installs a complete one beside it.
    if (Test-RegisteredPython $missingAt) {
        if ($missingPart -eq 'TK') { Stop-Setup 'TTM-PY-03' @{} $missingAt }
        if ($missingPart -like '*venv*') { Stop-Setup 'TTM-PY-04' @{ part = $missingPart } $missingAt }
    }
    if (-not (Test-Winget)) {
        $detail = ''
        if ($missingAt) { $detail = 'not usable: ' + $missingAt + ' (' + ($missingPart -replace '^TK$', 'no Tk (tkinter)') + ')' }
        Stop-Setup 'TTM-PY-01' @{} $null $detail
    }
    # These packages live in the community source. Do not query msstore:
    # an unrelated Store certificate/source failure would abort setup.
    & winget.exe install --id Python.Python.3.11 --exact --source winget --scope user --architecture x64 --silent --accept-package-agreements --accept-source-agreements | Out-Host
    $wingetCode = [int]$LASTEXITCODE
    if ($wingetCode -ne 0 -and -not (Test-WingetAlreadyInstalled $wingetCode)) {
        Stop-Setup 'TTM-PY-02' @{ winget = ('0x{0:X8}' -f $wingetCode); meaning = (Get-WingetMeaning $wingetCode) } $null ('WinGet exit ' + $wingetCode)
    }
    if ($wingetCode -eq 0) { $script:systemChanged = $true }
    $found = Find-PlayerPython
    $python = [string]$found[0]
    if ($python) { return $python }
    $closest = [string]$found[1]; $part = 'Python 3.11 (64-bit) was not found after installation'
    if ($closest) {
        $part = $closest.Split('|')[0]
        if ($part -eq 'TK') { Stop-Setup 'TTM-PY-03' @{} $closest.Split('|')[1] '' (-not $script:systemChanged) }
    }
    Stop-Setup 'TTM-PY-05' @{ part = $part } $null ('WinGet exit ' + $wingetCode) (-not $script:systemChanged)
}
function Install-VcRuntime([string]$System32) {
    # The Microsoft Visual C++ runtime PCSX2 needs: present and 14.40 or newer; WinGet installs or updates it.
    $problem = Get-VcRuntimeProblem $System32
    if (-not $problem) { return }
    Write-Host (L 'Installing the Microsoft Visual C++ runtime required by PCSX2...')
    if (-not (Test-Winget)) {
        if ($problem -eq 'missing') { Stop-Setup 'TTM-PY-06' @{} $null '' (-not $script:systemChanged) }
        Stop-Setup 'TTM-PY-09' @{ version = $problem.Substring(4) } (Join-Path $System32 'msvcp140.dll') '' (-not $script:systemChanged)
    }
    & winget.exe install --id 'Microsoft.VCRedist.2015+.x64' --exact --source winget --architecture x64 --silent --accept-package-agreements --accept-source-agreements | Out-Host
    $wingetCode = [int]$LASTEXITCODE
    if ($wingetCode -ne 0 -and $wingetCode -ne 3010 -and -not (Test-WingetAlreadyInstalled $wingetCode)) {
        Stop-Setup 'TTM-PY-07' @{ winget = ('0x{0:X8}' -f $wingetCode); meaning = (Get-WingetMeaning $wingetCode) } $null ('WinGet exit ' + $wingetCode) (-not $script:systemChanged)
    }
    $problem = Get-VcRuntimeProblem $System32
    if ($problem -eq 'missing') { Stop-Setup 'TTM-PY-08' @{} $null ('WinGet exit ' + $wingetCode) $false }
    if ($problem) { Stop-Setup 'TTM-PY-09' @{ version = $problem.Substring(4) } (Join-Path $System32 'msvcp140.dll') ('WinGet exit ' + $wingetCode) $false }
}
function Install-BundledPackages([string]$Private, [string]$Folder) {
    # The bundled, hash-checked wheels (offline), then pip check. They were verified with the installer's files, so a
    # failure here means a full disk, antivirus or missing permission (TTM-PY-11), not an incomplete download.
    & $Private -I -m pip --isolated install --disable-pip-version-check --no-cache-dir --no-index --find-links (Join-Path $script:setupFolder 'wheels') --only-binary=:all: --require-hashes -r (Join-Path $script:setupFolder 'requirements-player.lock') | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Setup 'TTM-PY-11' @{} $Folder ('pip exit ' + $LASTEXITCODE) $false }
    & $Private -I -m pip --isolated check | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Setup 'TTM-PY-12' @{} $Folder ('pip check exit ' + $LASTEXITCODE) $false }
}
function New-PrivatePython([string]$Python, [string]$Destination) {
    $venv = Join-Path $Destination '.venv'
    & $Python -I -m venv $venv | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Setup 'TTM-PY-10' @{} $venv ('venv exit ' + $LASTEXITCODE) $false }
    $private = Join-Path $venv 'Scripts\python.exe'
    Install-BundledPackages $private $venv
    return $private
}
function Repair-PrivatePython([string]$Python, [string]$Installation) {
    # Only the installation's .venv is rebuilt, from the same bundled wheels; nothing else is touched.
    $venv = Join-Path $Installation '.venv'
    & $Python -I -m venv --clear $venv | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Setup 'TTM-PY-13' @{} $Installation ('venv exit ' + $LASTEXITCODE) $false }
    $private = Join-Path $venv 'Scripts\python.exe'
    try { Install-BundledPackages $private $venv }
    catch { if ($script:failure) { Stop-Setup 'TTM-PY-13' @{} $Installation ([string]$script:failure.Code) $false }; throw }
    & $private (Join-Path $Installation 'check_installation.py') | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Setup 'TTM-PY-13' @{} $Installation ('check_installation.py exit ' + $LASTEXITCODE) $false }
}
#endregion setup functions

function Choose-Language {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Tag Team Mod - Language / Idioma'
    $form.StartPosition = 'CenterScreen'; $form.ClientSize = New-Object System.Drawing.Size(370,140)
    $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false; $form.MinimizeBox = $false
    $label = New-Object System.Windows.Forms.Label
    $label.Text = 'Language / Idioma'; $label.SetBounds(20,18,320,22)
    $choices = New-Object System.Windows.Forms.ComboBox
    $choices.DropDownStyle = 'DropDownList'; $choices.SetBounds(20,46,320,24)
    [void]$choices.Items.Add('English'); [void]$choices.Items.Add([string][char]69 + 'spa' + [char]241 + 'ol')
    $choices.SelectedIndex = 0
    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = 'Continue / Continuar'; $ok.SetBounds(170,92,170,28); $ok.DialogResult = 'OK'
    $form.AcceptButton = $ok; $form.Controls.AddRange(@($label,$choices,$ok))
    try {
        if ($form.ShowDialog() -ne 'OK') { Stop-Cancelled 'Setup cancelled / Instalacion cancelada.' }
        if ($choices.SelectedIndex -eq 1) { return 'es' }; return 'en'
    } finally { $form.Dispose() }
}
function Pick-File([string]$Title,[string]$Filter,[string]$Folder = '') {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = L $Title; $dialog.Filter = $Filter
    if ($Folder -and (Test-Path -LiteralPath $Folder -PathType Container)) { $dialog.InitialDirectory = $Folder }
    try { if ($dialog.ShowDialog() -ne 'OK') { Stop-Cancelled 'Setup cancelled; existing games are unchanged.' }; return $dialog.FileName }
    finally { $dialog.Dispose() }
}
function Ask-YesNo([string]$Text) {
    $answer = [System.Windows.Forms.MessageBox]::Show($Text, 'Tag Team Mod', [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
    return ($answer -eq [System.Windows.Forms.DialogResult]::Yes)
}
function Assert-InstallerFiles {
    $manifestPath = Join-Path $PSScriptRoot 'installer-files.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { Stop-Setup 'TTM-ZIP-02' @{} $manifestPath }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $manifestRoot = $PSScriptRoot
    if ($manifest.schema -eq 2) { $manifestRoot = Split-Path -Parent $PSScriptRoot }
    $prefix = [IO.Path]::GetFullPath($manifestRoot).TrimEnd('\') + '\'
    foreach ($item in $manifest.files.PSObject.Properties) {
        $path = [IO.Path]::GetFullPath((Join-Path $manifestRoot $item.Name))
        if (-not $path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
            Stop-Setup 'TTM-ZIP-03' @{ name = $item.Name } $null ('Installer file is missing or unsafe: ' + $item.Name)
        }
        $stream = [IO.File]::OpenRead($path)
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $digest = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
        finally { $stream.Dispose(); $sha.Dispose() }
        if ($digest -ne $item.Value) { Stop-Setup 'TTM-ZIP-04' @{ name = $item.Name } $path ('Installer checksum failed: ' + $item.Name) }
    }
}
function New-SetupLog {
    # %LOCALAPPDATA%\TagTeamMod\logs\setup-<time>.log (TAGTEAM_SETUP_LOGS overrides it for tests); TEMP as a fallback.
    $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss', [Globalization.CultureInfo]::InvariantCulture)
    $folders = @()
    if ($env:TAGTEAM_SETUP_LOGS) { $folders += $env:TAGTEAM_SETUP_LOGS }
    elseif ($env:LOCALAPPDATA) { $folders += (Join-Path $env:LOCALAPPDATA 'TagTeamMod\logs') }
    $folders += [IO.Path]::GetTempPath()
    foreach ($folder in $folders) {
        try {
            [void][IO.Directory]::CreateDirectory($folder)
            $path = Join-Path $folder ('setup-' + $stamp + '.log'); $number = 2
            while (Test-Path -LiteralPath $path) { $path = Join-Path $folder ('setup-' + $stamp + '-' + $number + '.log'); $number++ }
            return $path
        } catch {}
    }
    return (Join-Path ([IO.Path]::GetTempPath()) ('setup-' + $stamp + '.log'))
}

$setupLog = New-SetupLog
$detailsLog = $setupLog -replace '\.log$', '-details.log'
try {
    try { Start-Transcript -LiteralPath $setupLog | Out-Null; $transcriptStarted = $true } catch {}
    Assert-InstallerFiles
    $release = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release.json') -Raw | ConvertFrom-Json
    Write-Host ("Tag Team Mod " + $release.version + ' - BT3 and BT4 player setup')
    Write-Host ('Setup log: ' + $setupLog)
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        $machine = [string]$env:PROCESSOR_ARCHITECTURE
        if ($env:PROCESSOR_ARCHITEW6432) { $machine = [string]$env:PROCESSOR_ARCHITEW6432 }
        Stop-Setup 'TTM-OS-01' @{ needed = 'Windows x64 (Intel/AMD)'; found = ('Windows ' + $machine) }
    }
    Add-Type -AssemblyName System.Windows.Forms
    if (-not $Language) {
        if ($Destination) { $Language = 'en' } else { $Language = Choose-Language }
    }
    $script:blockLanguage = $Language
    $script:translations = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'installer-es.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $stage = 'Choosing installation inputs'
    $platform = Get-PlatformValues
    $explicit = [bool]$Destination
    if (-not $Destination) {
        $recommended = [string]$platform.recommended
        if (Ask-YesNo ((L 'Install into the recommended folder?') + "`n`n" + $recommended + "`n`n" + (L 'Choose No to pick another folder.'))) {
            $Destination = $recommended
        } else {
            $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $dialog.Description = L 'Choose the parent folder for a new Tag Team Mod installation'
            try { if ($dialog.ShowDialog() -ne 'OK') { Stop-Cancelled 'Setup cancelled.' }; $Destination = Get-ChosenInstallation $dialog.SelectedPath }
            finally { $dialog.Dispose() }
        }
    }
    $Destination = [IO.Path]::GetFullPath($Destination)
    if ($Destination.Length -gt 3) { $Destination = $Destination.TrimEnd('\') }
    $plan = Get-DestinationPlan $Destination $explicit ([string]$release.version)
    # The unfinished attempt's new name is chosen once: the checklist and the rename show the same name.
    $asideTarget = ''
    if ($plan.Aside) { $asideTarget = Get-AsideName ([string]$plan.Aside) }
    $Destination = [string]$plan.Destination
    $script:beside = [string]$plan.Beside
    # A complete installation whose private Python no longer starts can be repaired instead (only its .venv is rebuilt).
    $repair = ''
    if ($script:interactive -and $script:beside) {
        $oldPython = Join-Path $script:beside '.venv\Scripts\python.exe'
        $sameWheels = $false
        try { $sameWheels = ([IO.File]::ReadAllText((Join-Path $script:beside 'dependencies.json')) -eq [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'dependencies.json'))) } catch {}
        if ((Invoke-Probe $oldPython @('-c', 'pass')).Code -ne 0) {
            if (-not $sameWheels) {
                # Another release's .venv needs that release's bundled packages: say so instead of silently going beside it.
                Write-Check 'warn' ((L 'The existing installation cannot start its private Python, but it comes from another release: run the Install.cmd of that release to repair it. This new installation goes beside it.') + ' ' + $script:beside) 'Yellow'
            } elseif (Ask-YesNo ((L 'The existing installation cannot start its private Python. Repair it? (Only its .venv folder is rebuilt; choose No for a new installation beside it.)') + "`n`n" + $script:beside)) {
                $repair = $script:beside
            }
        }
    }
    if (-not $repair) {
        if (-not $Iso) { $Iso = Pick-File 'Choose BT3 USA / Europe / Japan or BT4 B14 REV2 English / Spanish (see README for supported discs)' 'Disc images (*.iso;*.img;*.bin;*.cue;*.chd;*.cso;*.zso;*.gz;*.7z;*.zip;*.rar)|*.iso;*.img;*.bin;*.cue;*.chd;*.cso;*.zso;*.gz;*.7z;*.zip;*.rar|All files|*.*' }
        if (-not $PCSX2) { $PCSX2 = Pick-File 'Choose extracted PCSX2 2.6.0 or newer (pcsx2-qt.exe) - download link is in README.md' 'PCSX2 (pcsx2-qt.exe)|pcsx2-qt.exe|Programs (*.exe)|*.exe|All files|*.*' }
        foreach ($path in @($Iso,$PCSX2)) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-Setup 'TTM-PAYLOAD-02' @{ reason = @{ en = ('Missing input: ' + $path); es = ((L 'Missing input:') + ' ' + $path) } } $path }
        }
        # Without -Bios: the BIOS the selected PCSX2 is set up with. Setup asks only when its settings give none it can
        # use; an unattended run (no dialogs) records that as a coded failure in the checklist below.
        $biosFound = $null; $biosFailure = $null
        if (-not $Bios) {
            # install_player.find_configured_bios: an unexpected error only means that no BIOS was found.
            try { $biosFound = Find-ConfiguredBios $PCSX2 }
            catch { $biosFound = New-BiosResult @() @{ Error = ($_.Exception.GetType().Name + ': ' + $_.Exception.Message) } }
            if ($biosFound.Bios) {
                # A configured file setup could not use is named before the only PS2 BIOS of its folder is taken.
                foreach ($line in @(Get-BiosNotes $biosFound)) { Write-Host $line -ForegroundColor Yellow }
                $Bios = [string]$biosFound.Bios
            }
            elseif ($script:unattended) { $biosFailure = Get-ConfiguredBiosFailure $biosFound }
            else {
                foreach ($line in @(Get-BiosNotes $biosFound)) { Write-Host $line -ForegroundColor Yellow }
                $Bios = Pick-File 'Choose your PlayStation 2 BIOS ROM' 'BIOS files|*.bin;*.rom;*.rom0;*.zip;*.7z|All files|*.*' ([string]$biosFound.Folder)
                $biosFound = $null
            }
        }
        if ($Bios -and -not (Test-Path -LiteralPath $Bios -PathType Leaf)) { Stop-Setup 'TTM-PAYLOAD-02' @{ reason = @{ en = ('Missing input: ' + $Bios); es = ((L 'Missing input:') + ' ' + $Bios) } } $Bios }
        # Preflight: every selected file and the folder in one list, before anything is changed.
        $stage = 'Checking your files before changing anything'
        Write-Host (L 'Checking your files before changing anything:')
        $failures = @()
        $findings = Get-DestinationFindings $Destination
        foreach ($finding in $findings[0]) { $failures += ,$finding; Write-Check 'fail' (Format-SetupLine $finding.Code $Language $finding.Values) 'Red' }
        if (@($findings[0]).Count -eq 0) { Write-Check 'ok' ((L 'Installation folder:') + ' ' + $Destination) }
        foreach ($warning in $findings[1]) { Write-Check 'warn' (Format-SetupLine $warning $Language @{}) 'Yellow' }
        if ($plan.Aside) { Write-Check 'ok' (Format-SetupLine 'TTM-DEST-25' $Language @{ name = (Split-Path -Leaf $asideTarget) }) }
        if ($script:beside) { Write-Check 'ok' (Format-SetupLine 'TTM-DEST-26' $Language @{ name = (Split-Path -Leaf $Destination) }) }
        $free = Get-FreeSpace $Destination
        if ($free -ge 0 -and $free -lt 3758096384) { $failures += ,@{ Code = 'TTM-DEST-05'; Values = @{ free = (Format-Size $free); needed = '3.5 GiB' }; File = (Get-ExistingAncestor $Destination) }; Write-Check 'fail' (Format-SetupLine 'TTM-DEST-05' $Language @{ free = (Format-Size $free); needed = '3.5 GiB' }) 'Red' }
        elseif ($free -ge 0) { Write-Check 'ok' ((L 'Free space:') + ' ' + (Format-Size $free)) }
        $problem = Get-IsoProblem $Iso
        if ($problem) { $failures += ,@{ Code = $problem.Code; Values = $problem.Values; File = $Iso }; Write-Check 'fail' (Format-SetupLine $problem.Code $Language $problem.Values) 'Red' }
        else { Write-Check 'ok' ('ISO: ' + $Iso) }
        # TTM-BIOS-07/08 describe the settings of the selected PCSX2: when setup refuses that PCSX2 too, its block comes
        # first (the main block and exit code), since the player replaces it and runs setup again anyway.
        $settingsFailure = $null
        if ($biosFailure) {
            if (@('TTM-BIOS-07', 'TTM-BIOS-08') -contains $biosFailure.Code) { $settingsFailure = $biosFailure } else { $failures += ,$biosFailure }
            Write-Check 'fail' (Format-SetupLine $biosFailure.Code $Language $biosFailure.Values) 'Red'
        }
        elseif ([IO.Path]::GetFullPath($Iso) -eq [IO.Path]::GetFullPath($Bios)) { $failures += ,@{ Code = 'TTM-BIOS-05'; Values = @{}; File = $Bios }; Write-Check 'fail' (Format-SetupLine 'TTM-BIOS-05' $Language @{}) 'Red' }
        else {
            $problem = Get-BiosProblem $Bios
            if ($problem) { $failures += ,@{ Code = $problem.Code; Values = $problem.Values; File = $Bios }; Write-Check 'fail' (Format-SetupLine $problem.Code $Language $problem.Values) 'Red' }
            else { Write-Check 'ok' ('BIOS: ' + $Bios + (Get-BiosOrigin $biosFound)) }
        }
        $emulator = Get-Pcsx2Problem $PCSX2 $release
        if ($emulator.Code) {
            $detail = ''; if ($emulator.ContainsKey('Detail')) { $detail = [string]$emulator.Detail }
            $failures += ,@{ Code = $emulator.Code; Values = $emulator.Values; File = $PCSX2; Detail = $detail }
            Write-Check 'fail' (Format-SetupLine $emulator.Code $Language $emulator.Values) 'Red'
        } else {
            Write-Check 'ok' ('PCSX2 ' + $emulator.Version + ' (x64)')
            if (-not $emulator.Tested) {
                Write-Host ((L 'This PCSX2 version is not one of the supported stable releases; setup continues. Supported stable releases:') + ' ' + (@($release.pcsx2_supported) -join ', ') + ' (PCSX2 ' + $emulator.Version + ')') -ForegroundColor Yellow
            }
        }
        if ($settingsFailure) { $failures += ,$settingsFailure }
        if ($failures.Count -gt 0) {
            for ($index = 1; $index -lt $failures.Count; $index++) {
                $other = $failures[$index]; $detail = ''; if ($other.ContainsKey('Detail')) { $detail = [string]$other.Detail }
                Write-Host (Format-SetupFailure $other.Code $other.Values $Language $null $other.File $detail '') -ForegroundColor Red
            }
            $first = $failures[0]; $detail = ''; if ($first.ContainsKey('Detail')) { $detail = [string]$first.Detail }
            Stop-Setup $first.Code $first.Values $first.File $detail
        }
    }
    $stage = '[1/6] Checking Python and Microsoft runtime'
    Write-Host (L $stage)
    $python = Install-PlayerPython
    Write-Host ('Python: ' + $python)
    Install-VcRuntime (Join-Path $env:WINDIR 'System32')
    if ($repair) {
        $stage = 'Repairing the private Python of an existing installation'
        Write-Host (L $stage)
        Repair-PrivatePython $python $repair
        Write-Host ((L 'Repaired. Open') + ' ' + (Join-Path $repair 'Play.cmd')) -ForegroundColor Green
    } else {
    # Nothing was changed until here. An unfinished earlier attempt is renamed aside, never deleted.
    if ($plan.Aside) {
        $aside = $asideTarget
        if (Test-Path -LiteralPath $aside) { $aside = Get-AsideName ([string]$plan.Aside) }
        Rename-Item -LiteralPath ([string]$plan.Aside) -NewName (Split-Path -Leaf $aside)
        Write-Host (Format-SetupLine 'TTM-DEST-25' $Language @{ name = (Split-Path -Leaf $aside) }) -ForegroundColor Yellow
    }
    # CreateDirectory: no wildcard reading of the path (unlike New-Item -Path); missing parent folders are created too.
    [void][IO.Directory]::CreateDirectory($Destination)
    $ownedDestination = $true
    Write-SetupStatus (Join-Path $Destination 'install-bootstrap.json') @{ schema=1; version=$release.version; created=[DateTime]::UtcNow.ToString('o') }
    $stage = '[2/6] Creating private Python environment and installing verified bundled dependencies'
    Write-Host (L $stage)
    $privatePython = New-PrivatePython $python $Destination
    $stage = 'Installing and verifying game adapter'
    & $privatePython (Join-Path $PSScriptRoot 'install_player.py') --destination $Destination --iso $Iso --pcsx2 $PCSX2 --bios $Bios --language $Language --log $detailsLog --quiet-failure
    $backend = $LASTEXITCODE
    if ($backend -ne 0) {
        # install_player.py records its coded reason in install-status.json; the block is drawn from it here.
        $status = $null
        try { $status = Get-Content -LiteralPath (Join-Path $Destination 'install-status.json') -Raw -Encoding UTF8 | ConvertFrom-Json } catch {}
        if ($status -and $status.PSObject.Properties['error_code'] -and $status.error_code) {
            $details = ConvertTo-Table $status.error_details
            $file = $null; $detail = ''
            if ($details.Contains('file')) { $file = $details['file']; $details.Remove('file') }
            if ($details.Contains('detail')) { $detail = [string]$details['detail']; $details.Remove('detail') }
            if ($details.Contains('unchanged')) { $details.Remove('unchanged') }
            if ($status.PSObject.Properties['failed_stage']) { $stage = [string]$status.failed_stage }
            Stop-Setup ([string]$status.error_code) $details $file $detail $false
        }
        Stop-Setup 'TTM-PAYLOAD-91' @{ exit = $backend } $null '' $false
    }
    Write-Host ((L 'Ready. Open') + " $Destination\Play.cmd") -ForegroundColor Green
    Write-Host (L 'Press Select at the main menu for Modded Modes. Existing games, BIOS, emulator profiles and saves were not changed.')
    # The installation is complete: nothing after this line may turn it into a failure.
    $exitCode = 0
    $script:installed = $true
    if ($script:interactive) { Complete-OptionalSteps $privatePython $Destination ([string]$release.version) $detailsLog }
    }
    $exitCode = 0
}
catch {
    if ($script:installed) {
        # After "Ready" the installation is complete and its status says so: an error here is logged, never a failure.
        try { [IO.File]::AppendAllText($detailsLog, ($_ | Out-String), (New-Object Text.UTF8Encoding($false))) } catch {}
        Write-Host ((Get-Label 'warn' $script:blockLanguage) + ': ' + $_.Exception.Message) -ForegroundColor Yellow
        $exitCode = 0
    } elseif ($script:cancelled) {
        Write-Host (L $script:cancelled)
        $exitCode = 1
    } else {
        if ($null -eq $script:failure) {
            # Unexpected: the PowerShell record goes to the log, the player gets the coded block.
            $position = ''
            if ($_.InvocationInfo) { $position = ' at line ' + $_.InvocationInfo.ScriptLineNumber }
            try { [IO.File]::AppendAllText($detailsLog, ($_ | Out-String), (New-Object Text.UTF8Encoding($false))) } catch {}
            $script:failure = @{ Code = 'TTM-PAYLOAD-90'; Values = @{}; File = $null; Detail = ($_.Exception.GetType().Name + ': ' + $_.Exception.Message + $position); Unchanged = $null }
        }
        $failure = $script:failure
        $unchanged = $failure.Unchanged
        if ($ownedDestination -and $null -eq $unchanged) { $unchanged = $false }
        Write-Host ''
        Write-Host (Format-SetupFailure $failure.Code $failure.Values $script:blockLanguage $unchanged $failure.File $failure.Detail $setupLog) -ForegroundColor Red
        # The folder this run made stays (setup never deletes one): say what the next run does with it.
        if ($ownedDestination -and ([string]$failure.Code) -notlike 'TTM-DEST-*') {
            Write-Host (L 'The unfinished installation folder is kept as it is. Run Install.cmd again with the same choices: setup renames that folder aside (adding "failed" and the time to its name) and installs a fresh copy.') -ForegroundColor Yellow
        }
        $exitCode = Get-FailureExitCode $failure.Code
        if ($ownedDestination) {
            $statusPath = Join-Path $Destination 'install-status.json'
            $recorded = $false
            try {
                $old = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
                # A recorded failure is kept, and so is a finished installation ('[6/6] Installed' is never overwritten).
                $recorded = [bool](($old.PSObject.Properties['error_code'] -and $old.error_code) -or ($old.PSObject.Properties['stage'] -and $old.stage -eq '[6/6] Installed'))
            } catch {}
            if (-not $recorded) {
                $details = ConvertTo-Table $failure.Values
                if ($failure.File) { $details['file'] = $failure.File }
                if ($failure.Detail) { $details['detail'] = $failure.Detail }
                try { Write-SetupStatus $statusPath @{ ready=$false; stage='FAILED'; failed_stage=$stage; error=(Get-MessageText $failure.Code 'what' 'en' $failure.Values); error_code=$failure.Code; error_details=$details } } catch {}
            }
        }
    }
}
finally {
    if ($transcriptStarted) { try { Stop-Transcript | Out-Null } catch {} }
    # installer.log: the transcript, then install_player.py's own log (the transcript can miss a child's output).
    if (Test-Path -LiteralPath $detailsLog -PathType Leaf) {
        try { [IO.File]::AppendAllText($setupLog, "`r`n==== install_player.py ====`r`n" + [IO.File]::ReadAllText($detailsLog), (New-Object Text.UTF8Encoding($false))) } catch {}
    }
    if ($ownedDestination -and (Test-Path -LiteralPath $setupLog)) {
        try { Copy-Item -LiteralPath $setupLog -Destination (Join-Path $Destination 'installer.log') -Force } catch {}
    }
}
exit $exitCode
