"""TTM-NET-xx: every refusal and failure of the online kit, in plain English and Spanish, with what to do.

A message is shown as a block (the same shape as the mod's TTM-PLAY blocks), in the lobby's error dialog and in the
console:

    ==============================================================================
    [TTM-NET-06] THE TWO GAME DISCS ARE DIFFERENT
    ------------------------------------------------------------------------------
    WHAT HAPPENED: ...
    HOW TO FIX: ...
    DETAILS: ...
    ==============================================================================

Codes 01-19 are about the two PCs disagreeing or the network; 20-39 are about this PC's own setup or the match.
HOW TO FIX names the lobby's fields ("Start > Game ISO", "Advanced > Port"); command-line flags are only in the
README. REMEDIES lists the dialog's buttons for a code (kit_lobby_ui draws them).
"""
import textwrap

WIDTH = 78
CODES = {
    'TTM-NET-01': ('THE TWO PCS HAVE DIFFERENT ONLINE VERSIONS',
                   'The other PC runs a different version of online play (protocol {theirs}; this PC: {mine}).',
                   'Both players: update Tag Team Mod with the same updater (or installer) download, then close '
                   'and reopen Play online. Everyone in a room needs the same Tag Team Mod version.'),
    'TTM-NET-02': ('THE ONLINE FILES ARE DIFFERENT',
                   'The online files of the two PCs are not identical (this PC {mine}, the other PC {theirs}): the '
                   'two installations are different Tag Team Mod versions, or a file in the online\\netplay folder '
                   'of one of them was changed, added or removed.',
                   'Both players: update Tag Team Mod with the same updater (or installer) download, then close '
                   'and reopen Play online. Do not edit the files in the online folder.'),
    'TTM-NET-03': ('THE TWO PCSX2 BUILDS CANNOT PLAY TOGETHER',
                   'The PCSX2 builds of the two PCs are not a tested pair (this PC {mine}, the other PC {theirs}). '
                   'Online play keeps every game identical only with the same PCSX2 on every PC, or with two '
                   'builds that were tested together: PCSX2 2.8.2 (Windows, or the official x64 AppImage on '
                   'Linux) and 2.8.0.',
                   'Use PCSX2 2.8.2 on every PC: download it from pcsx2.net, run the Tag Team Mod installer again '
                   'with it on the PC that has another build, and reopen Play online. If a PC already uses 2.8.2, '
                   'a file in its PCSX2 folder was replaced or added (a DLL, GameIndex.yaml or patches.zip): '
                   'reinstall there too.'),
    'TTM-NET-04': ('THE GAME PATCHES ARE DIFFERENT',
                   'The Tag Team Mod patch file (pnach) differs between the two PCs (this PC {mine}, the other PC '
                   '{theirs}) and one of them cannot take the host\'s.',
                   'Both players: update Tag Team Mod with the same updater (or installer) download, then close '
                   'and reopen Play online. If it continues, keep the newest online\\runs folder of both PCs for '
                   'the mod author.'),
    'TTM-NET-05': ('THE EMULATION SETTINGS ARE DIFFERENT',
                   'Settings that change how the game runs differ between the two PCs: {keys}.',
                   'Online play writes the same emulation settings on every PC at every start, from its own '
                   'files. Both players: update (or reinstall) Tag Team Mod with the same download and reopen Play '
                   'online. Graphics, sound, frame limiter and controller settings may differ; they are not '
                   'compared.'),
    'TTM-NET-06': ('THE TWO GAME DISCS ARE DIFFERENT',
                   'The game ISOs of the two players do not match: {what}.',
                   'All players need identical supported disc contents. Select the matching installed disc in '
                   'Mod settings > Game disc, then close and reopen Play online.'),
    'TTM-NET-07': ('THE TWO BIOS FILES ARE DIFFERENT',
                   'The two PCs use different PlayStation 2 BIOS files ({what}).',
                   'Different BIOS files (USA, Europe and Japan dumps, v1.00 to v2.20) were tested to keep both '
                   'games identical, so by default the kit only notes this. If you ever see a DESYNC, choose the '
                   'same BIOS on both PCs in Start > BIOS.'),
    'TTM-NET-08': ('THE MATCH FILE DID NOT ARRIVE INTACT',
                   'The match savestate the host sent does not have the expected SHA-256 ({what}).',
                   'Press Retry. If it happens every time, the connection damages data: try a VPN such as '
                   'Tailscale, ZeroTier or Radmin VPN (see the README).'),
    'TTM-NET-09': ('THE OTHER PC STOPPED ANSWERING',
                   'Waited {seconds} s for the other PC during "{step}" and nothing came.',
                   'Check that the other player\'s kit is still open and did not show an error, then press Retry.'),
    'TTM-NET-10': ('CANNOT REACH THE HOST',
                   'Could not connect to {address} ({error}).',
                   'Check that the host pressed "Open a room" first and is waiting, that the address and Advanced > '
                   'Port ({port}) are right, and that the host opened (forwarded) TCP and UDP port {port} on its '
                   'router and allowed Python in Windows Firewall. If nobody can open a port, use a VPN such as '
                   'Tailscale, ZeroTier or Radmin VPN.'),
    'TTM-NET-11': ('GAME DATA (UDP) DOES NOT GET THROUGH',
                   'The two kits can talk over TCP, but no UDP datagram came back from {address} in {seconds} s.',
                   'Forward UDP port {port} as well as TCP on the host\'s router, and allow Python in Windows '
                   'Firewall for private networks on both PCs. A VPN (Tailscale, ZeroTier, Radmin VPN) avoids '
                   'this.'),
    'TTM-NET-12': ('THE TWO GAMES WENT OUT OF SYNC',
                   'The state check of frame {frame} differs between the two PCs (DESYNC).',
                   'Nothing to do: the kit re-synchronizes both games from the host\'s game by itself (a short '
                   'pause). If that fails three times, the fight ends as No contest. Please keep the folder {logs} '
                   'on both PCs and send it to the mod author: it shows what differed.'),
    'TTM-NET-13': ('THE CONNECTION TO THE OTHER PC ENDED',
                   'The other PC ended the session, or the connection to it was lost ({why}).',
                   'You are back in the lobby (or on the Start screen). Press Retry to join the same room again, or '
                   'host or join another one.'),
    'TTM-NET-14': ('THE PORT IS ALREADY IN USE',
                   'This PC cannot listen on {what} port {port}: another program (or another copy of the kit) '
                   'uses it.',
                   'Close the other program or the other kit window, or choose another port in Advanced > Port on '
                   'both PCs (and forward that one).'),
    'TTM-NET-15': ('THE ROOM IS FULL',
                   'The host\'s room already holds 16 people.',
                   'Wait until somebody leaves the room, then press Retry.'),
    'TTM-NET-16': ('THE RELAY REFUSED THE CONNECTION',
                   'The relay at {address} answered: {why}.',
                   'Both players must use the same relay address and the same room name in Advanced > Relay, one '
                   'hosting and one joining. If the room is taken, pick another room name.'),
    'TTM-NET-17': ('THE MATCH SETTINGS DO NOT FIT TOGETHER',
                   '{what}',
                   'Change the setting named above and try again.'),
    'TTM-NET-18': ('THE GAMES COULD NOT BE RE-SYNCHRONIZED',
                   'The two games went out of sync again after {count} re-synchronizations in this fight ({why}). '
                   'The fight ends as No contest.',
                   'Choose Retry or Return to lobby to play on. If it keeps happening, please send the runs folder of '
                   'both PCs to the mod author.'),
    'TTM-NET-19': ('THE CONNECTION WAS LOST',
                   'The connection to the host was lost, and joining the room again did not work for {seconds} s.',
                   'Check this PC\'s network and ask the host whether its room is still open, then press Retry (or '
                   'join again from the Start screen). Coming back within a few minutes gives you your name and '
                   'fighter back.'),
    'TTM-NET-20': ('THE GAME ISO CANNOT BE USED',
                   '{what}',
                   'Select a reviewed BT3 USA/Europe/Japan or BT4 B14 REV2 disc in Mod settings > Game disc, then reopen Play online.'),
    'TTM-NET-21': ('THE PS2 BIOS CANNOT BE USED',
                   '{what}',
                   'Choose your own PlayStation 2 BIOS file in Start > BIOS.'),
    'TTM-NET-22': ('PCSX2 DID NOT START THE MATCH',
                   '{what}',
                   'Close every PCSX2 window that the kit started and press Retry. The log of this run is in '
                   '{logs}.'),
    'TTM-NET-23': ('THE MATCH CANNOT BE PREPARED',
                   '{what}',
                   '{fix}'),
    'TTM-NET-24': ('THE TAG TEAM MOD INSTALLATION CANNOT BE USED',
                   '{what}',
                   'Use a complete installation of the same Tag Team Mod release on every PC. Reinstall if the installation check fails.'),
    'TTM-NET-25': ('AN ONLINE FILE IS MISSING OR DAMAGED',
                   '{what}',
                   'Close Play online, run the Tag Team Mod updater (or installer) again on this PC so its files '
                   'are complete, then reopen Play online.'),
    # Shown by Play online.cmd / relay.cmd themselves (no Python to run this module); listed here for the README.
    'TTM-NET-26': ('PYTHON 3.9 OR NEWER IS NEEDED',
                   'No Python 3.9 or newer was found on this PC.',
                   'Install Python 3 from python.org (tick "Add python.exe to PATH"), or start the kit once from a '
                   'Tag Team Mod folder\'s own Python (see the README). The kit uses only Python\'s standard '
                   'library.'),
    'TTM-NET-27': ('THE ONLINE PCSX2 HAS EXTRA PATCHES OR PER-GAME SETTINGS',
                   '{what}',
                   'Remove the files named above (online play installs the only patch it needs by itself, and '
                   'per-game settings would override the settings every PC must share), then reopen Play online.'),
    'TTM-NET-28': ('THIS PCSX2 BUILD WAS NOT TESTED FOR ONLINE PLAY',
                   'This PC would run {build}. Online play only uses PCSX2 builds that were tested to keep two PCs '
                   'identical: {tested}.',
                   'Download PCSX2 2.8.2 from pcsx2.net (Windows: the x64 Qt build; Linux: the official x64 '
                   'AppImage), run the Tag Team Mod installer again with it, and reopen Play online.'),
    'TTM-NET-29': ('THAT CHOICE CANNOT BE PLAYED',
                   '{what}',
                   'Choose another fighter, colour or setting. Your last valid team was kept.'),
    'TTM-NET-30': ('THE HOST COULD NOT PREPARE THE MATCH',
                   '{what}',
                   'The host presses START MATCH again: its game prepares the match once more (it restarts first '
                   'when it failed). If the same fighters fail again, change one of them. When the host\'s Tag Team '
                   'Mod installation was refused (TTM-NET-24), the host updates or reinstalls Tag Team Mod and '
                   'reopens Play online.'),
    'TTM-NET-31': ('THE PREPARED MATCH DOES NOT MATCH THE LOBBY',
                   '{what}',
                   'Press Ready again: the host prepares the match once more. If it happens every time, send the '
                   'runs folder of both PCs to the mod author.'),
    'TTM-NET-32': ('A FIGHTER UPDATE FAILED ONLINE',
                   '{what}',
                   'The fight goes on without that feature. Please send the runs folder of both PCs to the mod '
                   'author.'),
    'TTM-NET-33': ('THE FIGHTER LIST COULD NOT BE READ FROM YOUR ISO',
                   '{what}',
                   'Select a reviewed BT3 USA/Europe/Japan or BT4 B14 REV2 disc in Mod settings > Game disc, then reopen Play online.'),
    'TTM-NET-34': ('THE TWO PCS HAVE DIFFERENT TAG TEAM MOD VERSIONS',
                   'This PC has Tag Team Mod {mine}, the other PC has {theirs}. Everyone in an online room needs '
                   'the same version.',
                   'The player with the older version runs the newest Tag Team Mod updater (saves and settings are '
                   'kept), then both close and reopen Play online.'),
}

CODES_ES = {
    'TTM-NET-01': ('LOS DOS PC TIENEN VERSIONES EN LÍNEA DISTINTAS',
                   'El otro PC usa otra versión del juego en línea (protocolo {theirs}; este PC: {mine}).',
                   'Los dos jugadores: actualizad Tag Team Mod con la misma descarga del actualizador (o '
                   'instalador) y volved a abrir Play online. Todos en una sala necesitan la misma versión de Tag '
                   'Team Mod.'),
    'TTM-NET-02': ('LOS ARCHIVOS EN LÍNEA SON DISTINTOS',
                   'Los archivos en línea de los dos PC no son idénticos (este PC {mine}, el otro PC {theirs}): las '
                   'dos instalaciones son versiones distintas de Tag Team Mod, o se cambió, añadió o borró un '
                   'archivo de la carpeta online\\netplay de una de ellas.',
                   'Los dos jugadores: actualizad Tag Team Mod con la misma descarga del actualizador (o '
                   'instalador) y volved a abrir Play online. No editéis los archivos de la carpeta online.'),
    'TTM-NET-03': ('LAS DOS VERSIONES DE PCSX2 NO PUEDEN JUGAR JUNTAS',
                   'Las versiones de PCSX2 de los dos PC no son una pareja probada (este PC {mine}, el otro PC '
                   '{theirs}). El juego en línea solo mantiene todas las partidas idénticas con el mismo PCSX2 en '
                   'todos los PC, o con dos versiones probadas juntas: PCSX2 2.8.2 (Windows, o la AppImage oficial '
                   'x64 en Linux) y 2.8.0.',
                   'Usad PCSX2 2.8.2 en todos los PC: descárgalo de pcsx2.net, ejecuta otra vez el instalador de '
                   'Tag Team Mod con él en el PC que tiene otra versión y vuelve a abrir Play online. Si un PC ya '
                   'usa 2.8.2, se cambió o añadió un archivo en su carpeta de PCSX2 (una DLL, GameIndex.yaml o '
                   'patches.zip): reinstala también ahí.'),
    'TTM-NET-04': ('LOS PARCHES DEL JUEGO SON DISTINTOS',
                   'El archivo de parches de Tag Team Mod (pnach) es distinto en los dos PC (este PC {mine}, el '
                   'otro PC {theirs}) y uno de ellos no puede recibir el del anfitrión.',
                   'Los dos jugadores: actualizad Tag Team Mod con la misma descarga del actualizador (o '
                   'instalador) y volved a abrir Play online. Si continúa, guardad la carpeta online\\runs más '
                   'reciente de los dos PC para el autor del mod.'),
    'TTM-NET-05': ('LOS AJUSTES DE EMULACIÓN SON DISTINTOS',
                   'Hay ajustes que cambian cómo funciona el juego y son distintos en los dos PC: {keys}.',
                   'El juego en línea escribe los mismos ajustes de emulación en todos los PC cada vez que empieza, '
                   'desde sus propios archivos. Los dos jugadores: actualizad (o reinstalad) Tag Team Mod con la '
                   'misma descarga y volved a abrir Play online. Los gráficos, el sonido, el limitador de '
                   'fotogramas y los mandos pueden ser distintos; no se comparan.'),
    'TTM-NET-06': ('LOS DOS DISCOS DEL JUEGO SON DISTINTOS',
                   'Las ISO de los dos jugadores no coinciden: {what}.',
                   'Todos los jugadores necesitan discos compatibles idénticos. Elige el mismo disco instalado en '
                   'Mod settings > Disco del juego y vuelve a abrir Play online.'),
    'TTM-NET-07': ('LOS DOS ARCHIVOS DE BIOS SON DISTINTOS',
                   'Los dos PC usan archivos de BIOS de PlayStation 2 distintos ({what}).',
                   'Se probó que BIOS distintas (volcados de EE. UU., Europa y Japón, v1.00 a v2.20) mantienen las '
                   'dos partidas idénticas, así que el kit solo lo anota. Si alguna vez ves una DESINCRONIZACIÓN, '
                   'elige la misma BIOS en los dos PC en Inicio > BIOS.'),
    'TTM-NET-08': ('EL ARCHIVO DEL COMBATE NO LLEGÓ INTACTO',
                   'El estado guardado que envió el anfitrión no tiene el SHA-256 esperado ({what}).',
                   'Pulsa Reintentar. Si pasa siempre, la conexión daña los datos: prueba una VPN como '
                   'Tailscale, ZeroTier o Radmin VPN (mira el LEAME).'),
    'TTM-NET-09': ('EL OTRO PC DEJÓ DE RESPONDER',
                   'Se esperó {seconds} s al otro PC durante "{step}" y no llegó nada.',
                   'Comprueba que el kit del otro jugador sigue abierto y no muestra un error, y pulsa Reintentar.'),
    'TTM-NET-10': ('NO SE PUEDE CONECTAR CON EL ANFITRIÓN',
                   'No se pudo conectar con {address} ({error}).',
                   'Comprueba que el anfitrión pulsó primero "Abrir una sala" y está esperando, que la dirección y '
                   'Avanzado > Puerto ({port}) son correctos, y que el anfitrión abrió (redirigió) los puertos TCP y '
                   'UDP {port} en su router y permitió Python en el Firewall de Windows. Si nadie puede abrir un '
                   'puerto, usa una VPN como Tailscale, ZeroTier o Radmin VPN.'),
    'TTM-NET-11': ('LOS DATOS DEL JUEGO (UDP) NO PASAN',
                   'Los dos kits hablan por TCP, pero no volvió ningún datagrama UDP de {address} en {seconds} s.',
                   'Redirige también el puerto UDP {port} en el router del anfitrión y permite Python en el Firewall '
                   'de Windows para redes privadas en los dos PC. Una VPN (Tailscale, ZeroTier, Radmin VPN) lo '
                   'evita.'),
    'TTM-NET-12': ('LAS DOS PARTIDAS SE DESINCRONIZARON',
                   'La comprobación del fotograma {frame} es distinta en los dos PC (DESINCRONIZACIÓN).',
                   'No hay que hacer nada: el kit vuelve a sincronizar las dos partidas desde la del anfitrión (una '
                   'pausa corta). Si falla tres veces, el combate termina sin resultado. Guarda la carpeta {logs} '
                   'de los dos PC y envíala al autor del mod: muestra qué cambió.'),
    'TTM-NET-13': ('LA CONEXIÓN CON EL OTRO PC TERMINÓ',
                   'El otro PC terminó la sesión, o se perdió la conexión con él ({why}).',
                   'Has vuelto a la sala (o a la pantalla de inicio). Pulsa Reintentar para entrar otra vez en la '
                   'misma sala, o crea o únete a otra.'),
    'TTM-NET-14': ('EL PUERTO YA ESTÁ EN USO',
                   'Este PC no puede escuchar en el puerto {what} {port}: otro programa (u otra copia del kit) lo '
                   'usa.',
                   'Cierra el otro programa o la otra ventana del kit, o elige otro puerto en Avanzado > Puerto en '
                   'los dos PC (y redirige ese).'),
    'TTM-NET-15': ('LA SALA ESTÁ LLENA',
                   'La sala del anfitrión ya tiene 16 personas.',
                   'Espera a que alguien salga de la sala y pulsa Reintentar.'),
    'TTM-NET-16': ('EL RELAY RECHAZÓ LA CONEXIÓN',
                   'El relay en {address} respondió: {why}.',
                   'Los dos jugadores deben usar la misma dirección de relay y el mismo nombre de sala en Avanzado > '
                   'Relay, uno creando y otro uniéndose. Si la sala está ocupada, elige otro nombre.'),
    'TTM-NET-17': ('LOS AJUSTES DEL COMBATE NO ENCAJAN',
                   '{what}',
                   'Cambia el ajuste indicado y vuelve a intentarlo.'),
    'TTM-NET-18': ('NO SE PUDO VOLVER A SINCRONIZAR LAS PARTIDAS',
                   'Las dos partidas se desincronizaron otra vez tras {count} resincronizaciones en este combate '
                   '({why}). El combate termina sin resultado.',
                   'Elige Repetir o Volver a la sala para seguir jugando. Si se repite, envía la carpeta runs de los '
                   'dos PC al autor del mod.'),
    'TTM-NET-19': ('SE PERDIÓ LA CONEXIÓN',
                   'Se perdió la conexión con el anfitrión y no se pudo volver a entrar en la sala en {seconds} s.',
                   'Comprueba la red de este PC y pregunta al anfitrión si su sala sigue abierta; después pulsa '
                   'Reintentar (o entra otra vez desde la pantalla de inicio). Si vuelves en pocos minutos '
                   'recuperas tu nombre y tu luchador.'),
    'TTM-NET-20': ('NO SE PUEDE USAR LA ISO DEL JUEGO',
                   '{what}',
                   'Elige un disco revisado de BT3 USA/Europa/Japón o BT4 B14 REV2 en Mod settings > Disco del juego y vuelve a abrir Play online.'),
    'TTM-NET-21': ('NO SE PUEDE USAR LA BIOS DE PS2',
                   '{what}',
                   'Elige tu propio archivo de BIOS de PlayStation 2 en Inicio > BIOS.'),
    'TTM-NET-22': ('PCSX2 NO EMPEZÓ EL COMBATE',
                   '{what}',
                   'Cierra todas las ventanas de PCSX2 que abrió el kit y pulsa Reintentar. El registro de esta '
                   'sesión está en {logs}.'),
    'TTM-NET-23': ('NO SE PUEDE PREPARAR EL COMBATE',
                   '{what}',
                   '{fix}'),
    'TTM-NET-24': ('NO SE PUEDE USAR LA INSTALACIÓN DE TAG TEAM MOD',
                   '{what}',
                   'Usa la misma versión completa de Tag Team Mod en todos los PC. Reinstala si falla la comprobación de instalación.'),
    'TTM-NET-25': ('FALTA UN ARCHIVO EN LÍNEA O ESTÁ DAÑADO',
                   '{what}',
                   'Cierra Play online, ejecuta otra vez el actualizador (o instalador) de Tag Team Mod en este PC '
                   'para que sus archivos estén completos y vuelve a abrir Play online.'),
    'TTM-NET-26': ('SE NECESITA PYTHON 3.9 O MÁS NUEVO',
                   'No se encontró Python 3.9 o más nuevo en este PC.',
                   'Instala Python 3 desde python.org (marca "Add python.exe to PATH"), o inicia el kit una vez con '
                   'el Python propio de una carpeta de Tag Team Mod (mira el LEAME). El kit solo usa la biblioteca '
                   'estándar de Python.'),
    'TTM-NET-27': ('EL PCSX2 EN LÍNEA TIENE PARCHES O AJUSTES POR JUEGO DE MÁS',
                   '{what}',
                   'Quita los archivos indicados (el juego en línea instala él mismo el único parche que necesita, '
                   'y los ajustes por juego cambiarían los ajustes que todos los PC deben compartir) y vuelve a '
                   'abrir Play online.'),
    'TTM-NET-28': ('ESTA VERSIÓN DE PCSX2 NO SE PROBÓ PARA JUGAR EN LÍNEA',
                   'Este PC usaría {build}. El juego en línea solo usa versiones de PCSX2 probadas para mantener '
                   'dos PC idénticos: {tested}.',
                   'Descarga PCSX2 2.8.2 de pcsx2.net (Windows: la versión x64 Qt; Linux: la AppImage oficial '
                   'x64), ejecuta otra vez el instalador de Tag Team Mod con él y vuelve a abrir Play online.'),
    'TTM-NET-29': ('ESA ELECCIÓN NO SE PUEDE JUGAR',
                   '{what}',
                   'Elige otro luchador, color o ajuste. Se conservó tu último equipo válido.'),
    'TTM-NET-30': ('EL ANFITRIÓN NO PUDO PREPARAR EL COMBATE',
                   '{what}',
                   'El anfitrión pulsa EMPEZAR COMBATE otra vez: su juego prepara el combate de nuevo (antes se '
                   'reinicia si falló). Si los mismos luchadores vuelven a fallar, cambia uno. Si se rechazó la '
                   'instalación de Tag Team Mod del anfitrión (TTM-NET-24), el anfitrión actualiza o reinstala Tag '
                   'Team Mod y vuelve a abrir Play online.'),
    'TTM-NET-31': ('EL COMBATE PREPARADO NO COINCIDE CON LA SALA',
                   '{what}',
                   'Pulsa Listo otra vez: el anfitrión prepara el combate de nuevo. Si pasa siempre, envía la '
                   'carpeta runs de los dos PC al autor del mod.'),
    'TTM-NET-32': ('FALLÓ UNA ACTUALIZACIÓN DE LUCHADOR EN LÍNEA',
                   '{what}',
                   'El combate sigue sin esa función. Envía la carpeta runs de los dos PC al autor del mod.'),
    'TTM-NET-33': ('NO SE PUDO LEER LA LISTA DE LUCHADORES DE TU ISO',
                   '{what}',
                   'Elige un disco revisado de BT3 USA/Europa/Japón o BT4 B14 REV2 en Mod settings > Disco del juego y vuelve a abrir Play online.'),
    'TTM-NET-34': ('LOS DOS PC TIENEN VERSIONES DISTINTAS DE TAG TEAM MOD',
                   'Este PC tiene Tag Team Mod {mine} y el otro PC tiene {theirs}. Todos en una sala en línea '
                   'necesitan la misma versión.',
                   'El jugador con la versión más antigua ejecuta el actualizador más reciente de Tag Team Mod (se '
                   'conservan las partidas guardadas y los ajustes) y después los dos cierran y vuelven a abrir '
                   'Play online.'),
}

# Dialog buttons per code (kit_lobby_ui): retry, advanced, choose_iso, choose_bios, compare_files, logs.
REMEDIES = {
    'TTM-NET-06': ('choose_iso', 'compare_files', 'logs'), 'TTM-NET-07': ('choose_bios', 'retry'),
    'TTM-NET-08': ('retry', 'advanced'), 'TTM-NET-09': ('retry', 'logs'), 'TTM-NET-10': ('retry', 'advanced'),
    'TTM-NET-11': ('retry', 'advanced'), 'TTM-NET-12': ('logs',), 'TTM-NET-13': ('retry',),
    'TTM-NET-14': ('advanced', 'retry'),
    'TTM-NET-15': ('retry',), 'TTM-NET-16': ('advanced', 'retry'), 'TTM-NET-18': ('logs',),
    'TTM-NET-19': ('retry', 'logs'), 'TTM-NET-20': ('choose_iso',), 'TTM-NET-21': ('choose_bios',),
    'TTM-NET-22': ('retry', 'logs'), 'TTM-NET-24': ('logs',), 'TTM-NET-27': ('logs',), 'TTM-NET-28': ('logs',),
    'TTM-NET-31': ('retry', 'logs'), 'TTM-NET-32': ('logs',), 'TTM-NET-33': ('choose_iso',),
}
LABELS = {'en': ('WHAT HAPPENED', 'HOW TO FIX', 'DETAILS', 'WARNING'),
          'es': ('QUÉ PASÓ', 'CÓMO ARREGLARLO', 'DETALLES', 'AVISO')}
assert set(CODES) == set(CODES_ES)


class KitError(Exception):
    """A refusal or failure with its TTM-NET code; str() is the whole English block, block('es') the Spanish one."""

    def __init__(self, code, details=None, **values):
        self.code, self.values, self.details = code, values, details
        super().__init__(block(code, details=details, **values))

    def block(self, lang='en'):
        return block(self.code, details=self.details, lang=lang, **self.values)

    def payload(self):
        """What travels to the UI or the other PC: both languages, so each side shows its own."""
        return dict(code=self.code, en=self.block('en'), es=self.block('es'), remedies=list(REMEDIES.get(self.code, ())),
                    title_en=texts(self.code)[0], title_es=texts(self.code, lang='es')[0])


class _Missing(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def texts(code, lang='en', **values):
    """(title, what happened, how to fix) of a code; a value 'what_es' / 'fix_es' replaces 'what' / 'fix' in Spanish."""
    title, what, fix = (CODES_ES if lang == 'es' else CODES)[code]
    if lang != 'es':
        values = {k: v for k, v in values.items() if not k.endswith('_es')}
    else:
        values = dict(values, **{k[:-3]: v for k, v in values.items() if k.endswith('_es')})
    fill = _Missing({k: v for k, v in values.items()})
    return title, what.format_map(fill), fix.format_map(fill)


def block(code, details=None, warning=False, lang='en', **values):
    title, what, fix = texts(code, lang, **values)
    l_what, l_fix, l_details, l_warning = LABELS['es' if lang == 'es' else 'en']
    lines = ['=' * WIDTH, f'[{code}] {l_warning + ": " if warning else ""}{title}', '-' * WIDTH]
    lines += textwrap.wrap(f'{l_what}: ' + what, WIDTH, subsequent_indent='  ')
    lines += textwrap.wrap(f'{l_fix}: ' + fix, WIDTH, subsequent_indent='  ')
    for item in ([details] if isinstance(details, str) else (details or [])):
        lines += textwrap.wrap(f'{l_details}: ' + str(item), WIDTH, subsequent_indent='  ')
    lines.append('=' * WIDTH)
    return '\n'.join(lines)


def payload(code, **values):
    return KitError(code, **values).payload()
