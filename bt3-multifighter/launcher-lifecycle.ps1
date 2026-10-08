<# Shared launch/cleanup ownership. Dot-sourcing does not start anything. #>
function Test-Bt3ControllerStatus {
    param($Status, [string]$Token, [int]$EmulatorId)
    # Windows venv python.exe may be a redirector whose child has a different
    # PID. Authenticate the fresh launch token and owned emulator, not that stub.
    if (-not $Status -or -not $Token) { return $false }
    foreach ($key in @('launcher_token','pid','emulator_pid','state')) {
        if (-not $Status.PSObject.Properties[$key]) { return $false }
    }
    return ($Status.launcher_token -ceq $Token -and $Status.pid -gt 0 -and
        $Status.emulator_pid -eq $EmulatorId -and $Status.state -notin @('FAILED','CLOSED'))
}

function Enter-Bt3LauncherLease {
    param([string]$ProjectRoot, [int]$TimeoutMilliseconds = 12000)
    $leaseDirectory = Join-Path $ProjectRoot 'analysis\autopilot'
    [void][System.IO.Directory]::CreateDirectory($leaseDirectory)
    $leasePath = Join-Path $leaseDirectory '.launcher.lock'
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    do {
        try {
            return [System.IO.File]::Open($leasePath, [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        }
        catch [System.IO.IOException] {
            if ([DateTime]::UtcNow -ge $deadline) {
                $language = Get-Bt3Language -ProjectRoot $ProjectRoot
                throw (New-Bt3Failure -Code 'TTM-PLAY-31' -What (Get-Bt3Text 'lease.what' $language) `
                    -Fix (Get-Bt3Text 'lease.fix' $language) -ExitCode 2 -NothingChanged `
                    -Message 'Another Play window is still starting or closing. Close its PCSX2 before launching again.')
            }
            Start-Sleep -Milliseconds 100
        }
    } while ($true)
}

function Invoke-Bt3LaunchStep {
    # Run one idempotent pre-launch Python step. Its complete output is kept in the
    # launch's log folder as well as shown here, and a failure is retried once: a file
    # briefly locked by a scanner, or a tools tree caught mid-save, must not cost the
    # launch. The final error names the saved output so the cause is never lost.
    param([string]$PythonPath, [string]$LogDirectory, [string]$Name, [string]$Description,
          [string]$Arguments, [int]$Attempts = 2, [int]$RetryDelayMilliseconds = 2000, [string]$Language = 'en')
    $errorPath = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        $outputPath = Join-Path $LogDirectory ('launch-' + $Name + '-' + $attempt + '.out.log')
        $errorPath = Join-Path $LogDirectory ('launch-' + $Name + '-' + $attempt + '.err.log')
        $step = Start-Process -FilePath $PythonPath -ArgumentList $Arguments -NoNewWindow -PassThru `
            -RedirectStandardOutput $outputPath -RedirectStandardError $errorPath
        $null = $step.Handle   # keeps ExitCode readable after exit on Windows PowerShell 5.1
        $step.WaitForExit()
        foreach ($path in @($outputPath, $errorPath)) {
            if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 0) {
                # Raw proof lines (the hook's SHA-256, the clean-up list, the session settings) stay in the log.
                Get-Content -LiteralPath $path -Encoding UTF8 | Where-Object { $_ -cnotmatch $Bt3StepRawLine } | ForEach-Object { Write-Host $_ }
            }
        }
        if ($step.ExitCode -eq 0) { return }
        if ($attempt -lt $Attempts) {
            Write-Host (Get-Bt3Text 'step.retry' $Language) -ForegroundColor Yellow
            Start-Sleep -Milliseconds $RetryDelayMilliseconds
        }
    }
    $what = $Description
    if ($Bt3Text.ContainsKey('step.' + $Name)) { $what = Get-Bt3Text ('step.' + $Name) $Language }
    throw (New-Bt3Failure -Code 'TTM-PLAY-32' -What $what -Fix (Get-Bt3Text 'step.fix' $Language) -File $errorPath `
        -Message ($Description + ' Details: ' + $errorPath))
}

function Write-Bt3LaunchFailure {
    # A startup error is shown in a console that closes on a key press; keep it on disk.
    param($ErrorRecord, [string]$Directory)
    try {
        [void][System.IO.Directory]::CreateDirectory($Directory)
        $path = Join-Path $Directory ('launch-error-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
        $lines = @((Get-Date -Format 'o'), [string]$ErrorRecord.Exception.Message,
                   [string]$ErrorRecord.InvocationInfo.PositionMessage, [string]$ErrorRecord.ScriptStackTrace)
        [System.IO.File]::WriteAllLines($path, [string[]]$lines)
        return $path
    }
    catch { return $null }
}

function Stop-Bt3OwnedHelper {
    param($Process, [int]$GraceMilliseconds = 5000)
    if ($null -eq $Process) { return }
    # Retain the original Process object/handle; never find a replacement by
    # name or PID during teardown. Helpers normally finish on emulator exit.
    if (-not $Process.HasExited -and -not $Process.WaitForExit($GraceMilliseconds)) {
        $Process.Kill()
        if (-not $Process.WaitForExit(5000)) { throw 'An owned BT3 helper did not stop.' }
    }
}

# ---- Player-facing failures ------------------------------------------------------------------------
# One explained block per failure, in the player's language (game\mod-settings.json), with the same
# labels, 78-column frame and codes as tools\player_errors.py (block, frame, wrap, LAUNCH_CODES).
# ASCII only: Windows PowerShell 5.1 reads a script without a BOM as ANSI, so Spanish is unaccented.
$Bt3Labels = @{
    en = @{ what = 'WHAT HAPPENED'; why = 'WHY'; fix = 'HOW TO FIX'; file = 'FILE'; details = 'DETAILS'; log = 'LOG'
            report = 'REPORT'; unchanged = 'Nothing was changed.'; copy = 'Copy this block when asking for help.' }
    es = @{ what = 'QUE HA PASADO'; why = 'POR QUE'; fix = 'COMO SOLUCIONARLO'; file = 'ARCHIVO'; details = 'DETALLES'
            log = 'REGISTRO'; report = 'INFORME'; unchanged = 'No se ha cambiado nada.'; copy = 'Copia este bloque si pides ayuda.' }
}
$Bt3Text = @{
    'running.what' = @('PCSX2 is already running, so Play did not start.', 'PCSX2 ya se esta ejecutando, asi que Play no se ha iniciado.')
    'running.why' = @('Only one PCSX2 can run while the mod plays.', 'Solo puede haber un PCSX2 abierto mientras se juega con el mod.')
    'running.fix' = @('Close every PCSX2 window (check the taskbar), then start Play again.', 'Cierra todas las ventanas de PCSX2 (mira la barra de tareas) y vuelve a abrir Play.')
    'hung.why' = @("This installation's PCSX2 is still running without a window: it is probably stuck after a crash.", 'El PCSX2 de esta instalacion sigue abierto sin ventana: probablemente se quedo bloqueado tras un fallo.')
    'hung.prompt' = @('End this stuck PCSX2 now? Anything unsaved in it is lost. (Y/N)', 'Cerrar ahora este PCSX2 bloqueado? Se pierde lo que no este guardado. (S/N)')
    'port.what' = @('Another program is using the connection port Play needs.', 'Otro programa esta usando el puerto de conexion que Play necesita.')
    'port.fix' = @('Close that program, then start Play again.', 'Cierra ese programa y vuelve a abrir Play.')
    'missing.what' = @('A file Play needs is missing.', 'Falta un archivo que Play necesita.')
    'missing.why' = @('The installation is incomplete, or a security program removed a file.', 'La instalacion esta incompleta o un programa de seguridad elimino un archivo.')
    'missing.fix' = @('Run Check installation.cmd. If it reports a problem, run Install.cmd and choose the folder of this installation itself (the one that holds the game folder): setup installs a fresh copy beside it and offers to copy your memory cards and mod settings into it.', 'Ejecuta Check installation.cmd. Si indica un problema, ejecuta Install.cmd y elige la propia carpeta de esta instalacion (la que contiene la carpeta game): el instalador crea una copia nueva junto a ella y ofrece copiar en ella tus tarjetas de memoria y los ajustes del mod.')
    'missing.fix.dev' = @('Restore the missing file, or install the mod again into a new folder.', 'Recupera el archivo que falta o instala el mod de nuevo en una carpeta nueva.')
    'venv.what' = @("The mod's private Python (.venv) does not start.", 'El Python privado del mod (.venv) no arranca.')
    'venv.why' = @('The Python it was made from (named under DETAILS) was removed, upgraded or changed.', 'El Python con el que se creo (indicado en DETALLES) se elimino, se actualizo o cambio.')
    'venv.missing' = @('The .venv folder beside the game folder is missing or incomplete.', 'Falta la carpeta .venv junto a la carpeta game o esta incompleta.')
    'venv.packages' = @('The private Python starts, but a package the mod needs is missing or damaged.', 'El Python privado arranca, pero falta un paquete que necesita el mod o esta danado.')
    'venv.tk' = @('The private Python starts, but its Tk (the window toolkit Mod settings uses) is missing or damaged.', 'El Python privado arranca, pero su Tk (las ventanas que usa Mod settings) falta o esta danado.')
    'venv.fix' = @('Run Install.cmd from the same release, choose the folder of this installation itself (the one that holds the game folder), and answer Yes when setup offers to repair its private Python. When it offers no repair (the private Python still starts), it installs a fresh copy beside it and offers to copy your memory cards and mod settings into it.', 'Ejecuta Install.cmd de la misma version, elige la propia carpeta de esta instalacion (la que contiene la carpeta game) y responde Si cuando el instalador ofrezca reparar su Python privado. Si no ofrece repararlo (el Python privado aun arranca), crea una copia nueva junto a ella y ofrece copiar en ella tus tarjetas de memoria y los ajustes del mod.')
    'nopython.what' = @('No Python with the mod packages could start.', 'No se pudo iniciar ningun Python con los paquetes del mod.')
    'nopython.fix' = @('Install Python 3.11 or later with the packages the mod needs, then start Play again.', 'Instala Python 3.11 o posterior con los paquetes que necesita el mod y vuelve a abrir Play.')
    'settings.what' = @('Your mod settings file cannot be read.', 'No se puede leer tu archivo de ajustes del mod.')
    'settings.why' = @('The file game\mod-settings.json is damaged or comes from an unsupported version.', 'El archivo game\mod-settings.json esta danado o es de una version no compatible.')
    'settings.fix' = @('Open Mod settings and choose Restore defaults (or delete game\mod-settings.json), then start Play again.', 'Abre Mod settings y elige Restaurar valores predeterminados (o borra game\mod-settings.json); despues vuelve a abrir Play.')
    'gamefiles.what' = @('A game file the mod needs is missing or does not match.', 'Falta un archivo del juego que necesita el mod o no coincide.')
    'version.what' = @('This PCSX2 version is not supported.', 'Esta version de PCSX2 no es compatible.')
    'version.fix' = @('Install the mod again into a new folder; setup installs a supported PCSX2.', 'Instala el mod de nuevo en una carpeta nueva; la instalacion incluye un PCSX2 compatible.')
    'version.untested' = @('PCSX2 {version} is not one of the supported stable releases ({tested}). It is allowed; report any problem with this version.', 'PCSX2 {version} no es una de las versiones estables compatibles ({tested}). Se permite; informa de cualquier problema con esta version.')
    'profile.what' = @('A PCSX2 setting this installation needs was changed.', 'Se cambio un ajuste de PCSX2 que esta instalacion necesita.')
    'lease.what' = @('Another Play window is still starting or closing.', 'Otra ventana de Play todavia se esta iniciando o cerrando.')
    'lease.fix' = @('Close its PCSX2, wait a few seconds, then start Play again.', 'Cierra su PCSX2, espera unos segundos y vuelve a abrir Play.')
    'step.storage' = @('Play could not clean up old generated files.', 'Play no pudo limpiar los archivos generados antiguos.')
    'step.boot-hooks' = @('Play could not install the in-game loading screen.', 'Play no pudo instalar la pantalla de carga del juego.')
    'step.display' = @('Play could not prepare the display settings.', 'Play no pudo preparar los ajustes de pantalla.')
    'step.fix' = @('Start Play again. If it happens again, send the saved log file to the mod author.', 'Vuelve a abrir Play. Si vuelve a ocurrir, envia el registro guardado al autor del mod.')
    'step.retry' = @('That startup step failed; retrying it once.', 'Ese paso del inicio ha fallado; se vuelve a intentar una vez.')
    'helper.what' = @("The mod's helper could not start.", 'El asistente del mod no se pudo iniciar.')
    'helper.fix' = @('Start Play again. If it happens again, send the log folder to the mod author.', 'Vuelve a abrir Play. Si vuelve a ocurrir, envia la carpeta de registros al autor del mod.')
    'confirm.what' = @("The mod's helper did not start in time, so PCSX2 was closed.", 'El asistente del mod no se inicio a tiempo, asi que se cerro PCSX2.')
    'confirm.why' = @('The PC was busy, or a security program delayed Python.', 'El PC estaba ocupado o un programa de seguridad retraso Python.')
    'confirm.fix' = @('Start Play again.', 'Vuelve a abrir Play.')
    'early.what' = @('PCSX2 closed while Play was starting.', 'PCSX2 se cerro mientras Play se iniciaba.')
    'early.fix' = @('Start Play again. If PCSX2 closes again, open game\runtime28\pcsx2-qt.exe once to see its own message.', 'Vuelve a abrir Play. Si PCSX2 se cierra otra vez, abre una vez game\runtime28\pcsx2-qt.exe para ver su propio mensaje.')
    'crash.what' = @('PCSX2 closed with an error.', 'PCSX2 se cerro con un error.')
    'crash.why' = @('PCSX2 crashed; a graphics driver problem is the usual cause.', 'PCSX2 fallo; la causa habitual es un problema del controlador grafico.')
    'crash.fix' = @('Start Play again. If it keeps happening, update your graphics driver or choose another renderer in PCSX2.', 'Vuelve a abrir Play. Si sigue pasando, actualiza el controlador grafico o elige otro renderizador en PCSX2.')
    'stopped.what' = @("The mod's helper stopped during the session.", 'El asistente del mod se detuvo durante la sesion.')
    'stopped.fix' = @('Close PCSX2, then start Play again. If it happens again, send the log folder to the mod author.', 'Cierra PCSX2 y vuelve a abrir Play. Si vuelve a ocurrir, envia la carpeta de registros al autor del mod.')
    'session.what' = @('The session ended after an error. Details are above and in the report file.', 'La sesion termino despues de un error. Los detalles estan arriba y en el archivo del informe.')
    'recovered.what' = @('A problem was handled during the session; you could keep playing.', 'Se resolvio un problema durante la sesion; pudiste seguir jugando.')
    'iso.what' = @('The game ISO is no longer at its saved location.', 'La ISO del juego ya no esta en su ubicacion guardada.')
    'iso.why' = @('It was moved, renamed or deleted, or its drive is not connected.', 'Se movio, se cambio de nombre o se borro, o su unidad no esta conectada.')
    'iso.fix' = @('Put it back or reconnect its drive, or choose its new location when {play} asks.', 'Vuelve a ponerla en su sitio o conecta su unidad, o elige su nueva ubicacion cuando {play} lo pregunte.')
    'iso.prompt' = @('Choose the new location of the game ISO now? (Y/N)', 'Elegir ahora la nueva ubicacion de la ISO del juego? (S/N)')
    'iso.title' = @('Choose the same game ISO ({disc}) at its new location', 'Elige la misma ISO del juego ({disc}) en su nueva ubicacion')
    'isocheck.what' = @('The game ISO could not be checked.', 'No se pudo comprobar la ISO del juego.')
    'isocheck.fix' = @('Read the details below. If you replaced the ISO, add the new file in {mod_settings} > Game disc and use it.', 'Lee los detalles de abajo. Si sustituiste la ISO, anade el archivo nuevo en {mod_settings} > Disco del juego y usalo.')
    'maps.what' = @('The expanded-map ISO could not be selected.', 'No se pudo elegir la ISO de mapas ampliados.')
    'maps.fix' = @('Turn expanded maps off in Mod settings, or build them again.', 'Desactiva los mapas ampliados en Mod settings o vuelve a crearlos.')
    'unexpected.what' = @('Play stopped because of an unexpected error.', 'Play se detuvo por un error inesperado.')
    'unexpected.fix' = @('Start Play again. If it happens again, send the saved log file to the mod author.', 'Vuelve a abrir Play. Si vuelve a ocurrir, envia el registro guardado al autor del mod.')
    'appeared.what' = @('A PCSX2 opened while Play was starting.', 'Se abrio un PCSX2 mientras Play se iniciaba.')
    'appeared.fix' = @('Close it, then start Play again.', 'Cierralo y vuelve a abrir Play.')
    'settingsfail.what' = @('The Mod settings window could not finish.', 'La ventana de ajustes del mod no pudo terminar.')
    'notk.what' = @('No Python with Tk could open Mod settings.', 'Ningun Python con Tk pudo abrir los ajustes del mod.')
    'notk.fix' = @('Install Python 3.11 or later with Tk (the tcl/tk option of the Python installer), then open Mod settings again.', 'Instala Python 3.11 o posterior con Tk (la opcion tcl/tk del instalador de Python) y vuelve a abrir Mod settings.')
    'brackets.what' = @('The Tag Team Mod folder is in a path with square brackets ([ or ]).', 'La carpeta de Tag Team Mod esta en una ruta con corchetes ([ o ]).')
    'brackets.why' = @('PowerShell reads square brackets as wildcards, so Play and Mod settings cannot open their files in that folder.', 'PowerShell interpreta los corchetes como comodines, asi que Play y Mod settings no pueden abrir sus archivos en esa carpeta.')
    'brackets.fix' = @('Move the whole Tag Team Mod folder to a path without square brackets (for example, rename a folder "Games [PS2]" to "Games PS2"), then start Play again.', 'Mueve toda la carpeta de Tag Team Mod a una ruta sin corchetes (por ejemplo, cambia el nombre de una carpeta "Games [PS2]" a "Games PS2") y vuelve a abrir Play.')
    'helperstop.line' = @("[TTM-PLAY-37] The mod's helper stopped (exit {code}), so the mod no longer prepares matches in this session. Close PCSX2, then start Play again. Logs: {logs}", '[TTM-PLAY-37] El asistente del mod se detuvo (salida {code}), asi que el mod ya no prepara combates en esta sesion. Cierra PCSX2 y vuelve a abrir Play. Registros: {logs}')
    'venv.home' = @('Base Python (.venv\pyvenv.cfg, home): {home}', 'Python base (.venv\pyvenv.cfg, home): {home}')
}

function Get-Bt3Text {
    # Text in the player's language; {name} placeholders are filled literally (never a format string).
    param([string]$Key, [string]$Language = 'en', [hashtable]$Values = @{})
    if (-not $Bt3Text.ContainsKey($Key)) { return $Key }
    $pair = $Bt3Text[$Key]
    $text = $pair[0]
    if ($Language -eq 'es') { $text = $pair[1] }
    foreach ($name in $Values.Keys) { $text = $text.Replace('{' + $name + '}', [string]$Values[$name]) }
    return $text
}

function Get-Bt3Language {
    # The language saved in game\mod-settings.json; English when it cannot be read.
    param([string]$ProjectRoot)
    try {
        $path = Join-Path $ProjectRoot 'mod-settings.json'
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $value = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($value.PSObject.Properties['language'] -and [string]$value.language -eq 'es') { return 'es' }
        }
    }
    catch { }
    return 'en'
}

function Test-Bt3PlayerInstall {
    # localization.install_kind(): an installer-made folder carries game\player-install.json; without it
    # (quarantined, a partial copy) setup's file receipt beside the game folder still marks a player's copy.
    param([string]$ProjectRoot)
    if (Test-Path -LiteralPath (Join-Path $ProjectRoot 'player-install.json') -PathType Leaf) { return $true }
    return (Test-Path -LiteralPath (Join-Path (Split-Path -Parent $ProjectRoot) 'installed-files.json') -PathType Leaf)
}

function Test-Bt3BracketPath {
    # PowerShell reads [ and ] in -Path/-WorkingDirectory/-Redirect* arguments as wildcards, so Play and Mod settings
    # cannot start from such a folder (setup refuses it too: TTM-DEST-04). Checked before anything starts.
    param([string]$ProjectRoot)
    return ([string]$ProjectRoot).IndexOfAny([char[]]@([char]'[', [char]']')) -ge 0
}

function Split-Bt3Text {
    # player_errors.wrap: greedy word wrap on single spaces; a longer word is cut.
    param([string]$Text, [int]$Width)
    $lines = New-Object System.Collections.Generic.List[string]
    $current = ''
    foreach ($word in $Text.Split(' ')) {
        while ($word.Length -gt $Width) {
            if ($current) { $lines.Add($current); $current = '' }
            $lines.Add($word.Substring(0, $Width))
            $word = $word.Substring($Width)
        }
        if (-not $current) { $current = $word }
        elseif ($current.Length + 1 + $word.Length -le $Width) { $current = $current + ' ' + $word }
        else { $lines.Add($current); $current = $word }
    }
    $lines.Add($current)
    $lines.ToArray()
}

function Format-Bt3Block {
    # player_errors.block: code and WHAT HAPPENED first; paths and raw detail lines are never wrapped.
    param([string]$Code, [string]$What, [string]$Why = '', [string]$Fix = '', [string]$File = '',
          [string]$Report = '', [string]$Log = '', [string]$Details = '', [string[]]$DetailLines = @(),
          [switch]$NothingChanged, [string]$Language = 'en')
    $text = $Bt3Labels['en']
    if ($Language -eq 'es') { $text = $Bt3Labels['es'] }
    $rows = New-Object System.Collections.Generic.List[object]
    $rows.Add(@(('[' + $Code + '] ' + $text['what'] + ': ' + $What), $false))
    if ($Why) { $rows.Add(@(($text['why'] + ': ' + $Why), $false)) }
    if ($Fix) { $rows.Add(@(($text['fix'] + ': ' + $Fix), $false)) }
    if ($File) { $rows.Add(@(($text['file'] + ':'), $false)); $rows.Add(@($File, $true)) }
    if ($Report) { $rows.Add(@(($text['report'] + ':'), $false)); $rows.Add(@($Report, $true)) }
    if ($Log) { $rows.Add(@(($text['log'] + ':'), $false)); $rows.Add(@($Log, $true)) }
    if ($Details) { $rows.Add(@(($text['details'] + ': ' + $Details), $false)) }
    $raw = @($DetailLines | Where-Object { $null -ne $_ -and ([string]$_).Trim() })
    if ($raw.Count) {
        $rows.Add(@(($text['details'] + ':'), $false))
        foreach ($line in $raw) { $rows.Add(@(([string]$line).TrimEnd(), $true)) }
    }
    if ($NothingChanged) { $rows.Add(@($text['unchanged'], $false)) }
    $rows.Add(@($text['copy'], $false))
    $inner = 74
    $edge = '+' + ('-' * 76) + '+'
    $out = New-Object System.Collections.Generic.List[string]
    $out.Add($edge)
    foreach ($row in $rows) {
        if ($row[1]) { $pieces = @([string]$row[0]) } else { $pieces = Split-Bt3Text -Text ([string]$row[0]) -Width $inner }
        foreach ($piece in $pieces) {
            if ($piece.Length -le $inner) { $out.Add('| ' + $piece.PadRight($inner) + ' |') } else { $out.Add('| ' + $piece) }
        }
    }
    $out.Add($edge)
    $out.ToArray()
}

function Write-Bt3Block {
    param([string[]]$Lines, [string]$Color = 'Red')
    foreach ($line in $Lines) { Write-Host $line -ForegroundColor $Color }
}

function New-Bt3Failure {
    # An exception that carries its explanation; the launcher's trap prints it as a block and exits with ExitCode.
    param([string]$Code, [string]$What, [string]$Why = '', [string]$Fix = '', [string]$File = '', [string]$Details = '',
          [string[]]$DetailLines = @(), [int]$ExitCode = 1, [switch]$NothingChanged, [string]$Message = '')
    if (-not $Message) { $Message = $What }
    $exception = New-Object System.Exception -ArgumentList $Message
    $exception.Data['bt3'] = @{ Code = $Code; What = $What; Why = $Why; Fix = $Fix; File = $File; Details = $Details
                                 DetailLines = @($DetailLines); ExitCode = $ExitCode; NothingChanged = [bool]$NothingChanged }
    return $exception
}

function Invoke-Bt3Probe {
    # Run Python and keep every output line. Under $ErrorActionPreference = 'Stop' the first stderr line
    # would throw and hide the rest (and reject a working Python that prints a warning), so this call
    # runs with 'Continue' and is judged by its exit code only.
    param([string]$PythonPath, [string[]]$Arguments)
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $lines = @()
    $code = -1
    try {
        $lines = @(& $PythonPath @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = -1 }
    }
    catch { $lines = @([string]$_.Exception.Message); $code = -1 }
    finally { $ErrorActionPreference = $saved }
    return [pscustomobject]@{ Code = [int]$code; Lines = $lines }
}

function Test-Bt3ProbeStarted {
    # True when the interpreter itself ran (a check line or a traceback): its base Python is fine. It did
    # not start: no probe (file missing), exit -1, the venv redirector's own codes 100-114 or 'No Python at'.
    param($Probe)
    if ($null -eq $Probe) { return $false }
    if ($Probe.Code -eq -1 -or ($Probe.Code -ge 100 -and $Probe.Code -le 114)) { return $false }
    if (@($Probe.Lines | Where-Object { ([string]$_) -match 'No Python at' }).Count) { return $false }
    return $true
}

function Get-Bt3VenvWhy {
    # Why the private Python fails: it ran but a package (or Tk: -StartedKey 'venv.tk') is missing; its
    # base Python (pyvenv.cfg 'home') was removed or changed; or the .venv itself is missing.
    param([string]$VenvRoot, [string]$Language = 'en', $Probe = $null, [string]$StartedKey = 'venv.packages')
    if (Test-Bt3ProbeStarted $Probe) { return (Get-Bt3Text $StartedKey $Language) }
    $home_ = Get-Bt3VenvHome -VenvRoot $VenvRoot
    if ($home_ -eq '?' -or -not (Test-Path -LiteralPath (Join-Path $VenvRoot 'Scripts\python.exe') -PathType Leaf)) {
        return (Get-Bt3Text 'venv.missing' $Language)
    }
    return (Get-Bt3Text 'venv.why' $Language)
}

function Get-Bt3VenvDetails {
    # The base Python a .venv was made from, as a DETAILS line of its own: a path is never wrapped mid-word there.
    param([string]$VenvRoot, [string]$Language = 'en')
    $home_ = Get-Bt3VenvHome -VenvRoot $VenvRoot
    if ($home_ -eq '?') { return @() }
    return @(Get-Bt3Text 'venv.home' $Language @{ home = $home_ })
}

function Get-Bt3VenvHome {
    # The Python a .venv was made from (pyvenv.cfg 'home').
    param([string]$VenvRoot)
    try {
        foreach ($line in @(Get-Content -LiteralPath (Join-Path $VenvRoot 'pyvenv.cfg') -Encoding UTF8)) {
            if ($line -match '^\s*home\s*=\s*(.+?)\s*$') { return $Matches[1] }
        }
    }
    catch { }
    return '?'
}

function Resolve-Bt3IsoLocation {
    # game_profile.iso_path: iso-location.json wins when it names the same ISO (equal sha256) and that file
    # exists; an ISO moved back to its installed place is found again.
    param([string]$ProjectRoot, $Profile, [string]$Default)
    try {
        $path = Join-Path $ProjectRoot 'iso-location.json'
        if (-not $Profile.PSObject.Properties['iso_sha256'] -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { return $Default }
        $location = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($location.PSObject.Properties['path'] -and $location.PSObject.Properties['sha256'] -and
                ([string]$Profile.iso_sha256) -and ([string]$location.sha256).ToLowerInvariant() -eq ([string]$Profile.iso_sha256).ToLowerInvariant() -and
                (Test-Path -LiteralPath ([string]$location.path) -PathType Leaf)) {
            return [string]$location.path
        }
    }
    catch { }
    return $Default
}

function Test-Bt3Interactive {
    # A console a player can answer; tests and headless runs never get a question or a file picker.
    if ($env:TAGTEAM_NO_PROMPT) { return $false }
    try { return ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) } catch { return $false }
}

function Read-Bt3YesNo {
    param([string]$Prompt)
    if (-not (Test-Bt3Interactive)) { return $false }
    try { $answer = Read-Host $Prompt } catch { return $false }
    return ([string]$answer).Trim() -match '^(?i:y|yes|s|si)$'
}

# ---- The watcher log in the Play window ------------------------------------------------------------
# play_launcher.py uses the same patterns (test_b33a_launchers compares them). Telemetry stays in
# watcher.log but is not echoed: an explicit deny list, never an allow list.
$Bt3ErrorLine = '^\d\d:\d\d:\d\d ERROR:'
$Bt3WarningLine = '^\d\d:\d\d:\d\d WARNING:'
$Bt3DenyLine = '^(?:\d\d:\d\d:\d\d )?(?:[A-Z]+: )?(?:loading cover:|Menu return:|Extra reload timing:|Body Change (?:timing|pre-hold recovery|handoff actions):|Team activated\. Restart checkpoint:|The automatic launcher handles rematches\.|Capturing a fresh idle team match|Rematch checkpoint:|Saved clean [a-z ]+ checkpoint\.|Reused savestate slot\(s\) |Se reutilizaron las ranuras de guardado |Phase-1 stall: |Shared hold snapshot \(|Trail lists: |Frozen EE program counter )'
$Bt3ClosingLine = '^(?:\d\d:\d\d:\d\d )?WAITING: (?:The connection to PCSX2 did not answer|La conexi.n con PCSX2 no respondi.|Waiting for PCSX2 to start the game\.|Esperando a que PCSX2 inicie el juego\.)'
# A start-up step's raw proof lines stay in its launch-<step>-<n>.out.log (play_launcher.STEP_RAW_LINE).
$Bt3StepRawLine = '^(?:[0-9a-f]{64}|\{"removed": .*\}|Session (?:emulator speed|savestate compression): .*)$'

function Read-Bt3LogLines {
    # The complete new lines of a growing UTF-8 log since $State.Offset; a line still being written waits.
    param([string]$Path, $State, [switch]$Final)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $stream = $null
    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read,
            ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
        $length = $stream.Length
        if ($length -le $State.Offset) { return }
        [void]$stream.Seek($State.Offset, [System.IO.SeekOrigin]::Begin)
        $count = [int]($length - $State.Offset)
        $buffer = New-Object byte[] $count
        $read = 0
        while ($read -lt $count) {
            $n = $stream.Read($buffer, $read, $count - $read)
            if ($n -le 0) { break }
            $read += $n
        }
        if ($read -le 0) { return }
        $end = $read
        if (-not $Final) { $end = [Array]::LastIndexOf($buffer, [byte]10, $read - 1) + 1 }
        if ($end -le 0) { return }
        $State.Offset = $State.Offset + $end
        $text = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $end)
        $lines = @($text -split "`r?`n")
        if ($lines.Count -and $lines[$lines.Count - 1] -eq '') { $lines = @($lines | Select-Object -First ($lines.Count - 1)) }
        foreach ($line in $lines) { $line }
    }
    catch { }
    finally { if ($stream) { $stream.Dispose() } }
}

function Write-Bt3LogLine {
    param([string]$Line, [switch]$Closing)
    if ($Line -cmatch $Bt3DenyLine) { return }
    if ($Closing -and $Line -cmatch $Bt3ClosingLine) { return }
    if ($Line -cmatch $Bt3ErrorLine) { Write-Host $Line -ForegroundColor Red }
    elseif ($Line -cmatch $Bt3WarningLine) { Write-Host $Line -ForegroundColor Yellow }
    else { Write-Host $Line }
}

function Read-Bt3LastError {
    # status.json's sticky last_error (autopilot), or $null.
    param([string]$StatusPath)
    try {
        if (Test-Path -LiteralPath $StatusPath -PathType Leaf) {
            $status = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($status.PSObject.Properties['last_error'] -and $status.last_error) { return $status.last_error }
        }
    }
    catch { }
    return $null
}

function Get-Bt3Field {
    param($Object, [string]$Name)
    if ($null -ne $Object -and $Object.PSObject.Properties[$Name] -and $null -ne $Object.$Name) { return [string]$Object.$Name }
    return ''
}

# ---- Who blocks a launch ------------------------------------------------------------------------------
function Get-Bt3PortOwner {
    # The process listening on the PINE port, or $null (Get-NetTCPConnection, else netstat).
    param([int]$Port)
    try {
        $connection = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
        if ($connection.Count) { return [int]$connection[0].OwningProcess }
    }
    catch { }
    try {
        foreach ($line in @(& netstat.exe -ano -p TCP 2>$null)) {
            # The state column is translated (LISTENING, ESCUCHANDO ...): a listener is the row whose remote port is 0.
            if ([string]$line -match ('^\s*TCP\s+\S+:' + $Port + '\s+\S+:0\s+\S+\s+(\d+)\s*$')) { return [int]$Matches[1] }
        }
    }
    catch { }
    return $null
}

function Get-Bt3Blockers {
    # Running PCSX2 processes and the PINE port's listener: name, PID, path (can be unreadable), and
    # whether it is this installation's own emulator without a window (a stuck leftover).
    param([string]$EmulatorPath, [int]$Port)
    $found = New-Object System.Collections.Generic.List[object]
    $wanted = ''
    try { $wanted = [System.IO.Path]::GetFullPath($EmulatorPath) } catch { }
    foreach ($process in @(Get-Process -Name 'pcsx2*' -ErrorAction SilentlyContinue)) {
        $path = $null
        try { $path = $process.Path } catch { }
        $own = $false
        try { $own = [bool]($path -and $wanted -and [string]::Equals([System.IO.Path]::GetFullPath($path), $wanted, [System.StringComparison]::OrdinalIgnoreCase)) } catch { }
        $windowless = $false
        try { $windowless = ($process.MainWindowHandle -eq [IntPtr]::Zero) } catch { }
        $found.Add([pscustomobject]@{ Name = $process.ProcessName; Id = $process.Id; Path = $path; Own = $own; Windowless = $windowless; Pcsx2 = $true })
    }
    $listening = $false
    try { $listening = [bool](@([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq $Port }).Count) } catch { }
    if ($listening) {
        $owner = Get-Bt3PortOwner -Port $Port
        if (-not ($found | Where-Object { $_.Id -eq $owner })) {
            $name = 'unknown program'; $path = $null
            if ($owner) {
                try { $other = Get-Process -Id $owner -ErrorAction Stop; $name = $other.ProcessName; try { $path = $other.Path } catch { } } catch { }
            }
            $found.Add([pscustomobject]@{ Name = $name; Id = $owner; Path = $path; Own = $false; Windowless = $false; Pcsx2 = $false })
        }
    }
    $found.ToArray()
}

function Format-Bt3Blocker {
    param($Blocker, [int]$Port)
    $text = [string]$Blocker.Name
    if ($Blocker.Id) { $text += ' (process ' + $Blocker.Id + ')' }
    if (-not $Blocker.Pcsx2) { $text += ' listening on port ' + $Port }
    if ($Blocker.Path) { $text += ': ' + $Blocker.Path }
    elseif ($Blocker.Id) { $text += ': path not readable (another user or administrator)' }
    return $text
}

function Resolve-Bt3Blockers {
    # Wait up to 10 s for this installation's PCSX2 to finish closing, and offer to end a stuck leftover
    # of it (no window) in an interactive console. Returns what still blocks the launch.
    param([string]$EmulatorPath, [int]$Port, [string]$Language = 'en', [int]$WaitSeconds = 10)
    $blockers = @(Get-Bt3Blockers -EmulatorPath $EmulatorPath -Port $Port)
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ($blockers.Count -and @($blockers | Where-Object { -not $_.Own }).Count -eq 0 -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
        $blockers = @(Get-Bt3Blockers -EmulatorPath $EmulatorPath -Port $Port)
    }
    $stuck = @($blockers | Where-Object { $_.Own -and $_.Windowless })
    if ($stuck.Count -and $stuck.Count -eq $blockers.Count) {
        foreach ($blocker in $stuck) { Write-Host (Format-Bt3Blocker $blocker $Port) -ForegroundColor Yellow }
        Write-Host (Get-Bt3Text 'hung.why' $Language) -ForegroundColor Yellow
        if (Read-Bt3YesNo (Get-Bt3Text 'hung.prompt' $Language)) {
            foreach ($blocker in $stuck) {
                try { Stop-Process -Id $blocker.Id -Force -ErrorAction Stop; Wait-Process -Id $blocker.Id -Timeout 10 -ErrorAction SilentlyContinue } catch { }
            }
            Start-Sleep -Milliseconds 500
            $blockers = @(Get-Bt3Blockers -EmulatorPath $EmulatorPath -Port $Port)
        }
    }
    $blockers
}
