# Tag Team Mod — beta pública

Un instalador para **BT3 USA**, **BT3 Europa**, **BT3 Japón** (*Sparking! Meteor*) y
**BT4 B14 REV2 (English / Español)**.
El disco europeo (SLES-54945, AU/EU) funciona a 50 Hz, como el juego europeo original;
el mod muestra los nombres de los personajes en inglés del disco. El disco japonés
(SLPS-25815) conserva los textos y las voces en japonés, y sus menús confirman con
Círculo y vuelven con Cruz; el mod muestra los nombres de los personajes en inglés,
y las pantallas propias del mod (la elección de equipos y los Ajustes del mod en el
juego) usan los botones que indica su línea de ayuda inferior. BT4 es experimental:
incluye el adaptador y el análisis de recursos, pero todavía no se han probado
todas las combinaciones de personajes, ataques y escenarios.
La ISO española de BT4 inicia el mod en español aunque el instalador se ejecute
en inglés. Puedes cambiarlo después en Ajustes del mod → Menús → Language / Idioma.

## Instalación

El ZIP contiene **Install.cmd**, una guía breve (**README.txt**) y la carpeta
**setup**. Conserva esa carpeta completa; sus archivos se ejecutan automáticamente.

1. Extrae **todo el ZIP**. No ejecutes Install.cmd desde dentro del archivo ZIP.
2. Prepara tu ISO sin comprimir, tu BIOS de PS2 y PCSX2 para Windows x64 ya
   extraído: cualquier 2.x desde la **2.6.0** (la 3.x todavía no se admite).
   Usa una versión estable: 2.6.0, 2.6.1, 2.6.2, 2.6.3, 2.8.0, 2.8.1 o 2.8.2; se
   recomienda la más reciente,
   [PCSX2 2.8.2](https://github.com/PCSX2/pcsx2/releases/tag/v2.8.2). Con el
   mod se ha jugado en 2.8.0 y 2.8.2; las demás se han comprobado con el código
   fuente de PCSX2. Las nightly y otras versiones 2.x se instalan con un aviso
   de versión no probada; si el mod no reconoce el formato de estados guardados
   de esa versión, se detiene con un mensaje al preparar el primer combate con
   el mod. Las anteriores a la 2.6.0 se rechazan. Elige **pcsx2-qt.exe**, no un
   instalador de PCSX2.
3. Abre **Install.cmd** y elige **Español**. El instalador propone la carpeta
   recomendada **%USERPROFILE%\Games\Tag Team Mod** (elige No para escoger otra
   carpeta contenedora) y, después, pide la ISO y el ejecutable del emulador.
   El instalador usa la BIOS que ya tiene configurada tu PCSX2 (en PCSX2,
   **Configuración → BIOS**): lee los ajustes de ese PCSX2 (junto a
   pcsx2-qt.exe si es portable, o en la carpeta que indique su portable.txt;
   si no, en Documentos\PCSX2) y nunca los cambia. Si ese PCSX2 no tiene
   ninguna, también lee los ajustes de otro PCSX2 de este PC y lo indica. Las
   copias idénticas de un mismo volcado cuentan como una, y un archivo
   configurado que no puede usar se indica en amarillo. Si no hay ninguna
   elegida y la carpeta de BIOS de PCSX2 tiene varias, usa la misma con la que
   arranca PCSX2: la primera BIOS de PS2 por nombre, en una unidad NTFS (donde
   Windows lista los archivos en ese orden). Solo pide una BIOS si ese PCSX2 no
   tiene ninguna configurada, o si tiene varias y no puede saber con cuál
   arranca PCSX2; entonces la ventana de archivos se abre en
   la carpeta de BIOS de PCSX2. Para usar otra BIOS, inicia el instalador desde
   un símbolo del sistema con `Install.cmd -Bios "D:\BIOS\SCPH-70012.bin"`.
   Las ventanas de archivos también muestran imágenes comprimidas (.chd,
   .cso, .7z, .zip...) para que el instalador pueda explicarte cómo
   convertirlas. Usa una ruta corta y local en la que puedas escribir, fuera de
   Program Files y de carpetas sincronizadas en la nube; el instalador avisa de
   OneDrive, unidades de red, Program Files y de la ejecución como
   administrador, y rechaza las rutas con corchetes `[ ]`. Necesitas al menos
   3,5 GiB libres, aparte de la ISO y de cualquier copia opcional con mapas
   ampliados.
4. El instalador comprueba todos los archivos elegidos y la carpeta **antes de
   cambiar nada** y muestra todos los problemas a la vez. Después prepara
   Python, crea la carpeta e instala. Espera a que indique **Listo**. Abre
   **Play.cmd** en la instalación nueva.

Si Windows muestra «Windows protegió su PC» al abrir Install.cmd, elige **Más
información → Ejecutar de todas formas**: son los archivos que has extraído del
ZIP. El instalador quita a sus propios archivos la marca de archivo descargado.
Si el administrador del PC bloquea los scripts de PowerShell mediante una
directiva de grupo, el instalador lo indica (TTM-OS-02); solo ese administrador
puede permitirlos.

Se requiere Windows x64 Intel/AMD, Python 3.11 x64 con Tk y los componentes
Visual C++ x64 de Microsoft. Si faltan, el instalador intenta obtenerlos mediante
WinGet; puede que Windows pida permisos de administrador o que tengas que
reiniciar. Si WinGet no está disponible, instala
[Python 3.11 x64](https://www.python.org/downloads/release/python-3119/) y los
[componentes Visual C++ x64](https://learn.microsoft.com/es-es/cpp/windows/latest-supported-vc-redist)
y repite la instalación en una carpeta nueva. Las dependencias de Python del mod
vienen incluidas y verificadas; solo se necesita Internet para instalar
requisitos del sistema que falten o para descargar PCSX2.

No se distribuyen juegos ni BIOS, y no se abre ningún emulador durante la
instalación. Tu ISO y tu BIOS original no se modifican. PCSX2 y la BIOS se
copian a un perfil independiente; tus ajustes, tarjetas de memoria y estados
guardados de PCSX2 no se importan ni se sobrescriben. El perfil privado
necesita su propia copia de la BIOS porque el mod usa sus propios ajustes de
PCSX2, así que nunca cambia el PCSX2 que ya usas. La ISO se usa desde su
ubicación actual; no la muevas después.

## Linux

La compatibilidad con Linux es nueva en esta beta: el instalador, las
dependencias y las comprobaciones funcionan en Linux, pero todavía hay que
probar las partidas en Linux. Necesitas un sistema Intel/AMD de 64 bits
(x86-64) y el **AppImage oficial de PCSX2** para Linux, cualquier 2.x desde la
2.6.0 (las mismas versiones que en Windows; se recomienda
`pcsx2-v2.8.2-linux-appimage-x64-Qt.AppImage` de la página de
[PCSX2 2.8.2](https://github.com/PCSX2/pcsx2/releases/tag/v2.8.2)). Descarga el
archivo de la versión para Linux, **linux-x86_64.tar.gz**.

- **PCSX2 en Flatpak no es compatible.** Su aislamiento le da a PCSX2 una
  carpeta de ejecución privada, así que el mod no puede llegar a la conexión
  PINE de PCSX2 (un socket en esa carpeta), y sus ajustes quedan dentro del
  aislamiento en lugar del perfil privado del mod. El instalador rechaza los
  archivos de Flatpak con esta explicación. Los paquetes de PCSX2 de las
  distribuciones tampoco son compatibles todavía.
- **Python 3.11, 3.12, 3.13 o 3.14 (64 bits) con venv y Tk.** Debian, Ubuntu,
  Mint: `sudo apt install python3-venv python3-tk`; Fedora:
  `sudo dnf install python3-tkinter`; Arch: `sudo pacman -S tk`; openSUSE:
  `sudo zypper install python3-tk`. Ubuntu 22.04 y anteriores traen
  Python 3.10: instala antes python3.11 (con python3.11-venv y python3.11-tk).
  El instalador se ha comprobado en Ubuntu 24.04 (Python 3.12, WSL2); las
  dependencias incluidas cubren CPython 3.11 a 3.14. Python 3.15 necesitará
  una versión posterior del mod con dependencias actualizadas.
- **Steam Deck, Fedora Atomic, Bazzite y otros sistemas de solo lectura:**
  instala [uv](https://docs.astral.sh/uv/) en tu carpeta personal, ejecuta
  `uv python install 3.12` e inicia el instalador con
  `TAGTEAM_PYTHON="$(uv python find 3.12)" sh Install.sh`. Ese Python
  (python-build-standalone) incluye venv y Tk.
- **FUSE 3 y libOpenGL:** el AppImage necesita `fusermount3` con setuid
  (paquete fuse3, instalado en la mayoría de los escritorios; no hace falta
  libfuse2) y `libOpenGL.so.0` (libopengl0 en Debian/Ubuntu, libglvnd-opengl en
  Fedora, libglvnd en Arch). El instalador se detiene e indica qué falta.
- **Tres o cuatro jugadores** necesitan además `libSDL2-2.0.so.0`
  (libsdl2-2.0-0 en Debian/Ubuntu, SDL2 o sdl2-compat en otras). Los mandos 3
  y 4 se leen directamente y la memoria de PCSX2 se comparte mediante /proc,
  así que PCSX2 debe ejecutarse con el mismo usuario (el lanzador lo hace).
  Los jugadores se registran en Configurar jugadores pulsando START, así que el
  orden en que Linux detecta los mandos solo importa para los jugadores 1 y 2 de
  PCSX2: revisa sus asignaciones con **PCSX2 settings.sh**. Si la entrada de 3-4
  jugadores no está disponible, esos modos lo indican en lugar de empezar
  (TTM-CTRL-20).

Instalación: extrae el archivo completo en tu carpeta personal, abre una
terminal en **Tag Team Mod Installer** y ejecuta `sh Install.sh`. Elige en los
diálogos el idioma, la carpeta, la ISO y el AppImage. Como en Windows, el
instalador usa la BIOS que ya tiene configurada tu PCSX2 (los ajustes con los
que arranca el AppImage: `$XDG_CONFIG_HOME/PCSX2` o `~/.config/PCSX2`, o los de
la carpeta `.config` o `.home` con el nombre del archivo AppImage; después, los
de `PCSX2/` junto al AppImage, que se usan con `-portable`, y los de un PCSX2
Flatpak) y solo pide una si no encuentra ninguna que pueda usar (si hay varias
y ninguna elegida, en Linux siempre la pide). Si lo abres
desde un gestor de archivos, el instalador muestra por qué la pide, y la
ventana final indica la BIOS que ha copiado. Sin escritorio, indícalos así:
`sh Install.sh --destination ~/Juegos/"Tag Team Mod" --iso ... --pcsx2 ...
--language es`, y añade
`--bios ...` si tu PCSX2 no tiene ninguna BIOS configurada
(`sh Install.sh --help`). La carpeta de
instalación debe estar en un sistema de archivos de Linux (no FAT, exFAT ni una
unidad de Windows) que permita ejecutar programas. El instalador copia el
AppImage en la instalación nueva, así que después puedes borrar el descargado.

Jugar: ejecuta **Play.sh** en la instalación nueva (`sh Play.sh` en una
terminal, o la entrada **Tag Team Mod.desktop**, que abre una terminal para el
lanzador). Si cierras la terminal cuando el juego ya ha empezado, PCSX2
sigue abierto. **Mod settings.sh** abre el editor de ajustes de escritorio,
**PCSX2 settings.sh** abre el PCSX2 propio de esta instalación sin juego (para
asignar los mandos) y **Check installation.sh** comprueba la instalación. Los
archivos .desktop abren los mismos scripts; cópialos en
`~/.local/share/applications` para tenerlos en el menú. En Linux, las tarjetas
de memoria y los estados guardados están en
**game/runtime28/PCSX2/memcards** y **game/runtime28/PCSX2/sstates**.

Diferencias con Windows: el texto se dibuja con la fuente incluida Liberation
Sans (con los anchos de Arial y letras algo distintas), y el arte de carga Ki
Storm la usa en lugar de Bahnschrift y Segoe UI Black, que solo existen en
Windows. No hay portada de escritorio ni silencio automático mientras carga un
combate (la pantalla de carga del juego se sigue viendo) y, cuando hay que
pausar el juego, el lanzador te pide que pulses la tecla de pausa de PCSX2 en
lugar de pulsarla por ti. Si el entorno privado de Python deja de funcionar
tras una actualización del sistema, Play.sh lo indica: ejecuta Install.sh y
elige la propia carpeta de la instalación; el instalador crea una copia nueva
junto a ella y ofrece copiar tus tarjetas de memoria y los ajustes del mod.

## Jugar e idioma

En el menú principal original, pulsa **Select** para abrir los modos del mod.
Los modos del menú original se juegan con normalidad, sin el mod. Elige un modo
(**Por equipos**, **Todos contra todos** o **Entrenamiento mod**) y, después, el
número de jugadores. En los modos por equipos, el jugador 1 asigna el equipo de
cada mando antes de elegir luchadores. Todos pueden compartir un equipo para
jugar en cooperativo. Las casillas muestran a qué jugador pertenecen; el
jugador 1 elige los luchadores CPU.

**Registro de mandos.** Con dos a cuatro jugadores, la pantalla de jugadores y
equipos (Configurar jugadores) muestra a cada jugador con el mando que usa, y
una luz en su fila parpadea con cada pulsación. Con tres o cuatro jugadores,
cada uno pulsa **START** una vez en su propio mando para unirse; **Continuar** se
activa cuando todos los puestos están ocupados. Un mando que PCSX2 ya usa como
su jugador 1 o 2 conserva ese número (PCSX2 mantiene su asignación y su
vibración); cualquier otro mando pasa a ser el jugador 3, luego el 4, y después
ocupa los puestos 1 y 2 si siguen libres. **SELECT** deja el puesto, Izquierda/
derecha en tu propio mando cambia tu equipo y **Borrar los registros** empieza
de nuevo. Con dos jugadores se mantiene el orden de PCSX2, pero cualquiera puede
pulsar START para registrarse. Un teclado, o un mando que solo PCSX2 puede leer,
se une como jugador 1 o 2 a través de PCSX2 (pulsa su START). Los registros se
conservan para los próximos combates hasta cerrar Play; el modo cooperativo, que
no tiene Configurar jugadores, también los usa, o el orden de conexión.
**Ajustes del mod → Jugadores y mandos → Registro de mandos** elige cuándo es
obligatorio: con 3 o 4 jugadores (instalaciones nuevas), con 2 a 4 jugadores, u
**Opcional (orden de conexión)**, que mantiene el orden anterior (los jugadores 3
y 4 son el tercer y cuarto mando conectados).

Si se desconecta el mando de un jugador, solo su luchador se queda quieto
(TTM-CTRL-22 en la ventana de Play): vuelve a conectarlo o mantén START 2
segundos en un mando libre para ocupar el puesto. El mod lee los mandos con la
base de datos de mandos de PCSX2 (y con tu propio game_controller_db.txt en la
carpeta de datos de PCSX2, si lo tienes).

Los jugadores 3 y 4 nunca vienen de PCSX2: el juego no carga el multitap, así
que las asignaciones de Pad 3 y Pad 4 de PCSX2 y su ajuste de multitap no hacen
nada. Los jugadores 1 y 2 usan en el PCSX2 de esta instalación **Ajustes →
Mandos** (**Settings → Controllers** si está en inglés). Para jugar con teclado,
asigna allí las teclas al primer mando, incluido el botón Select.

Por defecto, para cambiar de objetivo o de luchador observado, pulsa **L3** una
vez: pasas al siguiente enemigo a la derecha, a tu alrededor (en **Controles**
puedes elegir el más cercano primero o el orden de selección). Las
instalaciones nuevas eligen solo con el stick derecho: con el objetivo fijado en
combate, muévelo (sin botón) e izquierda/derecha recorre a tu alrededor y
arriba/abajo elige al enemigo por encima o por debajo de tu objetivo; el stick
derecho deja entonces de mover la cámara. Sin objetivo fijado mueve la cámara
como siempre, y R3 siempre transforma. Para elegir solo mientras mantienes L3
(y conservar los controles de cámara del stick), pon
**Controles → Elegir con el stick derecho** en **Con el botón de cambio**. Si tu objetivo
cae, pasas al enemigo más cercano al centro de tu pantalla. Una flecha dorada
sobre su cabeza marca tu objetivo en tu propia vista y cae al cambiar de
objetivo. **Interfaz → Indicador del objetivo** puede mostrar en su lugar un
doble anillo amarillo con flechas laterales (como en el juego de PSP Tenkaichi
Tag Team) alrededor de su cuerpo, o ambos; el anillo se ajusta al tamaño del
objetivo en pantalla (más pequeño de lejos y en pantalla dividida). Se ve en
cualquier disposición, cada vista con el objetivo de su jugador. Se desactiva en
**Interfaz → Marcar tu objetivo**, aparte de las barras de salud. Con un aviso de ataque (o hasta medio segundo después), la pulsación de
cambio fija en su lugar al enemigo que te ataca (**Controles → Cambiar a quien te
ataca**: Nunca, Pulsando durante el aviso o Pulsando o al recibir golpes). Unas
flechas rojas apuntan a los enemigos que te fijan, o aparecen en el borde de tu
vista si no se ven; crecen y parpadean en amarillo y rojo mientras ese enemigo
te ataca (igual que las flechas del anillo cuando te ataca tu objetivo) (**Interfaz → Enemigos que te fijan**), en cualquier disposición de
pantalla.
Mantén **L3 durante 0,5 segundos** para quitar el objetivo: mantén L3 solo. Con
el stick solo se quita al cumplirse el tiempo, mientras lo mantienes; con
**Con el botón de cambio**, al soltarlo, así que un giro tardío del stick sigue
apuntando.
Pulsa de nuevo para fijar al enemigo visible más cercano
al centro de tu cámara; si no hay ninguno visible, sigues sin objetivo.
Puedes desactivar esta función o cambiar sus botones y tiempos por separado
en **Ajustes del mod → Controles**. Las
instalaciones nuevas activan la reanimación (3 reservas y 3 segundos), las
cámaras compartidas de definitivos y transformaciones y un límite de 80 segundos
para la Danza de la Fusión. Los Potara no tienen temporizador.
Si te derrotan, puedes observar a un aliado CPU vivo y tomar el control con el
botón que aparece en pantalla. Solo es posible con aliados: no está disponible
con enemigos, en partidas solo CPU ni en **Todos contra todos**.

**Modos del mod → Ajustes del mod → Menús → Idioma / Language** permite cambiar
entre inglés y español. También puedes abrir **Mod settings.cmd**. Guardado en
el juego, los menús del mod cambian al salir de Ajustes del mod y el texto del
combate, desde el próximo combate; vuelve a abrir el editor de escritorio para
verlo traducido. El idioma no altera tus otros ajustes.

Se traducen los menús, ajustes, pantallas de carga y avisos de combate del mod.
Los nombres, textos y voces del juego dependen de la ISO y no se reemplazan.
Los registros técnicos y las herramientas de diagnóstico permanecen en inglés.

## Ajustes

**Modos del mod → Ajustes del mod** (con el mando) y **Mod settings.cmd**
(editor de escritorio) ofrecen todos los ajustes con las mismas 17 categorías:
Menús, Jugadores y mandos, Controles, Movimiento, Cinemáticas, Fusión,
Luchadores, Gigantes, Interfaz, Interfaz dividida, Espectador, Reanimación,
Inferioridad numérica, Forcejeos de rayos, Entrenamiento,
Opciones de inicio (reiniciar), Diagnóstico. Ambos incluyen también las
excepciones de transformación de la CPU por personaje y Restaurar valores
predeterminados (conserva el idioma). Cada categoría tiene su ayuda. En
**Fusión** hay dos interruptores del modo alterno: el aviso
"Fusión - Jn controla" y la cuenta "Jn controla en". **Forcejeos de rayos** ajusta
la cámara del choque, la duración del forcejeo, la victoria anticipada por
ventaja de pulsaciones, la fuerza de la CPU, los golpes a quien forcejea y el
apoyo al rayo. **Cámara del choque de rayos**: Pasar al choque (la cámara
original del forcejeo, por defecto) o Mantener las vistas (cada vista, dividida
o completa, sigue a su jugador durante el choque). Apoyo al
rayo: cerca de un aliado que forcejea (**Alcance del apoyo desde el
aliado**, 60 por defecto),
pulsa solo **R3** (la ayuda «R3 - APOYAR AL RAYO» aparece mientras estás en
alcance). Vuelas a un sitio justo detrás y al lado de tu aliado y te unes al
forcejeo en pose de disparo hasta que termina; solo cuando tu pose está hecha
tu vista pasa a la de tu aliado en el choque. Solo cuando el compañero está en
la pose se gasta 1 reserva y se suma su parte de empuje y daño final («APOYO AL
RAYO X1.5»); si no puede unirse (ocupado, golpeado o sin sitio) no se gasta
nada y «APOYO FALLIDO - OCUPADO / BLOQUEADO / GOLPEADO» dice por qué. Hasta
cuatro aliados por bando pueden apoyar, cada uno con su reserva y su parte (el
extra de un bando llega como mucho a x3, «APOYO AL RAYO X3»); los aliados de la
CPU también pueden apoyar. Esa pulsación de R3 nunca te transforma; R3 funciona como siempre
cuando no puedes apoyar. Las instalaciones nuevas empiezan con los golpes a
quien forcejea y el apoyo al rayo (también de la CPU) activados; con todo
desactivado no cambia nada.

**Movimiento → Caminar y correr por el suelo** hace que los luchadores caminen o
corran por el suelo en lugar de deslizarse justo por encima; los acelerones, los
saltos, el vuelo y el agua no cambian. Inclina el stick izquierdo más de lo
indicado (60% por defecto) para correr, menos para caminar; los luchadores de la
CPU siempre corren. La velocidad sigue la longitud de las piernas de cada
luchador (**El tamaño cambia la velocidad**, activado): los pequeños corren más
lento con zancadas a saltos y los grandes más rápido. La carrera acelera en un
tercio de segundo, un giro brusco hacia atrás derrapa y las piernas se mueven a
la velocidad real del luchador, así que los pies no patinan. Las velocidades al
caminar y al correr son porcentajes de una carrera natural (40% y 100% por
defecto). Viene desactivado.
**Cinemáticas → Mantener ataques y transformaciones en su posición actual**
(desactivado por defecto) muestra los ataques Rush, los definitivos y las
transformaciones donde empiezan y no en el centro de la arena; un definitivo a
distancia aún acerca su objetivo al atacante, y al terminar quien haya quedado
bajo el suelo vuelve a él.

**Cinemáticas → Distancia de la cámara de combate** aleja la cámara normal del
combate más que la del juego: 100% (predeterminado) es la cámara del juego,
hasta 200% de 5 en 5. Un mismo valor sirve para la vista de cada jugador,
también en pantalla dividida y al observar, en **Por equipos**, **Todos contra
todos** y **Entrenamiento mod** (un buen sitio para probar valores); los
combates del menú original conservan la cámara del juego. Los primeros planos
(definitivos, transformaciones, presentaciones, agarres, resultados) conservan
su encuadre, y las paredes y el escenario aún pueden acercar la cámara. Con
gigantes grandes, la distancia de cámara para gigantes la multiplica; ninguna
cámara pasa de una distancia fija, así que los luchadores muy grandes ganan
menos. Un luchador de la CPU al que observas puede luchar algo distinto con más
distancia.

**Inferioridad numérica** ayuda a un luchador del equipo más pequeño o, por
defecto, a uno al que apuntan dos o más enemigos. **Desactivado** (por defecto)
no cambia nada. **Equilibrada** y **Fuerte** fijan cuatro ayudas y
**Personalizada (filas de abajo)** usa las filas de abajo: el daño sigue el
número de luchadores vivos (por cada enemigo de más que afronta cada uno, el
equipo menor causa más y recibe menos, como mucho 300% causado y al menos 40%
recibido; con equipos iguales o en Todos contra todos el daño es normal); la
velocidad al recuperarse y levantarse acorta los lanzamientos, las levantadas y
las reacciones a golpes; la protección al levantarse hace que los golpes
normales no te aturdan ni te dañen (los ataques Blast 2, los Rush y los agarres
sí); y romper el combo da un segundo de esa protección tras un número de
golpes, como mucho cada 5 segundos y nunca durante un Rush o un agarre.
Equilibrada es +15%/-10% por enemigo de más, 150%, 0,5 s y 12 golpes; Fuerte
+40%/-30%, 200%, 1 s y 8 golpes. **Quién está en inferioridad** y **La ayuda
se aplica a** (Todos los luchadores o Solo jugadores) valen para todas. Las
flechas rojas de **Interfaz → Enemigos que te fijan** muestran quién te ataca.

En el juego, en la lista de categorías, Cruz abre, Círculo muestra la ayuda,
Cuadrado guarda y sale y Triángulo cierra; si hay cambios sin guardar, pregunta
antes. En una categoría: Arriba/abajo eligen (mantén para repetir),
Izquierda/derecha o Cruz cambian el valor, L2/R2 avanzan diez pasos o van al
primer/último valor, L1/R1 cambian de categoría, Círculo muestra la ayuda,
Cuadrado guarda y Triángulo vuelve. En la lista de excepciones,
Izquierda/derecha alternan Predeterminado/Permitir/Bloquear, L1/R1 pasan
página, L2/R2 cinco páginas y Select muestra solo las excepciones. El botón de
cambio de menú funciona como Volver.

La mayoría de los cambios guardados se aplican desde el próximo combate (la
ayuda de cada categoría indica cuándo); la revancha (Fight Again) conserva los
ajustes de su combate. Las **Opciones de inicio** se aplican al reiniciar
Play.cmd y la velocidad de carga, desde la próxima pantalla de carga. Si
desactivas los menús de modos del mod, solo Mod settings.cmd puede
reactivarlos.

### Cambiar el disco del juego

El editor de escritorio (Mod settings.cmd; Mod settings.sh en Linux) tiene una
página más después de las 17 categorías: **Disco del juego**. Con ella eliges
cuál de tus ISO inicia Play, y cada cambio se aplica al momento (Guardar y
Cancelar son para las demás páginas):

- **Añadir ISO…** comprueba una ISO y la añade a la lista. Una ISO de otro
  juego o un disco no compatible se rechaza en menos de un segundo, antes de
  escribir nada. Al añadirla se lee la ISO completa una vez (hasta un minuto
  para un archivo de 3-6 GB; es inmediato si el instalador o Scan
  compatibility ya comprobaron ese archivo) y se extraen sus nombres de
  luchadores, retratos y programa del juego en `game/discs` (unos 10 MB).
- **Usar este disco** hace que Play inicie el disco elegido, desde el próximo
  Play. Tarda menos de un segundo y se rechaza mientras Play o el PCSX2 de esta
  instalación estén abiertos.
- **Buscar ISO…** indica dónde está ahora la ISO de un disco (solo se acepta el
  mismo archivo). **Quitar de la lista** borra los archivos extraídos de un
  disco, nunca la ISO; el disco con el que instalaste siempre se queda.
  **Borrar mapas ampliados** borra la ISO de mapas ampliados de ese disco (unos
  3 GB).
- Una instalación cambia entre los discos de **un mismo juego**: BT3 de EE. UU.,
  de Europa y de Japón, o BT4 B14 REV2 en inglés y en español. No se puede cambiar
  entre BT3 y BT4 en una instalación: instala el mod del otro juego en una
  carpeta nueva con Install.cmd (el instalador ofrece copiar tus tarjetas de
  memoria).
- El progreso del juego se guarda por disco: los personajes desbloqueados con
  un disco de BT3 no lo están con los demás. El disco europeo funciona a
  50 Hz. Los dos discos de BT4 usan los mismos nombres de estados guardados de
  PCSX2, así que carga un estado guardado solo con el disco con el que se creó.
  No se admite la opción Cambiar disco del propio PCSX2 durante una sesión.
- Los mapas ampliados se crean por disco: después de cambiar, vuelve a ejecutar
  Build expanded maps.cmd si los usas.
- Una versión nueva se instala en una carpeta nueva: el instalador copia tus
  tarjetas de memoria y tus ajustes del mod, pero no los discos que añadiste
  aquí (indica cuántos). Vuelve a añadir sus ISO en la página Disco del juego de
  la nueva instalación.
- Si los archivos del disco elegido están dañados, Play se detiene con
  TTM-PLAY-46 y Check installation indica TTM-CHECK-19: abre Mod settings.cmd >
  Disco del juego y vuelve a elegir un disco (el disco con el que instalaste
  siempre funciona), o elige Añadir ISO… con la misma ISO para volver a extraer
  sus archivos.

## Juego en línea

La instalación incluye el juego en línea (TTM Online): **Play online.cmd**
(Linux: **Play online.sh**, o la entrada de menú "Tag Team Mod - En línea") abre
la ventana de la sala en línea junto a Play.cmd. No hay que elegir nada: usa el
disco seleccionado de BT3 USA/Europa/Japón o BT4 revisado en inglés/español,
su BIOS y su PCSX2. Todos los PC de una sala necesitan discos idénticos. Todos los PC instalan esta
misma versión.

- Un PC abre una sala y los demás entran con la dirección del anfitrión. Todos
  entran mirando; cualquiera de los hasta diez luchadores (5 contra 5) puede
  tomarlo un jugador y los demás son de la CPU. Cada equipo admite 1-5 luchadores
  de forma independiente. El anfitrión crea el combate al
  momento y sus reglas (también las de cámara) valen para todos.
- Volver a la sala abre la selección de personajes. Volver al hub es otra
  acción del anfitrión. Una sala tiene un combate activo; aún no hay instancias
  independientes para retos. Las salas con contraseña pueden publicarse en LAN
  o en una URL de directorio compartida; no hay un servicio público incluido.
- Los ajustes en línea (tu nombre en la sala, las reglas del anfitrión, tus
  opciones de pantalla) se guardan en `online\data` y nunca cambian el
  `game\mod-settings.json` sin conexión. El PCSX2 en línea es una copia propia
  (`online\pcsx2`; en Linux, la AppImage de la instalación con su propia
  configuración en `online/linux`), así que jugar en línea nunca cambia tu perfil
  de PCSX2, tus tarjetas de memoria ni tus estados guardados sin conexión.
- Por internet, redirige el puerto 47400 (TCP y UDP) en el anfitrión, o usa una
  VPN como Tailscale, ZeroTier o Radmin VPN. `online\LEAME - Jugar en linea.txt`
  explica las salas, las reglas, el hub y cada código de mensaje.
- Al actualizar, la nueva instalación importa los ajustes en línea junto con tus
  tarjetas de memoria. Para desinstalar, borrar la carpeta de la instalación
  borra también la parte en línea.

## Compatibilidad

El instalador genera **COMPATIBILITY.md** en la carpeta de instalación, con los
personajes y formas, trajes, escenarios, destinos de destrucción y fusiones
disponibles en tu disco. Adaptadores de ejecutable compatibles:

| Disco | Estado |
| --- | --- |
| BT3 USA, SLUS-21678 | Adaptador en beta pública |
| BT3 Europa, SLES-54945 | Adaptador en beta pública; funciona a 50 Hz, como el juego europeo original |
| BT3 Japón (*Sparking! Meteor*), SLPS-25815 | Adaptador en beta pública; sus menús confirman con Círculo; nombres de personajes en inglés |
| BT4 B14 REV2 English / Español, SLUS-21978 | Adaptador experimental en beta pública |
| Mods de recursos con el mismo ejecutable y el mismo menú revisados | Se analizan; se instalan solo si superan las comprobaciones |
| Otras ediciones (como la demo japonesa de *Sparking! Meteor*, SLPM-61162), otras versiones de BT4 o un ejecutable o menú modificado | El instalador indica qué disco es y cuáles son compatibles, y se detiene; COMPATIBILITY.md conserva el inventario |

BT4 tiene algunas entradas de trajes o recursos no válidas, que el informe
señala y el mod evita. Los últimos cambios de la cámara de fusión de BT4 aún
deben probarse en un combate normal. Las vistas de tres y cuatro jugadores y
algunas combinaciones poco habituales de fusión y separación siguen en beta.
Los mapas ampliados y los gigantes más grandes son experimentales y vienen
desactivados; pueden tener limitaciones de gráficos, colisiones o alcance de
ataques.

## Problemas y comprobaciones

- No cambies de versión de PCSX2 dentro de esta instalación: su copia de PCSX2
  se comprueba con los demás archivos. Para cambiar, instala una copia nueva
  con la versión elegida. Los estados guardados de PCSX2 2.6 y 2.8 no se pueden
  cargar en la otra versión. Play.cmd usa la compresión Zstandard para los
  estados guardados durante cada sesión (el mod no puede leer Deflate64 ni
  LZMA2) y restaura tu elección al cerrar PCSX2.
- Si el juego o el menú fallan, cierra el emulador y ejecuta
  **Check installation.cmd**: comprueba archivos, dependencias, ISO y
  configuración sin abrir el emulador. Consulta **check-installation.log** y
  **check-status.json**. No restablece tus preferencias ni repara archivos por
  su cuenta. Para volver a comprobar el disco completo, ejecútalo con
  **--full-iso**.
- Si falla la instalación, el instalador muestra un bloque por problema. Empieza
  con un código como **[TTM-BIOS-02]** e indica qué ha pasado, por qué, cómo
  solucionarlo, si se ha cambiado algo, el archivo afectado y dónde está el
  registro. Copia ese bloque si pides ayuda. El registro está en
  **%LOCALAPPDATA%\TagTeamMod\logs\setup-<fecha>.log** (Linux:
  **~/.local/state/tagteammod/logs**); cuando ya existe la carpeta de
  instalación, también se copia a **installer.log** dentro de ella, e
  **install-status.json** guarda el código (`error_code`). Play.cmd solo se crea
  si se superan todas las comprobaciones. Corrige el problema y vuelve a
  ejecutar Install.cmd con la **misma** carpeta: el intento sin terminar se
  renombra a **Tag Team Mod (failed <fecha>)** y la instalación continúa. El
  instalador nunca borra carpetas; borra tú la renombrada cuando la nueva
  instalación funcione.
- **Códigos frecuentes:** TTM-ZIP-01, Install.cmd se abrió dentro del ZIP
  (extrae antes el ZIP completo). TTM-ISO-01/02/03/04, la imagen es un archivo
  comprimido, CHD, CSO/ZSO o BIN/CUE (descomprímela,
  `chdman extractdvd -i juego.chd -o juego.iso`,
  `maxcso --decompress juego.cso -o juego.iso`, o convierte el BIN/CUE en ISO).
  TTM-ISO-06, la ISO está incompleta (descárgala o cópiala de nuevo).
  TTM-ISO-07, la ISO está dañada (vuélcala o cópiala de nuevo y compruébala con
  redump.org). TTM-BIOS-02, se eligió o se configuró en PCSX2 una BIOS de
  PlayStation 1 (elige la BIOS de PS2 de 4 MiB). TTM-BIOS-07/08, un instalador
  iniciado con la carpeta, la ISO y PCSX2 en la línea de comandos no encontró
  ninguna BIOS en los ajustes de PCSX2, o encontró varias y ninguna elegida
  (elige una en PCSX2, **Configuración → BIOS**, o añade -Bios / --bios).
  TTM-BIOS-06, se eligió un archivo complementario de un
  volcado de BIOS (.ROM1, .ROM2, .EROM, .NVM o .MEC; elige el .bin o .rom0 de
  4 MiB del mismo volcado). TTM-PCSX2-02/03, PCSX2 es demasiado antiguo o es la 3.x.
  TTM-PCSX2-05, solo se extrajo pcsx2-qt.exe (extrae la descarga completa de
  PCSX2). TTM-PY-03, a Python 3.11 le falta «tcl/tk and IDLE» (Configuración →
  Aplicaciones → Python 3.11 → Modificar). TTM-DEST-04, la carpeta tiene
  corchetes. TTM-CHECK-02, faltan archivos de la instalación: la causa habitual
  es la cuarentena del antivirus. TTM-PLAY-50, un lanzador se copió fuera de su
  carpeta: crea un acceso directo en su lugar.
- **Error de suma de comprobación** (en inglés, *Installer checksum failed*):
  vuelve a extraer el ZIP completo de la versión. No mezcles archivos de
  versiones distintas; el archivo .sha256 que acompaña al ZIP contiene su hash.
- **Scan compatibility.cmd** vuelve a analizar la ISO y guarda el informe de
  compatibilidad actualizado en **game/COMPATIBILITY.md**. Encontrar recursos no
  garantiza que todos los ataques, efectos y escenarios funcionen.
- **ISO no compatible:** el instalador indica qué disco ha encontrado (por
  ejemplo la demo japonesa de *Sparking! Meteor*, otra versión de BT4 o un
  ejecutable modificado de EE. UU., de Europa o de Japón) y cuáles son los discos
  compatibles. Solo se genera el inventario (**COMPATIBILITY.md**) y la
  instalación se detiene sin crear Play.cmd. Cambiar el nombre de la ISO o su número de serie no la hace
  compatible.
- **Build expanded maps.cmd** crea la copia opcional de la ISO con mapas
  ampliados. Necesitas espacio adicional igual al tamaño de la ISO, más espacio
  de trabajo. Cuando termine correctamente, activa Mapas 2× en Ajustes del mod y
  vuelve a abrir Play.cmd. Algunos mapas conservan su tamaño original.
- **No aparece el menú del mod:** inicia con Play.cmd, llega al menú principal
  original y pulsa Select. Revisa el mensaje del lanzador y la asignación del
  botón Select de tu mando. Si desactivaste los menús de modos del mod,
  actívalos en Mod settings.cmd.
- **Mandos (códigos TTM-CTRL en la ventana de Play):**
  - **TTM-CTRL-20:** los jugadores 3 y 4 no pueden unirse porque el lector de
    mandos del mod (SDL2) no se ha iniciado. Los jugadores 1 y 2 siguen con sus
    mandos de PCSX2. En Linux instala libsdl2-2.0-0 (Debian/Ubuntu), SDL2 o
    sdl2-compat.
  - **TTM-CTRL-21:** un mando está conectado pero no tiene un esquema de mando,
    así que no puede ser el jugador 3 o 4. Aun así puede ser el jugador 1 o 2 a
    través de PCSX2 (Ajustes → Mandos), o cámbialo a su modo XInput/X.
  - **TTM-CTRL-22:** se ha desconectado el mando de un jugador; ese luchador se
    queda quieto. Vuelve a conectarlo o mantén START 2 segundos en un mando libre.
  - **TTM-CTRL-23:** un mando aparece dos veces (DS4Windows, Steam Input u otro
    programa); el mod usa una copia. Si un jugador se mueve dos veces, oculta la
    copia (HidHide) o desactiva ese programa.
  - **TTM-CTRL-24:** un mando mueve a dos jugadores: se registró como un jugador
    y PCSX2 también lo usa en otro puerto. Quítalo de ese puerto en Ajustes de
    PCSX2 → Mandos, o deja que se registre como ese jugador.
  - **TTM-CTRL-25:** la entrada de los mandos de los jugadores se ha detenido; la
    línea indica por qué. El combate sigue y los jugadores 1 y 2 usan sus mandos
    de PCSX2.
- **Sin sonido en menús o combates (Windows):** las versiones anteriores a la
  0.1.0-beta.34 podían dejar PCSX2 silenciado en el mezclador de volumen de
  Windows si se cerraba PCSX2 durante una pantalla de carga o de error del
  mod, y Windows conserva ese silencio en el siguiente inicio. Play de esta
  versión quita el silencio de su propio PCSX2 automáticamente. En una
  instalación anterior, inicia su Play.cmd y, con el juego en marcha, abre el
  mezclador de volumen (clic derecho en el icono del altavoz de la barra de
  tareas > Mezclador de volumen, o Configuración > Sistema > Sonido >
  Mezclador de volumen), busca PCSX2 y quita el silencio.
- **La pantalla de carga se queda en 0 %:** Corregido: en raras ocasiones la
  pantalla de carga se quedaba en 0 % en «CARGANDO TUS LUCHADORES...» (con
  cualquier luchador o escenario). En beta.36 o anteriores, pulsa Start para
  continuar.
- **Un combate grande se congela del todo, o dos parejas se quedan quietas unos
  20 segundos (TTM-MATCH-21):** Corregido: un combate con más de dos
  luchadores por equipo podía congelarse cuando muchos dibujaban estelas a la
  vez (por ejemplo un 5 contra 5 en Muscle Tower con definitivos), y un Rush o
  un definitivo que empezaba mientras otra pareja hacía un Rush podía dejar
  quietas a las dos parejas (beta.36 y anteriores).
- **TTM-MATCH-08 «Additional cached primary-row reference prevents safe
  relocation»:** Corregido: algunas músicas (por ejemplo «Hero - Kibou no Uta -»
  en el disco español de BT4), los datos de algunos luchadores y el escenario 70
  de BT4 podían detener un combate mientras se preparaba. Si el código vuelve a
  aparecer, el mensaje indica el valor y la dirección que encontró: inclúyelos
  al informar del problema.
- **Linux: Play.sh pide cerrar el emulador aunque PCSX2 está cerrado:** un
  programa abierto desde PCSX2 (por ejemplo, un gestor de archivos o un
  navegador abierto desde sus menús) hereda la variable `APPIMAGE` del
  AppImage, así que Play.sh lo cuenta como PCSX2 y lo nombra tras «Found:».
  Cierra ese programa y vuelve a iniciar Play.sh.
- **Linux: Mod settings.sh o PCSX2 settings.sh muestran un error:** si los
  abres desde el escritorio, muestran los errores en una ventana. Los detalles
  están en **game/analysis/settings/launcher.log** (Mod settings) y en
  **pcsx2-settings.log** (PCSX2 settings). Si PCSX2 no puede iniciarse, el
  mensaje indica la biblioteca del sistema o la parte de FUSE que falta.

Al informar de un problema, indica la versión del mod y del juego, el modo y el
número de jugadores, los luchadores, formas y escenario elegidos, qué ocurrió y
el error. El comprobador y el instalador **no envían nada**. Los registros
pueden contener rutas locales; revísalos antes de compartirlos. Para un informe
normal del instalador no hace falta enviar tarjetas de memoria, BIOS, ISO ni
volcados completos.

## Partidas y actualizaciones

Los nombres `.cmd` de esta guía corresponden a Windows; en Linux usa los archivos
`.sh` equivalentes. Las tarjetas de memoria y los estados de Linux están en
**game/runtime28/PCSX2/memcards** y **game/runtime28/PCSX2/sstates**.

Si faltan bibliotecas gráficas o componentes FUSE obligatorios en Linux, la
instalación aún **no está lista para jugar**, aunque los archivos sean correctos.
La opción `--allow-missing-libraries` permite instalar sin esas dependencias:
instala después los paquetes indicados y ejecuta **Check installation.sh**.
La ausencia de SDL2 solo impide la entrada para tres/cuatro jugadores y el
registro de mandos; no bloquea el juego con uno/dos jugadores.

Los volcados de RAM y diagnósticos extensos están desactivados por defecto.
Los archivos temporales de preparación se gestionan automáticamente, y esa
limpieza nunca borra tus tarjetas de memoria ni tus estados guardados. Cierra
PCSX2 con normalidad para detener sus procesos auxiliares y la ventana del
lanzador, que solo sigue abierta si tiene que mostrar un error. Inicia siempre
con Play.cmd.

Tus tarjetas de memoria y estados guardados están en
**game/runtime28/memcards** y **game/runtime28/sstates**; las preferencias del
mod, en **game/mod-settings.json**. Para conservar tu progreso entre versiones,
usa la tarjeta de memoria: cargar un estado guardado de otra versión del mod no
es una forma compatible de actualizar.

Para actualizar, ejecuta el Install.cmd nuevo, responde No a la carpeta
recomendada salvo que tu instalación esté allí y elige la propia carpeta de tu
instalación (la que contiene Play.cmd). La instalación existente no se
modifica: la nueva se crea junto a ella como **<nombre de la carpeta>
<versión>** (por ejemplo **Tag Team Mod <versión>**) y el instalador ofrece
copiar tus tarjetas de memoria (**game/runtime28/memcards/*.ps2**) y
**game/mod-settings.json**. Los ajustes del mod solo se copian entre
instalaciones del mismo juego (de BT3 a BT3, de BT4 a BT4); del otro juego solo
se ofrecen las tarjetas de memoria. Si la copia falla (TTM-DEST-27), la nueva
instalación funciona igual: copia a mano los archivos .ps2. Los ajustes de
PCSX2 (asignación de mandos, gráficos) y los estados guardados de PCSX2 no se
copian: se quedan en la carpeta anterior; si cambiaste la asignación de mandos,
vuelve a hacerla en el PCSX2 de la nueva instalación. No copies instantáneas
del entrenamiento, trucos ni cachés generadas. Conserva la carpeta anterior
hasta comprobar que todo funciona.

Si Play indica que el Python privado de la instalación ya no se inicia
(TTM-PLAY-51), su Python 3.11 se desinstaló o se movió: ejecuta el Install.cmd
de la misma versión, responde No a la carpeta recomendada salvo que la
instalación esté allí, elige la propia carpeta de la instalación (la que
contiene Play.cmd) y responde Sí cuando el instalador ofrezca reparar su Python
privado (solo se reconstruye su carpeta .venv). Una instalación de otra versión
se repara con el Install.cmd de esa versión.

Si has movido o cambiado de nombre la ISO, Play ofrece buscarla; solo acepta el
mismo disco (el mismo SHA-256), así que rechaza una ISO distinta o modificada.
También puedes devolverla a la ruta que indica Check installation. Si Play se
detiene con un error, su ventana sigue abierta (código de salida 2 o 3) para que
puedas leer y copiar el mensaje; los informes de fallo se guardan en
**game\analysis\failures**. El PCSX2 privado de cada instalación es
**game\runtime28\pcsx2-qt.exe** (en Linux lo abre PCSX2 settings.sh).

Antes de desinstalar, cierra el emulador y guarda una copia de las tarjetas de
memoria, estados y preferencias que quieras conservar; después borra solo la
carpeta de instalación (**Tag Team Mod**). Tu ISO, tu BIOS y tu emulador
originales están fuera de ella y no se tocan. Python y los componentes
Visual C++ son compartidos y no se eliminan.

Es una beta pública: los archivos no llevan firma digital y no se han probado en
partida todas las combinaciones de personajes, trajes, efectos, fusiones y
escenarios. El paquete solo incluye las herramientas para jugar, sin
herramientas de desarrollo. Consulta **CHANGELOG.md** para ver los cambios y
**THIRD_PARTY_NOTICES.md** para las licencias de las dependencias.
