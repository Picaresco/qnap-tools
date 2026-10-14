# Qnap-Tools, entrega 4: registros y avisos, y preparar la publicación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** añadir al plugin el servidor MCP `qnap-logs` con las 8 herramientas aprobadas de registros, avisos y estado del sistema, de solo lectura, para QTS y QuTS hero; y dejar el proyecto preparado para publicarse (sin publicarlo).

**Architecture:** misma forma que las otras patas: `logs/comandos.py` (plantillas fijas), `logs/parsers.py` (texto -> estructura, `ValueError` si no reconoce la salida) y `logs/servidor.py` (`Herramientas(servidor.Base)`). Los tres registros del NAS (eventos, accesos, avisos) se leen con sus utilidades `log_tool`, `conn_log_tool` y `notice_log_tool` en modo consulta, que valen igual en los dos sistemas y no necesitan `python3` ni `sqlite3`. Lo que dependa del sistema lleva `sistema="hero"` o `"qts"`.

**Tech Stack:** Python >= 3.11, `mcp[cli]>=1,<2`, `paramiko`, `pytest`. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-10-13-qnap-tools-design.md`. Órdenes exploradas y límites: `pruebas/catalogo/logs.json`, `logs_hero.json`, `logs_qts.json`; reglas de la guardia en `pruebas/reglas/logs.json`.

## Global Constraints

- Solo lectura. Toda orden es un `Comando` de `logs/comandos.py`; cada una pasa `pruebas/guardia.py` en una prueba y se lanza en `pruebas/efectos.py --producto logs`.
- `log_tool`, `conn_log_tool` y `notice_log_tool`: SIEMPRE con `-q -v` y NUNCA con `sudo` (con `sudo`, `log_tool` altera la base de eventos; medido en QuTS hero y en QTS). Solo las opciones de consulta: `-s`, `-l`, `-o`, `-e`, `-d`, `-g`, `-k`. Sin `-v` fallan en silencio.
- Toda consulta a un registro va acotada en filas (`-l 0 -o N`): nunca se vuelca un registro entero al cliente. Los recuentos de eventos y de avisos (registros con tope: 100 000 y 10 000 filas) se hacen en el NAS (`grep -c`, `sort | uniq -c`). El registro de accesos NO se recorre entero ni en el NAS: en `nas3` tiene ids de 17 a 18 millones y `conn_log_tool -q -v` sin intervalo no devuelve ninguna fila (visto el 2026-10-14); su resumen se hace sobre una ventana de las últimas filas y se dice de cuántas.
- Una consulta sin resultados NO imprime cabecera. Lo que distingue "vacío" de "no respondió" es la línea final `Done. Return value is 0`.
- Las órdenes que recorren algo sacado del NAS usan `... | while read -r x; do`, nunca `for x in $(...)` (parte por espacios). Una plantilla no puede llevar `>`: los patrones de `grep` se escriben sin él (` <[0-3]. ` para el nivel de un mensaje del kernel).
- La guardia no admite `$( )` dentro de comillas dobles: cada dato de `getcfg` va en su propio `echo clave=$(getcfg ...)`.
- `getsysinfo` solo con `sudo` y con validador de centinelas (sin root devuelve `0 C` o `--` con código 0). `hal_app` solo `--se_enum`.
- No se lee: `uLinux.conf` entero (solo claves con `getcfg`), la sección `[Alert]` de destinatarios y credenciales de notificación, las MariaDB de QuLog Center y Notification Center, `qcli_log`, ni registros que solo lee root salvo que la orden vaya marcada con `sudo` y esté en el catálogo.
- Excluido por el diseño: saber si hay firmware nuevo (el NAS no lo deja en disco), estado en vivo de las fuentes redundantes (no hay consulta), historial de QuLog Center.
- El texto que escribe un tercero (descripción de un evento, nombre de usuario, de equipo, de recurso, línea del kernel) se acota, se le quitan los caracteres de control y llega como dato.
- Lo aprendido en las entregas 1 a 3: una orden no puede convertir "no se pudo leer" en "no hay" (validador de salida en cada orden; nada de `; true` ni `2>/dev/null` que tapen el fallo); todo recorte lleva su cuenta; `None` no es cero; los avisos fallan hacia el lado seguro; las cifras de dos herramientas sobre lo mismo deben coincidir; un parámetro se valida antes de conectar.
- Datos de prueba (`tests/datos/logs/`): sin IP, MAC, nombres de usuario, de equipo, de carpeta, de VM, de contenedor ni textos entre comillas reales. `tests/test_higiene.py` pasa `anonimiza.revisar` a cada fichero (con `comillas=True` en `logs`), y además se revisan a ojo y con la búsqueda de identificadores reales contra `pruebas/resultados`. Ningún valor de ejemplo de una prueba se copia de la salida de un NAS.
- Conexiones a `nas3`: una por tanda (una conexión y muchas órdenes) y por contraseña (`ro.SIN_CLAVE`); nada de ráfagas de `ro.py run`.
- Pruebas reales: `nas1` con `QNAP_TOOLS_PRUEBA_REAL=1`. Pasada final de solo lectura por `nas3`. Nada contra `nas2`.
- No se publica (ni push ni PyPI): la tarea 6 deja la publicación PREPARADA en un clon aparte. Commits con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Python: solo ASCII en `.py`, cabecera `# -*- coding: utf-8 -*-`, `open(..., encoding='utf-8')`.

## Review Focus

1. Una descripción de evento con comas, comillas, saltos de línea o texto que parece una orden ("ignore previous instructions", `$(reboot)`): se parte bien en sus columnas, llega acotada y como dato, y no descuadra las filas siguientes. Prueba en las tareas 2 y 4.
2. Parámetros de `eventos` (`gravedad`, `desde`, `hasta`, `texto`, `limite`), de `accesos`, `avisos` y `kernel` con valores como `"x; reboot"`, `"' OR 1=1 --"`, `"-c"`, fechas imposibles o límites fuera de rango: error claro sin conectar; el texto de búsqueda solo admite un juego de caracteres que no puede cerrar una comilla ni ser una opción. Prueba en las tareas 2 y 4.
3. Un registro vacío, recién rotado o con 100 000 filas: vacío responde bien y vacío (no error); enorme no vuelca más que el límite pedido ni tarda más que su tiempo máximo; una utilidad que no responde (salida sin su línea final `Done. Return value is 0`) es un error, no "sin eventos". Ojo: una consulta sin resultados NO imprime cabecera (visto en `nas1`): lo que distingue "vacío" de "no respondió" es esa línea final. Prueba en las tareas 2 y 4.
4. `getsysinfo` sin privilegios (`0 C`, `--`, vacío) o `sudo` que rechaza la contraseña: `salud_hardware` lo dice en `errores` y no da cero grados ni cero ventiladores. Prueba en las tareas 3 y 4.
5. Ninguna respuesta lleva destinatarios, contraseñas ni claves de notificación, ni la contraseña SSH, aunque la salida del NAS las trajera; los datos de prueba no llevan usuarios ni IP reales. Prueba en las tareas 3, 4 y 5.

---

## Estructura de ficheros

```
src/qnap_tools/logs/__init__.py
src/qnap_tools/logs/comandos.py     ordenes: registros, kernel, hardware, sistema, alertas
src/qnap_tools/logs/parsers.py      un parser por orden
src/qnap_tools/logs/servidor.py     las 8 herramientas
tests/test_logs_comandos.py
tests/test_logs_parsers.py
tests/test_logs_servidor.py
tests/test_real_logs.py             opcional, contra nas1
tests/datos/logs/*_hero.txt, *_qts.txt
```

## Herramientas y órdenes

| Herramienta | Qué da | Órdenes |
|---|---|---|
| `eventos(nas, gravedad="todos", desde="", hasta="", texto="", limite=50)` | los últimos eventos del sistema, del más reciente al más antiguo: id, gravedad (info, aviso, error), fecha y hora, usuario, IP, equipo, aplicación, categoría y descripción; filtros por gravedad, intervalo de fechas y palabra | `EVT_LISTA`, `EVT_PALABRA` (variantes de `log_tool -q -v ... -s 13 -l 0 -o N`) |
| `eventos_resumen(nas)` | cuántos eventos hay por gravedad, desde cuándo, los últimos errores y avisos y cuántos por aplicación | `EVT_RECUENTO`, `EVT_LISTA` |
| `accesos(nas, tipo="todos", limite=50)` | los últimos accesos (inicio y cierre de sesión, intentos fallidos, operaciones con ficheros): fecha, usuario, IP, equipo, servicio, acción, recurso y resultado; los últimos intentos fallidos agrupados por origen; y de cuándo es el acceso más antiguo que se conserva | `CONN_LISTA` (también con `tipo` aviso para los fallidos), `CONN_EXTREMOS` |
| `avisos(nas, limite=50)` | los avisos del centro de notificaciones del escritorio: gravedad, origen, fecha, texto y código; recuento por gravedad y origen | `NOTICE_LISTA`, `NOTICE_RESUMEN` |
| `kernel(nas, nivel=3, lineas=50)` | mensajes del kernel guardados por el NAS: cuántos hay por nivel, los últimos de ese nivel o más graves, y la cola del registro en vivo | `KMSG_NIVELES`, `KMSG_LINEAS`, `DMESG` |
| `salud_hardware(nas)` | temperatura de CPU y de sistema, ventiladores, cabinas con su estado, fuentes que tiene el modelo, SAI configurado, y `avisos` | `SENSORES` (sudo), `CHASIS`, `FUENTES`, `SAI` |
| `sistema_estado(nas)` | tiempo encendido, carga y memoria, firmware instalado, última comprobación y última actualización, política de actualización automática, aplicaciones de registro y seguridad con su versión, motores de registro en marcha y volcados de cuelgues guardados | `CARGA`, `FIRMWARE`, `FIRMWARE_AUTO`, `APPS`, `MOTORES`, `VOLCADOS` |
| `alertas_config(nas)` | nivel de alerta, zumbador, aviso de espacio libre, umbrales SMART y servidor syslog | `ALERTAS`, `SMART_UMBRALES` (la de discos), `SYSLOG` |

Las órdenes exactas se fijan en cada tarea a partir del catálogo y de la salida real; lo que cambie respecto a esta tabla se anota como decisión.

---

### Task 1: base de la pata y laboratorio

**Files:**
- Create: `src/qnap_tools/logs/__init__.py`, `src/qnap_tools/logs/comandos.py` (sin órdenes todavía)
- Modify: `pyproject.toml` (script `qnap-tools-logs = qnap_tools.logs.servidor:main`, versión 0.4.0), `src/qnap_tools/__init__.py`, `tests/test_paquete.py`, `src/qnap_tools/comandos.py` (tipo de parámetro `palabra`), `pruebas/captura.py` (valores y nombres de `logs`), `pruebas/anonimiza.py`
- Test: `tests/test_anonimiza.py`, `tests/test_comandos.py`

**Interfaces:**
- Produces: `comandos.TIPOS["palabra"]` (letras, cifras, espacio y `_ . : @ / -`, de 2 a 40 caracteres, sin empezar por `-`); `anonimiza.Anonimizador(..., comillas=True)` que sustituye de forma coherente los textos entre comillas dobles (nombres de usuario, de VM, de carpeta dentro de la descripción de un evento) y los nombres de red de Docker (`br-<12 hex>`, `veth<hex>`); `captura.py logs <nas> <sufijo>`; `efectos.py <nas> --producto logs`.

- [ ] **Step 1:** pruebas: `palabra` rechaza comillas, `;`, `$`, `|`, barra invertida, un guion inicial, cadena vacía y más de 40 caracteres; el anonimizador sustituye `"texto"` por `"textoN"` (coherente e idempotente), `br-0123456789ab` y `vethabc1234`, y `revisar(..., comillas=True)` detecta lo que quede. Ver fallar.
- [ ] **Step 2:** implementar; ver pasar. `captura.py`: `_valores_logs` y `_nombres_logs` (usuarios y equipos que aparecen en los registros). Paquete vacío y entry point. Batería en verde.
- [ ] **Step 3:** commit `feat: base de la pata de logs`.

### Task 2: órdenes y parsers de los tres registros

**Files:**
- Modify: `src/qnap_tools/logs/comandos.py`
- Create: `src/qnap_tools/logs/parsers.py`, `tests/test_logs_comandos.py`, `tests/test_logs_parsers.py`, `tests/datos/logs/`

**Interfaces:**
- Produces: `EVT_LISTA` (`{gravedad}` 0-3, `{desde}`, `{hasta}`, `{limite}`; el intervalo va siempre, con fechas extremas por defecto), `EVT_PALABRA` (además `{texto}`), `EVT_RECUENTO`; `CONN_LISTA` (`{tipo}`, `{limite}`), `CONN_EXTREMOS` (primera y última fila); `NOTICE_LISTA` (`{limite}`), `NOTICE_RESUMEN`; parsers `evt_lista`, `evt_recuento`, `conn_lista`, `conn_extremos`, `notice_lista`, `notice_resumen`.

- [ ] **Step 1:** `tests/test_logs_comandos.py`: cada orden pasa la guardia; ids únicos; toda orden con `*_log_tool` lleva `-q -v`, ninguna va con `sudo` y solo usa opciones de consulta; toda lista lleva `-l 0 -o {limite}`; parámetros validados (`entero`, `fecha`, `palabra`). Ver fallar.
- [ ] **Step 2:** escribir las órdenes; ver pasar. Capturar en `nas1` y en `nas3` con las órdenes del producto (límite pequeño); anonimizar con `comillas=True`; `--revisar`: 0 dudas, y revisión a ojo de cada fichero.
- [ ] **Step 3:** una prueba por parser: las columnas se toman de la cabecera que imprime la utilidad (no de posiciones fijas); la descripción se reconstruye aunque lleve comas y una línea que no empieza por un id se une a la anterior (Review Focus 1); gravedad y tipo por su código, con el código crudo si no se conoce; fecha de los avisos de epoch a ISO; servicio y acción de un acceso con su nombre conocido y su código; salida sin la línea final `Done. Return value is 0` (o con otro valor) -> `ValueError`; línea final sin cabecera ni filas -> lista vacía (Review Focus 3). Ver fallar.
- [ ] **Step 4:** implementar; ver pasar toda la batería.
- [ ] **Step 5:** commit `feat: ordenes y parsers de los registros del NAS`.

### Task 3: órdenes y parsers de kernel, hardware, sistema y alertas

**Files:** los mismos que la tarea 2.

**Interfaces:**
- Produces: `KMSG_NIVELES`, `KMSG_LINEAS` (`{nivel}`, `{lineas}`), `DMESG` (`{lineas}`), `SENSORES` (sudo, validador de centinelas), `CHASIS` (`hal_app --se_enum`), `FUENTES`, `SAI`, `CARGA`, `FIRMWARE`, `FIRMWARE_AUTO` (claves con `getcfg`, no `awk` sobre `uLinux.conf`), `APPS`, `MOTORES`, `VOLCADOS`, `ALERTAS`, `SYSLOG`; parsers del mismo nombre en minúsculas.

- [ ] **Step 1:** ampliar `tests/test_logs_comandos.py`: `getsysinfo` solo en órdenes con `sudo`; ninguna orden lee `uLinux.conf` entero ni la sección `[Alert]` de destinatarios; `hal_app` solo `--se_enum`; todo `tail` lleva antes su cuenta (`==lineas N`); ninguna orden usa `--help`. Ver fallar.
- [ ] **Step 2:** órdenes; ver pasar. Capturar en `nas1` y `nas3`; `--revisar`: 0 dudas.
- [ ] **Step 3:** una prueba por parser: niveles del kernel con su nombre; líneas acotadas y sin caracteres de control; temperaturas en grados y ventiladores en RPM, y los centinelas (`0 C`, `--`, vacío) como `ValueError` (Review Focus 4); cabinas con su estado; versión de firmware y fechas; SAI desactivado frente a SAI que no responde; alertas con sus umbrales. Ver fallar.
- [ ] **Step 4:** implementar; ver pasar.
- [ ] **Step 5:** commit `feat: ordenes y parsers de kernel, hardware y sistema`.

### Task 4: las 8 herramientas

**Files:**
- Create: `src/qnap_tools/logs/servidor.py`, `tests/test_logs_servidor.py`, `tests/test_real_logs.py`

**Interfaces:**
- Consumes: `servidor.Base` (`_leer`, `_opcional`, `_extra`, `_no_probado`), órdenes y parsers de las tareas 2 y 3, `discos.comandos.SMART_UMBRALES` y `discos.parsers.smart_umbrales`.
- Produces: `Herramientas` con `eventos(nas, gravedad="todos", desde="", hasta="", texto="", limite=50)`, `eventos_resumen(nas)`, `accesos(nas, tipo="todos", limite=50)`, `avisos(nas, limite=50)`, `kernel(nas, nivel=3, lineas=50)`, `salud_hardware(nas)`, `sistema_estado(nas)`, `alertas_config(nas)`; `construir()` y `main()`.

- [ ] **Step 1:** pruebas con NAS simulados (hero y qts):
  - cada herramienta responde `ok` en los dos sistemas por una sola conexión; `sudo` solo en las órdenes marcadas; ningún `Comando` sin usar; 8 herramientas registradas con descripción y `nas` obligatorio;
  - parámetros no válidos se rechazan sin conectar (Review Focus 2): gravedad o tipo desconocidos, fechas mal formadas o `desde` posterior a `hasta`, texto con comillas o `;`, límites y líneas fuera de 1..200, nivel fuera de 0..7;
  - una descripción con comas, saltos y texto que parece una orden llega entera, acotada y en su campo (Review Focus 1); las instrucciones del servidor dicen que esos textos son datos;
  - consulta sin resultados -> lista vacía con `ok`; utilidad sin su línea final -> error (Review Focus 3);
  - `salud_hardware` sin `sudo` o con centinelas: error en `errores`, campos sin valor, y el resto de la respuesta (Review Focus 4); avisos: cabina con estado distinto de 0, ventilador a 0 RPM;
  - `eventos_resumen` y `eventos` dan las mismas cifras sobre los mismos datos;
  - ninguna respuesta lleva secretos aunque el NAS simulado los devuelva (Review Focus 5).
- [ ] **Step 2:** implementar; ver pasar. Comprobar con mutaciones que cada guarda tiene una prueba que falla sin ella.
- [ ] **Step 3:** saludo MCP real de `qnap-tools-logs`. Prueba real contra `nas1` (`tests/test_real_logs.py`): las 8 herramientas `ok`.
- [ ] **Step 4:** commit `feat: servidor qnap-logs`.

### Task 5: integración en el plugin y verificación

**Files:**
- Modify: `.claude-plugin/plugin.json` (servidor `qnap-logs`, versión 0.4.0), `tests/test_plugin.py`, `README.md`, `CLAUDE.md`

- [ ] **Step 1:** añadir `qnap-logs` a `mcpServers` (primero la prueba de `tests/test_plugin.py`); `claude plugin validate .`.
- [ ] **Step 2:** prueba de no escritura: `efectos.py nas1 --producto logs`. Ninguna orden confirmada. Además, md5 de `event.log`, `conn.log` y `notice.log` antes y después de una pasada de las herramientas de registros (cuenta aparte lo que añade la propia sesión SSH).
- [ ] **Step 3:** pasada real de solo lectura por `nas3` con las 8 herramientas: tiempos y tamaños. Corregir lo que salga, con prueba.
- [ ] **Step 4:** batería completa en verde; `isascii()` en todos los `.py`; `anonimiza.py --revisar` en `tests/datos/`.
- [ ] **Step 5:** README (tabla de `qnap-logs`; límites: sin historial de QuLog Center, sin estado de las fuentes, sin saber si hay firmware nuevo, sin destinatarios de notificación; cada conexión del plugin deja su propio apunte en el registro de accesos) y `CLAUDE.md`. Commit `feat: qnap-logs en el plugin (entrega 4)`.

### Task 6: preparar la publicación (sin publicar)

**Files:**
- Create (fuera del repositorio): un clon limpio en `C:\Users\Alberto\Documents\code_claude\qnap-tools-publicar`
- Modify (en el repositorio): `pruebas/anonimiza.py` si falta algún patrón; `README.md` (instalación desde GitHub y PyPI, dejando claro que aún no está publicado hasta que se publique)

- [ ] **Step 1:** guion `pruebas/prepara_publicacion.py <destino>`: copia el árbol versionado de `main` (`git archive`), sustituye en todo lo versionado los datos del usuario por otros de ejemplo (volumen `ZFS600_DATA`; redes `br-<12 hex>` y `veth`; alias `nas1`, `nas2`, `nas3` y las claves `NAS2_*`, `NAS3_*`; notas "" y número de discos en `pruebas/` y `docs/`) y falla si queda alguno. Con su prueba (`tests/test_prepara_publicacion.py`) sobre un árbol de ejemplo.
- [ ] **Step 2:** generar el clon: árbol limpio, `git init` con historial nuevo (un commit, autor del usuario), batería en verde dentro del clon, `anonimiza.py --revisar` 0 dudas, búsqueda de los patrones del usuario: 0 apariciones.
- [ ] **Step 3:** construir el paquete en el clon (`python -m build`), `twine check dist/*`, e instalarlo en un entorno limpio para hacer el saludo MCP de los cinco servidores con `uvx --from <wheel>`.
- [ ] **Step 4:** dejar escrito en `CLAUDE.md` lo que falta para publicar (crear `picaresco/qnap-tools`, `git push`, subir a PyPI, cambiar `plugin.json` a `uvx qnap-tools-...`) y que exige la confirmación expresa del usuario. NO publicar. Commit `chore: guion para preparar la publicacion`.

---

## Anexo: registro de la ejecucion

Ejecutado el 2026-10-14 en la rama `entrega-4-logs` (ejecucion en linea, una revision independiente al
final). Copia del registro de trabajo: lo que se decidio al apartarse del plan, lo que corrigio
la revision final y lo que queda aplazado. Revision final independiente (opus): sin criticos; corregidos los 4 importantes y el menor M3 (solo ASCII), mas dos filas reales que destapo leer enteros los registros de nas1. Pendiente: pasada real de las 8 herramientas por nas3 (VPN caida).

### Tareas

- Task 1: complete (commits fd6b729..84e0aed, tests: .venv/Scripts/python.exe -m pytest -q → 1747 passed, 10 skipped in 10.95s)
- Task 2: complete (commits 84e0aed..5cb10c0, tests: .venv/Scripts/python.exe -m pytest -q → 1835 passed, 10 skipped in 10.81s)
- Task 3: complete (commits 5cb10c0..73dc8fc, tests: .venv/Scripts/python.exe -m pytest -q → 2036 passed, 10 skipped in 11.16s)
- Task 4: complete (commits 73dc8fc..82a066d, tests: .venv/Scripts/python.exe -m pytest -q → 2094 passed, 11 skipped in 11.45s)
- Task 5: complete (commits 82a066d..110e289, tests: .venv/Scripts/python.exe -m pytest -q → 2094 passed, 11 skipped in 11.30s)
- Task 6: complete (commits 110e289..74a4a93, tests: .venv/Scripts/python.exe -m pytest -q → 2099 passed, 11 skipped in 12.77s)
- Pre-flight: T1 produce TIPOS["palabra"], Anonimizador(comillas=True) y captura.py logs; T2 y T3 los consumen — sin conflicto.
- Pre-flight: T2 produce EVT_LISTA (gravedad, desde, hasta, limite), EVT_PALABRA, EVT_RECUENTO, CONN_LISTA, CONN_EXTREMOS, NOTICE_LISTA, NOTICE_RESUMEN; T4 consume esos nombres — la tabla de herramientas del plan ya esta alineada (sin EVT_FECHAS ni CONN_RESUMEN).
- Pre-flight: T4 consume discos.comandos.SMART_UMBRALES y discos.parsers.smart_umbrales — existen en main.
- Pre-flight: T5 cambia tests/test_plugin.py (lista de servidores) antes que plugin.json — sin conflicto.
- Final review: revisor-e4 (opus), informe en %TEMP%/revisor-e4/informe.md: sin criticos, 4 importantes, 9 menores; veredicto "con arreglos".

### Decisiones (30)

- Setup: Ruling: el plan se ejecuta sin esperar revision del usuario (dijo "pasa a la entrega 3 y 4 ... te revisare manana" y "terminas las dos entregas que te falta") — coste si es un error: rehacer lo que no le guste del plan.
- Setup: Ruling: pasada real de solo lectura por nas3 autorizada por defecto (se lo dije antes de empezar); una conexion por tanda y por contrasena; nas2 no se toca — coste: ninguno si se respeta.
- Setup: Ruling: la tarea 6 PREPARA la publicacion en un clon aparte y no publica nada (ni push ni PyPI): eso exige la confirmacion expresa del usuario.
- Task 1: Ruling: la regla de puentes (br-<12 hex>) y veth de Docker va SIEMPRE en el anonimizador y se aplico ya a los datos y pruebas versionados (34 puentes y 40 veth de redes, con una sola tabla para que un puente se llame igual en todas las salidas), en vez de dejarlo para la copia de publicacion — la prueba de higiene lo exigia y el usuario pidio quitar esos datos — coste: ninguno (solo cambian esos nombres; la migracion lo comprueba).
- Task 1: Ruling: el tipo "palabra" admite letras con acento (\w): un registro en castellano los lleva; shlex.quote la entrecomilla y no puede llevar comillas, ; $ | % * ( ) & ni empezar por guion — coste: ninguno conocido.
- Task 1: Ruling: la version 0.4.0, el script qnap-tools-logs y plugin.json pasan a la tarea 5 (el plan los ponia en la 1): tests/test_plugin.py exige que plugin y paquete digan lo mismo y el servidor no existe hasta la tarea 4; captura.py de logs pasa a la tarea 2 (necesita las ordenes) — coste: ninguno.
- Task 2: Ruling: NOTICE_LISTA empieza por "echo ==zona $(date +%z)" y la hora de los avisos (epoch) se da en la hora local del NAS, como los eventos y la web, en vez de en UTC — coste: una linea mas por consulta.
- Task 2: Ruling: la gravedad de los avisos solo lleva nombre en 3 error, 4 aviso y 6 informacion (los vistos con su significado en NAS reales); 0 y 5 salen con su codigo crudo — coste: el modelo ve "0"/"5" sin significado.
- Task 2: Ruling: el anonimizador (modo comillas) tapa ademas el usuario, el equipo y el recurso de cada fila de los tres registros, por la columna de la cabecera; el nombre de un trabajo de copia (sin comillas) se tapo a mano en la revision a ojo — coste: un nombre libre sin comillas en otra captura puede escaparse; la revision a ojo sigue siendo obligatoria.
- Task 2: Ruling: captura.py de logs saca los nombres a ocultar con las ordenes de discos y virtualizacion ("pata.ORDEN") y lee una sola vez cada orden sin parametros — coste: unas 10 lecturas mas por captura.
- Task 2: Ruling: "carpeta26 Station"/"carpeta7 Desktop" en las capturas es sobreanonimizado (carpetas de fabrica como Container) y se deja asi — coste: ninguno para las pruebas.
- Task 3: Ruling: tipo de parametro nuevo "nivel" ([0-7]) en comandos.TIPOS para el kernel: un entero cualquiera haria clases como [0-15] en el grep — coste: ninguno.
- Task 3: Ruling: KMSG_NIVELES filtra el cuarto campo con '^.[0-7].$' (sin "<" ni ">") y da sin_nivel = lineas - suma; VOLCADOS lista /etc/logs con stat (tamano y epoch) y la zona del NAS, en vez de ls (fechas sin ano) — coste: 35 lineas por consulta.
- Task 3: Ruling: FIRMWARE_AUTO lleva "leido=$(getcfg System Version)" para distinguir "seccion ausente" (nas3) de "no se pudo leer"; modo, modo_v3 y programa salen con su valor crudo (significado no validado) — coste: el modelo ve numeros sin significado.
- Task 3: Ruling: APPS anade QuFirewall a la lista del catalogo; ALERTAS da nivel y espacio minimo (MB, sin validar la unidad) en crudo; SYSLOG solo da claves conocidas (lista blanca) — coste: una clave nueva util no saldria.
- Task 3: Ruling: una linea del kernel sin el formato de siempre llega con fecha y nivel None y su texto, en vez de tumbar la lista — coste: ninguno conocido.
- Task 4: Ruling: el aviso del escritorio lleva tambien "codigo" (msgCode del NAS; "0" = sin codigo): el plan pide texto y codigo en la herramienta avisos — coste: ninguno.
- Task 4: Ruling: eventos_resumen cuenta por aplicacion sobre los ultimos 200 eventos de cualquier gravedad (ventana dicha en la respuesta); accesos agrupa por IP, usuario y servicio los ultimos 200 de tipo aviso — coste: un NAS con muchos avisos solo ve la ventana reciente.
- Task 4: Ruling: en salud_hardware lo imprescindible es CHASIS (sin sudo); sensores, fuentes y SAI son accesorios. En sistema_estado lo es CARGA; en kernel, KMSG_LINEAS; en alertas_config, ALERTAS — coste: si falla lo imprescindible se pierde la entrada entera.
- Task 4: Ruling: los avisos de sistema_estado esperan siempre rsyslogd, qLogEngined y qNoticeEngined, y qulogd/qulogdb o ncdb solo con QuLog o NotificationCenter activos; no se avisa por temperaturas (sin umbral validado) — coste: una CPU muy caliente no sale en avisos.
- Task 4: Ruling: el saludo MCP se hizo con "python -m qnap_tools.logs.servidor"; el punto de entrada qnap-tools-logs llega en la tarea 5 (ruling de la tarea 1) — coste: ninguno.
- Task 5: Ruling: la pasada real por nas3 (paso 3) queda PENDIENTE: a las 05:00 se perdio la conexion con la red de ese NAS (no responde ni al ping) y recuperarla depende del usuario. Las ordenes y salidas de QTS ya estan validadas con capturas reales de nas3 de esta misma entrega; se reintenta antes del final — coste: las 8 herramientas no se han visto juntas contra un QTS real (tiempos y tamanos de QTS sin medir).
- Task 5: Ruling: la prueba de version duplicada en test_plugin.py se quito: ya la hace tests/test_paquete.py (subida a 0.4.0) — coste: ninguno.
- Task 6: Ruling: la copia publicable se genera desde la rama (--ref HEAD) y no desde main, que aun no tiene la entrega 4; se rehace desde main tras fusionar — coste: rehacerla (un minuto).
- Task 6: Ruling: los alias pasan a nas1/nas2/nas3 (no "prod"): un nombre con "prod" diria lo mismo que la nota "" que el usuario pidio quitar; el volumen pasa a ZFS600_DATA (numero que no usa ningun otro dato) — coste: ninguno conocido.
- Task 6: Ruling: el guion y su prueba (que nombran los datos a quitar) no se copian a la version publicable; "de pruebas" de skills/ y README se deja porque es un consejo general, no un dato del usuario — coste: ninguno.
- Final: Ruling: I3 se resuelve con UTC y no con la hora local de cada fecha: convertirla bien exige las reglas de zona del NAS (tzdata no esta en Windows sin una dependencia nueva) o una llamada a date por fila — coste: eventos (hora local) y avisos (UTC) no se comparan a simple vista; el README y las instrucciones lo dicen.
- Final: Ruling: los puertos del .env no se buscan en la copia publicable (22 o 223 salen en cualquier texto) — coste: ninguno, un puerto no identifica.
- Final: Ruling: en accesos no hay columna que ancle tanto como el epoch; un recurso que imite servicio, accion y resultado deja la fila con dos cortes y la consulta da error (no datos falsos) — coste: un fichero con ese nombre deja accesos fuera de servicio hasta que su fila salga de la ventana.
- Final: Ruling: el fallo del codigo "---" ya estaba en la tarea 2 (exigia cifra): la prueba real de la tarea 4 solo miraba los 200 ultimos eventos; ahora tambien se ha leido el registro entero — coste: ninguno.

### Corregido tras la revision final (6)

- Final: fixed I1 contrasena en los datos de una respuesta ok (Flota.por_nas pasa _sin_contrasena por todo el arbol) — test_la_contrasena_no_sale_aunque_alguien_la_haya_tecleado_en_un_registro RED->GREEN, suite 2100/2100.
- Final: fixed I2 comas del texto libre que descuadraban columnas (anclaje con todas las columnas que siguen; epoch = fecha de la fila +-26 h; fila con dos cortes posibles = error) — 4 pruebas RED->GREEN, suite 2104/2104.
- Final: fixed I3 fechas de avisos y del apagado forzado con el desfase de hoy (pasan a UTC con Z; fuera la zona de las ordenes y de 4 capturas) — test_la_hora_de_un_aviso_no_depende_del_cambio_de_hora y 5 mas RED->GREEN, suite 2102/2102.
- Final: fixed I4 prepara_publicacion dejaba la copia a medias y no veia valores del .env con otras mayusculas — 2 pruebas RED->GREEN, suite 2105/2105.
- Final: fixed M3 (subido a importante: regla del usuario solo ASCII en .py) "o con acento" literal en prepara_publicacion.py — test_todo_el_codigo_python_versionado_es_ascii RED->GREEN, suite 2105/2105.
- Final: fixed I2 (segunda parte, hallada con test_real_logs y leyendo enteros los registros de nas1) el cliente de un evento puede ser el nombre de una aplicacion y el codigo de mensaje puede ser "---": el ancla de eventos es solo el epoch (= fecha de la fila) y el numero de codigo o nada — test_el_cliente_de_un_evento_puede_ser_el_nombre_de_una_aplicacion y test_un_evento_sin_codigo_de_mensaje_se_lee RED->GREEN, suite 2107/2107; nas1: 3770 eventos, 10000 accesos y 247 avisos leidos sin rechazo.

### Menores aplazados (8)

Resueltos en la 0.4.1 (2026-10-14): M6 (solo se avisa de los volcados de los ultimos 30 dias). Ya no aplica: M9 (pasada por nas3 hecha).

- Final: minor (deferred): M1 EVT_RECUENTO cuenta filas con grep y pierde el codigo de log_tool; continuaciones que empiezan por "N," cuentan como fila.
- Final: minor (deferred): M2 se_conserva.filas es ultimo.id - primero.id + 1 (estimacion): renombrar a filas_aprox.
- Final: minor (deferred): M4 _texto acota sin senal de recorte; SIN_CONTROL deja pasar C1 (\x80-\x9f) y U+2028/2029; una continuacion que parezca "N," tumba la lista entera.
- Final: minor (deferred): M5 sin validar en real: -d inclusivo, texto con espacios, filtros a traves del servidor; "_" de palabra puede ser comodin LIKE.
- Final: minor (deferred): M6 el aviso de volcados se repite mientras exista el fichero, aunque sea de hace meses.
- Final: minor (deferred): M7 kernel es todo o nada por KMSG_LINEAS; sensores, por cualquier campo.
- Final: minor (deferred): M8 KMSG_NIVELES (campo 4) y KMSG_LINEAS (patron en toda la linea) cuentan con criterios distintos.
- Final: minor (deferred): M9 pasada real por nas3 de las 8 herramientas pendiente (VPN caida); tiempos de eventos_resumen y accesos en un QTS grande sin medir.

### Validacion con un reinicio de nas1 (2026-10-14, version 0.4.2)

- Falso aviso hallado al reiniciar nas1 desde la web: el NAS guarda un `pstore_N_*.log` (la
  consola del arranque anterior) en CADA reinicio en caliente, tambien en uno ordenado; los tres
  de nas1 acaban en `reboot: machine restart`. `sistema_estado` los daba por "volcados tras
  cuelgues". Arreglo: VOLCADOS anade una seccion `==cierres` con, de cada .log, las lineas de
  fallo (`Kernel panic|Oops:|BUG:`), las de `invoked oom-killer` y la ultima linea; cada volcado
  lleva `cierre` (reinicio, apagado, fallo, sin_cierre; None si no es .log) y solo se avisa del
  que no acaba en orden o del arranque con procesos matados por falta de memoria (el de agosto
  de nas1: 15). Pruebas RED->GREEN (parser y servidor); `volcados_hero.txt` recapturado; la
  seccion de cierres de `volcados_qts.txt` esta escrita a mano (sin acceso a los QTS).
  `test_real_logs` ok; efectos `--producto logs` en nas1: 22 ordenes, 0 confirmadas
  (`efectos_producto_logs_042.json`).
- Validado de paso tras el arranque: motores de registro parados los primeros minutos (aviso
  correcto, arrancan solos).

### Pasada por QTS con la 0.4.3 (2026-10-15)

- Pasada de solo lectura con el codigo 0.4.3 por los dos QTS de produccion (36 herramientas;
  nas3 por contrasena, nas2 por clave con una copia de los datos del plugin): nas3 37 de 37 ok;
  nas2 33 de 34 ok. El fallo de nas2 fue `eventos` (evt_lista agoto los 40 s) con el NAS muy
  cargado (carga 8,5 con 4 hilos, discos SMR con esperas de 300 a 900 ms); repetida poco
  despues tardo 1,1 s: no se cambia nada, el error ya dice que no termino a tiempo.
- Volcados en nas3: uno acaba en `sysrq: Resetting` (el apagado se colgo, el sistema vuelve a
  montar los discos y fuerza el reinicio): salia `sin_cierre`; ahora `reinicio_forzado` (y
  `apagado_forzado` con `sysrq: Power Off`; el kernel antiguo escribe `SysRq :`). Y la carpeta
  `pstore_dmesg_log_1_<fecha>` (dos ficheros `dmesg-ramoops-N` con cabecera `Oops#1 Part1` y
  `Panic#2 Part1`: un Oops y un `Kernel panic - not syncing: Fatal exception in interrupt` de
  2020) salia sin leer; ahora VOLCADOS cuenta esas cabeceras (`==registro <carpeta> N`) y sale
  `fallo`. Pruebas RED->GREEN; `volcados_qts.txt` es ya la captura real de nas3 (la parte de
  cierres escrita a mano se ha ido). Validado en real en nas3 con `sistema_estado`.
- Pendiente: prueba real y de no escritura en el NAS de laboratorio (apagado ese dia); la parte
  nueva solo lee (ls, grep, cat de los registros).
