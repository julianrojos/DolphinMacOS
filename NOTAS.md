# Dolphin para macOS — uso personal

Adaptación local del gestor de archivos de KDE: https://invent.kde.org/system/dolphin.

## Instalar y abrir

- `./setup.sh` comprueba las herramientas e instala las dependencias de Dolphin
  con Craft. Solo las dependencias usan la caché. Si faltan las fuentes o la
  configuración local, ejecuta `fetch`, `unpack` y `configure` sin caché para
  Dolphin. Después llama al instalador completo, a `fix-dbus-service.sh` y a
  `install-open-with.sh`. Los registros de Craft están en `bootstrap/` y los de
  compilación en `run/`. No se ha repetido la descarga de todas las
  dependencias en un entorno vacío.
- Dolphin se puede abrir desde el Dock o el Finder
  (`CraftRoot/Applications/KDE/dolphin.app`) gracias a `fix-dbus-service.sh`
  y al `LSEnvironment` del Info.plist (ver Incidencias).
- `./abrir-dolphin.sh [carpeta]` abre Dolphin con una sesión D-Bus privada y
  genera un registro independiente en `run/`. Útil para depurar. Detecta si el
  proceso termina en los dos primeros segundos; que siga activo no demuestra
  que haya una ventana funcional.
- `./fix-dbus-service.sh` corrige y recarga el servicio D-Bus de launchd que
  instala Craft. Solo lo recarga si cambia o no responde, porque recargarlo
  desconecta las aplicaciones KDE abiertas. Repetirlo si Craft reinstala su
  paquete de D-Bus. El plist original está en
  `run/org.freedesktop.dbus-session.plist.original`.
- `./install-open-with.sh` registra las aplicaciones de macOS para "Abrir con" y
  su diálogo "Otra aplicación…" (ver Incidencias); `--remove` las retira.
- `python3 install-kio-filter.py` recompila e instala el filtro del diálogo de
  KIO; `--restore` (o `--restaurar`) recupera la biblioteca anterior y
  `--recover` (o `--recuperar`) revierte una
  sustitución interrumpida. Dolphin debe estar cerrado. Una ejecución inicial
  desde fuentes necesita Python 3.12 o posterior y acceso a la descarga oficial.
- La versión se define en `dolphin-version.json`. Los scripts comprueban el
  ejecutable antes de modificarlo. Cambiar la versión exige validar también los
  parches: una versión sin `patches/<versión>/` se rechaza explícitamente.
- Los parches están en `patches/<versión>/`, uno por corrección, y se aplican en
  orden de nombre (`0001-…`, `0002-…`). Cada uno se comprueba por separado: unas
  fuentes preparadas con un conjunto anterior solo reciben los que faltan, y al
  generar la versión sin parche se retiran en orden inverso. Una corrección
  nueva se añade como un archivo nuevo, sin modificar los existentes.

## Parche, metadatos y recuperación

Cerrar Dolphin antes de cambiar la instalación y volverlo a abrir al terminar.

`python3 parchear-dolphin.py` compila e instala Dolphin completo: ejecutable,
bibliotecas, plugins, utilidades y recursos. Genera primero una instalación sin
parche y después otra corregida desde las mismas fuentes y dependencias. Ambas
se preparan con DESTDIR y se firman localmente antes de desplegarse. Los 380
archivos de la instalación probada coinciden con el artefacto corregido.
Compila con tantos trabajos en paralelo como núcleos tenga el Mac.

`python3 parchear-dolphin.py --restaurar` instala la compilación completa sin
parche registrada para esa instalación. Esta referencia se genera desde fuentes:
no es una copia de la instalación previa ni se infiere de la biblioteca instalada.
La restauración verifica todas las huellas y rechaza archivos modificados.
También restaura los metadatos sin modificar, incluidos los campos vacíos del
Info.plist. Para conservar esa compilación sin parche con identificación de
macOS, ejecutar después `python3 configurar-app.py`.

Si Craft modifica o retira archivos, `python3 parchear-dolphin.py --reinstalar`
permite reconstruir desde fuentes sin borrar el manifiesto a mano. Conserva una
instantánea previa y genera de nuevo la referencia sin parche. Los demás modos
siguen rechazando modificaciones externas. El instalador comprueba que Dolphin
esté cerrado al empezar y de nuevo justo antes de sustituir archivos, porque la
compilación tarda minutos; no cierra procesos automáticamente.

`python3 configurar-app.py` aplica nombre, identificador y versión al paquete de
una instalación registrada y actualiza sus firmas y manifiesto.
`python3 configurar-app.py --restaurar` repone el Info.plist sin modificar generado
por CMake para esa compilación, conserva el parche de código y vuelve a firmar
el paquete. Repetir estas operaciones no cambia la referencia original.

Las instalaciones y las copias previas a cada despliegue están en
`backups/<versión>/artifacts/`, identificadas y verificadas por su contenido.
`instalacion.json` registra el artefacto sin parche, el instalado y los archivos
gestionados. `historial/` conserva los estados confirmados. Las copias del
prototipo se mantienen como históricas, pero no se usan como originales.

El despliegue sustituye archivos individualmente y verifica firma y versión.
Si falla, repone la instalación previa. Si se interrumpe el proceso, queda
`pendiente.json`: `python3 parchear-dolphin.py --recuperar` repone la instantánea
anterior. No se promete atomicidad del conjunto frente a una interrupción.
Un bloqueo evita dos instalaciones simultáneas. No borrar `backups/` si se quiere
conservar la recuperación.

Limitaciones conocidas:

- El bloqueo solo cubre `parchear-dolphin.py`, `configurar-app.py` y
  `limpiar-copias.py`, y vive en `backups/<versión>/`. La parte de Craft de
  `setup.sh` (dependencias, fuentes y carpeta de compilación, compartidas entre
  versiones) no está bloqueada: no ejecutar dos `setup.sh` a la vez.
- `limpiar-copias.py --quitar-proteccion` valida antes todas las copias
  protegidas. Si una copia protegida está dañada, no se puede retirar su
  protección con la herramienta; habría que editar `protegidas.json` a mano.

Las copias diferentes consumen espacio y no se eliminan automáticamente.
`python3 limpiar-copias.py` enumera tanto copias como archivos de historial.
Con `--aplicar`, la primera limpieza registra todas las copias e historiales
existentes en `protegidas.json` y los conserva hasta retirar sus protecciones. No se ha
demostrado cuál contiene la instalación inicial de Craft: no se deduce por fechas.
Para futuras copias, mantiene además las referencias activas, tres estados
recientes y tres artefactos recientes. El modo informativo no modifica el registro.
La limpieza se bloquea ante una operación interrumpida, un bloqueo ocupado,
historiales ilegibles o referencias protegidas dañadas.
Para gestionar esas protecciones sin editar JSON:

```sh
python3 limpiar-copias.py --listar-protecciones
python3 limpiar-copias.py --quitar-proteccion copia:ID_COMPLETO
python3 limpiar-copias.py --quitar-proteccion historial:NOMBRE_COMPLETO.json
python3 limpiar-copias.py
```

Copiar el identificador completo del listado. La consulta muestra las referencias
activas, las protecciones manuales y las copias que referencia cada historial.
La retirada solo actualiza `protegidas.json`: no elimina la copia ni el historial.
No admite retirar las referencias de la instalación activa y su restauración.
Una copia desprotegida puede seguir retenida por los historiales protegidos o
recientes y por la retención de copias recientes. Los historiales conservados
protegen siempre las copias que referencian. Revisar de nuevo el plan y ejecutar
`--aplicar` solo para realizar la limpieza indicada. Estos modos son mutuamente
excluyentes: retirar una protección y borrar son operaciones separadas.
Si aún no existe el registro, la primera retirada conserva todas las demás
protecciones iniciales; el listado no modifica el registro.

Los errores técnicos del instalador y los metadatos se guardan en
`run/error-instalacion.log`, `run/error-metadatos.log` y `run/error-limpieza.log`.

## Resultados comprobados

- Entorno inicial: macOS 27.0.1, Apple M2, Xcode 27.2, Python 3.14.0 de python.org.
  Craft `5ec1bc92f`, recetas `1db14d611`, ABI `macos-clang-arm64`.
- `python3 tests/comprobar-accesibilidad.py` compila el método real de cálculo de
  filas y pasa diez casos. La prueba detecta el fallo original con un elemento y
  tres columnas. No es una prueba de integración de accesibilidad con Qt/Cocoa.
- `python3 tests/comprobar-ciclo-real.py` completó en este Mac la restauración
  byte a byte del Info.plist sin perder el parche, la reaplicación de metadatos,
  la restauración completa sin parche y la reinstalación corregida. Se verificó
  cada archivo contra su artefacto, las firmas y la versión del ejecutable.
  Esta prueba modifica la instalación real y termina con el parche aplicado.
- `./comprobar-kio.sh` copia archivos y carpetas, rechaza un conflicto sin alterar
  el destino, mueve, envía a `trash:/` y restaura un archivo temporal propio,
  verificando ruta y contenido. No vacía ninguna papelera.
- `python3 -m unittest discover -s tests -p 'test_*.py'` ejecuta pruebas de
  instalación, errores claros de JSON/configuración, copias dañadas, metadatos,
  cambios del ejecutable, reversión por fallo y recuperación de una interrupción.
  La preparación inicial con Craft se simula; el despliegue completo y la
  restauración también se han probado realmente con la compilación local.
  Las nuevas pruebas usan archivos temporales para ejecutar la limpieza,
  comparar el plan con lo borrado, proteger copias iniciales y comprobar la
  reinstalación tras cambios externos y el archivo de configuraciones CMake.
  También cubren procesos con rutas absolutas, relativas y nombre de ejecutable,
  y que abrir Dolphin durante la compilación impide el despliegue. Para los
  parches comprueban activar y retirar el conjunto, actualizar fuentes que solo
  tienen los primeros parches y detenerse ante fuentes que no coinciden.
  `tests/comprobar-accesibilidad.py` compila y ejecuta el `rowCount()` corregido
  (parche 0001). Las correcciones de conversión de interfaces (0002) y de vida
  del temporizador (0003) no tienen pruebas automáticas de ejecución: se han
  validado a mano (ver Incidencias).

## Incidencias investigadas

- Python de python.org dio `CERTIFICATE_VERIFY_FAILED`: el instalador usa
  `SSL_CERT_FILE=/etc/ssl/cert.pem` manteniendo la verificación HTTPS.
- Enlaces rotos de Qt en `CraftRoot/include/` bloquearon una instalación. El
  instalador reintenta una vez solo si encuentra y elimina esos enlaces rotos.
- El D-Bus de launchd de Craft buscaba su configuración en una ruta de KDE
  (`/Users/gitlab/...`) y moría; Dolphin abierto desde el Dock esperaba el bus
  para siempre sin mostrar ventana. `fix-dbus-service.sh` añade
  `--config-file` al servicio. `abrir-dolphin.sh` sigue usando un bus privado.
  Los dos demonios del lanzador antiguo recibieron SIGTERM; sus archivos de
  estado y registros se archivaron en `run/legacy/`.
- Tipos MIME: el Qt de Craft busca datos adicionales en `QT_DATA_DIRS` (parche
  de Craft `qstandardpaths-extra-dirs-macos.diff`), no en `XDG_DATA_DIRS`.
  `abrir-dolphin.sh` lo exporta y el Info.plist lo declara en `LSEnvironment`
  para los arranques desde el Dock (`set_metadata`, `configurar-app.py`).
- "Abrir con" estaba vacío: KIO lo llena con `KApplicationTrader`, que solo
  conoce aplicaciones con `.desktop`, y en macOS KService solo los busca en
  `/Applications` y `~/Applications`, sin seguir carpetas enlazadas. Los puentes
  están en `share/applications/` (`Exec=/usr/bin/open -b <bundle id> %F`):
  TextEdit (texto, JSON), Preview (imágenes), QuickTime Player, VLC e IINA
  (vídeo). `install-open-with.sh` crea `~/Applications/Dolphin Open With/` con
  un enlace por archivo y regenera la caché con `kbuildsycoca6`. Tras añadir un
  puente: ejecutar el script y reiniciar Dolphin. Comprobación:
  `QT_DATA_DIRS=CraftRoot/share run/kio-check-build/mime-apps-check text/plain`
  (se compila desde `tests/` como `kio-check`). Solo aparecen las aplicaciones
  con puente; listar todas las de macOS requeriría consultar LaunchServices.
- El diálogo "Otra aplicación…" salía vacío aunque el submenú funcionara: su
  árbol sale de los grupos del menú de KService (`KServiceGroup`), y sin
  `applications.menu` los puentes no quedaban en ningún grupo.
  `install-menu.py` (llamado por `install-open-with.sh`) instala el fragmento
  `~/Library/Preferences/menus/applications-merged/dolphin-open-with.menu` con
  `<Include><All/></Include>`; las aplicaciones aparecen en la raíz, sin
  categorías. `mime-apps-check` lista el árbol con los filtros del diálogo:
  0 aplicaciones sin el fragmento, 5 con él. Comprobado también a mano en Dolphin.
  El instalador valida los argumentos y herramientas y configura el fragmento
  antes de modificar enlaces. Si el fragmento es ajeno, ambos modos fallan sin
  tocar los enlaces. Un fallo posterior puede dejar el menú ya actualizado:
  el mensaje identifica el paso; corregir la causa y repetir el comando con los
  mismos argumentos. Los errores de caché quedan en `run/open-with-cache.log`.
  Las pruebas de `tests/test_open_with.py` cubren esos casos y la repetición de
  instalación y retirada en directorios temporales, sin tocar la configuración real.
  `./install-open-with.sh --help` muestra el uso sin necesitar Craft ni cambiar
  la configuración. El fragmento se escribe mediante sustitución atómica y no
  se reescribe si ya coincide; la caché se regenera igualmente. Se conservan los
  permisos existentes y los enlaces simbólicos a fragmentos gestionados. Las
  pruebas incluyen rutas con espacios y caracteres no ASCII y un fallo de
  sustitución que deja intacto el archivo anterior.
  `tests/test_desktop_bridges.py` revisa cada puente de `share/applications/`:
  `Exec=/usr/bin/open -b <bundle id> %F` con el nombre de archivo igual al
  bundle id, `MimeType` válidos sin duplicados y categorías asignadas manualmente.
  Esa exigencia se aplica a los puentes manuales, no a los generados. Si una aplicación
  no está instalada en este Mac solo avisa, sin fallar.
- El diálogo "Otra aplicación…" filtra por los tipos MIME de los archivos y,
  cuando se seleccionan varios tipos, presenta las aplicaciones compatibles con
  todos. Si no existe ninguna aplicación común, el diálogo lo indica. La casilla
  "Show all applications" permite volver al catálogo completo.
  Si el tipo no se puede determinar, se conserva el catálogo completo. Preview
  está asociado también a PDF. La prueba `open-with-dialog-check` ejecuta el
  diálogo con archivos temporales de texto, PDF y vídeo, incluyendo selecciones
  múltiples y la opción de mostrar todo. Usa el modo de pruebas de Qt (rutas en
  `~/.qttest`) con tres aplicaciones de ejemplo propias y su fragmento de menú,
  en una carpeta y un archivo con nombre único para cada ejecución; nunca
  sobrescribe un archivo existente y solo borra lo que ha creado. No depende de
  las aplicaciones ni de los puentes registrados del usuario. Falla con la biblioteca de KIO original sin filtro.
- El cambio está en `patches/kio-6.31.0/` y se aplica a KIO Widgets, compartida
  por las aplicaciones de Craft que utilicen ese diálogo. El instalador verifica
  la versión activa, los símbolos exportados y la prueba del diálogo antes de
  sustituir la biblioteca; conserva y protege una copia anterior. `setup.sh`
  reaplica el filtro tras configurar las asociaciones. Si Craft instala una
  versión distinta de KIO, `setup.sh` avisa y termina sin el filtro; hay que
  adaptar y comprobar el parche para esa versión. Los demás errores siguen
  deteniendo la instalación. La instalación desde
  fuentes en un entorno completamente vacío sigue sin comprobarse.
- El Info.plist tenía vacíos nombre, identificador y versión. Ahora se rellenan.
  Esto podría afectar a la identificación y el foco de la ventana, pero no se ha
  demostrado que fuera la causa ni que el foco esté resuelto.
- La inspección automatizada registró un cierre inesperado por NSRangeException
  en Qt/Cocoa. Se corrigió un cálculo de filas que informaba cero filas cuando
  había menos elementos que columnas. Tras reiniciar el proceso no apareció esa
  excepción en el registro nuevo, pero la herramienta de accesibilidad continuó
  agotando el tiempo. El cierre inesperado sigue pendiente de validación real.
- Cierres al usar Dolphin con Bartender 6 y Raycast abiertos (programas que leen
  la interfaz de otras aplicaciones mediante accesibilidad):
  - Al arrastrar la ventana o abrir un menú: `static_cast` a
    `KItemListViewAccessible` de una interfaz que en macOS no lo era. Corregido
    en `0002-accessibility-interface-cast.patch` con `dynamic_cast`.
  - Al pulsar "Ordenar por": el temporizador de anuncios, propiedad de la vista,
    se disparaba tras destruirse la interfaz de accesibilidad que captura.
    Corregido en `0003-accessibility-timer-lifetime.patch`.
  - Al abrir el menú contextual: fallo de memoria en Qt/AppKit al liberar un
    `NSTextField` durante `QMenu::exec`. No corregido. No se reprodujo con
    Bartender y Raycast cerrados, ni con solo Bartender abierto (menú
    contextual, "Ordenar por" y arrastrar la ventana). Todo apunta a Raycast;
    no se ha confirmado con solo Raycast abierto porque no se usa. Si se
    vuelve a usar Raycast, mantenerlo cerrado mientras se usa Dolphin.
  Validado a mano: tras cada corrección, el cierre correspondiente no se repitió.
- KIO advierte que `/System/Volumes/Data/.Trashes` no pasa sus comprobaciones.
  La prueba de restauración pasó en el disco principal; esto no demuestra
  integración con discos externos.
- La papelera de Dolphin (KIO) vive en `~/.Trash/KDE.trash/`, con el formato de
  Linux (`files/` e `info/*.trashinfo`). Finder solo muestra la carpeta
  `KDE.trash` y no puede devolver los archivos; Dolphin sí los restaura.
  Vaciar la papelera desde Finder también borra `KDE.trash`. Lo borrado desde
  Finder no aparece en la papelera de Dolphin.

## Fase 2: resultados (2026-11-06, sin Raycast abierto)

Funcionan: navegación, pestañas (se ven pequeñas), vista dividida, copiar,
pegar, mover arrastrando, renombrar, duplicar, crear carpeta, enviar a la
papelera y restaurar desde Dolphin. Abrir desde el Dock y "Abrir con" (submenú
y "Otra aplicación…") con TextEdit, Preview y los reproductores de vídeo.

## Pendiente de validar

- Estabilidad de la interfaz en un uso más largo.
- Papelera en un disco externo, con un archivo temporal creado en ese disco.
- Descarga y preparación desde cero en un entorno vacío.

## Preparar una prueba manual de papelera

La carpeta de prueba no se incluye en Git. Desde la raíz del repositorio:

```sh
mkdir -p prueba/codex-verificacion
printf 'Prueba de papelera\n' > prueba/codex-verificacion/papelera-prueba.txt
./abrir-dolphin.sh "$PWD/prueba/codex-verificacion"
```

Enviar únicamente ese archivo a la papelera desde Dolphin y comprobar que puede
restaurarse, tanto desde Dolphin como desde Finder. No vaciar la papelera.
Usar nombres nuevos si el archivo de una prueba anterior ya existe.

### Piloto de aplicaciones de macOS

`python3 tools/install-macos-pilot.py` consulta LaunchServices para extensiones
simples de la base MIME de Dolphin; `--pilot` limita la consulta a texto, Python,
JSON, PDF y MP4. Instala puentes adicionales en
`~/Applications/Dolphin Open With Pilot`. `--remove` retira el piloto y
regenera la caché. Los puentes originales conservan sus metadatos y tipos; los tipos detectados
se combinan en una sola entrada por aplicación. El piloto no cambia las asociaciones
predeterminadas ni garantiza la edición de archivos remotos. Se deben ejecutar
las órdenes de nuevo para reflejar cambios en las aplicaciones instaladas.
La selección se limita a las carpetas habituales de aplicaciones; puede omitir
aplicaciones instaladas en otras ubicaciones. La lista puede incluir programas
poco habituales porque refleja las asociaciones declaradas a macOS. Los puentes
generados no incluyen categorías: LaunchServices no proporciona una categoría de
menú equivalente y no se asigna una sin datos fiables. El menú actual incluye todas
las aplicaciones sin agruparlas; para un menú agrupado habría que clasificarlas.
LaunchServices puede devolver varias copias de una aplicación (por ejemplo,
actualizaciones en carpetas de caché); se descartan las que están fuera de las
carpetas habituales antes de quedarse con una por identificador. Un bloqueo en
`run/open-with.lock`, compartido con `install-open-with.sh`, impide que el piloto
y la instalación de "Abrir con" cambien a la vez los enlaces o la caché. Al
sincronizar los enlaces de los puentes manuales se comprueban todos antes de
cambiar ninguno. Si una ejecución se
interrumpe, la siguiente revisa las carpetas `~/Applications/.dolphin-pilot-*`:
recupera los puentes anteriores si no hay otros instalados, borra los restos
obsoletos (también una carpeta de preparación vacía) y se detiene, indicando la
ruta, si encuentra contenido ajeno. Tras resolver restos regenera la caché, por
si la ejecución interrumpida no llegó a hacerlo. Si la regeneración falla,
se conservan los restos y basta con repetir la orden para volver a intentarlo.
El piloto requiere que se haya ejecutado antes `./install-open-with.sh`. Los archivos
`.DS_Store` se conservan; si aparecen en una carpeta temporal de recuperación,
sus restos gestionados se descartan para que no se restauren por error tras
retirar el piloto, y la carpeta puede permanecer en disco para conservar los
metadatos.

La opción `--full` amplía el piloto a extensiones simples con un tipo declarado
por macOS y aplicaciones disponibles, usando el MIME que Qt asigna al nombre.
Conserva también las cinco asociaciones del piloto. Compara las familias conocidas de macOS con Qt; si no puede compararlas,
acepta la extensión si macOS no declara MIME (no hay prueba de conflicto) o si su MIME
coincide con el de Qt tras resolver alias y mayúsculas; si macOS declara otro MIME, la
rechaza. `KNOWN_CONFLICTS` excluye formatos distintos que comparten familia, como
`.pcf`, `.pic` y `.vlc`. Aunque coincidan las familias, se rechaza la extensión si
Qt reconoce el MIME de macOS como otro tipo (`.f4v`: `video/x-flv` frente a
`video/mp4`), porque sus aplicaciones se ofrecerían para todos los archivos del tipo
de Qt; si Qt no conoce ese MIME (`.py`: `text/x-python-script`), se acepta por
compatibilidad de familia al no haber conflicto conocido. Así quedan fuera también `.m3u`, `.m3u8`, `.svgz` y las
variantes de JPEG 2000. Las cinco extensiones del piloto se conservan salvo que el
informe las rechace por cualquier motivo. Excluye también
tipos dinámicos, patrones complejos y el tipo genérico
`application/octet-stream`. Las extensiones aceptadas son compatibles por
familia (texto, imagen, audio, vídeo), no un formato verificado. `python3 tools/preview-macos-bridges.py --full-report`
produce un informe JSON detallado antes de instalar. El instalador usa esta cobertura ampliada por defecto; `--pilot` instala
únicamente el piloto de cinco extensiones. Los puentes manuales se combinan con los tipos detectados y se restauran al retirar el piloto.
