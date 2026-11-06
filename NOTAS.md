# Dolphin para macOS — uso personal

Adaptación local del gestor de archivos de KDE: https://invent.kde.org/system/dolphin.

## Instalar y abrir

- `./setup.sh` comprueba las herramientas e instala las dependencias de Dolphin
  con Craft. Solo las dependencias usan la caché. Si faltan las fuentes o la
  configuración local, ejecuta `fetch`, `unpack` y `configure` sin caché para
  Dolphin. Después llama al instalador completo. Los registros de Craft están en
  `bootstrap/` y los de compilación en `run/`. No se ha repetido la descarga de
  todas las dependencias en un entorno vacío.
- `./abrir-dolphin.sh [carpeta]` abre una sesión D-Bus privada y genera un registro
  independiente en `run/`. Detecta si el proceso termina en los dos primeros
  segundos; que siga activo no demuestra que haya una ventana funcional.
- La versión se define en `dolphin-version.json`. Los scripts comprueban el
  ejecutable antes de modificarlo. Cambiar la versión exige validar también el
  parche: una versión aún no adaptada se rechaza explícitamente.

## Parche, metadatos y recuperación

Cerrar Dolphin antes de cambiar la instalación y volverlo a abrir al terminar.

`python3 parchear-dolphin.py` compila e instala Dolphin completo: ejecutable,
bibliotecas, plugins, utilidades y recursos. Genera primero una instalación sin
parche y después otra corregida desde las mismas fuentes y dependencias. Ambas
se preparan con DESTDIR y se firman localmente antes de desplegarse. Los 380
archivos de la instalación probada coinciden con el artefacto corregido.

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
- `python3 -m unittest discover -s tests -p 'test_*.py'` pasa veinticinco pruebas de
  instalación, errores claros de JSON/configuración, copias dañadas, metadatos,
  cambios del ejecutable, reversión por fallo y recuperación de una interrupción.
  La preparación inicial con Craft se simula; el despliegue completo y la
  restauración también se han probado realmente con la compilación local.
  Las nuevas pruebas usan archivos temporales para ejecutar la limpieza,
  comparar el plan con lo borrado, proteger copias iniciales y comprobar la
  reinstalación tras cambios externos y el archivo de configuraciones CMake.
  También cubren procesos con rutas absolutas, relativas y nombre de ejecutable,
  y que abrir Dolphin durante la compilación impide el despliegue.

## Incidencias investigadas

- Python de python.org dio `CERTIFICATE_VERIFY_FAILED`: el instalador usa
  `SSL_CERT_FILE=/etc/ssl/cert.pem` manteniendo la verificación HTTPS.
- Enlaces rotos de Qt en `CraftRoot/include/` bloquearon una instalación. El
  instalador reintenta una vez solo si encuentra y elimina esos enlaces rotos.
- El D-Bus de launchd de Craft buscaba su configuración en una ruta de KDE.
  El lanzador usa un bus privado con configuración y socket explícitos. Los dos
  demonios del lanzador antiguo se identificaron y recibieron SIGTERM. Sus
  archivos de estado y registros antiguos se archivaron en `run/legacy/`.
- El Info.plist tenía vacíos nombre, identificador y versión. Ahora se rellenan.
  Esto podría afectar a la identificación y el foco de la ventana, pero no se ha
  demostrado que fuera la causa ni que el foco esté resuelto.
- La inspección automatizada registró un cierre inesperado por NSRangeException
  en Qt/Cocoa. Se corrigió un cálculo de filas que informaba cero filas cuando
  había menos elementos que columnas. Tras reiniciar el proceso no apareció esa
  excepción en el registro nuevo, pero la herramienta de accesibilidad continuó
  agotando el tiempo. El cierre inesperado sigue pendiente de validación real.
- KIO advierte que `/System/Volumes/Data/.Trashes` no pasa sus comprobaciones.
  La prueba de restauración pasó en el disco principal; esto no demuestra
  integración con la papelera de Finder ni con discos externos.

## Pendiente de validar

- Navegación, pestañas, vista dividida y estabilidad de la interfaz tras reiniciar.
- Visibilidad y restauración desde Finder de un archivo enviado a la papelera por
  Dolphin. Repetir con un archivo temporal en un disco externo disponible.
- Descarga y preparación desde cero en un entorno vacío y acceso desde el Dock.
- Si conviene corregir o retirar el servicio de launchd instalado por Craft.

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
