"""Every text of the online lobby in English and Spanish: TEXT[key] = {'en': ..., 'es': ...}; t(key, lang, **args).

Disc names stay as on the disc in both languages (fighters, stages, referees and the game's own menu labels); a native
setting's row carries the game's label in parentheses in Spanish ("Tiempo de combate (Duel Time)"). Language, first
match wins: the EN/ES switch on the Start screen (data/settings.json), --lang, the host installation's
mod-settings.json 'language', Windows' display language (Spanish = es), English.
"""

TEXT = {
    'room.load_policy': {'en': 'If a player fails to load', 'es': 'Si un jugador no carga'},
    'room.load_cancel': {'en': 'Cancel the start', 'es': 'Cancelar el inicio'},
    'room.load_drop': {'en': 'Drop and continue', 'es': 'Expulsar y continuar'},
    'room.load_policy_note': {'en': 'A failed load removes that player immediately; a loading timeout allows 120 seconds. Their fighter becomes a CPU. Losing the host always stops the session.',
                              'es': 'Un fallo de carga expulsa al jugador; el tiempo máximo de carga es de 120 segundos. Su luchador pasa a la CPU. Perder al anfitrión siempre detiene la sesión.'},
    'notice.load_dropped': {'en': 'Your match failed to load in time. The host removed you so the others could start. You can join the room again.',
                            'es': 'Tu combate no pudo cargarse a tiempo. El anfitrión te expulsó para que los demás pudieran empezar. Puedes volver a entrar en la sala.'},
    'notice.load_players_dropped': {'en': '{names} could not load and were removed. Their fighters will be CPUs.',
                                    'es': '{names} no pudieron cargar y fueron expulsados. Sus luchadores pasarán a la CPU.'},
    'join.address_hint': {'en': 'Enter the address shown in the host\'s room: an IP address or hostname, optionally followed by :port.',
                          'es': 'Escribe la dirección que aparece en la sala del anfitrión: una IP o un nombre de servidor, con :puerto si hace falta.'},
    'join.address_required': {'en': 'Enter the host address to join.', 'es': 'Escribe la dirección del anfitrión para entrar.'},
    'join.address_invalid': {'en': 'Use an IP address or hostname, with a port from 1 to 65535 if needed.',
                             'es': 'Usa una IP o un nombre de servidor, con un puerto del 1 al 65535 si hace falta.'},
    'browser.warning': {'en': 'Room listing unavailable: {reason}. Direct joining still works.',
                        'es': 'La publicación de la sala no está disponible: {reason}. Aún puedes entrar por dirección.'},
    'browser.password': {'en': 'Room password (optional)', 'es': 'Contraseña de la sala (opcional)'},
    'browser.protected': {'en': 'Password', 'es': 'Contraseña'},
    'browser.listed': {'en': 'List my room', 'es': 'Publicar mi sala'},
    'browser.directory': {'en': 'Directory URL (optional; blank = LAN)', 'es': 'URL del directorio (opcional; vacío = LAN)'},
    'browser.open': {'en': 'Server browser', 'es': 'Buscar salas'},
    'browser.name': {'en': 'Room', 'es': 'Sala'},
    'browser.disc': {'en': 'Disc adapter', 'es': 'Versión'},
    'browser.players': {'en': 'Members', 'es': 'Miembros'},
    'browser.phase': {'en': 'Status', 'es': 'Estado'},
    'browser.source': {'en': 'Source', 'es': 'Origen'},
    'browser.searching': {'en': 'Searching…', 'es': 'Buscando…'},
    'browser.found': {'en': '{n} rooms found. LAN discovery needs the same network.', 'es': '{n} salas encontradas. La búsqueda LAN requiere la misma red.'},
    'browser.refresh': {'en': 'Refresh', 'es': 'Actualizar'},
    'browser.choose': {'en': 'Use address', 'es': 'Usar dirección'},
    'browser.chosen': {'en': 'Address selected. Enter the room password if needed, then Join.', 'es': 'Dirección elegida. Escribe la contraseña si hace falta y pulsa Entrar.'},
    'room.back_hub': {'en': 'Back to hangout hub', 'es': 'Volver al punto de encuentro'},
    # ---- general
    'app.title': {'en': 'TTM Online', 'es': 'TTM Online'},
    'lang.other': {'en': 'Español', 'es': 'English'},
    'yes': {'en': 'Yes', 'es': 'Sí'},
    'no': {'en': 'No', 'es': 'No'},
    'ok': {'en': 'OK', 'es': 'Aceptar'},
    'cancel': {'en': 'Cancel', 'es': 'Cancelar'},
    'close': {'en': 'Close', 'es': 'Cerrar'},
    'kit': {'en': 'TTM Online Kit {version}', 'es': 'TTM Online Kit {version}'},
    'tk.missing': {'en': 'The lobby window needs tkinter; using the console lobby. On Linux: sudo apt install python3-tk',
                   'es': 'La ventana de la sala necesita tkinter; se usa la sala en consola. En Linux: sudo apt install '
                         'python3-tk'},
    # ---- S1 start
    's1.title': {'en': 'Play online', 'es': 'Jugar en línea'},
    's1.subtitle': {'en': 'Tag Team Mod team battles with a friend on another PC: one screen each.',
                    'es': 'Combates por equipos de Tag Team Mod con un amigo en otro PC: una pantalla cada uno.'},
    's1.name': {'en': 'Display Name', 'es': 'Nombre visible'},
    's1.host': {'en': 'Host a match', 'es': 'Crear partida'},
    's1.join': {'en': 'Join a match', 'es': 'Unirse a una partida'},
    's1.address': {'en': 'Host address', 'es': 'Dirección del anfitrión'},
    's1.address_hint': {'en': 'as the host\'s lobby shows it, e.g. 192.168.1.20',
                        'es': 'como la muestra la sala del anfitrión, p. ej. 192.168.1.20'},
    's1.iso': {'en': 'Game ISO', 'es': 'ISO del juego'},
    's1.bios': {'en': 'BIOS', 'es': 'BIOS'},
    's1.install': {'en': 'Tag Team Mod folder (to make matches)', 'es': 'Carpeta de Tag Team Mod (para crear combates)'},
    's1.install_ok': {'en': 'Tag Team Mod {version}: this PC can make online matches',
                      'es': 'Tag Team Mod {version}: este PC puede crear combates en línea'},
    's1.install_candidate': {'en': 'Tag Team Mod {version}: not a tested version; its game code is checked when it makes '
                                   'the first match',
                             'es': 'Tag Team Mod {version}: no es una versión probada; su código del juego se comprueba '
                                   'al crear el primer combate'},
    's1.install_refused': {'en': 'This Tag Team Mod folder cannot make online matches: {why}',
                           'es': 'Esta carpeta de Tag Team Mod no puede crear combates en línea: {why}'},
    's1.install_found': {'en': 'Found: {path} ({version})', 'es': 'Encontrada: {path} ({version})'},
    's1.use': {'en': 'Use', 'es': 'Usar'},
    's1.choose': {'en': 'Choose…', 'es': 'Elegir…'},
    's1.not_chosen': {'en': 'not chosen yet', 'es': 'sin elegir'},
    's1.first_run': {'en': 'First time: choose your game ISO and your PlayStation 2 BIOS.',
                     'es': 'Primera vez: elige tu ISO del juego y tu BIOS de PlayStation 2.'},
    's1.iso_ok': {'en': 'Supported disc ({serial}): OK', 'es': 'Disco compatible ({serial}): correcto'},
    's1.iso_europe': {'en': 'European version: supported; all PCs need the same disc',
                      'es': 'Versión europea compatible; todos los PC necesitan el mismo disco'},
    's1.iso_japan': {'en': 'Japanese version: supported; all PCs need the same disc',
                     'es': 'Versión japonesa compatible; todos los PC necesitan el mismo disco'},
    's1.iso_other': {'en': 'Unreviewed disc ({serial})', 'es': 'Disco sin adaptador revisado ({serial})'},
    's1.controllers': {'en': 'Controllers', 'es': 'Mandos'},
    's1.pads': {'en': '{count} controller(s) found: {list}', 'es': '{count} mando(s) encontrado(s): {list}'},
    's1.pad_n': {'en': 'controller {n}', 'es': 'mando {n}'},
    's1.pad_pressed': {'en': 'controller {n}: button pressed', 'es': 'mando {n}: botón pulsado'},
    's1.no_pad': {'en': 'No controller found: plug one in, or choose Keyboard in Advanced.',
                  'es': 'No se encontró ningún mando: conecta uno, o elige Teclado en Avanzado.'},
    's1.press_any': {'en': 'Press any button on your controller to test it.',
                     'es': 'Pulsa cualquier botón del mando para probarlo.'},
    's1.advanced': {'en': 'Advanced', 'es': 'Avanzado'},
    'adv.port': {'en': 'Port (TCP and UDP)', 'es': 'Puerto (TCP y UDP)'},
    'adv.relay': {'en': 'Relay (IP:port, empty = none)', 'es': 'Relay (IP:puerto, vacío = ninguno)'},
    'adv.room': {'en': 'Relay room', 'es': 'Sala del relay'},
    'adv.delay': {'en': 'Input delay (empty = automatic)', 'es': 'Retardo de entrada (vacío = automático)'},
    'adv.renderer': {'en': 'Renderer', 'es': 'Renderizador'},
    'adv.pad': {'en': 'Your controller', 'es': 'Tu mando'},
    'adv.pad.SDL-0': {'en': 'Controller 1', 'es': 'Mando 1'},
    'adv.pad.SDL-1': {'en': 'Controller 2', 'es': 'Mando 2'},
    'adv.pad.keyboard': {'en': 'Keyboard', 'es': 'Teclado'},
    'adv.fullscreen': {'en': 'Start the game in full screen', 'es': 'Iniciar el juego a pantalla completa'},
    'adv.make_match': {'en': 'Make a new saved match by hand…', 'es': 'Crear a mano un combate guardado nuevo…'},
    'adv.local': {'en': 'These are this PC\'s own choices; they are never compared with the other PC.',
                  'es': 'Son ajustes propios de este PC; nunca se comparan con el otro PC.'},
    # ---- S2 check
    's2.title': {'en': 'Checking this PC', 'es': 'Comprobando este PC'},
    's2.connecting': {'en': 'Connecting to {address}…', 'es': 'Conectando con {address}…'},
    'check.iso': {'en': 'Game ISO', 'es': 'ISO del juego'},
    'check.catalog': {'en': 'Fighter list', 'es': 'Lista de luchadores'},
    'check.disc': {'en': 'Game disc contents', 'es': 'Contenido del disco'},
    'check.bios': {'en': 'BIOS', 'es': 'BIOS'},
    'check.pcsx2': {'en': 'PCSX2', 'es': 'PCSX2'},
    'check.settings': {'en': 'Emulation settings', 'es': 'Ajustes de emulación'},
    'check.kit': {'en': 'Kit and netplay code', 'es': 'Kit y código de red'},
    'check.catalog_note': {'en': '{fighters} fighters, {stages} stages', 'es': '{fighters} luchadores, {stages} escenarios'},
    'check.kit_note': {'en': '{kit} / protocol {protocol}', 'es': '{kit} / protocolo {protocol}'},
    # ---- S3 lobby
    'lobby.title': {'en': 'Online lobby', 'es': 'Sala en línea'},
    'lobby.connected': {'en': 'Connected to {name}', 'es': 'Conectado con {name}'},
    'lobby.ping': {'en': 'Ping {ms} ms · input delay {d} ({dms} ms)', 'es': 'Ping {ms} ms · retardo {d} ({dms} ms)'},
    'lobby.joinwith': {'en': 'Your friend joins with {addr}', 'es': 'Tu amigo se une con {addr}'},
    'lobby.copy': {'en': 'Copy', 'es': 'Copiar'},
    'lobby.copied': {'en': 'Copied', 'es': 'Copiado'},
    'lobby.others': {'en': 'This PC\'s other addresses (VPN): {list}', 'es': 'Otras direcciones de este PC (VPN): {list}'},
    'lobby.internet': {'en': 'Over the internet: forward TCP and UDP port {port} on your router, or use a VPN or a relay.',
                       'es': 'Por internet: redirige los puertos TCP y UDP {port} en tu router, o usa una VPN o un '
                             'relay.'},
    'lobby.relay_room': {'en': 'Relay {relay} · room "{room}"', 'es': 'Relay {relay} · sala "{room}"'},
    'lobby.waiting_guest': {'en': 'Waiting for your friend…', 'es': 'Esperando a tu amigo…'},
    'lobby.waiting_lobby': {'en': 'Waiting for the host\'s lobby…', 'es': 'Esperando la sala del anfitrión…'},
    'lobby.warming': {'en': 'Host\'s game: getting ready ({t})', 'es': 'Juego del anfitrión: preparándose ({t})'},
    'lobby.letthemhost': {'en': 'Let {name} host', 'es': 'Que {name} sea el anfitrión'},
    'lobby.ihost': {'en': 'Host the match on this PC', 'es': 'Ser el anfitrión en este PC'},
    'lobby.swap_cancel': {'en': 'Do not swap', 'es': 'No cambiar'},
    'lobby.swap_note': {'en': '{name}\'s PC can make matches (Tag Team Mod {build}). Swap the roles? Both players '
                              'agree, and {name}\'s PC must be reachable (same network, a VPN or the relay).',
                        'es': 'El PC de {name} puede crear combates (Tag Team Mod {build}). ¿Cambiar los papeles? Los '
                              'dos deben aceptar, y el PC de {name} debe ser accesible (misma red, una VPN o el '
                              'relé).'},
    'lobby.swap_waiting': {'en': 'Waiting for {name} to agree to the swap', 'es': 'Esperando a que {name} acepte el '
                                                                                  'cambio'},
    'lobby.swap_asked': {'en': '{name} offers to swap the roles: press the button to agree',
                         'es': '{name} propone cambiar los papeles: pulsa el botón para aceptar'},
    'lobby.modlang': {'en': 'In-game mod text: {language} (the host\'s)', 'es': 'Texto del mod en el juego: {language} (el del '
                                                                          'anfitrión)'},
    'lobby.your_team': {'en': 'Your team', 'es': 'Tu equipo'},
    'lobby.their_team': {'en': '{name}\'s team', 'es': 'Equipo de {name}'},
    'lobby.player1': {'en': 'Player 1 (host)', 'es': 'Jugador 1 (anfitrión)'},
    'lobby.player2': {'en': 'Player 2 (guest)', 'es': 'Jugador 2 (invitado)'},
    'lobby.you': {'en': 'YOU', 'es': 'TÚ'},
    'lobby.player': {'en': 'PLAYER', 'es': 'JUGADOR'},
    'lobby.cpu': {'en': 'CPU', 'es': 'CPU'},
    'lobby.colour': {'en': 'Colour', 'es': 'Color'},
    'lobby.empty_slot': {'en': '(choose a fighter)', 'es': '(elige un luchador)'},
    'lobby.random_team': {'en': 'Random team', 'es': 'Equipo aleatorio'},
    'lobby.last_team': {'en': 'Last team', 'es': 'Último equipo'},
    'lobby.click_slot': {'en': 'Slot 1 is you; the others are your CPU partners. Click a fighter to change it.',
                         'es': 'El puesto 1 eres tú; los demás son tus compañeros de la CPU. Haz clic en un luchador '
                               'para cambiarlo.'},
    'lobby.read_only': {'en': 'Chosen by {name} (updates live).', 'es': 'Lo elige {name} (se actualiza al momento).'},
    'lobby.nobody': {'en': 'Nobody yet.', 'es': 'Nadie todavía.'},
    'lobby.match': {'en': 'MATCH', 'es': 'COMBATE'},
    'lobby.set_by_host': {'en': '(set by the host)', 'es': '(lo decide el anfitrión)'},
    'lobby.saved': {'en': 'Saved matches', 'es': 'Combates guardados'},
    'lobby.use_saved': {'en': 'Use', 'es': 'Usar'},
    'lobby.saved_none': {'en': '(none)', 'es': '(ninguno)'},
    'lobby.source_saved': {'en': 'Saved match: {title}', 'es': 'Combate guardado: {title}'},
    'lobby.no_saved': {'en': 'No saved match has these teams and settings, and the host\'s PC cannot make matches: '
                             'the host chooses one in Saved matches.',
                       'es': 'Ningún combate guardado tiene estos equipos y ajustes, y el PC del anfitrión no puede '
                             'crear combates: el anfitrión elige uno en Combates guardados.'},
    'lobby.ready': {'en': 'READY', 'es': 'LISTO'},
    'lobby.unready': {'en': 'Not ready', 'es': 'No estoy listo'},
    'lobby.ready_instant': {'en': 'Ready · wait: instant (saved match)', 'es': 'Listo · espera: inmediata (combate '
                                                                               'guardado)'},
    'lobby.ready_no_saved': {'en': 'Ready · the host must choose a saved match', 'es': 'Listo · el anfitrión debe elegir '
                                                                                    'un combate guardado'},
    'lobby.ready_incomplete': {'en': 'Complete your team first', 'es': 'Completa primero tu equipo'},
    'lobby.is_ready': {'en': '{name} is READY', 'es': '{name} está LISTO'},
    'lobby.choosing': {'en': '{name} is choosing', 'es': '{name} está eligiendo'},
    'lobby.leave': {'en': 'Leave', 'es': 'Salir'},
    'lobby.leave_confirm': {'en': 'Leave the lobby?', 'es': '¿Salir de la sala?'},
    'lobby.chat': {'en': 'Chat', 'es': 'Chat'},
    'lobby.send': {'en': 'Send', 'es': 'Enviar'},
    'lobby.controls_title': {'en': 'Controls for this match', 'es': 'Controles de este combate'},
    'lobby.notakeoverform': {'en': 'Teammates you take over cannot transform online yet',
                             'es': 'Los compañeros que controlas no pueden transformarse en línea todavía'},
    'rule.team_size': {'en': 'Team size', 'es': 'Tamaño del equipo'},
    'rule.one_v_one': {'en': '1 v 1 (not online yet)', 'es': '1 contra 1 (aún no en línea)'},
    'rule.stage': {'en': 'Stage', 'es': 'Escenario'},
    'rule.random': {'en': 'Random', 'es': 'Aleatorio'},
    'rule.time': {'en': 'Duel Time', 'es': 'Tiempo de combate (Duel Time)'},
    'rule.com': {'en': 'CPU level', 'es': 'Nivel de la CPU (COM Level)'},
    'rule.referee': {'en': 'Referee', 'es': 'Árbitro (Referee)'},
    'rule.destructible': {'en': 'Destructible stage', 'es': 'Escenario destructible (Map Setting)'},
    'rule.choose_stage': {'en': 'Choose…', 'es': 'Elegir…'},
    'stage.untested': {'en': 'not tested online yet', 'es': 'aún no probado en línea'},
    'locked.later': {'en': 'Not available online yet', 'es': 'Aún no disponible en línea'},
    'locked.list': {'en': 'Ginyu Body Change, timed fusion, CPU transformations, transforming a teammate you took over, '
                          'the extra fighters\' damaged costumes and Cell\'s absorption',
                    'es': 'el cambio de cuerpo de Ginyu, la fusión con tiempo, las transformaciones de la CPU, '
                          'transformar a un compañero que controlas, la ropa dañada de los luchadores extra y la '
                          'absorción de Cell'},
    # ---- notices
    'notice.joined': {'en': '{name} joined the lobby.', 'es': '{name} entró en la sala.'},
    'notice.left': {'en': '{name} left.', 'es': '{name} se fue.'},
    'notice.rule_changed': {'en': 'The host changed {rule} to {value}: press Ready again.',
                            'es': 'El anfitrión cambió {rule} a {value}: pulsa Listo otra vez.'},
    'notice.saved_chosen': {'en': 'The host chose the saved match {title}: press Ready.',
                            'es': 'El anfitrión eligió el combate guardado {title}: pulsa Listo.'},
    'notice.invalid_pick': {'en': 'That choice cannot be played: {what}', 'es': 'Esa elección no se puede jugar: {what}'},
    'notice.invalid_rule': {'en': 'That setting cannot be played: {what}', 'es': 'Ese ajuste no se puede jugar: {what}'},
    'notice.team_incomplete': {'en': 'Complete your team first.', 'es': 'Completa primero tu equipo.'},
    'notice.need_saved': {'en': 'Both players are ready, but no saved match has these teams: host, choose one in '
                                'Saved matches.',
                          'es': 'Los dos están listos, pero ningún combate guardado tiene estos equipos: anfitrión, '
                                'elige uno en Combates guardados.'},
    'notice.prep_refused': {'en': 'The host\'s Tag Team Mod installation cannot make online matches: the host can '
                                  'choose a saved match, or another installation on the Start screen.',
                            'es': 'La instalación de Tag Team Mod del anfitrión no puede crear combates en línea: el '
                                  'anfitrión puede elegir un combate guardado u otra instalación en la pantalla de '
                                  'inicio.'},
    'notice.swap_offer': {'en': '{name} offers to swap the roles (Let ... host).',
                          'es': '{name} propone cambiar los papeles (anfitrión e invitado).'},
    'notice.swap_withdrawn': {'en': '{name} no longer wants to swap the roles.',
                              'es': '{name} ya no quiere cambiar los papeles.'},
    'notice.swapped_host': {'en': 'Roles swapped: this PC is the host now; {name} joins.',
                            'es': 'Papeles cambiados: este PC es ahora el anfitrión; {name} se une.'},
    'notice.swapped_guest': {'en': 'Roles swapped: {name} is the host now; this PC joins.',
                             'es': 'Papeles cambiados: {name} es ahora el anfitrión; este PC se une.'},
    'notice.prep_failed': {'en': 'The host could not prepare the match: press Ready to try again.',
                           'es': 'El anfitrión no pudo preparar el combate: pulsa Listo para intentarlo otra vez.'},
    'notice.guest_refused': {'en': 'A player tried to join and was refused ({code}).',
                             'es': 'Un jugador intentó unirse y fue rechazado ({code}).'},
    'notice.no_such_saved': {'en': 'There is no saved match {id}.', 'es': 'No hay ningún combate guardado {id}.'},
    'notice.start_interrupted': {'en': 'The connection dropped while the match was starting: press Ready again.',
                                 'es': 'La conexión se cortó mientras empezaba el combate: pulsa Listo otra vez.'},
    # ---- S4 / S5 pickers
    'pick.title': {'en': 'Choose a fighter for slot {n}', 'es': 'Elige un luchador para el puesto {n}'},
    'pick.search': {'en': 'Search', 'es': 'Buscar'},
    'pick.colour': {'en': 'Colour', 'es': 'Color'},
    'pick.forms': {'en': 'Forms', 'es': 'Formas'},
    'stage.title': {'en': 'Choose the stage', 'es': 'Elige el escenario'},
    # ---- S6 / S7
    'prep.title': {'en': 'Preparing the match', 'es': 'Preparando el combate'},
    'prep.saved': {'en': 'Using the saved match', 'es': 'Usando el combate guardado'},
    'prep.state': {'en': 'Making the match file', 'es': 'Creando el archivo del combate'},
    'prep.ready': {'en': 'The match is ready', 'es': 'El combate está listo'},
    'prep.mode': {'en': 'Opening Team Battle', 'es': 'Abriendo Por equipos (Team Battle)'},
    'prep.cancel': {'en': 'Cancel', 'es': 'Cancelar'},
    'send.title': {'en': 'Loading', 'es': 'Cargando'},
    'send.sending': {'en': 'Sending the match ({mb} MB)', 'es': 'Enviando el combate ({mb} MB)'},
    'send.receiving': {'en': 'Receiving the match ({mb} MB)', 'es': 'Recibiendo el combate ({mb} MB)'},
    'load.starting': {'en': 'Starting the game', 'es': 'Iniciando el juego'},
    'load.waiting': {'en': 'Waiting for {name} to load the match', 'es': 'Esperando a que {name} cargue el combate'},
    'load.rematch': {'en': 'Loading the rematch', 'es': 'Cargando la revancha'},
    'load.rejoin': {'en': 'Rejoining the fight: receiving the host\'s game',
                    'es': 'Volviendo al combate: recibiendo la partida del anfitrión'},
    'load.rejoin_start': {'en': 'Rejoining the fight: starting the game', 'es': 'Volviendo al combate: iniciando el juego'},
    's1.rejoin': {'en': 'Rejoin the fight with {name}', 'es': 'Volver al combate con {name}'},
    's1.rejoin_hint': {'en': 'The kit closed during the fight "{title}". The other player waits 90 s for you.',
                       'es': 'El kit se cerró durante el combate "{title}". El otro jugador te espera 90 s.'},
    'session.rejoining': {'en': 'The kit\'s session process stopped during the fight: starting it again to rejoin...',
                          'es': 'El proceso de sesión del kit se detuvo durante el combate: reiniciándolo para volver...'},
    # ---- S8 fight
    'fight.title': {'en': 'Fight', 'es': 'Combate'},
    'fight.status': {'en': 'In sync · frame {frame} · ping {ms} ms · delay {d}',
                     'es': 'Sincronizado · fotograma {frame} · ping {ms} ms · retardo {d}'},
    'fight.diff': {'en': 'Checking a difference (frame {frame})…', 'es': 'Comprobando una diferencia (fotograma {frame})…'},
    'fight.window_hint': {'en': 'Play in the game window. This window shows the connection.',
                          'es': 'Juega en la ventana del juego. Esta ventana muestra la conexión.'},
    'fight.resync': {'en': 'Re-synchronizing the two games ({n}/3)…', 'es': 'Resincronizando las dos partidas ({n}/3)…'},
    'fight.reconnect': {'en': 'Connection lost: waiting for it to come back ({seconds} s)',
                        'es': 'Conexión perdida: esperando a que vuelva ({seconds} s)'},
    'fight.stall': {'en': 'Waiting for {name}…', 'es': 'Esperando a {name}…'},
    'fight.frozen': {'en': 'The game stopped at frame {frame} on both PCs: a game bug, not the connection. The fight '
                           'ends as No contest in {seconds} s, or press End fight.',
                     'es': 'El juego se detuvo en el fotograma {frame} en los dos PCs: un fallo del juego, no de la '
                           'conexión. El combate termina sin resultado en {seconds} s, o pulsa Terminar combate.'},
    'results.nocontest_frozen': {'en': 'No contest: the game stopped (a copy is in the runs folder for the mod author)',
                                 'es': 'Sin resultado: el juego se detuvo (hay una copia en la carpeta runs para el '
                                       'autor del mod)'},
    'fight.end': {'en': 'End fight', 'es': 'Terminar combate'},
    'fight.end_confirm': {'en': 'End this fight as No contest for both players?',
                          'es': '¿Terminar este combate sin resultado para los dos jugadores?'},
    'fight.advanced': {'en': 'Advanced', 'es': 'Avanzado'},
    'fight.resync_now': {'en': 'Resync now (test)', 'es': 'Resincronizar ahora (prueba)'},
    'fight.resync_confirm': {'en': 'Send this PC\'s game to the other PC now (a test of the recovery)?',
                             'es': '¿Enviar ahora la partida de este PC al otro PC (una prueba de la recuperación)?'},
    'fight.resyncs': {'en': 'Re-synchronizations in this fight: {n}', 'es': 'Resincronizaciones en este combate: {n}'},
    # ---- S9 results
    'results.title': {'en': 'Results', 'es': 'Resultados'},
    'results.you_won': {'en': 'You won', 'es': 'Ganaste'},
    'results.they_won': {'en': '{name} won', 'es': 'Ganó {name}'},
    'results.ko': {'en': 'by KO', 'es': 'por KO'},
    'results.time': {'en': 'on time', 'es': 'por tiempo'},
    'results.nocontest': {'en': 'No contest', 'es': 'Sin resultado'},
    'results.nocontest_desync': {'en': 'No contest: the two games disagreed',
                                 'es': 'Sin resultado: las dos partidas no coincidían'},
    'results.nocontest_why': {'en': 'No contest ({why})', 'es': 'Sin resultado ({why})'},
    'results.duration': {'en': 'Fight time {m}:{s:02d}', 'es': 'Duración {m}:{s:02d}'},
    'results.sync': {'en': 'State check: {compared} frames compared, {differing} differing, {resyncs} '
                           're-synchronization(s)',
                     'es': 'Comprobación: {compared} fotogramas comparados, {differing} distintos, {resyncs} '
                           'resincronización(es)'},
    'results.rematch': {'en': 'Rematch (same stage: {stage})', 'es': 'Revancha (mismo escenario: {stage})'},
    'results.change': {'en': 'Change teams', 'es': 'Cambiar equipos'},
    'results.leave': {'en': 'Leave', 'es': 'Salir'},
    'results.rematch_time': {'en': 'Rematch with Duel Time', 'es': 'Revancha con tiempo de combate'},
    'results.fightagain': {'en': 'Fight Again in the game = Rematch',
                           'es': 'La revancha (Fight Again) del juego = Revancha'},
    'results.waiting': {'en': 'Waiting for {name}\'s vote…', 'es': 'Esperando el voto de {name}…'},
    'results.back': {'en': 'Back to lobby', 'es': 'Volver a la sala'},
    'results.vote.rematch': {'en': 'Rematch', 'es': 'Revancha'},
    'results.vote.change': {'en': 'Change teams', 'es': 'Cambiar equipos'},
    'results.vote.leave': {'en': 'Leave', 'es': 'Salir'},
    'results.vote.none': {'en': 'not voted yet', 'es': 'aún no votó'},
    'results.votes': {'en': 'You: {mine} · {name}: {theirs}', 'es': 'Tú: {mine} · {name}: {theirs}'},
    'results.via_game': {'en': ' (in the game)', 'es': ' (en el juego)'},
    # ---- Stage 2: the host's game prepares the match (S6), mod rules, controls card
    'prep.wait_copy': {'en': 'finishing the previous match (cancelled); this one comes next',
                       'es': 'termina el combate anterior (cancelado); este va a continuación'},
    'prep.wait_warm': {'en': 'still starting up; the match is made right after',
                       'es': 'todavía arrancando; el combate se crea justo después'},
    'prep.copy': {'en': 'Copying the host\'s Tag Team Mod (first time only)', 'es': 'Copiando el Tag Team Mod del '
                                                                                    'anfitrión (solo la primera vez)'},
    'prep.start': {'en': 'Starting the host\'s game', 'es': 'Iniciando el juego del anfitrión'},
    'prep.boot': {'en': 'Opening the game\'s main menu', 'es': 'Abriendo el menú principal del juego'},
    'prep.picks': {'en': 'Going to the map select', 'es': 'Yendo a la selección de escenario'},
    'prep.settings': {'en': 'Writing the match settings', 'es': 'Escribiendo los ajustes del combate'},
    'prep.confirm': {'en': 'Starting the match with the lobby\'s teams', 'es': 'Empezando el combate con los equipos '
                                                                               'de la sala'},
    'prep.loading': {'en': 'Loading the fighters', 'es': 'Cargando a los luchadores'},
    'prep.capture': {'en': 'Saving the match', 'es': 'Guardando el combate'},
    'prep.convert': {'en': 'Making it an online match and checking it', 'es': 'Convirtiéndolo en combate en línea y '
                                                                             'comprobándolo'},
    'prep.verify': {'en': 'Checking the match against the lobby', 'es': 'Comprobando el combate con la sala'},
    'prep.cached': {'en': 'Using the match prepared earlier', 'es': 'Usando el combate preparado antes'},
    'prep.eta': {'en': 'about {t} left', 'es': 'faltan unos {t}'},
    'prep.host_step': {'en': 'Host\'s game: {step}', 'es': 'Juego del anfitrión: {step}'},
    'prep.cancelled': {'en': 'The host cancelled the preparation.', 'es': 'El anfitrión canceló la preparación.'},
    'prep.cancel_confirm': {'en': 'Stop preparing this match? Both players go back to the lobby.',
                            'es': '¿Dejar de preparar este combate? Los dos jugadores vuelven a la sala.'},
    'lobby.warm_cold': {'en': 'Host\'s game: not started (it starts when both players press Ready, about 2½ min)',
                        'es': 'Juego del anfitrión: sin arrancar (arranca cuando ambos pulsan Listo, unos 2½ min)'},
    'lobby.warm_none': {'en': 'Host: saved matches only (no Tag Team Mod folder chosen)',
                        'es': 'Anfitrión: solo combates guardados (no se eligió carpeta de Tag Team Mod)'},
    'lobby.warm_ready': {'en': 'Host\'s game: ready to make matches', 'es': 'Juego del anfitrión: listo para crear '
                                                                            'combates'},
    'lobby.warm_busy': {'en': 'Host\'s game: making a match', 'es': 'Juego del anfitrión: creando un combate'},
    'lobby.warm_paused': {'en': 'Host\'s game: paused during the fight', 'es': 'Juego del anfitrión: en pausa durante '
                                                                              'el combate'},
    'lobby.warm_failed': {'en': 'Host\'s game: could not get ready ({why}); it starts again at Ready',
                          'es': 'Juego del anfitrión: no pudo prepararse ({why}); empieza de nuevo al pulsar Listo'},
    'lobby.warm_refused': {'en': 'Host: this Tag Team Mod installation cannot make online matches ({why})',
                           'es': 'Anfitrión: esta instalación de Tag Team Mod no puede crear combates en línea ({why})'},
    'lobby.ready_warm': {'en': 'Ready · wait: about 1 min (the host\'s game makes the match)',
                         'es': 'Listo · espera: alrededor de 1 min (el juego del anfitrión crea el combate)'},
    'lobby.ready_cold': {'en': 'Ready · wait: about 2½ min (the host\'s game starts first)',
                         'es': 'Listo · espera: alrededor de 2½ min (primero arranca el juego del anfitrión)'},
    'lobby.source_new': {'en': 'New match: the host\'s game makes it when both players are ready.',
                         'es': 'Combate nuevo: el juego del anfitrión lo crea cuando los dos estén listos.'},
    'lobby.source_cached': {'en': 'Made earlier: {title}', 'es': 'Creado antes: {title}'},
    'lobby.mod_rules': {'en': 'Mod rules', 'es': 'Reglas del mod'},
    'lobby.mod_rules_note': {'en': 'For both players; set by the host. In-game names as in the mod\'s settings.',
                             'es': 'Para los dos jugadores; las decide el anfitrión. Nombres como en los ajustes del '
                                   'mod.'},
    'lobby.mod_show': {'en': 'Show mod rules…', 'es': 'Mostrar reglas del mod…'},
    'lobby.forced': {'en': 'Always online: battle camera zoom 100 %, no expanded maps, no widescreen patch, no extra '
                           'fighter intros.',
                     'es': 'Siempre en línea: zoom de la cámara 100 %, sin mapas ampliados, sin parche panorámico, sin '
                           'presentaciones de luchadores extra.'},
    'lobby.can_prepare': {'en': 'Makes matches with Tag Team Mod {build}', 'es': 'Crea combates con Tag Team Mod '
                                                                                 '{build}'},
    'card.switch_tap': {'en': 'Switch target: tap {button}', 'es': 'Cambiar de objetivo: pulsa {button}'},
    'card.switch_hold': {'en': 'Switch target: hold {button} {seconds} s', 'es': 'Cambiar de objetivo: mantén {button} '
                                                                                 '{seconds} s'},
    'card.stick_alone': {'en': 'Pick a target: right stick', 'es': 'Elegir objetivo: stick derecho'},
    'card.stick_with': {'en': 'Pick a target: right stick with {button} held', 'es': 'Elegir objetivo: stick derecho '
                                                                                     'con {button} pulsado'},
    'card.lockoff': {'en': 'Lock off: hold {button} {seconds} s', 'es': 'Soltar el objetivo: mantén {button} {seconds} '
                                                                        's'},
    'card.transform': {'en': 'Transform: R3', 'es': 'Transformarse: R3'},
    'card.takeover': {'en': 'Take over a teammate after you fall: {button}', 'es': 'Controlar a un compañero tras caer: '
                                                                                   '{button}'},
    'card.revive': {'en': 'Revive: stand in their circle {seconds} s ({stocks} blast stocks)',
                    'es': 'Reanimar: quédate en su círculo {seconds} s ({stocks} reservas)'},
    'card.pause': {'en': 'Pause: Start (either player)', 'es': 'Pausa: Start (cualquier jugador)'},
    'notice.prep_cancelled': {'en': 'The host cancelled the preparation: press Ready again.',
                              'es': 'El anfitrión canceló la preparación: pulsa Listo otra vez.'},
    'notice.mod_changed': {'en': 'The host changed the mod rule "{rule}" to {value}: press Ready again.',
                           'es': 'El anfitrión cambió la regla del mod "{rule}" a {value}: pulsa Listo otra vez.'},
    'notice.random_stage': {'en': 'Random stage: {stage}', 'es': 'Escenario aleatorio: {stage}'},
    'why.linux': {'en': 'a Linux host plays saved matches only for now',
                  'es': 'por ahora un anfitrión con Linux solo juega combates guardados'},
    'why.no_install': {'en': 'no Tag Team Mod folder was chosen (Start > Tag Team Mod folder)',
                       'es': 'no se eligió carpeta de Tag Team Mod (Inicio > Carpeta de Tag Team Mod)'},
    'why.no_python': {'en': 'the Tag Team Mod folder has no private Python (repair it with its installer)',
                      'es': 'la carpeta de Tag Team Mod no tiene su Python propio (repárala con su instalador)'},
    'why.no_iso': {'en': 'the game ISO of the Tag Team Mod folder is missing',
                   'es': 'falta la ISO del juego de la carpeta de Tag Team Mod'},
    'why.iso_unreadable': {'en': 'the game ISO of the Tag Team Mod folder cannot be read',
                           'es': 'no se puede leer la ISO del juego de la carpeta de Tag Team Mod'},
    'why.other_iso': {'en': 'the Tag Team Mod folder plays another game ISO than this kit',
                      'es': 'la carpeta de Tag Team Mod usa otra ISO del juego que este kit'},
    'why.refused': {'en': 'its game code is not one the kit knows',
                    'es': 'su código del juego no es uno que el kit conozca'},
    'why.refused_code': {'en': 'its game code differs from Tag Team Mod beta.35/beta.36 in {detail}',
                         'es': 'su código del juego difiere del de Tag Team Mod beta.35/beta.36 en {detail}'},
    # ---- errors
    'err.title': {'en': 'Problem', 'es': 'Problema'},
    'remedy.retry': {'en': 'Retry', 'es': 'Reintentar'},
    'remedy.advanced': {'en': 'Open Advanced', 'es': 'Abrir Avanzado'},
    'remedy.choose_iso': {'en': 'Choose ISO', 'es': 'Elegir ISO'},
    'remedy.choose_bios': {'en': 'Choose BIOS', 'es': 'Elegir BIOS'},
    'remedy.compare_files': {'en': 'Compare game files only', 'es': 'Comparar solo los archivos del juego'},
    'remedy.logs': {'en': 'Open logs folder', 'es': 'Abrir la carpeta de registros'},
    'session.lost': {'en': 'The kit\'s session process stopped. Start "Play online" again.',
                     'es': 'El proceso de sesión del kit se detuvo. Inicia "Play online" otra vez.'},
}

# Disc labels (the game's own Battle Settings and referees), identical in both languages.
TIME_LABELS = {60: '60', 90: '90', 180: '180', 240: '240', 0: '∞'}
COM_LABELS = ('Very Weak', 'Weak', 'Average', 'Strong', 'Very Strong')
REFEREES = {'en': ('Ox King', 'Videl', 'Supreme Kai', 'Shenron', 'Announcer 1', 'Announcer 2', 'Announcer 3'),
            'es': ('Ox King', 'Videl', 'Supreme Kai', 'Shenron', 'Locutor 1', 'Locutor 2', 'Locutor 3')}
ON_OFF = ('ON', 'OFF')
LANG_NAMES = {'en': {'en': 'English', 'es': 'Spanish'}, 'es': {'en': 'inglés', 'es': 'español'}}


class _Missing(dict):
    def __missing__(self, key):
        return '{' + key + '}'


def t(key, lang='en', **args):
    entry = TEXT.get(key)
    if entry is None:
        return key
    text = entry.get(lang) or entry['en']
    if args:
        try:
            return text.format_map(_Missing(args))
        except (ValueError, IndexError, KeyError):
            return text
    return text


# Spanish of the kit's validation messages (kit_spec, kit_lobby, kit_rules), for the {what} of a lobby notice.
_DETAIL_ES = (
    (r'team size (\S+) is not 2\.\.5( \(1 v 1 is not online yet\))?', 'el tamaño de equipo {0} no está entre 2 y 5'),
    (r'stage (\S+) is not 0\.\.34', 'el escenario {0} no está entre 0 y 34'),
    (r'Duel Time (\S+) is not one of 60, 90, 180, 240, infinite',
     'el tiempo de combate {0} no es 60, 90, 180, 240 ni infinito'),
    (r'CPU level (\S+) is not 0\.\.4', 'el nivel de la CPU {0} no está entre 0 y 4'),
    (r'referee (\S+) is not 0\.\.6', 'el árbitro {0} no está entre 0 y 6'),
    (r'destructible stage must be on or off', 'el escenario destructible debe ser ON u OFF'),
    (r'CPU transformations are not available online yet',
     'las transformaciones de la CPU aún no están disponibles en línea'),
    (r'slot (\d+): character (\S+) cannot be chosen', 'puesto {0}: no se puede elegir al personaje {1}'),
    (r'slot (\d+): (.+) has colours 1\.\.(\d+) \(got (\S+)\)', 'puesto {0}: {1} tiene los colores 1 a {2} (pedido: {3})'),
    (r'slot (\d+): not a fighter', 'puesto {0}: no es un luchador'),
    (r'a team needs exactly (\d+) fighters \(got (\d+)\)', 'un equipo necesita exactamente {0} luchadores (tiene {1})'),
    (r'a team has at most (\d+) fighters of \[character, colour\]',
     'un equipo tiene como máximo {0} luchadores [personaje, color]'),
    (r'nobody sits there', 'ese puesto está vacío'),
    (r'(\w+) cannot be set online', '{0} no se puede ajustar en línea'),
    (r'(\w+): on or off', '{0}: ON u OFF'),
    (r'(\w+): one of (.+)', '{0}: uno de {1}'),
    (r'(\w+): a whole number', '{0}: un número entero'),
    (r'(\w+): from (\S+) to (\S+)', '{0}: de {1} a {2}'),
)


# kit 2.0 (kit_spec v2, kit_lobby v2, kit_settings)
_DETAIL_ES += (
    (r'team (\d+) fighter (\d+): character (\S+) cannot be chosen',
     'equipo {0} luchador {1}: no se puede elegir al personaje {2}'),
    (r'team (\d+) fighter (\d+): (.+) has colours 1\.\.(\d+) \(got (\S+)\)',
     'equipo {0} luchador {1}: {2} tiene los colores 1 a {3} (pedido: {4})'),
    (r'team (\d+) fighter (\d+): (?:not a fighter|malformed)', 'equipo {0} luchador {1}: no es un luchador'),
    (r'team (\d+) fighter (\d+): player slot (\S+) is not offered',
     'equipo {0} luchador {1}: el puesto de jugador {2} no se ofrece'),
    (r'team (\d+) fighter (\d+): players play the first fighter of a team \(.*\)',
     'equipo {0} luchador {1}: los jugadores llevan al primer luchador de un equipo'),
    (r'team (\d+) fighter (\d+): its player slot is (\d+), not (\S+)',
     'equipo {0} luchador {1}: su puesto de jugador es {2}, no {3}'),
    (r'player slot (\S+) is used twice', 'el puesto de jugador {0} está usado dos veces'),
    (r"mode (\S+) is not teams or free-for-all", 'el modo {0} no es por equipos ni todos contra todos'),
    (r'the Tag Team Mod has two teams \(or free-for-all\): three or more teams cannot be played',
     'el Tag Team Mod tiene dos equipos (o todos contra todos): no se puede jugar con tres equipos o más'),
    (r'at most (\d+) fighters at once \(got (\d+)\)', 'como máximo {0} luchadores a la vez (hay {1})'),
    (r'at most (\d+) fighters in a column', 'como máximo {0} luchadores por columna'),
    (r'each team needs at least one fighter', 'cada equipo necesita al menos un luchador'),
    (r'free-for-all needs at least two fighters', 'todos contra todos necesita al menos dos luchadores'),
    (r'music (\S+) is not a track(?: 1\.\.24)?', 'la música {0} no es una pista entre 1 y 24'),
    (r'the service (\w+) is not available online', 'el servicio {0} no está disponible en línea'),
    (r'(\w+) is not available online yet', '{0} aún no está disponible en línea'),
    (r'(\w+) is not a host service', '{0} no es un servicio del anfitrión'),
    (r'(\w+) is not an online rule', '{0} no es una regla en línea'),
    (r'settings that are not online rules: (.+)', 'ajustes que no son reglas en línea: {0}'),
    (r'(.+) are not consistent \(the mod would change them\)', '{0} no son coherentes (el mod los cambiaría)'),
    (r'no such team', 'ese equipo no existe'),
    (r'no such fighter', 'ese luchador no existe'),
    (r'empty team', 'el equipo está vacío'),
    (r'the host locked this fighter \(it stays a CPU\)', 'el anfitrión bloqueó este luchador (sigue siendo de la CPU)'),
    (r'not a member', 'no está en la sala'),
    (r'(.+) already plays it', '{0} ya juega con él'),
    (r'you can only choose your own fighter', 'solo puedes elegir tu propio luchador'),
    (r'the fighter tables of the ISOs differ', 'las tablas de luchadores de las ISO son distintas'),
    (r'the hub is free-for-all', 'el hub es todos contra todos'),
    (r'uneven columns freeze the game at the K\.O\. \(a Tag Team Mod limit\): give both the same size',
     'las columnas desiguales congelan el juego en el K.O. (un límite del Tag Team Mod): dales el mismo tamaño'),
    (r'the hub needs an infinite Duel Time', 'el hub necesita un tiempo de combate infinito'),
    (r"match type (\S+) is not versus or hub", 'el tipo de partida {0} no es combate ni hub'),
    (r"players 3 and 4 \(a fighter that is not a team's first\) are not offered online yet",
     'los jugadores 3 y 4 (un luchador que no es el primero de su equipo) aún no se ofrecen en línea'),
)


def detail(text, lang):
    """A validation message ('; ' separated) in the lobby's language: Spanish for the kit's own messages, anything
    else unchanged."""
    import re
    if lang != 'es' or not text:
        return text
    out = []
    for part in str(text).split('; '):
        for pattern, spanish in _DETAIL_ES:
            m = re.fullmatch(pattern, part)
            if m:
                part = spanish.format(*m.groups())
                break
        out.append(part)
    return '; '.join(out)


def rule_label(rule, lang):
    """A notice's rule key ('rule.time') as this language's row name."""
    return t(rule, lang) if rule else ''


def check_texts():
    """Every key has both languages and the same {fields}."""
    import string
    problems = []
    for key, entry in TEXT.items():
        if set(entry) != {'en', 'es'}:
            problems.append(f'{key}: languages {sorted(entry)}')
            continue
        fields = [{f for _, f, _, _ in string.Formatter().parse(entry[lang]) if f} for lang in ('en', 'es')]
        if fields[0] != fields[1]:
            problems.append(f'{key}: fields {fields}')
    return problems


# ---- kit 2.0 ---------------------------------------------------------------------------------------------------------
TEXT.update({
    's1.subtitle': {'en': 'Tag Team Mod battles online: open a room or join one. One screen each; watch or play.',
                    'es': 'Combates de Tag Team Mod en línea: abre una sala o únete a una. Una pantalla cada uno; '
                          'mira o juega.'},
    's1.host': {'en': 'Open a room', 'es': 'Abrir una sala'},
    's1.join': {'en': 'Join a room', 'es': 'Unirse a una sala'},
    's1.name_hint': {'en': 'empty: the room calls you Player N', 'es': 'vacío: la sala te llama Player N'},
    'room.title': {'en': 'Room', 'es': 'Sala'},
    'room.members': {'en': 'People in the room', 'es': 'Personas en la sala'},
    'room.host_tag': {'en': 'host', 'es': 'anfitrión'},
    'room.you_tag': {'en': 'you', 'es': 'tú'},
    'room.watching': {'en': 'watching', 'es': 'mirando'},
    'room.playing': {'en': 'plays team {team}', 'es': 'juega en el equipo {team}'},
    'room.playing_fighter': {'en': 'plays team {team}, fighter {index}',
                             'es': 'juega en el equipo {team}, luchador {index}'},
    'room.human': {'en': 'PLAYER: {name}', 'es': 'JUGADOR: {name}'},
    'room.cpu_locked': {'en': 'CPU (locked by the host)', 'es': 'CPU (bloqueado por el anfitrión)'},
    'room.lock': {'en': 'Lock', 'es': 'Bloquear'},
    'room.unlock': {'en': 'Unlock', 'es': 'Desbloquear'},
    'room.kick': {'en': 'Remove', 'es': 'Sacar'},
    'fight.hub_join': {'en': 'Join as a player', 'es': 'Entrar como jugador'},
    's1.integrated': {'en': 'Online play of this Tag Team Mod installation: the game disc, the BIOS and PCSX2 are the '
                            'installation\'s own (Mod settings > Game disc chooses the disc; online supports the reviewed BT3 regions and BT4 discs).',
                      'es': 'Juego en línea de esta instalación de Tag Team Mod: el disco, la BIOS y PCSX2 son los de la '
                            'instalación (Mod settings > Disco del juego elige el disco; en línea se necesita BT3 de '
                            'EE. UU.).'},
    'fight.hub_join_why': {'en': 'You take a free fighter (one whose player left, else a CPU) about 1.5 s later.',
                           'es': 'Tomas un luchador libre (uno cuyo jugador se fue, si no uno de la CPU) en unos 1,5 s.'},
    'notice.hub_joined': {'en': '{name} joined the hub as a player.', 'es': '{name} entró al hub como jugador.'},
    'notice.hub_full': {'en': 'Every fighter of the hub has a player.', 'es': 'Todos los luchadores del hub tienen jugador.'},
    'room.slot_hint21': {'en': '{n} of 10 fighters are players. Any fighter can be a player ("Play this fighter"); '
                               'every other fighter is a CPU the host picks, and everyone else watches. All the '
                               'fighters are on the stage at once: a player whose fighter is knocked out watches its team; '
                               'the first fighter of a team may then take over a CPU teammate (Square).',
                         'es': '{n} de 10 luchadores son jugadores. Cualquier luchador puede ser un jugador ("Jugar '
                               'con este luchador"); los demás luchadores son de la CPU y los elige el anfitrión, y el '
                               'resto mira. Todos los luchadores están a la vez en el escenario: un jugador cuyo '
                               'luchador cae mira a su equipo; el primer luchador de un equipo puede entonces tomar a '
                               'un compañero de la CPU (Cuadrado).'},
    'room.ready': {'en': 'READY', 'es': 'LISTO'},
    'room.rename': {'en': 'Rename', 'es': 'Cambiar nombre'},
    'room.your_name': {'en': 'Display Name', 'es': 'Nombre visible'},
    'room.team': {'en': 'Team {n}', 'es': 'Equipo {n}'},
    'room.column': {'en': 'Column {n}', 'es': 'Columna {n}'},
    'room.claim': {'en': 'Play this fighter', 'es': 'Jugar con este luchador'},
    'room.spectate': {'en': 'Just watch', 'es': 'Solo mirar'},
    'room.cpu': {'en': 'CPU', 'es': 'CPU'},
    'room.slot_hint': {'en': 'Players play each team\'s first fighter; everyone else watches. The host picks the CPU '
                             'fighters.',
                       'es': 'Los jugadores llevan al primer luchador de cada equipo; los demás miran. El anfitrión '
                             'elige los luchadores de la CPU.'},
    'room.mode': {'en': 'Battle', 'es': 'Combate'},
    'room.mode.teams': {'en': 'Two teams', 'es': 'Dos equipos'},
    'room.mode.ffa': {'en': 'Free-for-all', 'es': 'Todos contra todos'},
    'room.mode.three': {'en': 'Three or more teams', 'es': 'Tres equipos o más'},
    'room.mode.three_why': {'en': 'The Tag Team Mod has two teams or free-for-all: three or more teams need a mod '
                                  'update.',
                            'es': 'El Tag Team Mod tiene dos equipos o todos contra todos: tres equipos o más necesitan '
                                  'una actualización del mod.'},
    'room.quad_why': {'en': 'Players 3 and 4 (a player on a non-leader fighter) are not offered online yet.',
                      'es': 'Los jugadores 3 y 4 (un jugador en un luchador que no es el líder) aún no están en línea.'},
    'room.sizes': {'en': 'Fighters per team', 'es': 'Luchadores por equipo'},
    'room.columns': {'en': 'Fighters per column', 'es': 'Luchadores por columna'},
    'room.total': {'en': '{n} of 10 fighters', 'es': '{n} de 10 luchadores'},
    'room.music': {'en': 'Music', 'es': 'Música'},
    'room.track': {'en': 'Track {n}', 'es': 'Pista {n}'},
    'room.random_cpu': {'en': 'Random CPU fighters', 'es': 'CPU al azar'},
    'room.rules': {'en': 'Rules (the host\'s, for everybody)', 'es': 'Reglas (las del anfitrión, para todos)'},
    'room.rules_show': {'en': 'Gameplay rules…', 'es': 'Reglas de juego…'},
    'room.rules_note': {'en': 'Set by the host for everybody in this match. They are the host\'s next online '
                              'defaults; nobody\'s offline settings change.',
                        'es': 'Las decide el anfitrión para todos en este combate. Son los valores por defecto del '
                              'anfitrión en su próximo combate en línea; no cambian los ajustes sin conexión de nadie.'},
    'room.display': {'en': 'My display…', 'es': 'Mi pantalla…'},
    'room.display_note': {'en': 'Only on this PC and purely cosmetic (health bars, HUD, the target indicator\'s style): '
                                'never sent, never compared. Cameras are not here: camera rules are the host\'s.',
                          'es': 'Solo en este PC y puramente estético (barras de vida, HUD, el estilo del indicador de '
                                'objetivo): nunca se envía ni se compara. Las cámaras no están aquí: las reglas de cámara '
                                'son del anfitrión.'},
    'room.camera': {'en': 'Camera rules: set by the host', 'es': 'Reglas de cámara: las decide el anfitrión'},
    'room.camera_why': {'en': 'Cameras, cinematics, shared stops, zoom and attack warnings change what a player sees and '
                              'when a player can act, so everybody plays with the host\'s.',
                        'es': 'Las cámaras, cinemáticas, paradas compartidas, el zoom y los avisos de ataque cambian lo '
                              'que ve un jugador y cuándo puede actuar, así que todos juegan con los del anfitrión.'},
    'room.services': {'en': 'Not available online yet: {list}', 'es': 'Aún no disponible en línea: {list}'},
    'room.service.cpu_transform': {'en': 'CPU transformations', 'es': 'transformaciones de la CPU'},
    'room.service.fusion_timer': {'en': 'timed fusion', 'es': 'fusión con tiempo'},
    'room.service.body_change': {'en': 'Ginyu\'s Body Change', 'es': 'el cambio de cuerpo de Ginyu'},
    'room.start': {'en': 'START MATCH', 'es': 'EMPEZAR COMBATE'},
    'room.start_wait': {'en': 'Waiting for {names} to press Ready', 'es': 'Esperando a que {names} pulse Listo'},
    'room.start_hint': {'en': 'about 1 min (the host\'s game makes the match)',
                        'es': 'alrededor de 1 min (el juego del anfitrión crea el combate)'},
    'room.ready_btn': {'en': 'READY', 'es': 'LISTO'},
    'room.unready_btn': {'en': 'Not ready', 'es': 'No estoy listo'},
    'room.watch_hint': {'en': 'You are watching. Take a player slot to play.',
                        'es': 'Estás mirando. Toma un puesto de jugador para jugar.'},
    'room.in_match': {'en': 'A match is running: you watch it in a moment.',
                      'es': 'Hay un combate en curso: lo verás en un momento.'},
    'room.leave': {'en': 'Leave the room', 'es': 'Salir de la sala'},
    'room.close': {'en': 'Close the room', 'es': 'Cerrar la sala'},
    'room.close_confirm': {'en': 'Close the room for everybody?', 'es': '¿Cerrar la sala para todos?'},
    'fight.leave_match': {'en': 'Leave this match', 'es': 'Salir de este combate'},
    'fight.watching': {'en': 'Watching · team {side} view (L1 / R1 on your controller switch it)',
                       'es': 'Mirando · vista del equipo {side} (L1 / R1 en tu mando la cambian)'},
    'fight.playing': {'en': 'You play team {team}\'s leader', 'es': 'Juegas con el líder del equipo {team}'},
    'fight.end_host': {'en': 'End match (No contest)', 'es': 'Terminar combate (sin resultado)'},
    'fight.end_confirm2': {'en': 'End this match as No contest for everybody?',
                           'es': '¿Terminar este combate sin resultado para todos?'},
    'results.winner_team': {'en': 'Team {team} won', 'es': 'Ganó el equipo {team}'},
    'results.retry': {'en': 'RETRY', 'es': 'REPETIR'},
    'results.to_lobby': {'en': 'Return to lobby', 'es': 'Volver a la sala'},
    'results.vote_line': {'en': '{left} s: Retry needs every player ({agreed} of {players} agreed). Otherwise everyone '
                                'goes back to the lobby.',
                          'es': '{left} s: Repetir necesita a todos los jugadores ({agreed} de {players} aceptaron). Si '
                                'no, todos vuelven a la sala.'},
    'results.agreed_by': {'en': 'Agreed: {names}', 'es': 'Aceptaron: {names}'},
    'results.spectator': {'en': 'The players decide: Retry or Return to lobby.',
                          'es': 'Deciden los jugadores: repetir o volver a la sala.'},
    'results.decided_retry': {'en': 'Everybody agreed: the same match again.',
                              'es': 'Todos aceptaron: el mismo combate otra vez.'},
    'results.decided_lobby': {'en': 'Back to the lobby.', 'es': 'De vuelta a la sala.'},
    'load.retry': {'en': 'Loading the match again', 'es': 'Cargando el combate otra vez'},
    'load.join': {'en': 'Joining the running match (receiving the host\'s game)',
                  'es': 'Entrando al combate en curso (recibiendo la partida del anfitrión)'},
    'load.waiting_players': {'en': 'Waiting for the players to load the match',
                             'es': 'Esperando a que los jugadores carguen el combate'},
    'notice.claimed': {'en': '{name} plays team {team}, fighter {index}.',
                       'es': '{name} juega en el equipo {team}, luchador {index}.'},
    'notice.locked': {'en': 'The host locked team {team}, fighter {index}: it stays a CPU.',
                      'es': 'El anfitrión bloqueó el luchador {index} del equipo {team}: sigue siendo de la CPU.'},
    'notice.unlocked': {'en': 'Team {team}, fighter {index} can be taken again.',
                        'es': 'El luchador {index} del equipo {team} se puede tomar otra vez.'},
    'notice.kicked': {'en': 'The host removed you from the room.', 'es': 'El anfitrión te sacó de la sala.'},
    'notice.spectating': {'en': '{name} watches now.', 'es': '{name} ahora mira.'},
    'notice.renamed': {'en': '{old} is now {name}.', 'es': '{old} ahora es {name}.'},
    'notice.claim_refused': {'en': 'That slot cannot be taken: {what}', 'es': 'Ese puesto no se puede tomar: {what}'},
    'notice.host_changed_fighter': {'en': 'The host changed a player\'s fighter (team {team}): press Ready again.',
                                    'es': 'El anfitrión cambió el luchador de un jugador (equipo {team}): pulsa Listo '
                                          'otra vez.'},
    'notice.not_ready': {'en': 'Not every player is ready yet.', 'es': 'Aún no están listos todos los jugadores.'},
    'notice.starting': {'en': 'Starting: {title}', 'es': 'Empezando: {title}'},
    'notice.host_closed': {'en': 'The host closed the room.', 'es': 'El anfitrión cerró la sala.'},
    'notice.unpaused': {'en': 'The game window was paused during the match: resumed.',
                        'es': 'La ventana del juego se pausó durante el combate: reanudada.'},
    'notice.settings_changed': {'en': 'Emulator settings changed during the match ({what}): nothing changes now; the '
                                      'kit writes its own back when the game starts again.',
                                'es': 'Ajustes del emulador cambiados durante el combate ({what}): no cambia nada '
                                      'ahora; el kit vuelve a escribir los suyos al iniciar el juego otra vez.'},
    'rule.sizes': {'en': 'Fighters', 'es': 'Luchadores'},
    'rule.mode': {'en': 'Battle', 'es': 'Combate'},
    'rule.bgm': {'en': 'Music', 'es': 'Música'},
    'card.pause': {'en': 'No pause menu online', 'es': 'Sin menú de pausa en línea'},
    'fight.resync': {'en': 'Re-synchronizing a game…', 'es': 'Resincronizando una partida…'},
    'fight.stall': {'en': 'Waiting for another player…', 'es': 'Esperando a otro jugador…'},
    'why.refused_code': {'en': 'its game code differs from Tag Team Mod beta.35..42 in {detail}',
                         'es': 'su código del juego difiere del de Tag Team Mod beta.35..42 en {detail}'},
    'lobby.joinwith': {'en': 'Friends join with {addr}', 'es': 'Tus amigos se unen con {addr}'},
    'lobby.internet': {'en': 'Over the internet: forward TCP and UDP port {port} on your router, or use a VPN '
                             '(e.g. Tailscale, Radmin VPN).',
                       'es': 'Por internet: redirige los puertos TCP y UDP {port} en tu router, o usa una VPN '
                             '(p. ej. Tailscale, Radmin VPN).'},
})


TEXT.update({
    'rule.start_in': {'en': 'Start in', 'es': 'Empezar en'},
    'notice.hub_draw': {'en': 'The duel ended as a draw (2 minutes without a K.O.).',
                        'es': 'El duelo terminó en empate (2 minutos sin K.O.).'},
    'room.service_on': {'en': '{name} (beta: the host runs them for everybody)',
                        'es': '{name} (beta: el anfitrión las hace para todos)'},
    'fight.watch_team': {'en': 'Watch team {team}', 'es': 'Mirar al equipo {team}'},
    'room.start_in': {'en': 'Start in', 'es': 'Empezar en'},
    'room.start_menu': {'en': 'Menu (a match)', 'es': 'Menú (un combate)'},
    'room.start_hub': {'en': 'Hub (free roam)', 'es': 'Hub (libre)'},
    'room.hub_why': {'en': 'The hub: everybody roams one level, damage only counts once both have attacked, K.O.s '
                           'respawn; challenge somebody to a duel or a full match. Free-for-all, no time limit.',
                     'es': 'El hub: todos recorren un escenario, el daño cuenta solo cuando ambos atacaron, los K.O. '
                           'reaparecen; reta a alguien a un duelo o a un combate completo. Todos contra todos, sin '
                           'límite de tiempo.'},
    'fight.hub_title': {'en': 'Hub scoreboard', 'es': 'Marcador del hub'},
    'fight.hub_cols': {'en': 'Fighter · K · D · Wins', 'es': 'Luchador · K · M · Victorias'},
    'fight.hub_open_on': {'en': 'Fight freely: ON', 'es': 'Pelear libremente: SÍ'},
    'fight.hub_open_off': {'en': 'Fight freely: OFF', 'es': 'Pelear libremente: NO'},
    'fight.hub_challenge': {'en': 'Challenge', 'es': 'Retar'},
    'fight.hub_duel': {'en': 'Duel here', 'es': 'Duelo aquí'},
    'fight.hub_match': {'en': 'Full match', 'es': 'Combate completo'},
    'fight.hub_incoming': {'en': '{name} challenges you ({kind})', 'es': '{name} te reta ({kind})'},
    'fight.hub_accept': {'en': 'Accept', 'es': 'Aceptar'},
    'fight.hub_decline': {'en': 'Decline', 'es': 'Rechazar'},
    'fight.hub_dueling': {'en': 'Duel: {a} vs {b}', 'es': 'Duelo: {a} contra {b}'},
    'notice.hub_challenge': {'en': '{name} challenges {target} ({kind}).', 'es': '{name} reta a {target} ({kind}).'},
    'notice.hub_declined': {'en': '{name} declined {target}\'s challenge.',
                            'es': '{name} rechazó el reto de {target}.'},
    'notice.hub_duel': {'en': 'Duel: {name} vs {target}. Everybody watches.',
                        'es': 'Duelo: {name} contra {target}. Todos miran.'},
    'notice.hub_match': {'en': 'Full match: {name} vs {target}. Everybody else watches; the hub comes back after it.',
                         'es': 'Combate completo: {name} contra {target}. Los demás miran; después vuelve el hub.'},
    'notice.hub_busy': {'en': 'A duel is running: wait for it to end.', 'es': 'Hay un duelo en curso: espera a que '
                                                                              'termine.'},
    'notice.hub_returning': {'en': 'Back to the hub in {seconds} s.', 'es': 'De vuelta al hub en {seconds} s.'},
    'notice.hub_back': {'en': 'Back to the hub (the scoreboard is kept).', 'es': 'De vuelta al hub (se mantiene el '
                                                                               'marcador).'},
})


def notice_text(key, lang, args):
    """A lobby notice with its arguments in this language (rule names, values, validation details)."""
    args = dict(args or {})
    if args.get('what'):
        args['what'] = detail(args['what'], lang)
    rule = str(args.get('rule') or '')
    if rule.startswith('mod.'):
        try:
            import kit_settings
            k = rule[4:]
            if k in kit_settings.FIELDS:
                args['rule'] = kit_settings.label(k, lang)
                args['value'] = kit_settings.value_text(k, args.get('value'), lang)
        except Exception:  # noqa: BLE001 - a notice is text only
            pass
    elif rule.startswith('service.'):
        args['rule'] = t('room.service.' + rule[8:], lang)
    elif rule:
        args['rule'] = rule_label(rule, lang)
        if rule == 'rule.start_in':
            args['value'] = t('room.start_hub' if args.get('value') == 'hub' else 'room.start_menu', lang)
        if rule == 'rule.bgm' and isinstance(args.get('value'), int):
            args['value'] = t('room.track', lang, n=args['value'] + 1)
    return t(key, lang, **args)
