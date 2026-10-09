"""Mod-authored text only. Stable settings keys, ISO names and code stay untouched.

Host presentation reads the saved choice at most twice a second. Builders and
tests can use ``using`` to freeze the language for a whole generated artifact.
Guest text uses the existing ASCII atlas; host-rendered menus keep accents.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import time
import unicodedata

LANGUAGES = ('en', 'es')
WINDOWS = os.name == 'nt'
# The launchers each kind of installation really has (entry()). No other
# player-reachable text names one: messages use tr(template, play=entry('play')).
# '' means that kind has no such launcher; callers then use a variant without it.
ENTRY_NAMES = ('play', 'mod_settings', 'check_installation', 'scan_compatibility', 'build_expanded_maps',
               'pcsx2_settings')
ENTRIES = {
    'windows-player': ('Play.cmd', 'Mod settings.cmd', 'Check installation.cmd', 'Scan compatibility.cmd',
                       'Build expanded maps.cmd', ''),
    'linux-player': ('Play.sh', 'Mod settings.sh', 'Check installation.sh', 'Scan compatibility.sh',
                     'Build expanded maps.sh', 'PCSX2 settings.sh'),
    'dev-bt3': ('Play.cmd', 'Mod settings.cmd', '', '', '', ''),
    'dev-bt4': ('Play.cmd', 'Mod settings.cmd', '', '', '', ''),
    'dev-linux': ('Play.sh', 'Mod settings.sh', '', '', '', ''),
}
# Translate from stable English keys first, then show the actual installed
# launcher names. Windows text/pixels remain identical; formatted user paths
# are inserted afterward and must never have their extensions rewritten.
LINUX_SCRIPT_NAMES = {source: target for windows, linux in (('dev-bt3', 'dev-linux'), ('windows-player', 'linux-player'))
                      for source, target in zip(ENTRIES[windows], ENTRIES[linux]) if source and target}
NAMES = {'en': 'English', 'es': 'Español'}
SETTINGS = Path(__file__).resolve().parents[1] / 'mod-settings.json'
_override = ContextVar('mod_language', default=None)
_cached = ('en', 0.0)
_battle_language = None


def pin_battle(settings):
    """Generated match code keeps its language until the next preparation.

    Editing desktop preferences mid-match must not change the byte sequences
    that runtime ownership guards expect from already-installed guest programs.
    Host menus remain free to preview the newly selected language.
    """
    global _battle_language
    _battle_language = language(settings)


def language(settings=None):
    if settings is not None:
        value = settings.get('language', 'en') if isinstance(settings, dict) else settings
        return value if value in LANGUAGES else 'en'
    if _override.get() is not None:
        return _override.get()
    global _cached
    now = time.monotonic()
    if now >= _cached[1]:
        try:
            value = json.loads(SETTINGS.read_text(encoding='utf-8-sig')).get('language', 'en')
        except (OSError, ValueError, AttributeError):
            value = 'en'
        _cached = (value if value in LANGUAGES else 'en', now + .5)
    return _cached[0]


def invalidate():
    global _cached
    _cached = ('en', 0.0)


@contextmanager
def using(settings):
    token = _override.set(language(settings))
    try:
        yield
    finally:
        _override.reset(token)


ES = {
    'Session graphics: automatic hardware fixes; internal resolution = {multiplier}': 'Gráficos de la sesión: correcciones de hardware automáticas; resolución interna = {multiplier}',
    'Session graphics: existing hardware fix preferences; internal resolution = {multiplier}': 'Gráficos de la sesión: se mantienen las correcciones de hardware elegidas; resolución interna = {multiplier}',
    'Enable manual lock-off': 'Permitir quitar el objetivo manualmente',
    'Lock-off button': 'Botón para quitar el objetivo',
    'Target HUD while unlocked': 'Interfaz del objetivo sin fijar',
    'Lock-off hold time (seconds; 0 = tap)': 'Mantener para quitar el objetivo (segundos; 0 = pulsar)',
    'With the same button, lock-off hold time must be longer than target-switch hold time.': 'Con el mismo botón, quitar el objetivo debe requerir más tiempo que cambiarlo.',
    'Tap the switch button: next enemy in the set order; during an attack warning, your attacker (or automatically when hit, if set). Right stick, with the button held (not R3) or alone if set (locked on in combat; no camera then): left/right steps around you, up/down picks above/below. Hold the button to lock off; tap to relock. R3 transforms. Rebind in Mod settings.cmd. Applies next match; Fight Again keeps it.': 'Pulsa el botón de cambio: el siguiente según el orden; con aviso de ataque, tu atacante (o al recibir golpes, si lo eliges). Stick derecho, manteniendo el botón (no R3) o solo si lo eliges (fijado en combate; sin cámara): izquierda/derecha recorre, arriba/abajo, encima/debajo. Mantenlo para quitar el fijado; púlsalo para volver. R3 transforma. Reasigna en Mod settings.cmd. Se aplica al próximo combate y revancha.',
    'Target switch order': 'Orden al cambiar de objetivo',
    'Right stick picks a target': 'El stick derecho elige objetivo',
    'Picking with the right stick': 'Elegir con el stick derecho',
    'When your target is defeated': 'Cuando tu objetivo cae derrotado',
    'Mark your target': 'Marcar tu objetivo',
    'Target indicator': 'Indicador del objetivo',
    'Switch to your attacker': 'Cambiar a quien te ataca',
    'Enemies targeting you': 'Enemigos que te fijan',
    'Help when outnumbered': 'Ayuda en inferioridad numérica',
    'Who counts as outnumbered': 'Quién está en inferioridad',
    'Help applies to': 'La ayuda se aplica a',
    'Damage dealt: + per extra enemy (%)': 'Daño causado: + por enemigo de más (%)',
    'Damage taken: - per extra enemy (%)': 'Daño recibido: - por enemigo de más (%)',
    'Recovery and get-up speed (%; 100 = normal)': 'Velocidad al recuperarse y levantarse (%; 100 = normal)',
    'Protection after getting up (seconds; 0 = off)': 'Protección al levantarse (segundos; 0 = no)',
    'Break a combo after this many hits (0 = off)': 'Romper el combo tras estos golpes (0 = no)',
    'For a fighter on the smaller team or, if chosen, one targeted by two or more enemies. Damage follows the living team sizes: per extra enemy each of you faces, you deal more and take less (at most 300% dealt, at least 40% taken); equal teams and free-for-all keep normal damage. Recovery speed shortens knock-backs, get-ups and hit reactions. Protection: while you get up, ordinary hits neither stagger nor hurt you; Blast 2 attacks, rushes and throws still do. The combo breaker gives 1 s of it, at most every 5 s, never during a rush or throw. Balanced: +15%/-10%, 150%, 0.5 s, 12 hits. Strong: +40%/-30%, 200%, 1 s, 8 hits. Custom uses the rows below; the two rows about who is helped apply to every preset. The "Enemies targeting you" marks are on the HUD page. Applies from the next match; a Fight Again rematch keeps its settings.':
        'Para un luchador del equipo más pequeño o, si se elige, uno al que apuntan dos o más enemigos. El daño sigue el número de luchadores vivos: por cada enemigo de más que afronta cada uno, causas más y recibes menos (como mucho 300% causado, al menos 40% recibido); con equipos iguales o en Todos contra todos el daño es normal. La velocidad acorta los lanzamientos, las levantadas y las reacciones a golpes. Protección: al levantarte, los golpes normales no te aturden ni te dañan; los ataques Blast 2, los Rush y los agarres sí. Romper el combo da 1 s de protección, como mucho cada 5 s y nunca durante un Rush o un agarre. Equilibrada: +15%/-10%, 150%, 0,5 s, 12 golpes. Fuerte: +40%/-30%, 200%, 1 s, 8 golpes. Personalizada usa las filas de abajo; las dos filas sobre a quién se ayuda valen para todas. Las marcas de "Enemigos que te fijan" están en la página Interfaz. Se aplica al próximo combate; la revancha conserva sus ajustes.',
    'Team Battle': 'Por equipos', 'Free-for-all': 'Todos contra todos', 'Co-op': 'Cooperativo',
    'Modded Training': 'Entrenamiento mod', '1 Player': '1 jugador', '2 Players': '2 jugadores',
    'Modded Scenarios': 'Escenarios mod', 'MODDED SCENARIOS': 'ESCENARIOS MOD',
    'Play saved story battles.\nFighters are selected automatically.': 'Juega batallas de historia.\nLos luchadores se eligen solos.',
    'TEAM {team}': 'EQUIPO {team}', 'Reinforcement': 'Refuerzo',
    'Arena: {arena}': 'Escenario: {arena}',
    'Choose your arena after continuing.': 'Elige el escenario al continuar.',
    'Cross: play scenario    Triangle: back': 'Cruz: jugar    Triángulo: volver',
    'Unavailable scenario': 'Escenario no disponible', '{count} scenarios': '{count} escenarios',
    'No saved scenarios found.': 'No hay escenarios guardados.',
    'Up/Down: select   L1/R1: page   Cross: details': 'Arriba/Abajo: elegir   L1/R1: página   Cruz: detalles',
    'Triangle: return to Modded Modes': 'Triángulo: volver a los modos del mod',
    '3 Players': '3 jugadores', '4 Players': '4 jugadores', 'CPU Only': 'Solo CPU',
    'Mod Settings': 'Ajustes del mod', 'Back': 'Volver', 'Mod modes': 'Modos del mod',
    'Original game menu': 'Menú original',
    # Settings pages (mod_settings.GROUPS) and labels.
    'Menus': 'Menús', 'Controls': 'Controles',
    'Cinematics': 'Cinemáticas', 'Fusion': 'Fusión', 'Fighters': 'Luchadores', 'Giants': 'Gigantes',
    'HUD': 'Interfaz', 'Split-screen HUD': 'Interfaz dividida', 'Spectating': 'Espectador',
    'Revival': 'Reanimación', 'Training': 'Entrenamiento',
    'Outnumbered': 'Inferioridad numérica',
    'Beam struggles': 'Forcejeos de rayos',
    'Movement': 'Movimiento',
    'Launch options (restart)': 'Opciones de inicio (reiniciar)', 'Diagnostics': 'Diagnóstico',
    'Language / Idioma': 'Idioma / Language',
    'Mod mode menus': 'Menús de modos del mod',
    'Menu switch button': 'Botón para cambiar de menú',
    'Show the menu switch button hint': 'Mostrar el aviso del botón de menú',
    'Loading animation speed (%; 100 = normal)': 'Velocidad de la animación de carga (%; 100 = normal)',
    'Each player picks their own assigned fighters': 'Cada jugador elige a sus luchadores asignados',
    'Allow all controllers during character selection': 'Permitir todos los mandos al elegir personajes',
    'Show player numbers above selection slots': 'Mostrar el número de jugador en cada casilla',
    'Target / spectator switch button': 'Botón para cambiar de objetivo / luchador observado',
    'Target switch hold time (seconds; 0 = tap)': 'Tiempo de pulsación para cambiar de objetivo (s; 0 = toque)',
    'Special-move pause': 'Pausa en movimientos especiales',
    'Ultimate attacks: shared camera and pause': 'Definitivos: cámara compartida y pausa',
    'Transformations: camera and pause': 'Transformaciones: cámara y pausa',
    'Transformations in split screen': 'Transformaciones en pantalla dividida',
    'Rush attacks: shared camera and pause': 'Ataques Rush: cámara compartida y pausa',
    'Keep attacks and transformations at their current location': 'Mantener ataques y transformaciones en su posición actual',
    'Introductions for extra fighters': 'Presentación de los luchadores adicionales',
    'Two-player fusion controls': 'Controles de fusión entre dos jugadores',
    'Show "Fused - Player n has control" (swap mode)': 'Mostrar "Fusión - Jn controla" (modo alterno)',
    'Show "Pn takes control in" countdown (swap mode)': 'Mostrar la cuenta "Jn controla en" (modo alterno)',
    'Timed fusion and automatic defusion': 'Fusión temporal y separación automática',
    'Fusion time limit (seconds)': 'Límite de tiempo de fusión (segundos)',
    'Show remaining fusion time': 'Mostrar tiempo de fusión restante',
    'Play power-down animation before defusion': 'Animación de destransformación antes de separarse',
    'Ginyu: exchange bodies with the actual opponent': 'Ginyu: intercambiar cuerpos con el rival alcanzado',
    'Ginyu can use stolen-body abilities': 'Ginyu puede usar las habilidades del cuerpo robado',
    'Extra fighter voice lines': 'Voces de los luchadores adicionales',
    'Disable all CPU transformations': 'Desactivar todas las transformaciones de la CPU',
    'Disable CPU transformations into giants': 'Desactivar las transformaciones de la CPU en gigantes',
    'CPU transformation chance (%; 100 = normal)': 'Probabilidad de transformación de la CPU (%; 100 = normal)',
    'Larger canonical-style giants (expanded maps recommended)': 'Gigantes más grandes (se recomiendan mapas ampliados)',
    'Giant size multiplier': 'Multiplicador del tamaño de gigantes',
    'Giant ordinary attack speed (%)': 'Velocidad de ataques normales de gigantes (%)',
    'Giant attack damage (%)': 'Daño de los ataques de gigantes (%)',
    'Extra giant stagger resistance (0 = native)': 'Resistencia adicional de gigantes al tambaleo (0 = normal)',
    'Giant follow camera distance (%)': 'Distancia de cámara para gigantes (%)',
    'Battle camera zoom-out (%; 100 = normal)': 'Distancia de la cámara de combate (%; 100 = normal)',
    'Friendly overhead health bars': 'Barras de salud sobre los aliados',
    'Enemy overhead health bars': 'Barras de salud sobre los enemigos',
    'Battle HUD (including split-screen panels)': 'Interfaz de combate (también en pantalla dividida)',
    'Kill feed': 'Registro de bajas', 'Watched fighter kill count': 'Bajas del luchador observado',
    'Split-screen HUD style': 'Estilo de la interfaz dividida',
    'Top-row HUD size (%)': 'Tamaño de la interfaz superior (%)',
    'Split-screen HUD layout': 'Distribución de la interfaz dividida',
    'HUD texture filtering': 'Filtrado de texturas de la interfaz',
    'Co-op HUD panels': 'Paneles en cooperativo',
    'Fighter portraits (native style)': 'Retratos (estilo original)',
    'Sparking lightning (native style)': 'Rayos de Sparking (estilo original)',
    'Health damage trail (seconds; 0 = off)': 'Estela de daño en salud (segundos; 0 = sin estela)',
    'Allow taking over living CPU teammates': 'Permitir controlar a aliados CPU vivos al ser derrotado',
    'Allow spectating fallen fighters': 'Permitir observar a luchadores caídos',
    'Show takeover button hint': 'Mostrar el botón para tomar el control',
    'Show takeover confirmation': 'Confirmar al tomar el control',
    'Takeover hint delay (seconds)': 'Retraso del aviso para tomar el control (segundos)',
    'Takeover confirmation time (seconds)': 'Duración de la confirmación (segundos)',
    'Enable teammate revival': 'Permitir reanimar aliados',
    'Revival cost (blast stocks)': 'Coste de reanimación (reservas de habilidad)',
    'Stand nearby for (seconds)': 'Permanecer cerca durante (segundos)',
    'Revival distance (world units)': 'Distancia de reanimación (unidades del mundo)',
    'Health bars restored': 'Barras de salud recuperadas',
    'Minimum protected get-up time (seconds)': 'Tiempo mínimo de protección al levantarse (segundos)',
    'Keep fallen fighters in bounds': 'Mantener a los luchadores caídos dentro del escenario',
    'Show revival range ring': 'Mostrar el anillo de reanimación',
    'Revival ring opacity': 'Opacidad del anillo de reanimación',
    'Revival ring wave height (0 = flat)': 'Altura de las ondas del anillo (0 = plano)',
    'Revival ring wave speed (cycles per second)': 'Velocidad de ondas del anillo (ciclos por segundo)',
    'Beam clash camera': 'Cámara del choque de rayos',
    'Beam struggle length': 'Duración del forcejeo de rayos',
    'Win early by leading by (inputs; 0 = off)': 'Ganar antes con ventaja de (pulsaciones; 0 = no)',
    'CPU struggle strength (%; 100 = normal)': 'Fuerza de la CPU en el forcejeo (%; 100 = normal)',
    'Others can hit fighters in a beam struggle': 'Los demás pueden golpear a quien forcejea',
    'Push lost per health lost (%)': 'Empuje perdido por salud perdida (%)',
    'Teammates can assist a beam struggle (R3; 1 blast stock)': 'Los aliados pueden apoyar un forcejeo (R3; 1 reserva)',
    'Assist multiplier (push and final damage, %)': 'Multiplicador del apoyo (empuje y daño final, %)',
    'CPU fighters assist too': 'Las CPU también apoyan',
    'Assist range from the struggling ally (world units)': 'Alcance del apoyo desde el aliado (unidades del mundo)',
    'Walk and run on the ground': 'Caminar y correr por el suelo',
    'Stick tilt to run (%; 0 = always run)': 'Inclinación del stick para correr (%; 0 = siempre)',
    'Walking speed (% of normal)': 'Velocidad al caminar (% de la normal)',
    'Running speed (%; 100 = normal)': 'Velocidad al correr (%; 100 = normal)',
    'R3 - BEAM ASSIST': 'R3 - APOYAR AL RAYO',
    'ASSIST FAILED - BUSY': 'APOYO FALLIDO - OCUPADO', 'ASSIST FAILED - BLOCKED': 'APOYO FALLIDO - BLOQUEADO',
    'ASSIST FAILED - HIT': 'APOYO FALLIDO - GOLPEADO',
    'Size changes ground speed': 'El tamaño cambia la velocidad',
    'CPU behavior': 'Comportamiento de la CPU',
    'Refill health and prevent knockouts': 'Recuperar salud y evitar derrotas',
    'Health refill delay after damage (seconds)': 'Retraso de la recuperación de salud (segundos)',
    'Refill ki': 'Recuperar ki', 'Refill blast stocks': 'Recuperar reservas de habilidad',
    'PCSX2 16:9 widescreen patch (restart; automatic for BT4)': 'Parche panorámico 16:9 de PCSX2 (reiniciar; automático en BT4)',
    'Fast disc loading (restart)': 'Carga rápida del disco (reiniciar)',
    'Emulated PS2 CPU speed (restart)': 'Velocidad de la CPU emulada (reiniciar)',
    'Experimental 2x maps (restart)': 'Mapas 2× experimentales (reiniciar)',
    'Keep preparation RAM dumps (uses a lot of disk space)': 'Conservar volcados RAM de preparación (ocupa mucho espacio)',
    'Save a large diagnostic snapshot if a match freezes': 'Guardar un volcado de diagnóstico si se bloquea el combate',
    'Write diagnostic battle history to disk': 'Guardar historial de diagnóstico de combate',
    'ON': 'SÍ', 'OFF': 'NO', 'MOD SETTINGS': 'AJUSTES DEL MOD',
    '   [L1 / R1: category]': '   [L1 / R1: categoría]',
    'Up/Down: select    Left/Right: adjust': 'Arriba/abajo: elegir   Izq./der.: ajustar',
    'Square: save    Triangle: cancel    Applies to next match': 'Cuadrado: guardar   Triángulo: cancelar   (se aplica al próximo combate)',
    '{adapter} mod settings': 'Ajustes del mod {adapter}', 'Mod settings': 'Ajustes del mod',
    'Choose a category. Saved changes apply to the next match unless its page says otherwise. This window shows a newly saved language when you reopen it.': 'Elige una categoría. Los cambios guardados se aplican al próximo combate salvo que su página indique otra cosa. Esta ventana muestra el nuevo idioma guardado al volver a abrirla.',
    'Restore defaults': 'Restaurar valores predeterminados', 'Save': 'Guardar', 'Cancel': 'Cancelar',
    'Defaults restored. Save to keep them.': 'Valores predeterminados restaurados. Guarda para conservarlos.',
    'Replace them with the default settings? A copy of the old file is kept as {name}.': '¿Sustituirlos por los ajustes predeterminados? Se guarda una copia del archivo anterior como {name}.',
    'Run Build expanded maps.cmd first.': 'Ejecuta primero Build expanded maps.cmd.',
    'Expanded maps are on, but the expanded ISO is missing or out of date. Starting the original ISO; run Build expanded maps.cmd first.': 'Los mapas ampliados están activados, pero falta la ISO ampliada o no está al día. Se inicia la ISO original; ejecuta primero Build expanded maps.cmd.',
    'Rebind…': 'Asignar…', 'Rebind: {setting}': 'Asignar: {setting}',
    'That button is needed for selecting or navigating modes. Choose Select, Start, a stick click, a shoulder button or Square.': 'Ese botón se usa para elegir o recorrer los modos. Usa Select, Start, L3, R3, L1, L2, R1, R2 o Cuadrado.',
    'Per-character transformation exceptions…': 'Excepciones de transformación por personaje…',
    'CPU transformation exceptions': 'Excepciones de transformación de la CPU',
    'Select a character/form, then choose Default, Allow or Block.\nAllow overrides both global CPU restrictions; it does not bypass native move rules.': 'Elige un personaje o forma y selecciona Predeterminado, Permitir o Bloquear.\nPermitir anula las restricciones generales de la CPU, pero respeta las reglas del juego.',
    'Current character / form': 'Personaje / forma actual', 'Transformations': 'Transformaciones',
    'Default': 'Predeterminado', 'Allow': 'Permitir', 'Block': 'Bloquear',
    'Use these exceptions': 'Usar estas excepciones',
    'Press a controller button or a key mapped in PCSX2.': 'Pulsa un botón del mando o una tecla asignada en PCSX2.',
    'Or choose a PS2 button:': 'O elige un botón de PS2:',
    'The binding uses each player’s PCSX2 mapping. Native actions on this button still happen.': 'Usa la asignación de PCSX2 de cada jugador. El botón también conserva su acción original.',
    'Controller mappings could not be read. Choose a PS2 button below.': 'No se pudo leer la asignación del mando. Elige un botón de PS2.',
    'That input has no single PS2-button mapping. Choose a button below or assign it in PCSX2 first.': 'Esa entrada no corresponde a un único botón. Elige uno o asígnalo en PCSX2.',
    'Use selected button': 'Usar botón elegido',
    'Gamepad capture is unavailable. Press a mapped keyboard key or choose a PS2 button below.': 'No se pudo detectar el mando. Pulsa una tecla asignada o elige un botón.',
    'CHOOSE YOUR TEAMS': 'ELIGE LOS EQUIPOS',
    'PLAYER SETUP': 'CONFIGURAR JUGADORES',
    'Continue': 'Continuar',
    'Each player: press START on your own controller to join.': 'Cada jugador: pulsa START en su propio mando para unirse.',
    'Press START on your controller to join': 'Pulsa START en tu mando para unirte',
    'PCSX2 controller {k} (default order)': 'Mando {k} de PCSX2 (orden predeterminado)',
    'Controller {k} (connection order): {name}': 'Mando {k} (orden de conexión): {name}',
    '{name} (PCSX2 controller {k})': '{name} (mando {k} de PCSX2)',
    'Keyboard / PCSX2 controller {k}': 'Teclado / mando {k} de PCSX2',
    'Controller lost: reconnect it, or hold START on another': 'Mando perdido: reconéctalo o mantén START en otro',
    'Clear check-ins': 'Borrar los registros',
    'Waiting for players {list} to join.': 'Esperando a que se unan los jugadores {list}.',
    'Waiting for player {list} to join.': 'Esperando a que se una el jugador {list}.',
    'Everyone is in. Player 1: Continue.': 'Ya estáis todos. Jugador 1: Continuar.',
    'Connecting controllers…': 'Conectando los mandos…',
    "The mod's controller reader did not start: players 3 and 4 cannot join (TTM-CTRL-20).": 'El lector de mandos del mod no se ha iniciado: los jugadores 3 y 4 no pueden unirse (TTM-CTRL-20).',
    'The keyboard can only be player {k}. Player {k}: press SELECT to free that seat.': 'El teclado solo puede ser el jugador {k}. Jugador {k}: pulsa SELECT para dejar ese puesto.',
    'One controller appears twice (DS4Windows or Steam Input?): the mod uses one copy and ignores the other (TTM-CTRL-23).': 'Un mando aparece dos veces (¿DS4Windows o Steam Input?): el mod usa una copia e ignora la otra (TTM-CTRL-23).',
    '{name} also moves player {k} through PCSX2: remove it from PCSX2 controller port {k} (TTM-CTRL-24).': '{name} también mueve al jugador {k} a través de PCSX2: quítalo del puerto de mando {k} de PCSX2 (TTM-CTRL-24).',
    '{name} has no gamepad layout here; it can still play as player 1 or 2 through PCSX2 (TTM-CTRL-21).': '{name} no tiene un esquema de mando aquí; aun así puede jugar como jugador 1 o 2 a través de PCSX2 (TTM-CTRL-21).',
    'Player 1: Up/Down select · Left/Right team · Cross continue · Triangle back': 'Jugador 1: Arriba/abajo elegir · Izq./der. equipo · Cruz continuar · Triángulo volver',
    'Everyone: START join · Left/Right own team · SELECT leave': 'Todos: START unirse · Izq./der. tu equipo · SELECT salir',
    'Player 1: Up/Down select · Cross continue · Triangle back': 'Jugador 1: Arriba/abajo elegir · Cruz continuar · Triángulo volver',
    'Everyone: START join · SELECT leave': 'Todos: START unirse · SELECT salir',
    # Controller hub lines (TTM-CTRL-20..24; the watcher prefixes the code) and the back-on line.
    "Players 3 and 4 cannot join: the mod's controller reader (SDL2) did not start ({detail}). Players 1 and 2 keep their PCSX2 controllers. On Linux install libsdl2-2.0-0 (Debian/Ubuntu), SDL2 or sdl2-compat.": 'Los jugadores 3 y 4 no pueden unirse: el lector de mandos del mod (SDL2) no se ha iniciado ({detail}). Los jugadores 1 y 2 siguen con sus mandos de PCSX2. En Linux instala libsdl2-2.0-0 (Debian/Ubuntu), SDL2 o sdl2-compat.',
    '{name} is connected but has no gamepad layout (GUID {guid}), so it cannot join as player 3 or 4. It can still play as player 1 or 2 through PCSX2 (PCSX2 settings > Controllers), or in its XInput/X mode.': '{name} está conectado pero no tiene un esquema de mando (GUID {guid}), así que no puede unirse como jugador 3 o 4. Aun así puede jugar como jugador 1 o 2 a través de PCSX2 (ajustes de PCSX2 > Mandos) o en su modo XInput/X.',
    "Player {n}'s controller ({name}) disconnected; that fighter stands still. Reconnect it, or hold START for 2 seconds on a free controller to take over.": 'El mando del jugador {n} ({name}) se ha desconectado; ese luchador se queda quieto. Vuelve a conectarlo o mantén START 2 segundos en un mando libre para sustituirlo.',
    '{name} appears twice (DS4Windows, Steam Input or another remapper): the mod uses one copy and ignores the other. If a player moves twice, hide the copy (HidHide) or turn the remapper off.': '{name} aparece dos veces (DS4Windows, Steam Input u otro programa): el mod usa una copia e ignora la otra. Si un jugador se mueve dos veces, oculta la copia (HidHide) o desactiva ese programa.',
    '{name} moves player {n} and also player {k} through PCSX2 controller port {k}. Remove it from that port in PCSX2 settings > Controllers, or let it join as player {k}.': '{name} mueve al jugador {n} y también al jugador {k} por el puerto de mando {k} de PCSX2. Quítalo de ese puerto en los ajustes de PCSX2 > Mandos, o deja que se una como jugador {k}.',
    'Player {n} is back on {name}.': 'El jugador {n} vuelve a usar {name}.',
    'Players and controllers': 'Jugadores y mandos',
    'Controller check-in (each player presses START)': 'Registro de mandos (cada jugador pulsa START)',
    'Keep check-ins for the next matches (until Play closes)': 'Conservar los registros para los próximos combates (hasta cerrar Play)',
    'Check-in: on Player Setup each player presses START on their own controller to join; a light flashes with each press and SELECT leaves the seat. With 3 or 4 players everyone joins before Continue; with 2, PCSX2 keeps its order unless someone presses START (or check-in is set for 2 to 4 players). Optional keeps the connection order, and anyone may still check in. A keyboard joins as player 1 or 2 through PCSX2. Kept check-ins fill the seats again until Play closes. With own fighters on, each human picks their assigned slots; otherwise Player 1 picks. Allowing all controllers lets any controller move the cursor. Player numbers mark whose slot is whose. Saved in game, these apply when you leave Mod Settings; saved in Mod settings.cmd, after restarting Play.': 'Registro: en Configurar jugadores, cada jugador pulsa START en su propio mando para unirse; una luz parpadea con cada pulsación y SELECT deja el puesto. Con 3 o 4 jugadores todos se unen antes de Continuar; con 2, PCSX2 mantiene su orden salvo que alguien pulse START (o el registro sea con 2 a 4 jugadores). Opcional mantiene el orden de conexión y cualquiera puede registrarse. Un teclado se une como jugador 1 o 2 a través de PCSX2. Los registros conservados vuelven a ocupar los puestos hasta cerrar Play. Con luchadores propios, cada jugador elige sus casillas; si no, elige el jugador 1. Permitir todos los mandos deja mover el cursor a cualquiera. Los números marcan de quién es cada casilla. Guardados en el juego, se aplican al salir de Ajustes del mod; desde Mod settings.cmd, al reiniciar Play.',
    'Player 1 assigns teams before choosing fighters.': 'El jugador 1 asigna equipos antes de elegir luchadores.',
    'Unassigned slots are CPUs, selected by Player 1.': 'El jugador 1 elige a los luchadores CPU de las casillas libres.',
    'All players may share one team against CPUs.': 'Todos pueden formar un equipo contra la CPU.',
    'Up/Down: player   Left/Right: team': 'Arriba/abajo: jugador   Izq./der.: equipo',
    'Cross: continue       Triangle: back': 'Cruz: continuar       Triángulo: volver',
    'FREE-FOR-ALL': 'TODOS CONTRA TODOS', 'EVERY FIGHTER FOR THEMSELVES': 'CADA LUCHADOR POR SU CUENTA',
    'LAST FIGHTER STANDING WINS': 'GANA EL ÚLTIMO EN PIE',
    'ALLIES': 'ALIADOS', 'OPPONENTS': 'RIVALES', 'TEAM 1': 'EQUIPO 1', 'TEAM 2': 'EQUIPO 2',
    'TEAM BATTLE': 'COMBATE POR EQUIPOS', 'CO-OP BATTLE': 'COMBATE COOPERATIVO',
    'FIGHT TOGETHER / WIN TOGETHER': 'LUCHA Y VENCE EN EQUIPO',
    'YOUR SELECTED FIGHTERS': 'TUS LUCHADORES', 'PREPARING YOUR MATCH': 'PREPARANDO COMBATE',
    'MODDED TRAINING': 'ENTRENAMIENTO MOD', 'CO-OP TRAINING': 'ENTRENAMIENTO COOPERATIVO',
    'PRACTICE WITH YOUR SELECTED FIGHTERS': 'PRACTICA CON TUS LUCHADORES',
    'PRACTICE OPTIONS / MOD SETTINGS': 'OPCIONES EN AJUSTES DEL MOD',
    'LOADING YOUR FIGHTERS': 'CARGANDO LUCHADORES', 'PREPARING YOUR FIGHTERS': 'PREPARANDO LUCHADORES',
    'STARTING YOUR MATCH': 'INICIANDO COMBATE', 'READY': 'LISTO',
    'PRESS SQUARE TO TAKE OVER': 'CUADRADO PARA CONTROLAR',
    'PRESS L2 AND SQUARE TO TAKE OVER': 'L2 Y CUADRADO PARA CONTROLAR',
    'CONTROLLING ': 'CONTROLAS A ', 'DEFUSION PENDING': 'SEPARACION PENDIENTE',
    'UNKNOWN FIGHTER': 'LUCHADOR DESCONOCIDO', 'KILLS': 'BAJAS',
    'GETTING UP': 'LEVANTANDOSE', 'REVIVING TEAMMATE': 'REANIMANDO ALIADO',
    'FIGHTER': 'LUCHADOR', '1 FIGHTER': '1 LUCHADOR',
    'TWO PLAYERS / ONE TEAM': 'DOS JUGADORES / UN EQUIPO', 'THREE PLAYERS / ONE TEAM': 'TRES JUGADORES / UN EQUIPO',
    'FOUR PLAYERS / ONE TEAM': 'CUATRO JUGADORES / UN EQUIPO',
    'TWO PLAYERS / PRACTICE TOGETHER': 'DOS JUGADORES / ENTRENAN JUNTOS',
    'THREE PLAYERS / PRACTICE TOGETHER': 'TRES JUGADORES / ENTRENAN JUNTOS',
    'FOUR PLAYERS / PRACTICE TOGETHER': 'CUATRO JUGADORES / ENTRENAN JUNTOS',
    # Fusion chord names (guest ASCII); the joiner keeps its spaces.
    ' AND ': ' Y ', 'UP': 'ARRIBA', 'RIGHT': 'DERECHA', 'DOWN': 'ABAJO', 'LEFT': 'IZQUIERDA',
    'Your settings could not be opened. The saved file was left unchanged.': 'No se pudieron abrir los ajustes. El archivo guardado no se ha modificado.',
    'Your changes could not be saved.': 'No se pudieron guardar los cambios.',
    'GETTING YOUR FIGHTERS READY': 'PREPARANDO LUCHADORES',
    'GETTING YOUR FIGHTERS READY...': 'PREPARANDO LUCHADORES...',
    'PREPARING TEAM BATTLE': 'PREPARANDO COMBATE',
    'LOADING FIGHTERS': 'CARGANDO LUCHADORES', 'PREPARING ARENA': 'PREPARANDO ESCENARIO',
    'GETTING READY': 'PREPARANDO COMBATE', 'DEFEATED': 'DERROTADO',
    'LOADING YOUR SELECTED FIGHTERS...': 'CARGANDO TUS LUCHADORES...',
    'STARTING YOUR MATCH...': 'INICIANDO COMBATE...',
    'GETTING EVERYONE READY FOR THE REMATCH...': 'PREPARANDO LA REVANCHA...',
    'RETURNING TO YOUR SELECTED MENU...': 'VOLVIENDO AL MENÚ...',
    'RETURNING TO CHARACTER SELECTION...': 'VOLVIENDO A ELEGIR PERSONAJES...',
    'RETURNING TO THE MAIN MENU...': 'VOLVIENDO AL MENÚ PRINCIPAL...',
    'FINISHING THE PREVIOUS OPERATION BEFORE RETURNING...': 'TERMINANDO LA OPERACIÓN ANTERIOR...',
    'MENU DESTINATION UNKNOWN - CLOSE AND REOPEN THE GAME': 'ERROR DE MENÚ - CIERRA Y ABRE EL JUEGO',
    'MENU RETURN BUSY - CLOSE AND REOPEN THE GAME': 'MENÚ OCUPADO - CIERRA Y ABRE EL JUEGO',
    'MENU RESTORE FAILED - CLOSE AND REOPEN THE GAME': 'ERROR DE MENÚ - CIERRA Y ABRE EL JUEGO',
    'FIGHTER UPDATE FAILED - CLOSE AND REOPEN THE GAME': 'ERROR DE LUCHADOR - CIERRA Y ABRE EL JUEGO',
    'REMATCH RESTORE FAILED - CLOSE AND REOPEN THE GAME': 'ERROR DE REVANCHA - CIERRA Y ABRE EL JUEGO',
    'PRESS SPACE IN THE GAME TO CONTINUE LOADING.': 'PULSA ESPACIO PARA SEGUIR CARGANDO.',
    'PRESS SPACE IN THE GAME TO BEGIN LOADING.': 'PULSA ESPACIO PARA EMPEZAR A CARGAR.',
}

# Watcher covers and failure notices (beta.33 group B): a paused streaming preparation
# and the fixed texts player_errors translates (autopilot.py).
ES.update({
    'PAUSED: RESUME PCSX2 TO CONTINUE LOADING': 'EN PAUSA: REANUDA PCSX2 PARA SEGUIR CARGANDO',
    'The game went to a menu the mod cannot restore, so the clean main menu was loaded instead':
        'El juego fue a un menú que el mod no puede restaurar, así que se cargó el menú principal limpio',
    'The game did not say which menu it went to after the match, so the clean main menu was loaded instead':
        'El juego no indicó a qué menú fue tras el combate, así que se cargó el menú principal limpio',
    'Returning to character selection failed, so the clean main menu was loaded instead':
        'No se pudo volver a la selección de personajes, así que se cargó el menú principal limpio',
    'Another operation kept the preparation lock for 30 seconds, so no menu was loaded over it':
        'Otra operación mantuvo el bloqueo de preparación durante 30 segundos, así que no se cargó ningún menú encima',
    'Transformations, Body Change and fusion timers are off for the rest of this match. '
    'The match goes on; start a new match to turn them back on':
        'Las transformaciones, el Cambio de Cuerpo y los temporizadores de fusión quedan desactivados el resto del combate. '
        'El combate sigue; empieza un combate nuevo para reactivarlos',
    "The Modded Modes menu stopped. The game's own menus still work; to use Modded Modes, close PCSX2, then start {play} again":
        'El menú Modos del mod se ha detenido. Los menús del juego siguen funcionando; para usar los Modos del mod, '
        'cierra PCSX2 y vuelve a abrir {play}',
    'The Modded Modes menu rejected a choice and was reset. Choose again':
        'El menú Modos del mod rechazó una opción y se ha reiniciado. Vuelve a elegir',
    'A controller input thread did not stop; it was left running in the background. Players 1 and 2 are not affected':
        'Un proceso de entrada de mandos no se detuvo y sigue en segundo plano. Los jugadores 1 y 2 no se ven afectados',
    'The game did not confirm loading the rematch checkpoint':
        'El juego no confirmó la carga del punto de control de la revancha',
    # Console lines (autopilot say(), fresh_team_trainer, player_storage, presentation_settings).
    'Tag Team Mod is running. At the main menu, press {button} for Modded Modes.':
        'Tag Team Mod está en marcha. En el menú principal, pulsa {button} para abrir los modos del mod.',
    'The game is paused in its menus. Resume it with Space (or System > Resume in PCSX2).':
        'El juego está en pausa en sus menús. Reanúdalo con Espacio (o Sistema > Reanudar en PCSX2).',
    'PCSX2 is paused. Loading your fighters continues when you resume it (Space, or System > Resume in PCSX2).':
        'PCSX2 está en pausa. La carga de tus luchadores sigue cuando lo reanudes (Espacio, o Sistema > Reanudar en PCSX2).',
    'The match intro stopped at its start; the mod continued it.':
        'La presentación del combate se detuvo al empezar; el mod la continuó.',
    'PCSX2 resumed; loading your fighters continues.':
        'PCSX2 se ha reanudado; la carga de tus luchadores continúa.',
    'The game window of PCSX2 is not in front (another program or a PCSX2 dialog is), so no key was pressed. '
    'Click the game window and press Space.':
        'La ventana del juego de PCSX2 no está delante (hay otro programa o un diálogo de PCSX2), así que no se pulsó '
        'ninguna tecla. Haz clic en la ventana del juego y pulsa Espacio.',
    'Could not press Space in PCSX2 ({error}). Click the game window and press Space.':
        'No se pudo pulsar Espacio en PCSX2 ({error}). Haz clic en la ventana del juego y pulsa Espacio.',
    'PCSX2 did not answer in the menus ({error}); trying again in {delay} s.':
        'PCSX2 no respondió en los menús ({error}); se vuelve a intentar en {delay} s.',
    'PCSX2 did not answer while a match was starting ({error}); trying again in {delay} s.':
        'PCSX2 no respondió mientras empezaba un combate ({error}); se vuelve a intentar en {delay} s.',
    'PCSX2 did not answer while the main menu was loading ({error}); trying again in {delay} s.':
        'PCSX2 no respondió mientras se cargaba el menú principal ({error}); se vuelve a intentar en {delay} s.',
    'PCSX2 did not answer while character selection was loading ({error}); trying again in {delay} s.':
        'PCSX2 no respondió mientras se cargaba la selección de personajes ({error}); se vuelve a intentar en {delay} s.',
    'Character selection could not be loaded ({error}); loading the main menu instead.':
        'No se pudo cargar la selección de personajes ({error}); se carga el menú principal en su lugar.',
    'Returning to the main menu failed: {error}. No checkpoint was loaded, so the game is in its own menus with this '
    'match still set up. Close PCSX2, then start {play} again.':
        'No se pudo volver al menú principal: {error}. No se cargó ningún punto de control, así que el juego está en sus '
        'propios menús con este combate aún preparado. Cierra PCSX2 y vuelve a abrir {play}.',
    'Returning to character selection failed: {error}. No checkpoint was loaded, so the game is in its own menus with '
    'this match still set up. Close PCSX2, then start {play} again.':
        'No se pudo volver a la selección de personajes: {error}. No se cargó ningún punto de control, así que el juego '
        'está en sus propios menús con este combate aún preparado. Cierra PCSX2 y vuelve a abrir {play}.',
    'The match continued, so the return to the menu was cancelled.':
        'El combate continuó, así que se canceló la vuelta al menú.',
    'The Modded Modes menu stopped: {error}.':
        'El menú Modos del mod se ha detenido: {error}.',
    'Fighter update stopped: {error}. {hold} Close PCSX2, then start {play} again.':
        'La actualización de luchadores se ha detenido: {error}. {hold} Cierra PCSX2 y vuelve a abrir {play}.',
    'Combat is held.': 'El combate está detenido.',
    'Combat hold could not be confirmed.': 'No se pudo confirmar que el combate esté detenido.',
    'The fighter update services changed while the match was out of combat; attaching again.':
        'Los servicios de actualización de luchadores cambiaron mientras el combate estaba parado; se vuelven a conectar.',
    'Reused savestate slot(s) {slots} left by an earlier session.':
        'Se reutilizaron las ranuras de guardado {slots} que dejó una sesión anterior.',
    'Need two free savestate slots between 220 and 239 in {folder}, but the others hold savestates this mod did not '
    'create, which it never overwrites. Move those files out of that folder, then start {play} again':
        'Hacen falta dos ranuras de guardado libres entre 220 y 239 en {folder}, pero las demás tienen guardados que este '
        'mod no creó y que nunca sobrescribe. Saca esos archivos de esa carpeta y vuelve a abrir {play}',
    'Kept {count} old generated folder(s) that could not be deleted now (a file is in use); they are tried again at '
    'the next launch.':
        'Se conservaron {count} carpetas generadas antiguas que no se pudieron borrar ahora (hay un archivo en uso); se '
        'vuelve a intentar en el próximo inicio.',
    'Presentation receipt belongs to another configuration':
        'El registro de pantalla pertenece a otra configuración',
    'The saved display-settings receipt is unreadable ({detail})':
        'El registro guardado de los ajustes de pantalla no se puede leer ({detail})',
    '{problem}; it was kept as {name} and the current display settings are used.':
        '{problem}; se guardó como {name} y se usan los ajustes de pantalla actuales.',
    'The game stopped responding while the match was starting: its picture did not change for 10 seconds. '
    'Close PCSX2, then start {play} again.':
        'El juego dejó de responder mientras empezaba el combate: su imagen no cambió durante 10 segundos. '
        'Cierra PCSX2 y vuelve a abrir {play}.',
})

# Display labels only. Values in mod-settings.json never become translated text.
# Each setting's labels are unique in both languages (test_localization).
VALUES_EN = {'three_or_more':'Required with 3 or 4 players', 'two_or_more':'Required with 2 to 4 players',
             'connection_order':'Optional (connection order)', 'all':'Everyone', 'target':'Target only', 'none':'Nobody', 'shared':'One shared view',
    'single_enemy':'Only with one enemy left', 'hide':'Hide', 'show':'Always show',
    'each_half':'Each half frames it', 'swap_20s':'Swap every 20 s', 'split_controls':'P1 attacks, P2 moves',
    'player1':'Player 1 only', 'idle':'Stand still', 'fight':'Fight back', 'native':'Native',
    'compact':'Compact', 'top':'Same top row', 'top_bottom':'Player top, target bottom',
    'nearest':'Sharp (nearest)', 'linear':'Smooth (linear)', 'players':'Both players',
    'targets':'Each player and target', 'default':'PCSX2 setting', '130':'130%', '180':'180%', '300':'300%',
    'left_to_right':'Left to right, around you', 'nearest_first':'Nearest first', 'selection_order':'Selection order',
    'nearest_to_centre':'Nearest your screen centre', 'game_default':'Game default',
    'with_switch_button':'Hold switch button', 'right_stick_alone':'Stick alone (in combat)',
    'never':'Never', 'tap_during_warning':'Tap during a warning', 'when_hit':'Tap, or automatic when hit',
    'marks':'Arrows', 'marks_and_warning':'Arrows and attack warning',
    'arrow':'Gold arrow', 'ring':'Ring', 'both':'Arrow and ring',
    'off':'Off', 'balanced':'Balanced', 'strong':'Strong', 'custom':'Custom (rows below)',
    'smaller_team':'Smaller team only', 'also_ganged_up':'Smaller team or 2+ attackers', 'everyone':'Every fighter',
    'humans':'Players only', 'nearest_partner':'Nearest free partner', 'every_free_partner':'Every free partner',
    'long':'Long (x2)', 'very_long':'Very long (x4)', 'energy':'Energy ultimates',
    'all_ultimates':'All ultimates', 'clash':'Switch to clash (native)', 'keep':'Keep player views'}
VALUES = {'three_or_more':'Obligatorio con 3 o 4 jugadores', 'two_or_more':'Obligatorio con 2 a 4 jugadores',
          'connection_order':'Opcional (orden de conexión)', 'all':'Todos', 'target':'Solo objetivo', 'none':'Nadie', 'shared':'Vista compartida',
    'single_enemy':'Solo si queda un enemigo', 'hide':'Ocultar', 'show':'Mostrar siempre',
    'each_half':'Cada mitad', 'swap_20s':'Alternar cada 20 s', 'split_controls':'J1 ataca, J2 se mueve',
    'player1':'Solo jugador 1', 'idle':'Quietos', 'fight':'Combatir', 'native':'Original',
    'compact':'Compacta', 'top':'Ambos arriba', 'top_bottom':'Jugador arriba, objetivo abajo',
    'nearest':'Sin suavizado', 'linear':'Suavizado', 'players':'Ambos jugadores',
    'targets':'Jugador y objetivo', 'default':'Ajuste de PCSX2', '130':'130%', '180':'180%', '300':'300%',
    'left_to_right':'A la derecha, a tu alrededor', 'nearest_first':'El más cercano primero',
    'selection_order':'Orden de selección', 'nearest_to_centre':'El más cercano al centro',
    'game_default':'Como el juego original', 'with_switch_button':'Con el botón de cambio',
    'right_stick_alone':'Solo el stick (en combate)', 'never':'Nunca', 'tap_during_warning':'Pulsando durante el aviso',
    'when_hit':'Pulsando o al recibir golpes', 'marks':'Flechas', 'marks_and_warning':'Flechas y aviso de ataque',
    'arrow':'Flecha dorada', 'ring':'Anillo', 'both':'Flecha y anillo',
    'off':'Desactivado', 'balanced':'Equilibrada', 'strong':'Fuerte', 'custom':'Personalizada (filas de abajo)',
    'smaller_team':'Solo el equipo menor', 'also_ganged_up':'Equipo menor o 2+ atacantes',
    'everyone':'Todos los luchadores', 'humans':'Solo jugadores', 'nearest_partner':'El aliado libre más cercano',
    'every_free_partner':'Todos los aliados libres', 'long':'Larga (x2)', 'very_long':'Muy larga (x4)',
    'energy':'Definitivos de energía', 'all_ultimates':'Todos los definitivos', 'clash':'Pasar al choque (original)',
    'keep':'Mantener las vistas'}
# PS2 button values (input_binding.BUTTONS -> input_binding.LABELS). Only settings
# screens translate them; guest text keeps input_binding.LABELS unchanged.
BUTTON_LABELS = {'select':'Select', 'l3':'L3', 'r3':'R3', 'start':'Start', 'up':'Up', 'right':'Right',
    'down':'Down', 'left':'Left', 'l2':'L2', 'r2':'R2', 'l1':'L1', 'r1':'R1', 'triangle':'Triangle',
    'circle':'Circle', 'cross':'Cross', 'square':'Square'}
ES.update({'Up':'Arriba', 'Right':'Derecha', 'Down':'Abajo', 'Left':'Izquierda', 'Triangle':'Triángulo',
    'Circle':'Círculo', 'Cross':'Cruz', 'Square':'Cuadrado'})

ES.update({
    'Fight with every selected teammate\non the battlefield at the same time.': 'Lucha con todos tus aliados\nen el campo de batalla a la vez.',
    'Every fighter is an opponent.\nChoose one to four players, or CPUs.': 'Todos los luchadores son rivales.\nDe uno a cuatro jugadores, o solo CPU.',
    'Two to four players share Team 1.\nSelect an ally for every human player.': 'De dos a cuatro jugadores en el equipo 1.\nElige un aliado para cada jugador.',
    'Practice with selected team rosters.\nSet CPU behavior and refill in Mod settings.\nOriginal Training stays in the original menu.': 'Practica con tus equipos. Configura la CPU\ny la recuperación en Ajustes del mod.\nEl entrenamiento original sigue disponible.',
    'Adjust the mod with your controller.\nSave changes for your next match.': 'Ajusta el mod con tu mando.\nGuarda para el próximo combate.',
    'Control Team 1 against CPU opponents.\nChoose the fighters for each team.': 'Controla el equipo 1 contra la CPU.\nElige los luchadores de cada equipo.',
    'Player 1 faces Player 2.\nAdd CPU teammates on either side.': 'Jugador 1 contra jugador 2.\nAñade aliados CPU a ambos equipos.',
    'Watch two teams of CPU fighters.\nChoose the fighters for each team.': 'Observa un combate entre equipos CPU.\nElige los luchadores de cada equipo.',
    'Return to the mod mode groups.': 'Vuelve al menú de modos del mod.',
    'One player against every other fighter.\nAll remaining fighters are CPUs.': 'Un jugador contra todos los demás.\nLos otros luchadores son CPU.',
    'Two players fight each other and CPUs.\nEvery fighter is an opponent.': 'Dos jugadores luchan entre sí y contra la CPU.\nTodos los luchadores son rivales.',
    'Watch a free-for-all between CPUs.\nEvery fighter is an opponent.': 'Observa un todos contra todos entre CPU.\nTodos los luchadores son rivales.',
    'Two players share Team 1.\nChoose at least two Team 1 fighters\nand one or more CPU opponents.': 'Dos jugadores comparten el equipo 1.\nElige al menos dos aliados\ny al menos un rival CPU.',
    'Two to four allies practice together.\nSelect an ally for every human player\nand one or more CPU opponents.': 'De dos a cuatro aliados practican juntos.\nElige un aliado por jugador\ny uno o más rivales CPU.',
    'Practice with one human and CPU fighters.\nChoose CPU behavior and refill in Mod settings.': 'Practica con un jugador y luchadores CPU.\nConfigura la CPU y la recuperación en Ajustes.',
    'Practice with a human on each side.\nAdd CPU fighters to either team.': 'Practica con un jugador en cada equipo.\nAñade luchadores CPU a cualquier equipo.',
    'Four players and any selected CPUs.\nSelect at least four fighters total.': 'Cuatro jugadores y las CPU elegidas.\nSelecciona al menos cuatro luchadores.',
    'Four players share Team 1.\nSelect at least four Team 1 fighters.': 'Cuatro jugadores comparten el equipo 1.\nSelecciona al menos cuatro aliados.',
    'Four allies practice against CPUs.\nSelect at least four Team 1 fighters.': 'Cuatro aliados practican contra la CPU.\nSelecciona al menos cuatro aliados.',
    'Two allies practice against CPUs.\nSelect at least two Team 1 fighters.': 'Dos aliados practican contra la CPU.\nSelecciona al menos dos aliados.',
    'Return to Modded Training.': 'Vuelve al entrenamiento mod.',
    'Three players and any selected CPUs.\nSelect at least three fighters total.': 'Tres jugadores y las CPU elegidas.\nSelecciona al menos tres luchadores.',
    'Three allies share Team 1.\nSelect at least three Team 1 fighters.': 'Tres aliados comparten el equipo 1.\nSelecciona al menos tres aliados.',
    'Three allies practice against CPUs.\nSelect at least three Team 1 fighters.': 'Tres aliados practican contra la CPU.\nSelecciona al menos tres aliados.',
    'Choose each player team before character select.\nShare a team for cooperative play.\nAdd CPU fighters to either team.': 'Asigna equipos antes de elegir luchadores.\nComparte equipo para jugar en cooperativo.\nPuedes añadir CPU a ambos equipos.',
})


def value_label(value, settings=None):
    if type(value) is bool:
        return tr('ON' if value else 'OFF', settings)
    if isinstance(value, str) and value in NAMES:
        return NAMES[value]
    if isinstance(value, str) and value in BUTTON_LABELS:
        return tr(BUTTON_LABELS[value], settings)
    if isinstance(value, str) and value in VALUES_EN:
        return VALUES[value] if language(settings) == 'es' else VALUES_EN[value]
    return str(value).replace('_', ' ')


def tr(text, settings=None, **values):
    if language(settings) == 'es':
        translated = ES.get(text)
        if translated is None:
            for pattern, replacement in PATTERNS:
                if re.fullmatch(pattern, text):
                    translated = re.sub(pattern, replacement, text)
                    break
        text = translated if translated is not None else text
    if not WINDOWS and '.cmd' in text:
        for source, target in LINUX_SCRIPT_NAMES.items():
            text = text.replace(source, target)
    return text.format(**values) if values else text


PATTERNS = (
    (r'NEED 1 BLAST STOCKS', r'NECESITAS 1 RESERVA'),
    (r'NEED 1 BLAST STOCK', r'NECESITAS 1 RESERVA'),
    (r'NEED (\d+) BLAST STOCKS', r'NECESITAS \1 RESERVAS'),
    (r'PLAYER (\d+)', r'JUGADOR \1'), (r'SLOT (\d+)', r'CASILLA \1'),
    (r'<  TEAM (\d+)  >', r'<  EQUIPO \1  >'),
    (r'(\d+) unsaved changes', r'\1 cambios sin guardar'),
    (r'(\d+) FIGHTERS? / ALL CPU', r'\1 LUCHADORES / SOLO CPU'),
    (r'(\d+) FIGHTERS? / 1 PLAYER', r'\1 LUCHADORES / 1 JUGADOR'),
    (r'(\d+) FIGHTERS? / (\d+) PLAYERS?', r'\1 LUCHADORES / \2 JUGADORES'),
    (r'(\d+) FIGHTERS?', r'\1 LUCHADORES'),
    (r'(TWO|THREE|FOUR) PLAYERS / ONE TEAM', r'JUGADORES EN UN EQUIPO'),
    (r'(TWO|THREE|FOUR) PLAYERS / PRACTICE TOGETHER', r'PRACTICA EN EQUIPO'),
    (r'FUSION - P(\d) TAP R3 TO ACCEPT', r'FUSION - J\1 ACEPTA CON R3'),
    (r'FUSED - PLAYER (\d) HAS CONTROL', r'FUSION - J\1 CONTROLA'),
    (r'P(\d) TAKES CONTROL IN (\d+)', r'J\1 CONTROLA EN \2'),
    (r'BEAM ASSIST X([\d.]+)', r'APOYO AL RAYO X\1'),
)


def guest(text, settings=None):
    """ASCII glyphs for guest HUD strings, without lossy UTF-8 atlas indexing."""
    if settings is None and _override.get() is None and _battle_language is not None:
        settings = _battle_language
    translated = unicodedata.normalize('NFKD', tr(text, settings))
    return translated.encode('ascii', 'ignore')


def slot(text, size, settings=None):
    data = guest(text, settings)
    if len(data) >= size:
        raise ValueError('Localized guest text exceeds reserved slot: ' + text)
    return data.ljust(size, b'\0')

# Settings page help (mod_settings.notes), shown on the desktop and in game.
ES.update({
    'Press the menu switch button on the original main menu to open or close the mod menus; its hint can be hidden. With mod mode menus off, only Mod settings.cmd can turn them back on. Menu settings saved in game apply when you leave Mod Settings; saved in Mod settings.cmd, after restarting Play. Language also changes match text from the next match. Loading speed applies from the next loading screen.':
        'El botón de cambio de menú abre o cierra los menús del mod desde el menú principal original; su aviso se puede ocultar. Si los desactivas, solo Mod settings.cmd puede reactivarlos. Guardados en el juego, los ajustes de menú se aplican al salir de Ajustes del mod; desde Mod settings.cmd, al reiniciar Play. El idioma cambia también el texto del combate desde el próximo. La velocidad de carga, desde la próxima carga.',
    'Any PS2 button can switch target or watched fighter; its native action still happens, so Start also pauses and R3 also transforms. Hold for the set time, then release (0 = tap). Mod settings.cmd can also capture a pressed button. Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'Cualquier botón de PS2 puede cambiar de objetivo o de luchador observado; conserva su acción original, así que Start también pausa y R3 también transforma. Mantén el tiempo elegido y suelta (0 = toque). Mod settings.cmd también puede detectar el botón pulsado. Se aplica desde el próximo combate; la revancha (Fight Again) conserva los ajustes de su combate.',
    'On the ground, fighters walk or run instead of gliding just above it; dashes, jumps and flight stay as they are. Tilt the left stick past the set amount to run, less to walk; CPU fighters always run. Speeds are percentages of a natural run. With size on, small fighters run slower and giants faster; feet stay planted. Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'En el suelo, los luchadores caminan o corren en vez de deslizarse justo por encima; acelerones, saltos y vuelo no cambian. Inclina el stick izquierdo más de lo indicado para correr, menos para caminar; la CPU siempre corre. Las velocidades son porcentajes de una carrera natural. Con el tamaño, los pequeños corren más lento y los gigantes más rápido; los pies no patinan. Se aplica al próximo combate y a su revancha.',
    'Special-move pause chooses who stops. Shared cameras pause everyone outside the scene for one view; off keeps separate views (paired attacks still hold their fighters). Split-screen transformations use one view or each half. Extra intros can be skipped. Zoom-out above 100% pulls the camera back. Kept in place, attacks and transformations play where they start, not at the arena centre. Applies next match; Fight Again keeps it.':
        'La pausa en especiales elige quién se detiene. Las cámaras compartidas pausan a quien no aparece; sin ellas, cada uno tiene su vista (los ataques en pareja detienen a los suyos). En pantalla dividida, la transformación usa una vista o cada mitad. Las presentaciones extra pueden omitirse. Más del 100% aleja la cámara. En su posición, ataques y transformaciones se ven donde empiezan. Se aplica al próximo combate y a su revancha.',
    'When two humans share a fusion, swap passes control every 20 s, split gives P1 attacks and P2 movement, or Player 1 controls it. The control message and countdown show in swap mode only. The time limit covers Fusion Dance fusions made in the match, not Potara or preselected ones; its timer and power-down animation are optional. Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'Si dos jugadores comparten una fusión, el modo alterno pasa el control cada 20 s, el reparto da ataque al J1 y movimiento al J2, o controla el J1. El aviso y la cuenta atrás solo salen en modo alterno. El límite afecta a la Danza de la Fusión del combate, no a Potara ni a fusiones elegidas; el temporizador y la animación son opcionales. Se aplica desde el próximo combate; la revancha conserva sus ajustes.',
    'Ginyu can exchange bodies with the opponent he actually hits; stolen-body abilities are optional. Extra voices borrow idle native voice streams. The CPU switches and chance limit native CPU transformations; per-character exceptions override them. Humans, fusion and Body Change are unaffected. Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'Ginyu puede intercambiar cuerpos con el rival que alcanza; las habilidades robadas son opcionales. Las voces adicionales usan canales de voz libres. Los ajustes de la CPU y la probabilidad limitan sus transformaciones; las excepciones por personaje los anulan. No afectan a jugadores, fusiones ni al Cambio de Cuerpo. Se aplica desde el próximo combate; la revancha (Fight Again) conserva sus ajustes.',
    'Larger giants scale native giant forms; expanded maps give them room. Size, attack speed, damage, stagger resistance and camera distance apply only while larger giants are on; the Cinematics zoom-out multiplies that distance up to a fixed limit. Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'Los gigantes grandes amplían las formas gigantes del juego; los mapas ampliados les dan espacio. Tamaño, velocidad, daño, resistencia y distancia de cámara solo se aplican con gigantes grandes activados; la distancia de la cámara de combate (Cinemáticas) la multiplica hasta un límite fijo. Se aplica desde el próximo combate; la revancha (Fight Again) conserva los ajustes de su combate.',
    'Health bars, battle HUD, kill feed, watched fighter kill count, target indicator and attacker arrows are separate switches. Battle HUD off also hides split-screen panels. The indicator is a gold arrow, a ring sized to your target, or both, in every view. Red arrows point at each enemy locked on to you, on the screen edge if off screen; they flash while it attacks. Applies next match; Fight Again keeps it.':
        'Barras de salud, interfaz, registro de bajas, bajas del observado, indicador del objetivo y flechas de atacantes se activan por separado. Sin interfaz no hay paneles divididos. El indicador es una flecha dorada, un anillo a la medida del objetivo o ambos, en cada vista. Flechas rojas señalan a cada enemigo que te fija, en el borde si no se ve; parpadean mientras te ataca. Se aplica al próximo combate y revancha.',
    'Native style uses the game frames and meters; portraits and lightning need it. "Same top row" holds both panels (size in %); "Player top, target bottom" puts your target opposite you. Co-op panels show both players or each player and target. Smooth filtering softens textures. The damage trail briefly shows lost health (0 = off). Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'El estilo original usa marcos y medidores del juego; retratos y rayos lo requieren. "Ambos arriba" pone los dos paneles arriba (tamaño en %); "Jugador arriba, objetivo abajo" coloca a tu objetivo frente a ti. En cooperativo se ven los jugadores o cada uno con su objetivo. El suavizado alisa las texturas. La estela muestra la salud perdida (0 = no). Se aplica desde el próximo combate; la revancha conserva sus ajustes.',
    'A defeated human can watch fighters and take over a living CPU teammate, never an enemy, and not in free-for-all or CPU-only matches. Fallen fighters can be watched for their score. The hint shows the takeover button after its delay; the confirmation names your new fighter. Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'Un jugador derrotado puede observar y tomar el control de un aliado CPU vivo, nunca de un enemigo, y no en Todos contra todos ni solo CPU. También puede observar a caídos para ver sus bajas. El aviso muestra el botón tras su retraso; la confirmación indica tu nuevo luchador. Se aplica desde el próximo combate; la revancha (Fight Again) conserva sus ajustes.',
    'Stay inside the circle of a fallen teammate for the set time. Moving and taunting keep progress; damage or leaving interrupts. Revival costs blast stocks, not ki, and restores the set health. Get-up protection, corpse safety and ring appearance are adjustable. No revival in free-for-all. Applies from the next match; a Fight Again rematch keeps its settings.':
        'Permanece en el círculo de un aliado caído el tiempo elegido. Moverte y provocar conservan el progreso; recibir daño o salir lo interrumpe. Cuesta reservas, no ki, y restaura la salud elegida. Puedes ajustar la protección al levantarse, el límite para caídos y el aspecto del anillo. No funciona en Todos contra todos. Se aplica al próximo combate; la revancha conserva sus ajustes.',
    "Clash camera: switch to the struggle, or keep every view on its own player. Long struggles last 2x or 4x; a set input lead wins at once. CPU strength scales CPU inputs. With hits on, enemies can hit both fighters (no grabs) and lost health weakens their push. Near a struggling ally, press R3 (1 blast stock): you fly in beside them and join, adding push and final damage. Up to four per side (x3 at most). Applies next match; Fight Again keeps it.":
        'Cámara del choque: pasa al forcejeo o deja cada vista en su jugador. Los forcejeos largos duran x2 o x4; una ventaja fijada gana al instante. La CPU empuja según su fuerza. Con golpes, los rivales golpean a ambos (sin agarres) y la salud perdida resta empuje. Cerca de un aliado que forcejea, pulsa R3 (1 reserva): llegas a su lado y te unes, con más empuje y daño final. Hasta cuatro por bando (x3 como máximo). Se aplica al próximo combate y a su revancha.',
    'Modded Training takes one to four players; share a team to practice together. The CPU stands still or fights back. Health refills after the delay, and ki and blast stocks refill. With health refill off, defeats can end the session. Native Training stays in the original menu. Applies from the next session; a Fight Again rematch keeps the settings of its session.':
        'El entrenamiento mod admite de uno a cuatro jugadores; compartir equipo permite practicar juntos. La CPU se queda quieta o combate. La salud se recupera tras el retraso; el ki y las reservas también. Sin recuperación de salud, las derrotas pueden terminar la sesión. El entrenamiento original sigue en su menú. Se aplica desde la próxima sesión; la revancha conserva sus ajustes.',
    'Applied when Play starts, so restart Play after saving. Widescreen enables the PCSX2 16:9 patch. Fast disc loading shortens loading screens. A faster emulated CPU smooths split screen; PCSX2 setting leaves the rate alone. 2x maps need Build expanded maps.cmd first (seven animated stages stay native); without that build, Play starts the original ISO.':
        'Se aplican al iniciar Play: reinícialo después de guardar. El parche panorámico activa el 16:9 de PCSX2. La carga rápida acorta las pantallas de carga. Una CPU emulada más rápida suaviza la pantalla dividida; Ajuste de PCSX2 no la cambia. Los mapas 2× requieren Build expanded maps.cmd (siete escenarios animados no cambian); sin esa copia, Play inicia la ISO original.',
    'For troubleshooting; these files can be large. Preparation dumps keep intermediate RAM images, freeze snapshots save memory when a match stops responding, and battle history records match events. Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'Para diagnosticar problemas; estos archivos pueden ocupar mucho. Los volcados de preparación guardan imágenes intermedias de la RAM, las capturas de bloqueo guardan la memoria si un combate se congela y el historial registra los sucesos del combate. Se aplica desde el próximo combate; la revancha (Fight Again) conserva sus ajustes.',
})

# In-game Mod Settings screens (ingame_settings.TEXTS).
ES.update({
    'Choose a category': 'Elige una categoría',
    'Per-character exceptions ({n} set)…': 'Excepciones por personaje ({n} definidas)…',
    'Restore defaults…': 'Restaurar valores predeterminados…',
    'Up/Down: select    Cross: open    Circle: help': 'Arriba/abajo: elegir    Cruz: abrir    Círculo: ayuda',
    'Square: save and exit    Triangle: close': 'Cuadrado: guardar y salir    Triángulo: cerrar',
    'Up/Down: select    Left/Right: change    L2/R2: ×10': 'Arriba/abajo: elegir    Izq./der.: cambiar    L2/R2: ×10',
    'Up/Down: select    Left/Right: change    L2/R2: first/last': 'Arriba/abajo: elegir    Izq./der.: cambiar    L2/R2: primero/último',
    'Up/Down: select    Left/Right: change    L2/R2: off/on': 'Arriba/abajo: elegir    Izq./der.: cambiar    L2/R2: NO/SÍ',
    'L1/R1: category    Circle: help    Square: save    Triangle: back': 'L1/R1: categoría   Círculo: ayuda   Cuadrado: guardar   Triángulo: volver',
    'Help: {group}': 'Ayuda: {group}', 'Circle or Triangle: back': 'Círculo o Triángulo: volver',
    'Default follows the CPU switches; Allow and Block override them.': 'Predeterminado sigue los ajustes de la CPU; Permitir y Bloquear los anulan.',
    'Only characters with an exception ({n})': 'Solo personajes con excepción ({n})',
    'No exceptions set.': 'No hay excepciones.',
    'Up/Down: select    Left/Right: change    L1/R1: page    L2/R2: 5 pages': 'Arriba/abajo: elegir   Izq./der.: cambiar   L1/R1: página   L2/R2: 5 páginas',
    'Select: exceptions only    Square: save    Triangle: back': 'Select: solo excepciones    Cuadrado: guardar    Triángulo: volver',
    'Select: every character    Square: save    Triangle: back': 'Select: todos    Cuadrado: guardar    Triángulo: volver',
    'Discard unsaved changes?': '¿Descartar los cambios sin guardar?',
    'Your unsaved changes will be lost.': 'Se perderán los cambios sin guardar.',
    'Triangle: discard and close    Cross: go back': 'Triángulo: descartar y cerrar    Cruz: volver',
    'Square: save and exit': 'Cuadrado: guardar y salir',
    'Restore defaults?': '¿Restaurar los valores predeterminados?',
    'Every setting except the language returns to its default and the per-character exceptions are cleared. Nothing is saved until you press Square.':
        'Todos los ajustes salvo el idioma vuelven a su valor predeterminado y se borran las excepciones por personaje. No se guarda nada hasta que pulses Cuadrado.',
    'Cross: restore    Triangle: back': 'Cruz: restaurar    Triángulo: volver',
    'Turn off the mod mode menus?': '¿Desactivar los menús de modos del mod?',
    'This screen opens from those menus, so after saving only the desktop Mod settings (Mod settings.cmd) can turn them back on.':
        'Esta pantalla se abre desde esos menús: después de guardar, solo los ajustes de escritorio (Mod settings.cmd) pueden reactivarlos.',
    'Cross: turn off    Triangle: keep on': 'Cruz: desactivar    Triángulo: mantener',
    'Repair replaces the file with the default settings and keeps a copy as {name}.': 'Reparar sustituye el archivo por los ajustes predeterminados y guarda una copia como {name}.',
    'Cross: repair settings    Triangle: close': 'Cruz: reparar ajustes    Triángulo: cerrar',
    'This screen could not be drawn.': 'No se pudo dibujar esta pantalla.',
    'Cross: back to the categories    Triangle: close': 'Cruz: volver a las categorías    Triángulo: cerrar',
    'Triangle: close': 'Triángulo: cerrar',
    'Your settings could not be repaired.': 'No se pudieron reparar los ajustes.',
    'Settings repaired. The old file was kept as {name}.': 'Ajustes reparados. El archivo anterior se guardó como {name}.',
    'Saved.': 'Guardado.',
    'Saved. Launch options apply after restarting Play.': 'Guardado. Las opciones de inicio se aplican al reiniciar Play.',
    '{n} unsaved changes': '{n} cambios sin guardar', '1 unsaved change': '1 cambio sin guardar',
    'Character {cid}': 'Personaje {cid}',
    'An exception applies to a CPU fighter in that character or form. Default follows the CPU switches; Allow ignores them (the chance setting still applies); Block stops it from transforming. Humans are unaffected. Select lists only the exceptions. Applies from the next match; a Fight Again rematch keeps the settings of its match.':
        'Una excepción se aplica a un luchador CPU con ese personaje o forma. Predeterminado sigue los ajustes de la CPU; Permitir los ignora (la probabilidad se sigue aplicando); Bloquear impide que se transforme. No afecta a los jugadores. Select muestra solo las excepciones. Se aplica desde el próximo combate; la revancha (Fight Again) conserva sus ajustes.',
    'Restore defaults stages the default of every setting except the language and clears the per-character exceptions. It never turns the mod mode menus off. Nothing is saved until you press Square.':
        'Restaurar prepara el valor predeterminado de cada ajuste salvo el idioma y borra las excepciones por personaje. Nunca desactiva los menús de modos del mod. No se guarda nada hasta que pulses Cuadrado.',
})


# ---- Launcher names (group A, beta.33) ----------------------------------------------------------
_kind = None


def detect_kind(root=None, windows=None, bt4=None):
    """install_kind() for a given tree: the game folder (tools' parent) and platform."""
    root = Path(__file__).resolve().parents[1] if root is None else Path(root)
    windows = WINDOWS if windows is None else windows
    try:
        marker = root / 'player-install.json'
        if marker.is_file() and isinstance(json.loads(marker.read_text(encoding='utf-8-sig')), dict):
            return 'windows-player' if windows else 'linux-player'
    except (OSError, ValueError, UnicodeError):
        pass  # a damaged marker: the installation folder below still tells a player's copy
    # A missing, quarantined or damaged marker in an installer-made folder (its Play launcher or its file receipt
    # beside the game folder) is still a player installation: never name the developer launchers there.
    try:
        installer_files = (ENTRIES['windows-player'][0], ENTRIES['linux-player'][0], 'installed-files.json')
        if any((root.parent / name).is_file() for name in installer_files):
            return 'windows-player' if windows else 'linux-player'
    except OSError:
        pass
    if not windows:
        return 'dev-linux'
    try:
        bt4 = (root / 'tools' / 'bt4_preflight.py').is_file() if bt4 is None else bt4
    except OSError:
        bt4 = False
    return 'dev-bt4' if bt4 else 'dev-bt3'


def install_kind():
    """windows-player, linux-player, dev-bt3, dev-bt4 or dev-linux. Lazy, cached, never raises."""
    global _kind
    if _kind is None:
        try:
            _kind = detect_kind(Path(__file__).resolve().parents[1], WINDOWS,
                                Path(__file__).with_name('bt4_preflight.py').is_file())
        except Exception:
            _kind = 'dev-bt3' if WINDOWS else 'dev-linux'
    return _kind


def entry(name, short=False, kind=None):
    """The launcher `name` (ENTRY_NAMES) of this installation, '' when it has none.

    short=True is the in-game form, always the literal PLAY or MOD SETTINGS.
    """
    if short:
        return {'play': 'PLAY', 'mod_settings': 'MOD SETTINGS'}.get(name, '')
    try:
        return ENTRIES[kind or install_kind()][ENTRY_NAMES.index(name)]
    except (KeyError, ValueError):
        return ''


def entries(kind=None):
    """{name: launcher} for every ENTRY_NAMES name (tr(template, **entries()))."""
    return {name: entry(name, kind=kind) for name in ENTRY_NAMES}


# Failure explanations (player_errors) and launcher messages (play_launcher, map_scale_launch, game_profile).
ES.update({
    # player_errors.STOPPED / REASONS / CAUSES / ACTIONS
    'Play could not start': 'Play no se pudo iniciar',
    'Match setup stopped': 'La preparación del combate se ha detenido',
    'The rematch could not be loaded': 'No se pudo cargar la revancha',
    'The return to the menu failed': 'No se pudo volver al menú',
    'Controller setup failed': 'No se pudieron configurar los mandos',
    'Mod settings could not be used': 'No se pudieron usar los ajustes del mod',
    'The mod stopped following the match': 'El mod dejó de seguir el combate',
    'At the main menu': 'En el menú principal',
    'The transformation could not be applied': 'No se pudo aplicar la transformación',
    'The body change could not be applied': 'No se pudo aplicar el cambio de cuerpo',
    'The fusion could not be applied': 'No se pudo aplicar la fusión',
    'The costume change could not be applied': 'No se pudo aplicar el cambio de traje',
    'A fighter update could not be applied': 'No se pudo actualizar un luchador',
    'PCSX2 was closed.': 'PCSX2 se ha cerrado.',
    'the mod lost its connection to PCSX2.': 'el mod perdió la conexión con PCSX2.',
    'a step did not finish in time.': 'un paso no terminó a tiempo.',
    'the disk is full.': 'el disco está lleno.',
    'Windows refused access to a mod file.': 'Windows denegó el acceso a un archivo del mod.',
    'a mod safety check failed.': 'falló una comprobación de seguridad del mod.',
    'an unexpected error occurred.': 'se produjo un error inesperado.',
    'a file or folder name could not be printed.': 'no se pudo mostrar el nombre de un archivo o carpeta.',
    'a mod file is damaged.': 'un archivo del mod está dañado.',
    'PCSX2 stopped responding, crashed or was closed.': 'PCSX2 dejó de responder, falló o se cerró.',
    'The game was paused, the PCSX2 window was minimized, or the PC was busy.':
        'El juego estaba en pausa, la ventana de PCSX2 estaba minimizada o el PC estaba ocupado.',
    'The drive that holds the Tag Team Mod folder has no free space left.':
        'La unidad donde está la carpeta de Tag Team Mod no tiene espacio libre.',
    'OneDrive, an antivirus program or another program locked or blocked a file in the Tag Team Mod folder.':
        'OneDrive, un antivirus u otro programa bloqueó un archivo de la carpeta de Tag Team Mod.',
    'This combination of fighters, stage and disc is not supported, or the mod has a bug.':
        'Esta combinación de luchadores, escenario y disco no es compatible, o el mod tiene un error.',
    'A folder name contains characters this console cannot show.':
        'El nombre de una carpeta tiene caracteres que esta consola no puede mostrar.',
    'The file was cut short or edited by hand.': 'El archivo quedó incompleto o se editó a mano.',
    'Close PCSX2, then start {play} again.': 'Cierra PCSX2 y vuelve a abrir {play}.',
    'Start {play} again when you want to play.': 'Vuelve a abrir {play} cuando quieras jugar.',
    'Close PCSX2, then start {play} again and keep the game running in its window while it loads.':
        'Cierra PCSX2, vuelve a abrir {play} y deja el juego en marcha en su ventana mientras carga.',
    'Free some disk space, close PCSX2, then start {play} again.':
        'Libera espacio en el disco, cierra PCSX2 y vuelve a abrir {play}.',
    'Close PCSX2, pause OneDrive or allow the Tag Team Mod folder in your antivirus, then start {play} again.':
        'Cierra PCSX2, pausa OneDrive o permite la carpeta de Tag Team Mod en tu antivirus y vuelve a abrir {play}.',
    'Close PCSX2, then start {play} again and try other fighters or another stage. If it happens again, send the report file to the mod author.':
        'Cierra PCSX2, vuelve a abrir {play} y prueba otros luchadores u otro escenario. Si vuelve a ocurrir, envía el archivo del informe al autor del mod.',
    'Close PCSX2, then start {play} again. If it happens again, send the report file to the mod author.':
        'Cierra PCSX2 y vuelve a abrir {play}. Si vuelve a ocurrir, envía el archivo del informe al autor del mod.',
    'Move the Tag Team Mod folder to a path with plain letters, then start {play} again.':
        'Mueve la carpeta de Tag Team Mod a una ruta sin caracteres especiales y vuelve a abrir {play}.',
    'Close PCSX2, then start {play} again. If it happens again, install the mod again into a new folder.':
        'Cierra PCSX2 y vuelve a abrir {play}. Si vuelve a ocurrir, instala el mod de nuevo en una carpeta nueva.',
    'You can keep playing. If it happens again, send the report file to the mod author.':
        'Puedes seguir jugando. Si vuelve a ocurrir, envía el archivo del informe al autor del mod.',
    'The file game/mod-settings.json is damaged or comes from an unsupported version.':
        'El archivo game/mod-settings.json está dañado o es de una versión no compatible.',
    'Open {mod_settings} and choose Restore defaults (or delete game/mod-settings.json), then start {play} again.':
        'Abre {mod_settings} y elige Restaurar valores predeterminados (o borra game/mod-settings.json); después vuelve a abrir {play}.',
    # In-game failure covers (ASCII, <= 60 characters, fitted by loading_art_v4).
    'SETUP STOPPED - CLOSE PCSX2, THEN START PLAY AGAIN': 'PREPARACIÓN DETENIDA - CIERRA PCSX2 Y ABRE PLAY DE NUEVO',
    'REMATCH FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'REVANCHA FALLIDA - CIERRA PCSX2 Y ABRE PLAY DE NUEVO',
    'MENU RETURN FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'ERROR AL VOLVER AL MENÚ - CIERRA PCSX2 Y ABRE PLAY',
    'CONTROLLER SETUP FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'ERROR DE MANDOS - CIERRA PCSX2 Y ABRE PLAY DE NUEVO',
    'SETTINGS FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'ERROR DE AJUSTES - CIERRA PCSX2 Y ABRE PLAY DE NUEVO',
    'MOD STOPPED - CLOSE PCSX2, THEN START PLAY AGAIN': 'MOD DETENIDO - CIERRA PCSX2 Y ABRE PLAY DE NUEVO',
    'TRANSFORMATION FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'TRANSFORMACIÓN FALLIDA - CIERRA PCSX2 Y ABRE PLAY',
    'BODY CHANGE FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'CAMBIO DE CUERPO FALLIDO - CIERRA PCSX2 Y ABRE PLAY',
    'FUSION FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'FUSIÓN FALLIDA - CIERRA PCSX2 Y ABRE PLAY DE NUEVO',
    'COSTUME CHANGE FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'CAMBIO DE TRAJE FALLIDO - CIERRA PCSX2 Y ABRE PLAY',
    'FIGHTER UPDATE FAILED - CLOSE PCSX2, THEN START PLAY AGAIN': 'ERROR DE LUCHADOR - CIERRA PCSX2 Y ABRE PLAY DE NUEVO',
    'BACK AT THE MAIN MENU - YOU CAN KEEP PLAYING': 'DE VUELTA EN EL MENÚ PRINCIPAL - PUEDES SEGUIR JUGANDO',
    'FIGHTER UPDATES OFF FOR THIS MATCH': 'ACTUALIZACIONES DE LUCHADOR DESACTIVADAS EN ESTE COMBATE',
    'SOMETHING WENT WRONG - YOU CAN KEEP PLAYING': 'ALGO HA FALLADO - PUEDES SEGUIR JUGANDO',
    'CODE {code} - DETAILS IN THE PLAY WINDOW': 'CÓDIGO {code} - DETALLES EN LA VENTANA DE PLAY',
    # Guest status explanations (fresh_team_trainer.wait_word): the sentence before the technical detail.
    'PCSX2 did not give the game its extra memory': 'PCSX2 no le dio al juego su memoria adicional',
    'The expanded game memory could not be prepared': 'No se pudo preparar la memoria ampliada del juego',
    "A selected fighter's files could not be loaded from the disc": 'No se pudieron cargar del disco los archivos de un luchador elegido',
    'There are not enough model or drawing slots for this roster': 'No hay suficientes huecos de modelo o de dibujo para estos equipos',
    'The game ran out of expanded memory for this roster': 'El juego se quedó sin memoria ampliada para estos equipos',
    'A selected fighter could not be created': 'No se pudo crear un luchador elegido',
    'The graphics buffers could not be expanded': 'No se pudieron ampliar los búferes gráficos',
    'The CPU fighters could not be set up': 'No se pudieron preparar los luchadores de la CPU',
    'A setup step reported an error': 'Un paso de la preparación informó de un error',
    # Launcher failures (play_launcher; launch-autopilot.ps1 carries the same text unaccented).
    'PCSX2 is already running, so Play did not start.': 'PCSX2 ya se está ejecutando, así que Play no se ha iniciado.',
    'Only one PCSX2 can run while the mod plays.': 'Solo puede haber un PCSX2 abierto mientras se juega con el mod.',
    'Close every PCSX2 window (check the taskbar), then start {play} again.':
        'Cierra todas las ventanas de PCSX2 (mira la barra de tareas) y vuelve a abrir {play}.',
    'The game ISO is no longer at its saved location.': 'La ISO del juego ya no está en su ubicación guardada.',
    'It was moved, renamed or deleted, or its drive is not connected.':
        'Se movió, se cambió de nombre o se borró, o su unidad no está conectada.',
    'Put it back or reconnect its drive, or choose its new location when {play} asks.':
        'Vuelve a ponerla en su sitio o conecta su unidad, o elige su nueva ubicación cuando {play} lo pregunte.',
    'The game ISO could not be checked.': 'No se pudo comprobar la ISO del juego.',
    'Read the message above. If the ISO changed, install the mod again into a new folder.':
        'Lee el mensaje de arriba. Si la ISO cambió, instala el mod de nuevo en una carpeta nueva.',
    'A file Play needs is missing.': 'Falta un archivo que Play necesita.',
    'The installation is incomplete, or a security program removed a file.':
        'La instalación está incompleta o un programa de seguridad eliminó un archivo.',
    'Run {check_installation}. If it reports a problem, run {install} and choose the folder of this installation itself '
    '(the one that contains {play}): setup installs a fresh copy beside it and offers to copy your memory cards and mod '
    'settings into it.':
        'Ejecuta {check_installation}. Si indica un problema, ejecuta {install} y elige la propia carpeta de esta '
        'instalación (la que contiene {play}): el instalador crea una copia nueva junto a ella y ofrece copiar en ella '
        'tus tarjetas de memoria y los ajustes del mod.',
    'Restore the missing file, or install the mod again into a new folder.':
        'Recupera el archivo que falta o instala el mod de nuevo en una carpeta nueva.',
    "The mod's private Python (.venv) does not start.": 'El Python privado del mod (.venv) no arranca.',
    'The Python it was made from was removed, upgraded or changed.':
        'El Python con el que se creó se eliminó, se actualizó o cambió.',
    'Run {install} and choose the folder of this installation itself (the one that contains {play}): setup installs a '
    'fresh copy beside it and offers to copy your memory cards and mod settings into it.':
        'Ejecuta {install} y elige la propia carpeta de esta instalación (la que contiene {play}): el instalador crea una '
        'copia nueva junto a ella y ofrece copiar en ella tus tarjetas de memoria y los ajustes del mod.',
    'No Python with the mod packages could start.': 'No se pudo iniciar ningún Python con los paquetes del mod.',
    'Install Python 3.11 or later with the packages the mod needs, then start {play} again.':
        'Instala Python 3.11 o posterior con los paquetes que necesita el mod y vuelve a abrir {play}.',
    'Your mod settings file cannot be read.': 'No se puede leer tu archivo de ajustes del mod.',
    'A game file the mod needs is missing or does not match.': 'Falta un archivo del juego que necesita el mod o no coincide.',
    'This PCSX2 version is not supported.': 'Esta versión de PCSX2 no es compatible.',
    'Install the mod again into a new folder; setup installs a supported PCSX2.':
        'Instala el mod de nuevo en una carpeta nueva; la instalación incluye un PCSX2 compatible.',
    'A PCSX2 setting this installation needs was changed.': 'Se cambió un ajuste de PCSX2 que esta instalación necesita.',
    'Another Play window is still starting or closing.': 'Otra ventana de Play todavía se está iniciando o cerrando.',
    'Close its PCSX2, wait a few seconds, then start {play} again.':
        'Cierra su PCSX2, espera unos segundos y vuelve a abrir {play}.',
    'A startup step failed.': 'Falló un paso del inicio.',
    'Start {play} again. If it happens again, send the saved log file to the mod author.':
        'Vuelve a abrir {play}. Si vuelve a ocurrir, envía el registro guardado al autor del mod.',
    "The mod's helper could not start.": 'El asistente del mod no se pudo iniciar.',
    "The mod's helper did not start in time, so PCSX2 was closed.":
        'El asistente del mod no se inició a tiempo, así que se cerró PCSX2.',
    'The PC was busy, or a security program delayed Python.':
        'El PC estaba ocupado o un programa de seguridad retrasó Python.',
    'Start {play} again.': 'Vuelve a abrir {play}.',
    'PCSX2 closed while Play was starting.': 'PCSX2 se cerró mientras Play se iniciaba.',
    'Read the message above, then start {play} again.': 'Lee el mensaje de arriba y vuelve a abrir {play}.',
    'PCSX2 closed with an error.': 'PCSX2 se cerró con un error.',
    'PCSX2 crashed; a graphics driver problem is the usual cause.':
        'PCSX2 falló; la causa habitual es un problema del controlador gráfico.',
    'Start {play} again. If it keeps happening, update your graphics driver or choose another renderer in PCSX2.':
        'Vuelve a abrir {play}. Si sigue pasando, actualiza el controlador gráfico o elige otro renderizador en PCSX2.',
    "The mod's helper stopped during the session.": 'El asistente del mod se detuvo durante la sesión.',
    'Close PCSX2, then start {play} again. If it happens again, send the log folder to the mod author.':
        'Cierra PCSX2 y vuelve a abrir {play}. Si vuelve a ocurrir, envía la carpeta de registros al autor del mod.',
    'The session ended after an error.': 'La sesión terminó después de un error.',
    'The expanded-map ISO could not be selected.': 'No se pudo elegir la ISO de mapas ampliados.',
    'Read the message above. Turn expanded maps off in {mod_settings}, or build them again.':
        'Lee el mensaje de arriba. Desactiva los mapas ampliados en {mod_settings} o vuelve a crearlos.',
    'Play stopped because of an unexpected error.': 'Play se detuvo por un error inesperado.',
    'A PCSX2 opened while Play was starting.': 'Se abrió un PCSX2 mientras Play se iniciaba.',
    'Close it, then start {play} again.': 'Ciérralo y vuelve a abrir {play}.',
    'The chosen file is not the installed game ISO.': 'El archivo elegido no es la ISO del juego instalada.',
    'Only the same ISO file (same contents) can be used.': 'Solo se puede usar el mismo archivo ISO (el mismo contenido).',
    'Choose the ISO you installed the mod with, or install the mod again into a new folder for another ISO.':
        'Elige la ISO con la que instalaste el mod o, para otra ISO, instala el mod de nuevo en una carpeta nueva.',
    'The Mod settings window could not finish.': 'La ventana de ajustes del mod no pudo terminar.',
    'No Python with Tk could open Mod settings.': 'Ningún Python con Tk pudo abrir los ajustes del mod.',
    'Where is the game ISO now? Type its full path and press Enter (empty: stop): ':
        '¿Dónde está ahora la ISO del juego? Escribe su ruta completa y pulsa Intro (vacío: salir): ',
    'Game ISO found. Play continues with {path}': 'ISO del juego encontrada. Play continúa con {path}',
    'The session ended after an error. Details are above and in the report file.':
        'La sesión terminó después de un error. Los detalles están arriba y en el archivo del informe.',
    'A problem was handled during the session; you could keep playing.':
        'Se resolvió un problema durante la sesión; pudiste seguir jugando.',
    # Launch hints (play_launcher.hint_lines; launch-autopilot.ps1 prints the same lines).
    'Opening a clean game with automatic simultaneous-team preparation.':
        'Abriendo el juego limpio con la preparación automática de equipos simultáneos.',
    'Choose Team Battle, Free-for-all, or Modded Training in the modded main menu, including three- and four-player modes.':
        'Elige Por equipos, Todos contra todos o Entrenamiento mod en el menú principal del mod, también en los modos de tres y cuatro jugadores.',
    'Original-menu selections play normally; only a Modded Modes selection activates the trainer.':
        'Lo que elijas en el menú original se juega con normalidad; solo los modos del mod activan el entrenador.',
    "Choose each player's team before selecting fighters. Share a team for cooperative play against CPUs.":
        'Elige el equipo de cada jugador antes de seleccionar luchadores. Compartid equipo para jugar en cooperativo contra la CPU.',
    'Team Battle and Training let you assign each controller to either team before selecting fighters. Share a team for co-op; CPU slots are selected by Player 1. FFA needs at least one fighter per human.':
        'Por equipos y Entrenamiento permiten asignar cada mando a un equipo antes de elegir luchadores. Compartid equipo para el cooperativo; el jugador 1 elige las casillas de la CPU. Todos contra todos necesita al menos un luchador por jugador.',
    'A loading screen prepares every fighter and the full team display before the match begins.':
        'Una pantalla de carga prepara a todos los luchadores y los equipos completos antes del combate.',
    'Target/spectator switch: tap {button}.': 'Cambio de objetivo/luchador observado: pulsa {button}.',
    'Target/spectator switch: hold {button} for {seconds} seconds, then release.':
        'Cambio de objetivo/luchador observado: mantén {button} {seconds} segundos y suelta.',
    'Hold {button} and flick the right stick to pick a target; left/right steps around you.':
        'Mantén {button} y mueve el stick derecho para elegir objetivo; izquierda/derecha recorre a tu alrededor.',
    'Flick the right stick to pick a target while locked on; left/right steps around you.':
        'Mueve el stick derecho para elegir objetivo mientras lo tienes fijado; izquierda/derecha recorre a tu alrededor.',
    'Developer folder: {count} settings differ from a new installation: {keys}. Details: python tools/dev_settings_parity.py --report':
        'Carpeta de desarrollo: {count} ajustes difieren de una instalación nueva: {keys}. Detalles: python tools/dev_settings_parity.py --report',
    'Developer folder: 1 setting differs from a new installation: {keys}. Details: python tools/dev_settings_parity.py --report':
        'Carpeta de desarrollo: 1 ajuste difiere de una instalación nueva: {keys}. Detalles: python tools/dev_settings_parity.py --report',
    'During an attack warning, tap {button} to lock on to your attacker.': 'Con aviso de ataque, pulsa {button} para fijar a tu atacante.',
    'During an attack warning, your {button} target switch locks on to your attacker.':
        'Con aviso de ataque, tu cambio de objetivo con {button} fija a tu atacante.',
    'After defeat, watch a living CPU teammate and press Square to take over (L2+Square if Square is your target-switch button). Not available in FFA or CPU-only matches.':
        'Tras ser derrotado, observa a un aliado CPU vivo y pulsa Cuadrado para controlarlo (L2+Cuadrado si Cuadrado es tu botón de cambio de objetivo). No disponible en Todos contra todos ni en combates solo CPU.',
    'Fight Again reloads the prepared match with the button it was prepared with.':
        'Fight Again recarga el combate preparado con el botón con el que se preparó.',
    '{mod_settings} controls which game disc {play} starts, pauses, cinematics, fusion controls, display options and target-switch input/timing.':
        '{mod_settings} controla el disco del juego que inicia {play}, las pausas, las cinemáticas, los controles de fusión, las opciones de pantalla y el botón y tiempo de cambio de objetivo.',
    'Preparation status and errors remain in this window. Logs: {logs}':
        'El estado de la preparación y los errores se quedan en esta ventana. Registros: {logs}',
    'Manual pause mode: follow the Space instructions in this window.':
        'Modo de pausa manual: sigue las instrucciones de Espacio en esta ventana.',
    # Expanded maps, compatibility scan and ISO relink (map_scale_launch, game_profile).
    'Expanded maps built: {path}': 'Mapas ampliados creados: {path}',
    'Compatibility report updated: {path}': 'Informe de compatibilidad actualizado: {path}',
    'Checking the game ISO: {percent}%': 'Comprobando la ISO del juego: {percent}%',
    'The game ISO is linked again: {path}': 'La ISO del juego vuelve a estar enlazada: {path}',
    'Expanded maps are on: build them again with {build_expanded_maps} (they were made from the old location).':
        'Los mapas ampliados están activados: vuelve a crearlos con {build_expanded_maps} (se hicieron desde la ubicación anterior).',
    'This installation has no game profile; only an installed mod can relink its ISO.':
        'Esta instalación no tiene perfil de juego; solo un mod instalado puede volver a enlazar su ISO.',
    'The chosen file is not the installed game ISO (its contents differ).':
        'El archivo elegido no es la ISO del juego instalada (su contenido es distinto).',
})

# Wording for other groups' messages (autopilot run(), native_preparation, extra_reload_worker,
# controller_mailbox, guest_loading_screen.sync). Their owners use exactly these English keys.
ES.update({
    'This PCSX2 already carries changes from an earlier preparation. Close PCSX2, then start {play} again for a new roster.':
        'Este PCSX2 ya tiene cambios de una preparación anterior. Cierra PCSX2 y vuelve a abrir {play} para elegir otros equipos.',
    'The mod preparation service is not installed in this PCSX2. Close PCSX2, then start {play} again.':
        'El servicio de preparación del mod no está instalado en este PCSX2. Cierra PCSX2 y vuelve a abrir {play}.',
    'The fighter update service is not installed in this PCSX2. Close PCSX2, then start {play} again.':
        'El servicio de actualización de luchadores no está instalado en este PCSX2. Cierra PCSX2 y vuelve a abrir {play}.',
    'Controllers 3 and 4 cannot be read: Windows refused access to PCSX2. Do not run PCSX2 or Play as administrator, then start {play} again.':
        'No se pueden leer los mandos 3 y 4: Windows denegó el acceso a PCSX2. No ejecutes PCSX2 ni Play como administrador y vuelve a abrir {play}.',
    'In-game loading screen code differs at {address}; close PCSX2 and start {play} again.':
        'El código de la pantalla de carga es distinto en {address}; cierra PCSX2 y vuelve a abrir {play}.',
})


# Launcher refusals and the ISO relink (play_launcher, game_profile), second pass.
ES.update({
    'Another program is using the connection port Play needs.':
        'Otro programa está usando el puerto de conexión que Play necesita.',
    'Close that program, then start {play} again.': 'Cierra ese programa y vuelve a abrir {play}.',
    'The private Python starts, but a package the mod needs is missing or damaged.':
        'El Python privado arranca, pero falta un paquete que necesita el mod o está dañado.',
    'The chosen file cannot be opened.': 'No se puede abrir el archivo elegido.',
    'The path is mistyped, or the file was moved or its drive is not connected.':
        'La ruta está mal escrita, o el archivo se movió o su unidad no está conectada.',
    'Check the path, then start {play} again and choose the game ISO again.':
        'Comprueba la ruta, vuelve a abrir {play} y elige otra vez la ISO del juego.',
})


# BT4 only (compatibility_profile.py), carried with beta.33: a missing ISO compatibility profile.
ES.update({
    'The BT4 ISO compatibility profile is missing or outdated. Close PCSX2, then start {play} again to scan the ISO again.':
        'El perfil de compatibilidad de la ISO de BT4 falta o está desactualizado. Cierra PCSX2 y vuelve a abrir {play} para analizar la ISO de nuevo.',
})


# Beta.33 round 2: the watcher's own detections (player_errors.Detected: a frozen match, a released cinematic
# pause, a game restart, a slow PCSX2), the FAILED-at-menus notice, the 3-4 player notices, a fighter that was
# not idle at placement (spawn_placement.NOT_IDLE) and the Play window's helper line (play_launcher).
ES.update({
    'At the main menu, the Modded Modes menu rejected a choice and was reset.':
        'En el menú principal, el menú Modos del mod rechazó una opción y se ha reiniciado.',
    'Choose your mode again in Modded Modes.': 'Vuelve a elegir tu modo en los Modos del mod.',
    "At the main menu, the Modded Modes menu stopped; the game's own menus still work.":
        'En el menú principal, el menú Modos del mod se ha detenido; los menús del juego siguen funcionando.',
    'You can keep playing the original modes. To use Modded Modes again, close PCSX2, then start {play} again.':
        'Puedes seguir jugando los modos originales. Para volver a usar los Modos del mod, cierra PCSX2 y vuelve a '
        'abrir {play}.',
    "Original-menu match: the game plays it normally, without the mod's team setup.":
        'Combate del menú original: el juego lo juega con normalidad, sin la preparación de equipos del mod.',
    'Three/four-player input unavailable: {detail}. Players 3 and 4 (and the all-controllers option) cannot use their '
    'controllers on this selection screen; players 1 and 2 are not affected.':
        'Los jugadores 3 y 4 no tienen entrada: {detail}. Los jugadores 3 y 4 (y la opción de todos los mandos) no '
        'pueden usar sus mandos en esta pantalla de selección; los jugadores 1 y 2 no se ven afectados.',
    'Three/four-player input unavailable: {detail}. Players 3 and 4 (and the all-controllers option) cannot use their '
    'controllers yet (trying again); players 1 and 2 are not affected.':
        'Los jugadores 3 y 4 no tienen entrada: {detail}. Los jugadores 3 y 4 (y la opción de todos los mandos) aún no '
        'pueden usar sus mandos (se vuelve a intentar); los jugadores 1 y 2 no se ven afectados.',
    'Controller assignment stopped: {detail}. Default controls are restored (players 1 and 2 use their PCSX2 '
    'controllers); assign controllers again in Player Setup.':
        'La asignación de mandos se detuvo: {detail}. Se restauraron los controles predeterminados (los jugadores 1 y 2 '
        'usan sus mandos de PCSX2); vuelve a asignar los mandos en Configurar jugadores.',
    '3-4 player input stopped: {detail}. Players 3 and 4 cannot use their controllers in this match; the match goes on '
    'and players 1 and 2 are not affected.':
        'La entrada de los jugadores 3 y 4 se detuvo: {detail}. Los jugadores 3 y 4 no pueden usar sus mandos en este '
        'combate; el combate sigue y los jugadores 1 y 2 no se ven afectados.',
    'The game is in its menus now, but the mod stays stopped after this error, so no modded match can start:':
        'El juego está ahora en sus menús, pero el mod sigue detenido por este error, así que no puede empezar ningún '
        'combate del mod:',
    'The game stopped responding during the match: its picture did not change for 5 seconds while PCSX2 was running.':
        'El juego dejó de responder durante el combate: su imagen no cambió durante 5 segundos mientras PCSX2 estaba en '
        'marcha.',
    'The game hung inside the match, a rare problem of the mod with some moves, effects or rosters that is not fixed '
    'yet.':
        'El juego se bloqueó dentro del combate, un problema poco frecuente del mod con algunos movimientos, efectos '
        'o equipos que aún no está corregido.',
    'Close PCSX2, then start {play} again. So that the next freeze can be fixed, open {mod_settings}, choose Diagnostics '
    'and turn on "Save a large diagnostic snapshot if a match freezes"; then send the snapshot and the report file to '
    'the mod author.':
        'Cierra PCSX2 y vuelve a abrir {play}. Para que el próximo bloqueo se pueda corregir, abre {mod_settings}, elige '
        'Diagnóstico y activa «Guardar un volcado de diagnóstico si se bloquea el combate»; después envía el volcado y el '
        'archivo del informe al autor del mod.',
    'Close PCSX2, then start {play} again. Send the report file and the diagnostic snapshot it names to the mod author.':
        'Cierra PCSX2 y vuelve a abrir {play}. Envía al autor del mod el archivo del informe y el volcado de diagnóstico '
        'que indica.',
    'The game is drawing again after it stopped responding; the match goes on.':
        'El juego vuelve a dibujar después de dejar de responder; el combate sigue.',
    'The game stopped responding. Saving a diagnostic snapshot; this takes a moment.':
        'El juego dejó de responder. Guardando un volcado de diagnóstico; tarda un momento.',
    'The game stopped drawing while the match was starting. Saving a diagnostic snapshot; this takes a moment.':
        'El juego dejó de dibujar mientras empezaba el combate. Guardando un volcado de diagnóstico; tarda un momento.',
    'Diagnostic snapshot saved: {path}': 'Volcado de diagnóstico guardado: {path}',
    'A cinematic pause did not end on its own, so the mod released it; the fighters are moving again.':
        'Una pausa cinemática no terminó sola, así que el mod la liberó; los luchadores vuelven a moverse.',
    'A special move or transformation held every fighter for longer than its limit.':
        'Un movimiento especial o una transformación mantuvo detenidos a todos los luchadores más tiempo del límite.',
    'You can keep playing. If it happens again, note which move was used and send the report file to the mod author.':
        'Puedes seguir jugando. Si vuelve a ocurrir, apunta qué movimiento se usó y envía el archivo del informe al autor '
        'del mod.',
    'The game restarted during the match, so the mod loaded the clean main menu.':
        'El juego se reinició durante el combate, así que el mod cargó el menú principal limpio.',
    'PCSX2 was reset, or the game rebooted itself (for example after a crash).':
        'PCSX2 se reinició, o el juego se reinició solo (por ejemplo, tras un fallo).',
    'You can keep playing: choose your next match. If it happens again, send the report file to the mod author.':
        'Puedes seguir jugando: elige tu siguiente combate. Si vuelve a ocurrir, envía el archivo del informe al autor '
        'del mod.',
    'PCSX2 did not answer the mod several times in a row in the menus; the mod keeps trying.':
        'PCSX2 no respondió al mod varias veces seguidas en los menús; el mod sigue intentándolo.',
    'PCSX2 did not answer the mod several times in a row while a match was starting; the mod keeps trying.':
        'PCSX2 no respondió al mod varias veces seguidas mientras empezaba un combate; el mod sigue intentándolo.',
    'PCSX2 was busy (loading, an open settings window or a slow PC), or its connection dropped for a moment.':
        'PCSX2 estaba ocupado (cargando, con una ventana de ajustes abierta o en un PC lento), o su conexión se cortó un '
        'momento.',
    'You can keep playing. If no modded match starts, close PCSX2, then start {play} again.':
        'Puedes seguir jugando. Si no empieza ningún combate del mod, cierra PCSX2 y vuelve a abrir {play}.',
    'One of the fighters was still moving when the extra fighters were placed, so this match could not be set up. '
    'Close PCSX2, start {play} again, then choose the teams again in character selection.':
        'Uno de los luchadores seguía moviéndose cuando se colocaron los luchadores extra, así que no se pudo preparar '
        'este combate. Cierra PCSX2, vuelve a abrir {play} y elige de nuevo los equipos en la selección de personajes.',
    "[TTM-PLAY-37] The mod's helper stopped (exit {code}), so the mod no longer prepares matches in this session. "
    'Close PCSX2, then start {play} again. Logs: {logs}':
        '[TTM-PLAY-37] El asistente del mod se detuvo (salida {code}), así que el mod ya no prepara combates en esta '
        'sesión. Cierra PCSX2 y vuelve a abrir {play}. Registros: {logs}',
})


# Beta.33 round 4: the Play window's routine lines (autopilot say()/say_text(): a new match, the match and the rematch
# ready, the menus, the connection to PCSX2, the Modded Modes choice, the pending reasons, the closed-PCSX2 notice) and
# the untested-version notice (play_launcher; launch-autopilot.ps1 carries it unaccented).
ES.update({
    'New {teams} match: getting every fighter ready. They stay still until the match starts.':
        'Combate nuevo {teams}: preparando a todos los luchadores. Se quedan quietos hasta que empiece el combate.',
    'New {teams} match: press Space in the game window to pause it, so every fighter can be loaded.':
        'Combate nuevo {teams}: pulsa Espacio en la ventana del juego para pausarlo y poder cargar a todos los luchadores.',
    # beta.34: a free-for-all counts its fighters (autopilot.SAY_FRESH_FFA, SAY_FRESH_FFA_PAUSE).
    'New free-for-all with {count} fighters: getting every fighter ready. They stay still until the match starts.':
        'Combate nuevo de todos contra todos con {count} luchadores: preparando a todos los luchadores. Se quedan quietos '
        'hasta que empiece el combate.',
    'New free-for-all with {count} fighters: press Space in the game window to pause it, so every fighter can be loaded.':
        'Combate nuevo de todos contra todos con {count} luchadores: pulsa Espacio en la ventana del juego para '
        'pausarlo y poder cargar a todos los luchadores.',
    'PCSX2 did not confirm the automatic pause. Press Space in the game window to start loading your fighters.':
        'PCSX2 no confirmó la pausa automática. Pulsa Espacio en la ventana del juego para empezar a cargar a tus '
        'luchadores.',
    'The match is ready: every fighter is on the field.': 'El combate está listo: todos los luchadores están en el campo.',
    'Fight Again: loading the prepared match again.': 'Revancha: cargando de nuevo el combate preparado.',
    'The rematch is ready.': 'La revancha está lista.',
    'Fight Again stopped: PCSX2 is closing or its game was shut down.':
        'Revancha detenida: PCSX2 se está cerrando o su juego se apagó.',
    'The game is running again; loading your fighters continues.':
        'El juego vuelve a estar en marcha; la carga de tus luchadores continúa.',
    'The game is paused while your fighters load; PCSX2 was asked to resume it.':
        'El juego está en pausa mientras se cargan tus luchadores; se ha pedido a PCSX2 que lo reanude.',
    'The game is paused while your fighters load. Resume it with Space (or System > Resume in PCSX2).':
        'El juego está en pausa mientras se cargan tus luchadores. Reanúdalo con Espacio (o Sistema > Reanudar en PCSX2).',
    'Waiting for the game to hold the fighters for loading.':
        'Esperando a que el juego detenga a los luchadores para cargarlos.',
    '1v1 match: the game plays it normally.': 'Combate 1v1: el juego lo juega con normalidad.',
    'This {teams} match has more than {capacity} fighters on a side, so it plays as a normal tag match.':
        'Este combate {teams} tiene más de {capacity} luchadores en un equipo, así que se juega como un combate por '
        'relevos normal.',
    'Back at the main menu.': 'De vuelta en el menú principal.',
    'Back at character selection.': 'De vuelta en la selección de personajes.',
    'Returning to the menu once the previous step finishes.': 'Se vuelve al menú en cuanto termine el paso anterior.',
    'Saving the menu the mod returns to after a match is delayed ({error}); trying again.':
        'Se retrasa el guardado del menú al que vuelve el mod tras un combate ({error}); se vuelve a intentar.',
    'PCSX2 was paused in the menus; resuming it.': 'PCSX2 estaba en pausa en los menús; se reanuda.',
    'Waiting for PCSX2 to start the game.': 'Esperando a que PCSX2 inicie el juego.',
    'Waiting for PCSX2 to start the installed game ({expected}); it shows {serial} (CRC {crc}).':
        'Esperando a que PCSX2 inicie el juego instalado ({expected}); muestra {serial} (CRC {crc}).',
    'The connection to PCSX2 did not answer ({error}); trying again.':
        'La conexión con PCSX2 no respondió ({error}); se vuelve a intentar.',
    'The mod cannot use this PCSX2 ({error}).': 'El mod no puede usar este PCSX2 ({error}).',
    'Modded Modes: {mode}, {players}.': 'Modos del mod: {mode}, {players}.',
    # Also said on every arrival at the main menu (the pager arms its stock page there): a state, not a choice.
    "Original game menu: its matches play normally, without the mod's team setup.":
        'Menú original del juego: sus combates se juegan con normalidad, sin la preparación de equipos del mod.',
    # fresh_team_trainer.Session.wait_word: the preparation steps (reports keep the English step name)
    'Preparing expanded game memory...': 'Preparando la memoria ampliada del juego...',
    'Loading selected character resources...': 'Cargando los archivos de los personajes elegidos...',
    'Creating independent fighters...': 'Creando los luchadores independientes...',
    'Checking rendering...': 'Comprobando los gráficos...',
    'Expanding render object capacity...': 'Ampliando la capacidad de objetos en pantalla...',
    'Expanding graphics buffers...': 'Ampliando la memoria gráfica...',
    'Initializing individual NPCs...': 'Preparando a cada luchador de la CPU...',
    'Preparing dust and terrain effects...': 'Preparando los efectos de polvo y de terreno...',
    "Preparing each fighter's cosmetic effects...": 'Preparando los efectos visuales de cada luchador...',
    'Preparing afterimages and giant auras...': 'Preparando las estelas y las auras gigantes...',
    'Preparing fighter auras...': 'Preparando las auras de los luchadores...',
    'Preparing individual special effects...': 'Preparando los efectos especiales de cada luchador...',
    'Placing fighters on the arena terrain...': 'Colocando a los luchadores sobre el terreno del escenario...',
    'Checking selected fighter participation...': 'Comprobando que participen los luchadores elegidos...',
    # game_profile.scan_progress: the ISO check's progress ('Checking the game ISO: {percent}%' above)
    'Checking fighter resources: {done}/{total}': 'Comprobando los recursos de los luchadores: {done}/{total}',
    'Checking stage resources: {done}/{total}': 'Comprobando los recursos de los escenarios: {done}/{total}',
    # play_launcher.STEP_RETRY (launcher-lifecycle.ps1 'step.retry')
    'That startup step failed; retrying it once.': 'Ese paso del inicio ha fallado; se vuelve a intentar una vez.',
    'Co-op training': 'Entrenamiento cooperativo',
    # autopilot.Observation.pending_reason
    'Waiting in the game menus until a match starts.': 'Esperando en los menús del juego hasta que empiece un combate.',
    'This game mode is not one the mod prepares, so it plays normally.':
        'El mod no prepara este modo de juego, así que se juega con normalidad.',
    'Replay playback: the mod does not change replays.': 'Repetición: el mod no cambia las repeticiones.',
    'Waiting for the battle to finish loading.': 'Esperando a que termine de cargar el combate.',
    'Waiting for both team leaders and their selected teams to initialize.':
        'Esperando a que se preparen los dos líderes y sus equipos elegidos.',
    'Waiting for valid selected rosters.': 'Esperando a que los equipos elegidos sean válidos.',
    'A leader already tagged or was replaced; start a fresh match.':
        'Un líder ya hizo un relevo o fue sustituido; empieza un combate nuevo.',
    'A leader is already defeated; start a fresh match.': 'Un líder ya está derrotado; empieza un combate nuevo.',
    # runtime_owner.EmulatorClosed
    'PCSX2 was closed': 'PCSX2 se ha cerrado',
    "PCSX2 was closed; the mod's helper stops with it": 'PCSX2 se ha cerrado; el asistente del mod se detiene con él',
    # play_launcher.UNTESTED_VERSION
    'PCSX2 {version} is not one of the supported stable releases ({tested}). It is allowed; report any problem with this '
    'version.':
        'PCSX2 {version} no es una de las versiones estables compatibles ({tested}). Se permite; informa de cualquier '
        'problema con esta versión.',
})


# Mod settings > Game disc (disc_library, disc_page, game_profile, map_scale_launch, the launchers).
# The known_discs refusal texts and disc names are the same Spanish as the installer (installer-es.json;
# a test compares them).
ES.update({
    'The selected ISO is {disc}. This release is not supported.':
        'La ISO elegida es {disc}. Esta versión no es compatible.',
    'The selected ISO is {disc}, but its game executable differs from the original disc. Modified executables are not supported; select an unmodified image of the disc.':
        'La ISO elegida es {disc}, pero su ejecutable del juego no coincide con el del disco original. Los ejecutables modificados no son compatibles; elige una imagen sin modificar del disco.',
    'The selected ISO is {disc}, but its menu and game code (BIN/DBZP.BIN) differs from the original disc. Modified game code is not supported; select an unmodified image of the disc.':
        'La ISO elegida es {disc}, pero su código de menús y juego (BIN/DBZP.BIN) no coincide con el del disco original. El código modificado no es compatible; elige una imagen sin modificar del disco.',
    'The selected ISO boots the executable of {disc}, but its data files are not laid out like that disc. Modified discs are not supported; select an unmodified image of the disc.':
        'La ISO elegida arranca el ejecutable de {disc}, pero sus archivos de datos no están organizados como en ese disco. Los discos modificados no son compatibles; elige una imagen sin modificar del disco.',
    'The selected ISO is a Budokai Tenkaichi 4 build other than B14 REV2 English / Spanish ({serial}). Only that BT4 build is supported.':
        'La ISO elegida es una versión de Budokai Tenkaichi 4 distinta de B14 REV2 en inglés o español ({serial}). Solo es compatible esa versión de BT4.',
    'The selected ISO looks like a Budokai Tenkaichi 3 family disc ({serial}) that has no reviewed adapter.':
        'La ISO elegida parece un disco de la familia Budokai Tenkaichi 3 ({serial}) sin un adaptador revisado.',
    'The selected ISO ({serial}) is not a supported game.':
        'La ISO elegida ({serial}) no es un juego compatible.',
    'Budokai Tenkaichi 3 USA (SLUS-21678)':
        'Budokai Tenkaichi 3 de EE. UU. (SLUS-21678)',
    'Budokai Tenkaichi 3 Europe (SLES-54945)':
        'Budokai Tenkaichi 3 de Europa (SLES-54945)',
    'Budokai Tenkaichi 3 Japan (SLPS-25815)':
        'Budokai Tenkaichi 3 de Japón (SLPS-25815)',
    'Dragon Ball Z: Sparking! Meteor, the Japanese Budokai Tenkaichi 3 (SLPS-25815)':
        'Dragon Ball Z: Sparking! Meteor, el Budokai Tenkaichi 3 japonés (SLPS-25815)',
    'the Japanese Dragon Ball Z: Sparking! Meteor demo (SLPM-61162)':
        'la demo japonesa de Dragon Ball Z: Sparking! Meteor (SLPM-61162)',
    'Supported discs: Budokai Tenkaichi 3 USA (SLUS-21678), Europe (SLES-54945) or Japan (SLPS-25815, Sparking! Meteor), and Budokai Tenkaichi 4 B14 REV2 English / Spanish.':
        'Discos compatibles: Budokai Tenkaichi 3 de EE. UU. (SLUS-21678), de Europa (SLES-54945) o de Japón (SLPS-25815, Sparking! Meteor), y Budokai Tenkaichi 4 B14 REV2 en inglés o español.',
    'Selected ISO changed since installation. Add it in {mod_settings} > Game disc to refresh portraits, resources and native references, or put the original ISO back.':
        'La ISO elegida cambió después de la instalación. Añádela en {mod_settings} > Disco del juego para actualizar los retratos, los recursos y las referencias del juego, o vuelve a poner la ISO original.',
    'The ISO of {disc} changed since it was added. Add it again in {mod_settings} > Game disc.':
        'La ISO de {disc} cambió después de añadirla. Vuelve a añadirla en {mod_settings} > Disco del juego.',
    'The game disc chosen in {mod_settings} cannot be used.':
        'No se puede usar el disco del juego elegido en {mod_settings}.',
    'The game disc chosen in {mod_settings} cannot be used; see the message above.':
        'No se puede usar el disco del juego elegido en {mod_settings}; lee el mensaje de arriba.',
    'Try again in {mod_settings} > Game disc. If it happens again, send this block to the mod author.':
        'Vuelve a intentarlo en {mod_settings} > Disco del juego. Si vuelve a ocurrir, envía este bloque al autor del mod.',
    'Free some disk space, then try again in {mod_settings} > Game disc.':
        'Libera espacio en disco y vuelve a intentarlo en {mod_settings} > Disco del juego.',
    'Pause OneDrive or allow the Tag Team Mod folder in your antivirus, then try again in {mod_settings} > Game disc.':
        'Pausa OneDrive o permite la carpeta de Tag Team Mod en tu antivirus y vuelve a intentarlo en {mod_settings} > Disco del juego.',
    'Try again in {mod_settings} > Game disc. If it happens again, install the mod again into a new folder.':
        'Vuelve a intentarlo en {mod_settings} > Disco del juego. Si vuelve a ocurrir, instala el mod de nuevo en una carpeta nueva.',
    'Move the Tag Team Mod folder to a path with plain letters, then try again in {mod_settings} > Game disc.':
        'Mueve la carpeta de Tag Team Mod a una ruta con letras sencillas y vuelve a intentarlo en {mod_settings} > Disco del juego.',
    'Its extracted files are missing or changed, or the selection file game/discs/active.json is damaged.':
        'Faltan sus archivos extraídos o han cambiado, o el archivo de selección game/discs/active.json está dañado.',
    'Open {mod_settings} > Game disc and choose a disc again (the disc you installed with always works), then start {play} again.':
        'Abre {mod_settings} > Disco del juego y vuelve a elegir un disco (el disco con el que instalaste siempre funciona); después vuelve a abrir {play}.',
    'Choose the same ISO file again, or add another ISO in {mod_settings} > Game disc.':
        'Vuelve a elegir el mismo archivo ISO, o añade otra ISO en {mod_settings} > Disco del juego.',
    'Read the message above. If you replaced the ISO, add the new file in {mod_settings} > Game disc and use it.':
        'Lee el mensaje de arriba. Si sustituiste la ISO, añade el archivo nuevo en {mod_settings} > Disco del juego y úsalo.',
    'Game disc: {disc}':
        'Disco del juego: {disc}',
    # bt4_preflight.READY, SCANNED, LABELS (the Play window and Check installation of a BT4 installation).
    'BT4 B14 REV2 disc verified; independent profile, memory cards and PINE port {port} ready.':
        'Disco BT4 B14 REV2 verificado; perfil independiente, tarjetas de memoria y puerto PINE {port} listos.',
    'Compatibility scan: {fighters} fighters; {valid}/{total} costume variants validated. Unusable costumes are rejected before extra creation.':
        'Análisis de compatibilidad: {fighters} luchadores; {valid}/{total} variantes de traje validadas. Los trajes no utilizables se rechazan antes de crear luchadores extra.',
    'Battle labels verified for {count} character/form entries.':
        'Etiquetas de combate verificadas para {count} entradas de personaje o forma.',
    'Game disc: {disc}. To start another of your ISOs, close PCSX2 and choose it in {mod_settings} > Game disc.':
        'Disco del juego: {disc}. Para iniciar otra de tus ISO, cierra PCSX2 y elígela en {mod_settings} > Disco del juego.',
    'ISO: {path}':
        'ISO: {path}',
    'This game disc was added although its stage files differ from the original disc, so expanded maps are not built from it.':
        'Este disco del juego se añadió aunque sus archivos de escenarios difieren del disco original, así que no se crean mapas ampliados a partir de él.',
    'Expanded maps are already being built or deleted for this game disc. Wait for it to finish.':
        'Ya se están creando o borrando los mapas ampliados de este disco del juego. Espera a que termine.',
    'The game disc could not be changed':
        'No se pudo cambiar el disco del juego',
    'Budokai Tenkaichi 4 B14 REV2 English (SLUS-21978)':
        'Budokai Tenkaichi 4 B14 REV2 en inglés (SLUS-21978)',
    'Budokai Tenkaichi 4 B14 REV2 Spanish (SLUS-21978)':
        'Budokai Tenkaichi 4 B14 REV2 en español (SLUS-21978)',
    'USA':
        'EE. UU.',
    'Europe':
        'Europa',
    'Japan':
        'Japón',
    'English':
        'Inglés',
    'Spanish':
        'Español',
    'Budokai Tenkaichi 3 (USA, Europe or Japan)':
        'Budokai Tenkaichi 3 (EE. UU., Europa o Japón)',
    'Budokai Tenkaichi 4 B14 REV2 (English or Spanish)':
        'Budokai Tenkaichi 4 B14 REV2 (inglés o español)',
    "The game disc cannot be changed while {play} or this installation's PCSX2 is open.":
        'No se puede cambiar el disco del juego mientras {play} o el PCSX2 de esta instalación estén abiertos.',
    'The running session uses the current disc until PCSX2 closes.':
        'La sesión en curso usa el disco actual hasta que se cierra PCSX2.',
    'Close PCSX2 and wait for the {play} window to close, then try again.':
        'Cierra PCSX2 y espera a que se cierre la ventana de {play}; después vuelve a intentarlo.',
    'This disc is {disc}, but this installation runs {family}.':
        'Este disco es {disc}, pero esta instalación ejecuta {family}.',
    'An installation contains the mod for one game only; the other game needs its own mod files, PCSX2 profile and settings.':
        'Una instalación contiene el mod de un solo juego; el otro juego necesita sus propios archivos del mod, su perfil de PCSX2 y sus ajustes.',
    'Install the mod for that disc into a new folder with {install} from the release download. Setup can copy your memory cards; each installation keeps its own discs and settings.':
        'Instala el mod para ese disco en una carpeta nueva con {install} de la descarga de la versión. El instalador puede copiar tus tarjetas de memoria; cada instalación conserva sus propios discos y ajustes.',
    '{disc} is not enabled in this release of the mod.':
        '{disc} no está habilitado en esta versión del mod.',
    'This release was published without support for that disc.':
        'Esta versión se publicó sin compatibilidad con ese disco.',
    'Use another disc, or install a release that supports it into a new folder.':
        'Usa otro disco, o instala en una carpeta nueva una versión que lo admita.',
    'The extracted files of {disc} are missing or changed.':
        'Faltan los archivos extraídos de {disc} o han cambiado.',
    'A file in its folder game/discs/{key} was deleted or edited, or copying it was interrupted.':
        'Se borró o se modificó un archivo de su carpeta game/discs/{key}, o se interrumpió su copia.',
    'In {mod_settings} > Game disc, choose Add ISO… and select that ISO again (its files are extracted again), or use another disc.':
        'En {mod_settings} > Disco del juego, elige Añadir ISO… y vuelve a seleccionar esa ISO (sus archivos se extraen de nuevo), o usa otro disco.',
    'The ISO of {disc} is no longer at its saved location.':
        'La ISO de {disc} ya no está en su ubicación guardada.',
    'Reconnect its drive, or choose Find ISO… and select the same ISO at its new location.':
        'Conecta su unidad, o elige Buscar ISO… y selecciona la misma ISO en su nueva ubicación.',
    'The chosen file is not the ISO of {disc}.':
        'El archivo elegido no es la ISO de {disc}.',
    'Only the same ISO file (same contents) can be found again.':
        'Solo se puede volver a encontrar el mismo archivo ISO (con el mismo contenido).',
    "Choose that disc's ISO, or add the other file as a new disc with Add ISO….":
        'Elige la ISO de ese disco, o añade el otro archivo como un disco nuevo con Añadir ISO….',
    'The mod could not be prepared for {disc}.':
        'No se pudo preparar el mod para {disc}.',
    "A check of the mod's game files with this disc failed, so the disc was not added or selected.":
        'Falló una comprobación de los archivos del mod con este disco, así que el disco no se ha añadido ni seleccionado.',
    'Run {check_installation}. If it passes, send this block to the mod author.':
        'Ejecuta {check_installation}. Si todo es correcto, envía este bloque al autor del mod.',
    'The ISO changed while it was being checked.':
        'La ISO cambió mientras se comprobaba.',
    'Another program wrote to the file, or its download or copy had not finished.':
        'Otro programa escribió en el archivo, o su descarga o copia no había terminado.',
    'Wait until the copy or download has finished, then choose Add ISO… again.':
        'Espera a que termine la copia o la descarga y vuelve a elegir Añadir ISO….',
    'There is not enough free disk space to add the disc.':
        'No hay espacio libre suficiente para añadir el disco.',
    'Its names, portraits and check need about {needed} on the drive of the Tag Team Mod folder; {free} is free.':
        'Sus nombres, retratos y comprobación necesitan unos {needed} en la unidad de la carpeta de Tag Team Mod; hay {free} libres.',
    'Free some disk space, then choose Add ISO… again.':
        'Libera espacio en disco y vuelve a elegir Añadir ISO….',
    'This disc cannot be removed from the list.':
        'Este disco no se puede quitar de la lista.',
    'It is the disc in use, or the disc this installation was made with (its files belong to the installation).':
        'Es el disco en uso o el disco con el que se hizo esta instalación (sus archivos forman parte de la instalación).',
    'Use another disc first; the installed disc always stays in the list.':
        'Primero usa otro disco; el disco de la instalación siempre permanece en la lista.',
    'Another {mod_settings} window is changing the game discs.':
        'Otra ventana de {mod_settings} está cambiando los discos del juego.',
    'Only one window can add, switch or remove discs at a time.':
        'Solo una ventana a la vez puede añadir, cambiar o quitar discos.',
    'Wait for it to finish or close it, then try again.':
        'Espera a que termine o ciérrala y vuelve a intentarlo.',
    'The chosen ISO is the expanded-map copy the mod made, not an original disc.':
        'La ISO elegida es la copia de mapas ampliados creada por el mod, no un disco original.',
    'Expanded maps are built from an original ISO and follow it automatically.':
        'Los mapas ampliados se crean a partir de una ISO original y la siguen automáticamente.',
    'Add the original ISO instead; expanded maps are turned on in {mod_settings} > Launch options (restart).':
        'Añade en su lugar la ISO original; los mapas ampliados se activan en {mod_settings} > Opciones de inicio (reiniciar).',
    'This folder is not a player installation.':
        'Esta carpeta no es una instalación de jugador.',
    'Developer folders always start the ISO in their games folder.':
        'Las carpetas de desarrollo siempre inician la ISO de su carpeta games.',
    'Use a player installation made with {install} to switch discs.':
        'Usa una instalación de jugador hecha con {install} para cambiar de disco.',
    'The stage files of {disc} differ from the original disc.':
        'Los archivos de escenarios de {disc} difieren del disco original.',
    "The disc's program is the reviewed one, but its maps were changed (a map mod, or an expanded-map copy).":
        'El programa del disco es el revisado, pero sus mapas se cambiaron (un mod de mapas o una copia de mapas ampliados).',
    'Add the original ISO instead, or confirm to add this disc anyway; expanded maps are never built from it.':
        'Añade en su lugar la ISO original, o confirma para añadir este disco de todos modos; nunca se crean mapas ampliados a partir de él.',
    'Check the path, then choose Add ISO… again.':
        'Comprueba la ruta y vuelve a elegir Añadir ISO….',
    'The expanded maps of {disc} cannot be deleted now.':
        'Ahora no se pueden borrar los mapas ampliados de {disc}.',
    "They are being built, or {play} or this installation's PCSX2 is using them.":
        'Se están creando, o {play} o el PCSX2 de esta instalación los está usando.',
    'Wait for the build to finish and close PCSX2, then try again.':
        'Espera a que termine su creación y cierra PCSX2; después vuelve a intentarlo.',
    'Added: {disc}.':
        'Añadido: {disc}.',
    'Already added: {disc}.':
        'Ya estaba añadido: {disc}.',
    'Already added: {disc}. Its ISO location was updated.':
        'Ya estaba añadido: {disc}. Se ha actualizado la ubicación de su ISO.',
    'The files of {disc} were extracted again.':
        'Se han vuelto a extraer los archivos de {disc}.',
    'Switched to {disc}. It applies the next time you start {play}.':
        'Se ha cambiado a {disc}. Se aplica la próxima vez que inicies {play}.',
    '{disc} is already the disc {play} starts.':
        '{disc} ya es el disco que inicia {play}.',
    'Added {disc}, but it was not selected.':
        'Se ha añadido {disc}, pero no se ha seleccionado.',
    'Removed {disc} from the list. The ISO itself was not changed.':
        'Se ha quitado {disc} de la lista. La ISO no se ha modificado.',
    'Found the ISO of {disc} again: {path}':
        'Se ha vuelto a encontrar la ISO de {disc}: {path}',
    'Deleted the expanded maps of {disc} ({size}).':
        'Se han borrado los mapas ampliados de {disc} ({size}).',
    '{disc} has no expanded maps to delete.':
        '{disc} no tiene mapas ampliados que borrar.',
    'European disc (SLES-54945): the game runs at 50 Hz, like the original European release.':
        'Disco europeo (SLES-54945): el juego funciona a 50 Hz, como la versión europea original.',
    'Japanese disc (SLPS-25815, Sparking! Meteor): its menus confirm with Circle and go back with Cross; the game text and voices are Japanese, the fighter names in the mod are English.':
        'Disco japonés (SLPS-25815, Sparking! Meteor): sus menús confirman con Círculo y vuelven con Cruz; los textos y las voces del juego están en japonés y los nombres de los luchadores del mod, en inglés.',
    'Game progress is saved per disc: characters unlocked with one BT3 disc (USA, Europe or Japan) are not unlocked with the others.':
        'El progreso del juego se guarda por disco: los personajes desbloqueados con un disco de BT3 (EE. UU., Europa o Japón) no lo están con los demás.',
    'Both BT4 discs share one save: what you unlock with one is unlocked with the other.':
        'Los dos discos de BT4 comparten la partida guardada: lo que desbloqueas con uno queda desbloqueado con el otro.',
    'Both BT4 discs use the same PCSX2 save-state names: load a save state only with the disc it was made with.':
        'Los dos discos de BT4 usan los mismos nombres de estados guardados de PCSX2: carga un estado guardado solo con el disco con el que se creó.',
    "PCSX2's own Change Disc during a session is not supported; switch discs here with PCSX2 closed.":
        'No se admite la opción Cambiar disco del propio PCSX2 durante una sesión; cambia de disco aquí con PCSX2 cerrado.',
    'Expanded maps are on, but they are not built for this disc yet: run {build_expanded_maps} before the next {play} (about {needed}; {free} free), or the original maps are used.':
        'Los mapas ampliados están activados, pero aún no se han creado para este disco: ejecuta {build_expanded_maps} antes del próximo {play} (unos {needed}; hay {free} libres), o se usarán los mapas originales.',
    "The mod's menus and messages are now in Spanish, like this disc.":
        'Los menús y mensajes del mod están ahora en español, como este disco.',
    'The switch was saved, but a follow-up step failed: {detail}':
        'El cambio se ha guardado, pero falló un paso posterior: {detail}',
    'This developer folder always starts the ISO in its games folder; the game disc can be changed only in a player installation.':
        'Esta carpeta de desarrollo siempre inicia la ISO de su carpeta games; el disco del juego solo se puede cambiar en una instalación de jugador.',
    'Checking the chosen file…':
        'Comprobando el archivo elegido…',
    'Extracting fighter names and portraits…':
        'Extrayendo nombres y retratos de los luchadores…',
    'Checking the mod with this disc…':
        'Comprobando el mod con este disco…',
    'Switching to {disc}…':
        'Cambiando a {disc}…',
    'Deleting…':
        'Borrando…',
    'Reading the game discs…':
        'Leyendo los discos del juego…',
    'Game disc':
        'Disco del juego',
    "Choose which of your game ISOs {play} starts. This installation runs {family}; a disc of the other game needs its own installation. A switch applies the next time you start {play} and is refused while {play} or this installation's PCSX2 is open. Each disc keeps its own fighter names, portraits and expanded maps, so switching back is immediate. Changes on this page apply at once; Save and Cancel are for the other pages.":
        'Elige cuál de tus ISO del juego inicia {play}. Esta instalación ejecuta {family}; un disco del otro juego necesita su propia instalación. El cambio se aplica la próxima vez que inicies {play} y se rechaza mientras {play} o el PCSX2 de esta instalación estén abiertos. Cada disco conserva sus propios nombres, retratos y mapas ampliados, así que volver a uno anterior es inmediato. Los cambios de esta página se aplican al momento; Guardar y Cancelar son para las demás páginas.',
    'In use':
        'En uso',
    'Ready':
        'Listo',
    'ISO missing':
        'Falta la ISO',
    'Files damaged':
        'Archivos dañados',
    'Drive not answering':
        'La unidad no responde',
    '{status} (installed disc)':
        '{status} (disco instalado)',
    'The disc {play} starts:':
        'El disco que inicia {play}:',
    'Discs added to this installation':
        'Discos añadidos a esta instalación',
    'Disc':
        'Disco',
    'Serial':
        'Serie',
    'Status':
        'Estado',
    'ISO location':
        'Ubicación de la ISO',
    'Add ISO…':
        'Añadir ISO…',
    'Use this disc':
        'Usar este disco',
    'Find ISO…':
        'Buscar ISO…',
    'Remove from list':
        'Quitar de la lista',
    'Delete expanded maps':
        'Borrar mapas ampliados',
    'Region: {region}':
        'Región: {region}',
    'Serial: {serial}':
        'Serie: {serial}',
    'Use {disc} from now on? It applies the next time you start {play}. Your mod settings and memory cards stay as they are.':
        '¿Usar {disc} a partir de ahora? Se aplica la próxima vez que inicies {play}. Tus ajustes del mod y tus tarjetas de memoria no cambian.',
    "This disc's game text is in Spanish. Show the mod's menus and messages in Spanish too?":
        'El texto del juego de este disco está en español. ¿Mostrar también los menús y mensajes del mod en español?',
    'Remove {disc} from this list? Its extracted names and portraits are deleted; the ISO itself is not touched. You can add it again at any time.':
        '¿Quitar {disc} de esta lista? Se borran sus nombres y retratos extraídos; la ISO no se toca. Puedes volver a añadirlo cuando quieras.',
    'Also delete its expanded-map ISO ({size})?':
        '¿Borrar también su ISO de mapas ampliados ({size})?',
    'Delete the expanded maps of {disc} ({size})? You can build them again with {build_expanded_maps}.':
        '¿Borrar los mapas ampliados de {disc} ({size})? Puedes volver a crearlos con {build_expanded_maps}.',
    'Add this disc anyway? Expanded maps are never built from it.':
        '¿Añadir este disco de todos modos? Nunca se crean mapas ampliados a partir de él.',
    'Delete {size} of expanded maps that belong to discs no longer in the list?':
        '¿Borrar {size} de mapas ampliados de discos que ya no están en la lista?',
    'Expanded maps of discs no longer in the list use {size}.':
        'Los mapas ampliados de discos que ya no están en la lista ocupan {size}.',
    'Delete them':
        'Borrarlos',
    'Choose a game ISO to add':
        'Elige una ISO del juego para añadirla',
    'Choose the ISO of {disc}':
        'Elige la ISO de {disc}',
    'PlayStation 2 disc image':
        'Imagen de disco de PS2',
    'All files':
        'Todos los archivos',
    'Stop':
        'Detener',
    'Stopped.':
        'Detenido.',
    'Press Use this disc to play it.':
        'Pulsa Usar este disco para jugar con él.',
    '{play} or its PCSX2 is open: close PCSX2 to switch discs.':
        '{play} o su PCSX2 está abierto: cierra PCSX2 para cambiar de disco.',
    'The game discs could not be read.':
        'No se pudieron leer los discos del juego.',
    'The game disc could not be changed because of an unexpected error.':
        'No se pudo cambiar el disco del juego por un error inesperado.',
    'Budokai Tenkaichi 4 support is experimental in this release.':
        'La compatibilidad con Budokai Tenkaichi 4 es experimental en esta versión.',
})


# Version 11 gameplay settings.
ES.update({'Walking and running style': 'Estilo al caminar y correr', 'Allow fusions': 'Permitir fusiones', 'Battle rules': 'Reglas de combate', 'Tournament ring-outs': 'Eliminación por salir del ring', 'On the ground, fighters walk or run instead of gliding; dashes, jumps and flight stay unchanged. Classic keeps the previous animation. Natural is relaxed; Fighter has a more athletic stride. Tilt the left stick past the threshold to run; CPU fighters run. Speed and fighter size adjust the stride. Applies from the next match; Fight Again keeps the settings of its match.': 'En el suelo, los luchadores caminan o corren; los impulsos, saltos y el vuelo no cambian. Clásico conserva la animación anterior. Natural es relajado; Luchador tiene una zancada más atlética. Inclina el stick izquierdo más allá del umbral para correr; la CPU corre. La velocidad y el tamaño ajustan la zancada. Se aplica al próximo combate; la revancha conserva sus ajustes.', 'Tournament ring-outs use the original stage ground-contact rules. Flying outside the ring is safe until you touch a disallowed surface. Ringed-out fighters cannot be revived; their teammates keep fighting. Defeated humans can still take over a living CPU teammate when takeover is enabled. Turn this off to fight without ring-outs. Applies from the next match; Fight Again keeps the settings of its match.': 'La salida del ring sigue las reglas originales de contacto con el suelo del escenario. Volar fuera es seguro hasta tocar una superficie prohibida. Los eliminados no pueden reanimarse; sus aliados siguen luchando. Los jugadores derrotados pueden controlar un aliado CPU vivo si está permitido. Desactívalo para luchar sin salidas del ring. Se aplica al próximo combate; la revancha conserva sus ajustes.', 'Allow fusions controls new fusions for humans and CPUs; preselected fused characters are unaffected. When two humans share a fusion, swap passes control every 20 s, split gives P1 attacks and P2 movement, or Player 1 controls it. The control message and countdown show in swap mode only. The time limit covers Fusion Dance fusions made in the match, not Potara or preselected ones; its timer and power-down animation are optional. Applies from the next match; a Fight Again rematch keeps the settings of its match.': 'Permitir fusiones controla las nuevas fusiones de jugadores y CPU; no afecta a los personajes fusionados elegidos de antemano. Si dos jugadores comparten una fusión, el modo alterno pasa el control cada 20 s, el reparto da ataque al J1 y movimiento al J2, o controla el J1. El aviso y la cuenta atrás solo salen en modo alterno. El límite afecta a la Danza de la Fusión del combate, no a Potara ni a fusiones elegidas; el temporizador y la animación son opcionales. Se aplica desde el próximo combate; la revancha conserva sus ajustes.'})
VALUES_EN.update({'classic': 'Classic', 'natural': 'Natural', 'fighter': 'Fighter'})
VALUES.update({'classic': 'Clásico', 'natural': 'Natural', 'fighter': 'Luchador'})
