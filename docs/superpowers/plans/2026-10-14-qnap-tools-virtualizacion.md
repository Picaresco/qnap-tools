# Qnap-Tools, entrega 3: virtualización y contenedores

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** añadir al plugin el servidor MCP `qnap-virtualizacion` con las 10 herramientas aprobadas de máquinas virtuales (Virtualization Station) y contenedores (Container Station), de solo lectura, para QTS y QuTS hero.

**Architecture:** misma forma que redes y discos: `virtualizacion/comandos.py` (plantillas fijas), `virtualizacion/parsers.py` (texto -> estructura, `ValueError` si no reconoce la salida) y `virtualizacion/servidor.py` (`Herramientas(servidor.Base)`). Las órdenes son las mismas en los dos sistemas (`sistema="ambos"`): lo que cambia entre NAS es si el paquete está instalado y activo, que ya lo da `Flota.perfil(nas).paquetes` (`QKVM`, `container-station`). Si un paquete no está, la herramienta responde `ok` con `activo: false` y no lanza nada.

**Tech Stack:** Python >= 3.11, `mcp[cli]>=1,<2`, `paramiko`, `pytest`. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-10-13-qnap-tools-design.md`. Órdenes exploradas y límites: `pruebas/catalogo/virtualizacion.json`, `virtualizacion_hero.json`, `virtualizacion_qts.json`; reglas de la guardia en `pruebas/reglas/virtualizacion.json`.

## Global Constraints

- Solo lectura. Toda orden es un `Comando` de `virtualizacion/comandos.py`; cada una pasa `pruebas/guardia.py` en una prueba y se lanza en `pruebas/efectos.py --producto virtualizacion`.
- `virsh` SIEMPRE con `-r -c qemu:///system` y con `LD_LIBRARY_PATH=/QVS/usr/lib:/QVS/usr/lib64:/QVS/lib`; nunca `--security-info`; solo subórdenes de consulta (`list`, `domstats`, `dumpxml`, `domifaddr`, `snapshot-list`). Sin `sudo`.
- `qemu-img` solo `info -U` (no bloquea la imagen de una VM en marcha).
- `docker` solo con subórdenes de consulta (`info`, `ps`, `inspect`, `stats --no-stream`, `logs --tail`, `network ls|inspect`, `compose ls`, `system df`); `docker ps` nunca con el campo `Size`; `docker inspect` siempre con `--format` de campos concretos; nunca variables de entorno (`.Config.Env`), ni la orden de arranque (`.Config.Cmd`, `.Args`, `.Path`), ni etiquetas enteras; `docker logs` siempre con `--tail N` y sin `-f`. La ruta del cliente sale de `Install_Path` de `qpkg.conf`, nunca fija.
- Excluido por el diseño: API HTTP de Virtualization Station; el cliente `lxc` (escribe en el home); el agente del invitado (libvirt lo prohíbe en solo lectura); capturas de consola; `qvs.db` y `ctstation.sqlite`; contraseñas de VNC.
- Ninguna ruta que cambie entre NAS va fija: la carpeta de las VMs sale de la ruta de sus discos.
- El texto que escribe un tercero (nombre y descripción de una VM, nombre de contenedor, de imagen, de red, líneas de registro) se acota y llega como dato; las líneas de registro además sin caracteres de control.
- Lo aprendido en las entregas 1 y 2: una orden no puede convertir "no se pudo leer" en "no hay" (sin `; true` ni `2>/dev/null` que tapen el fallo; validador de salida en cada orden); todo recorte lleva su cuenta; `None` no es cero; los avisos fallan hacia el lado seguro (lo que no se reconoce se avisa, no se calla); las cifras de dos herramientas sobre lo mismo deben coincidir.
- Datos de prueba (`tests/datos/virtualizacion/`): sin IP, MAC, UUID, nombres de VM, de contenedor, de imagen privada, de red, de proyecto, de carpeta ni descripciones reales. `anonimiza.py --revisar` debe dar 0 dudas.
- Pruebas reales: `nas1` (QuTS hero; VS con VMs, contenedores parados) con `QNAP_TOOLS_PRUEBA_REAL=1`. Pasada final de solo lectura por `nas3` (VS con VMs en marcha y 45 contenedores). Nada contra `nas2`.
- No se publica (ni push ni PyPI). Commits con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Python: solo ASCII en `.py`, cabecera `# -*- coding: utf-8 -*-`, `open(..., encoding='utf-8')`.

## Review Focus

1. NAS sin Virtualization Station o sin Container Station (o con el paquete desactivado): las herramientas de esa mitad responden `ok` con `activo: false` y no lanzan `virsh` ni `docker`; el paquete activo pero con el servicio parado (sin socket) es un error claro, no una lista vacía. Prueba en la tarea 4.
2. `vm_detalle`, `contenedor_detalle` y `contenedor_logs` con un nombre que no existe, o con `"x; reboot"`, `"-f"`, `"$(id)"`: error claro sin lanzar nada con ese valor; `lineas` fuera de rango se rechaza. Prueba en la tarea 4.
3. `virsh` que devuelve lista vacía con código 0 (el fallo silencioso de la sesión de usuario) cuando VS dice tener VMs: no se da por bueno "0 máquinas" sin más; toda orden de `virsh` lleva `-r -c qemu:///system`. Prueba en las tareas 2 y 4.
4. Ninguna respuesta lleva variables de entorno de un contenedor, su orden de arranque, ni contraseñas de VNC, aunque la salida del NAS las trajera. Prueba en las tareas 2, 3 y 4.
5. Un NAS con muchos contenedores o un registro enorme: las respuestas van acotadas (`{filas, total, truncado}`, líneas de registro recortadas en número y en longitud) y ninguna orden pide tamaños que no terminan. Prueba en las tareas 3 y 4.

---

## Estructura de ficheros

```
src/qnap_tools/virtualizacion/__init__.py
src/qnap_tools/virtualizacion/comandos.py     ordenes: anfitrion, VMs, contenedores
src/qnap_tools/virtualizacion/parsers.py      un parser por orden
src/qnap_tools/virtualizacion/servidor.py     las 10 herramientas
tests/test_virtualizacion_comandos.py
tests/test_virtualizacion_parsers.py
tests/test_virtualizacion_servidor.py
tests/test_real_virtualizacion.py             opcional, contra nas1
tests/datos/virtualizacion/*_hero.txt, *_qts.txt
```

## Herramientas y órdenes

| Herramienta | Qué da | Órdenes |
|---|---|---|
| `virtualizacion_resumen(nas)` | qué hay instalado y en marcha (VS, Container Station, versión), CPU y memoria del NAS, cuántas VMs y contenedores hay y en qué estado, memoria asignada a las VMs en marcha, y `avisos` (servicio parado, contenedor reiniciándose o no sano, memoria de las VMs por encima de la del NAS) | `ANFITRION`, `VM_ESTADISTICAS`, `VM_XML`, `CT_INFO`, `CT_LISTA`, `CT_INTERNOS`, `CT_LXD` |
| `vm_lista(nas)` | cada VM: nombre, UUID, estado, vCPU, memoria, sistema, arranque automático, discos (número y tamaño) | `VM_XML`, `VM_ESTADISTICAS` |
| `vm_detalle(nas, vm)` | una VM (por nombre o UUID): descripción, firmware y tipo de máquina, orden de arranque, discos con fichero, formato, tamaño y lo que ocupan, NIC con MAC, modelo, conmutador e IP si se conoce, consola | `VM_XML`, `VM_ESTADISTICAS`, `VM_IP {uuid}` |
| `vm_uso(nas)` | de las VMs en marcha, medido durante 5 s: % de CPU, memoria, E/S de disco y de red | `VM_USO` (dos lecturas de `domstats`) |
| `vm_snapshots(nas)` | por VM: tipo de instantánea de VS, instantáneas deducidas de la cadena de imágenes de cada disco con su fecha y lo que ocupa cada capa, e instantáneas que conoce libvirt | `VM_XML`, `VM_IMAGENES`, `VM_SNAP_LIBVIRT` |
| `contenedores_lista(nas)` | contenedores: nombre, imagen, estado, tiempo, puertos, redes, proyecto compose; aplicaciones compose | `CT_LISTA`, `CT_COMPOSE` |
| `contenedor_detalle(nas, contenedor)` | un contenedor: imagen, estado, código de salida, salud, fechas, política de reinicio, límites, redes con IP, puertos, montajes, proyecto compose | `CT_LISTA` (para validar), `CT_DETALLE {contenedor}` |
| `contenedores_uso(nas)` | CPU, memoria, red, E/S y procesos de cada contenedor en marcha (una muestra) y espacio de imágenes, contenedores y volúmenes | `CT_STATS`, `CT_ESPACIO` |
| `contenedor_logs(nas, contenedor, lineas=50)` | últimas líneas del registro de un contenedor | `CT_LISTA` (para validar), `CT_LOGS {contenedor} {lineas}` |
| `contenedores_redes(nas)` | redes de Docker: driver, subred, puerta de enlace y contenedores conectados con su IP | `CT_REDES` |

Las órdenes exactas se fijan en cada tarea a partir del catálogo y de la salida real; lo que cambie respecto a esta tabla se anota como decisión.

---

### Task 1: base de la pata y laboratorio

**Files:**
- Create: `src/qnap_tools/virtualizacion/__init__.py`, `src/qnap_tools/virtualizacion/comandos.py` (sin órdenes todavía)
- Modify: `pyproject.toml` (script `qnap-tools-virtualizacion = qnap_tools.virtualizacion.servidor:main`, versión 0.3.0), `src/qnap_tools/__init__.py` (versión), `pruebas/captura.py` (valores y nombres de `virtualizacion`), `pruebas/anonimiza.py`, `pruebas/efectos.py` (si hace falta para `--producto virtualizacion`)
- Test: `tests/test_anonimiza.py`

**Interfaces:**
- Consumes: `comandos.TIPOS` (`uuid`, `nombre`, `entero` ya existen), `captura.VALORES`/`NOMBRES`.
- Produces: `anonimiza.Anonimizador` con reglas para el nombre y la descripción de una VM (`<qvs:name>`, `<description>`), y la lista de nombres a ocultar de la pata (VMs, contenedores, imágenes, redes, proyectos, carpetas); `captura.py virtualizacion <nas> <sufijo>`; `efectos.py <nas> --producto virtualizacion`.

- [ ] **Step 1:** `tests/test_anonimiza.py`: la descripción de una VM (`<description>texto</description>`) se sustituye por `descripcion de ejemplo N` de forma coherente e idempotente; `<qvs:name>X</qvs:name>` se sustituye por `vmN` y `X` pasa a la lista de nombres del texto (se sustituye también en rutas); `revisar` detecta las que quedan. Ver fallar.
- [ ] **Step 2:** implementar; ver pasar.
- [ ] **Step 3:** `captura.py`: `_valores_virtualizacion` (UUID de una VM y nombre de un contenedor reales, sacados de las órdenes de lista; `None` si el NAS no tiene) y `_nombres_virtualizacion`. Paquete vacío y entry point. Batería en verde.
- [ ] **Step 4:** commit `feat: base de la pata de virtualizacion`.

### Task 2: órdenes y parsers de máquinas virtuales

**Files:**
- Modify: `src/qnap_tools/virtualizacion/comandos.py`
- Create: `src/qnap_tools/virtualizacion/parsers.py`, `tests/test_virtualizacion_comandos.py`, `tests/test_virtualizacion_parsers.py`, `tests/datos/virtualizacion/`

**Interfaces:**
- Produces: `ANFITRION` (hilos, modelo de CPU, extensiones de virtualización, carga, campos de `/proc/meminfo`, y si existen los sockets de libvirt y de docker), `VM_ESTADISTICAS` (`virsh domstats`: estado, CPU, memoria, discos y red de todas las VMs), `VM_XML` (por VM, las líneas de `dumpxml` de una lista blanca de elementos), `VM_IP` (`virsh domifaddr {uuid} --source arp`), `VM_USO` (dos `domstats` de las VMs en marcha separados 5 s, con `/proc/uptime`), `VM_IMAGENES` (`qemu-img info -U --backing-chain` de cada disco de cada VM), `VM_SNAP_LIBVIRT` (`snapshot-list` por VM); parsers `anfitrion`, `vm_estadisticas`, `vm_xml`, `vm_ip`, `vm_uso`, `vm_imagenes`, `vm_snap_libvirt`.

- [ ] **Step 1:** `tests/test_virtualizacion_comandos.py` (como el de discos): cada orden pasa la guardia; ids únicos; toda orden con `virsh` lleva `-r -c qemu:///system` y ninguna `--security-info`; `qemu-img` solo `info -U`; ninguna con `sudo` salvo las marcadas; ninguna lee `qvs.db` ni usa `lxc`, `curl`, `wget`; parámetros validados (`uuid`). Ver fallar.
- [ ] **Step 2:** escribir las órdenes; ver pasar. Capturar en `nas1` (`captura.py virtualizacion nas1 hero`) y derivar las de QTS de `pruebas/resultados/nas3/virtualizacion_hero/` con el patrón de cada orden (sin tráfico nuevo). `anonimiza.py --revisar`: 0 dudas.
- [ ] **Step 3:** una prueba por parser con valores concretos de los datos: estados (`running`, `shut off`, `paused`...) por su código; memoria y discos en bytes; de `vm_xml`, nombre, descripción acotada, sistema, vCPU, memoria, firmware, arranque, discos (dispositivo, bus, fichero, formato) y NIC (MAC, conmutador, modelo), consola sin contraseña aunque el texto la trajera (Review Focus 4); `vm_uso` calcula % de CPU y caudales entre las dos lecturas y rechaza lecturas descuadradas; `vm_imagenes` da la cadena de cada disco con tamaños en bytes; salida vacía o no reconocida -> `ValueError` (Review Focus 3). Ver fallar.
- [ ] **Step 4:** implementar los parsers; ver pasar toda la batería.
- [ ] **Step 5:** commit `feat: ordenes y parsers de maquinas virtuales`.

### Task 3: órdenes y parsers de contenedores

**Files:** los mismos que la tarea 2.

**Interfaces:**
- Produces: `CT_INFO` (`docker info --format` de campos), `CT_LISTA` (`docker ps -a --no-trunc --format` con tabuladores, sin `Size`), `CT_COMPOSE` (`docker compose ls -a`), `CT_DETALLE` (`docker inspect {contenedor} --format` de campos, con `json` por campo), `CT_STATS` (`docker stats --no-stream --format`), `CT_ESPACIO` (`docker system df`), `CT_LOGS` (`docker logs --tail {lineas} {contenedor}`), `CT_REDES` (lista e `inspect --format` por red), `CT_INTERNOS` (contenedores del docker interno de Container Station), `CT_LXD` (si hay instancias LXD: solo sus carpetas, con sudo); parsers del mismo nombre en minúsculas.

- [ ] **Step 1:** ampliar `tests/test_virtualizacion_comandos.py`: `docker` solo con subórdenes de consulta; `ps` sin `Size`; `inspect` siempre con `--format` y sin `.Config.Env`, `.Config.Cmd`, `.Args`, `.Path` ni `.Config.Labels` entero; `logs` con `--tail` y sin `-f`; `stats` con `--no-stream`; la ruta del cliente sale de `qpkg.conf`. Ver fallar.
- [ ] **Step 2:** órdenes; ver pasar. Capturar en `nas1` y derivar de `nas3` lo que allí tiene contenedores en marcha (`stats`, puertos, redes con contenedores). `--revisar`: 0 dudas.
- [ ] **Step 3:** una prueba por parser: lista con estado, puertos, redes y proyecto; detalle con redes e IP, montajes, puertos, límites (0 = sin límite -> `None`), salud; `stats` con porcentajes como número y tamaños en bytes (`MiB`, `GiB`, `kB`, `MB`); registros acotados en número y longitud de línea y sin caracteres de control (Review Focus 5); redes con subred y contenedores; un error del demonio (`Error response from daemon`, `Cannot connect to the Docker daemon`) -> `ValueError`. Ver fallar.
- [ ] **Step 4:** implementar; ver pasar.
- [ ] **Step 5:** commit `feat: ordenes y parsers de contenedores`.

### Task 4: las 10 herramientas

**Files:**
- Create: `src/qnap_tools/virtualizacion/servidor.py`, `tests/test_virtualizacion_servidor.py`, `tests/test_real_virtualizacion.py`

**Interfaces:**
- Consumes: `servidor.Base`, `Flota.perfil(nas).paquetes`, órdenes y parsers de las tareas 2 y 3.
- Produces: `Herramientas` con `virtualizacion_resumen(nas)`, `vm_lista(nas)`, `vm_detalle(nas, vm: str)`, `vm_uso(nas)`, `vm_snapshots(nas)`, `contenedores_lista(nas)`, `contenedor_detalle(nas, contenedor: str)`, `contenedores_uso(nas)`, `contenedor_logs(nas, contenedor: str, lineas: int = 50)`, `contenedores_redes(nas)`; `construir()` y `main()`.

- [ ] **Step 1:** pruebas con NAS simulados (uno con VS y Container Station, otro sin ninguno de los dos, otro con el paquete activo y el servicio parado):
  - cada herramienta responde `ok`; sin el paquete responde `activo: false` y no lanza nada (Review Focus 1);
  - `vm_detalle` admite nombre o UUID, valida antes de conectar y dice qué VMs hay si no existe; lo mismo `contenedor_detalle` y `contenedor_logs`; `lineas` entre 1 y 200 (Review Focus 2);
  - `virsh` con lista vacía y VS con VMs definidas -> error (Review Focus 3);
  - ninguna respuesta contiene variables de entorno, orden de arranque ni contraseña de VNC aunque el NAS simulado las devuelva (Review Focus 4);
  - 300 contenedores -> lista recortada con su cuenta; registro con líneas de 10 000 caracteres -> recortadas (Review Focus 5);
  - `avisos` del resumen: contenedor `restarting`, `unhealthy` o `dead`, VM en pausa o bloqueada, servicio parado, memoria asignada a las VMs en marcha mayor que la del NAS;
  - `sudo` solo en las órdenes marcadas; ningún `Comando` de la pata queda sin usar; 10 herramientas registradas con descripción y `nas` obligatorio.
- [ ] **Step 2:** implementar; ver pasar.
- [ ] **Step 3:** saludo MCP real de `qnap-tools-virtualizacion`. Prueba real contra `nas1` (`tests/test_real_virtualizacion.py`): las 10 herramientas `ok`.
- [ ] **Step 4:** commit `feat: servidor qnap-virtualizacion`.

### Task 5: integración en el plugin y verificación

**Files:**
- Modify: `.claude-plugin/plugin.json` (servidor `qnap-virtualizacion`, versión 0.3.0), `README.md`, `CLAUDE.md`

- [ ] **Step 1:** añadir `qnap-virtualizacion` a `mcpServers`; `claude plugin validate .`.
- [ ] **Step 2:** prueba de no escritura: `efectos.py nas1 --producto virtualizacion`. Ninguna orden confirmada.
- [ ] **Step 3:** pasada real de solo lectura por `nas3` con las 10 herramientas (alta sin clave en carpeta temporal): tiempos y tamaños con 45 contenedores y VMs en marcha. Corregir lo que salga, con prueba.
- [ ] **Step 4:** batería completa en verde; `isascii()` en todos los `.py`; `anonimiza.py --revisar` en `tests/datos/`.
- [ ] **Step 5:** README (tabla de `qnap-virtualizacion`, límites: sin datos de dentro del invitado, sin LXD, sin copias de seguridad ni tareas de VS) y `CLAUDE.md`. Commit `feat: qnap-virtualizacion en el plugin (entrega 3)`.

---

## Anexo: registro de la ejecucion

Ejecutado el 2026-10-14 en la rama `entrega-3-virtualizacion` (ejecucion en linea, una revision independiente al
final). Copia del registro de trabajo: lo que se decidio al apartarse del plan, lo que corrigio
la revision final y lo que queda aplazado. Bateria final: 1719 pruebas.

### Tareas

- Task 1: complete (commits 06f5137..7533f43, tests: .venv/Scripts/python.exe -m pytest -q → 1162 passed, 9 skipped in 9.00s)
- Task 2: complete (commits 7533f43..c19978f, tests: .venv/Scripts/python.exe -m pytest -q → 1287 passed, 9 skipped in 9.09s)
- Task 3: complete (commits c19978f..945ee8e, tests: .venv/Scripts/python.exe -m pytest -q → 1439 passed, 9 skipped in 9.14s)
- Task 4: complete (commits 945ee8e..8318aee, tests: .venv/Scripts/python.exe -m pytest -q → 1551 passed, 10 skipped in 9.84s)
- Task 5: complete (commits 8318aee..9d26622, tests: .venv/Scripts/python.exe -m pytest -q → 1554 passed, 10 skipped in 10.05s)
- Pre-flight: T1 produce captura.py virtualizacion y efectos --producto virtualizacion / T2, T3 y T5 los consumen: coinciden.
- Pre-flight: T2 y T3 producen ordenes y parsers / T4 los consume por nombre: los nombres de la tabla son orientativos; T4 lee los reales (cada cambio se anota).
- Pre-flight: T4 depende de Flota.perfil(nas).paquetes (existe desde la entrega 1: dict nombre -> ruta, solo paquetes con Enable=TRUE): coincide.
- Task 5: pasada real nas3 (solo lectura, alta sin clave): 10/10 ok sin errores en bloques; tiempos 0.3-5.6 s; tamanos: contenedores_lista 20.7 KB (45), contenedor_logs(200) 46 KB, contenedores_redes 10 KB (35 redes), vm_snapshots 8 KB (9 VMs), resumen 0.9 KB. Un aviso real: un contenedor unhealthy. domifaddr --source arp vacio en los dos NAS.
- Final review: revisor independiente (general-purpose, opus) sobre 73535be..9d26622 — sin criticos; 4 importantes (I1-I4) y 13 menores (M1-M13). Re-graduados a importante por su efecto: M1, M6, M10 y el perfil en cache (de "Declined to judge").

### Decisiones (39)

- Setup: Ruling: el plan se ejecuta sin esperar revision del usuario — dijo "pasa a la entrega 3 y 4 ... te revisare manana" y pregunto si hacia falta algo mas; ejecucion nativa como en las entregas 1 y 2 — coste: si quisiera otro reparto de datos por herramienta, se rehace esa herramienta.
- Setup: Ruling: pasada real de solo lectura por nas3 autorizada por defecto (se lo dije antes de empezar y contesto "terminas las dos entregas"); nas2 no se toca; no se publica nada.
- Task 1: Ruling: el nombre de una VM (<qvs:name>) no lleva regla propia en el anonimizador: lo saca la captura del XML y va en la lista de nombres (asi se cambia tambien en las demas salidas, que se procesan antes); solo la descripcion (texto libre) tiene regla — coste: ninguno.
- Task 1: Ruling: regla nueva de rutas bajo /share (solo si se pide; la pide la pata de virtualizacion): cada carpeta o fichero del usuario pasa a rutaN conservando la extension; los componentes que pone el NAS o sus paquetes se dejan — coste: una carpeta con espacios en el nombre quedaria a medias (se revisa a ojo cada captura).
- Task 1: Ruling: las imagenes de contenedor se ocultan todas (imagenN), tambien las publicas: dicen que programas usa cada NAS — coste: datos de prueba menos legibles.
- Task 2: Ruling: los datos de QTS se capturan en nas3 con las ordenes del producto (solo lectura, pasadas por la guardia) en vez de derivarse de lo guardado en la exploracion — son las salidas reales de las ordenes que se entregan — coste: 8 ordenes cortas en un NAS de pruebas, de madrugada.
- Task 2: Ruling: VM_ESTADISTICAS (virsh domstats) hace de lista de VMs, de estado y de tamano de discos (da tambien las apagadas): no se definen list, dominfo, domblklist ni domblkinfo como ordenes aparte — coste: ninguno conocido.
- Task 2: Ruling: toda orden que recorre las VMs empieza con "echo uri=$(virsh uri)" y su parser exige "uri=qemu:///system": si la conexion a libvirt falla, la lista sale vacia sin error y sin esa linea pareceria "no hay VMs" (Review Focus 3) — coste: un proceso virsh mas por orden.
- Task 2: Ruling: VM_XML saca con grep solo las lineas de una lista blanca de elementos (nunca el XML entero ni los metadatos qvs:graphics); el patron no puede llevar el signo "mayor que" (Comando rechaza toda plantilla que lo tenga) y se cierra con "lo que no sea letra" — coste: una descripcion de varias lineas solo da la primera.
- Task 2: Ruling: se anade VM_SNAP_VS (no estaba en el plan): las instantaneas de VS son los ficheros <momento>.xml de la carpeta de metadatos de cada VM (ruta sacada de su definicion), con .state si guardan memoria; coinciden con las capas de la cadena de imagenes en las 15 VMs vistas — coste: una orden mas.
- Task 2: Ruling: VM_IMAGENES usa --output=json y recorre los discos con for sobre la salida de domblklist (la guardia no admite read): una ruta con espacios se partiria y ese disco quedaria sin cadena (sin valor, no un dato falso); en 15 VMs de dos NAS no hay ninguna.
- Task 2: Ruling: vm_uso da cpu_nucleos (nucleos ocupados) y cpu_pct (parte de sus vCPU, con tope en 100); un contador que retrocede (VM reiniciada entre lecturas) da sin valor, no una cifra negativa.
- Task 2: Ruling: el anonimizador conserva de cada fichero solo su ultima extension y `revisar --rutas` comprueba cada carpeta y fichero bajo /share: una captura dejaba a la vista un nombre real dentro de un fichero con varios puntos (cazado a ojo antes de versionar; ahora lo detecta la revision).
- Task 2: Ruling: virtualizacion/parsers.py lleva sus propias utilidades (como redes y discos, cada pata las suyas) — coste: unas lineas repetidas.
- Task 3: Ruling: no hay orden para el espacio que ocupan imagenes y contenedores: `docker system df` no termino en 60 s en nas3 (137 imagenes) y su proceso siguio vivo en el NAS unos minutos hasta acabar solo; es la misma familia que el campo Size de docker ps (Review Focus 5). contenedores_uso da solo la muestra de docker stats — coste: no se informa del espacio de Docker.
- Task 3: Ruling: CT_DETALLE pide de cada red solo direccion, prefijo, puerta de enlace y MAC (no el JSON entero, que trae alias e identificadores) y de las etiquetas solo las tres de compose; la salud se pide con "with index" porque un contenedor sin comprobacion de salud no tiene esa clave y pedirla sin mas hace fallar a docker.
- Task 3: Ruling: las palabras de plantilla de Go van con espacios ({{ end }}, {{ else }}): pegadas a las llaves, el nucleo las toma por un parametro de la orden; el salto de linea y el tabulador de info, inspect y network inspect se escriben como texto de Go ({{"\n"}}) porque esas ordenes no traducen "\t".
- Task 3: Ruling: CT_REDES es una sola consulta (network inspect de todas las redes que da network ls) en vez de una por red — 36 redes en nas3.
- Task 3: Ruling: los registros reales de un contenedor no se guardan como datos de prueba (son texto de los programas del usuario): CT_LOGS se prueba con texto escrito a mano y, en real, solo en las pruebas contra el NAS — coste: su formato no esta fijado con una captura.
- Task 3: Ruling: el anonimizador cambia ademas el servicio compose de un contenedor y el nombre de los volumenes de Docker ("Name" en JSON, igual que su carpeta); revisar --rutas los comprueba. Dos fugas mas cazadas a ojo antes de versionar (alias de red y nombre de volumen), y por eso la orden ya no pide los alias.
- Task 3: Ruling: LXD solo se mira por los nombres de sus carpetas, con sudo (sin el da "Permission denied" en QTS); los dos NAS de pruebas las tienen vacias: el caso con instancias esta escrito a mano.
- Task 4: Ruling: servicio parado = error en las 9 herramientas y aviso en el resumen; se comprueba con ANFITRION (una orden mas por llamada) antes de lanzar virsh o docker — el mensaje de docker/libvirt caido no es claro — coste si es un error: unos milisegundos por llamada.
- Task 4: Ruling: resumen con los dos paquetes inactivos no lanza nada y sale sin bloque "nas" — Review Focus 1 pide no lanzar nada — coste: no se ve si la CPU admite virtualizacion en un NAS sin paquetes.
- Task 4: Ruling: vm_detalle admite cualquier texto como nombre (los nombres de VS llevan espacios) porque el valor solo se compara en Python y nunca va al NAS; se valida tipo, longitud y caracteres de control antes de conectar; nombre repetido -> pide el UUID — coste: ninguno conocido.
- Task 4: Ruling: las dos consultas de libvirt (domstats y dumpxml) deben ver las mismas VMs o la herramienta falla (Review Focus 3) — coste: crear o borrar una VM justo entre las dos da un error pasajero que se arregla repitiendo.
- Task 4: Ruling: parser ct_logs (tarea 3) corregido: un fallo de docker solo se reconoce si la salida es UNA linea; antes, un registro cuya primera linea empezaba por "Error: " tumbaba la herramienta — coste: un contenedor cuyo registro entero sea una linea igual a un error de docker sale como error (con el texto de la linea).
- Task 4: Ruling: _extra pasa de discos/servidor.py a servidor.Base para compartirlo — coste: ninguno (pruebas de discos verdes).
- Task 4: Ruling: limites de respuesta: 100 contenedores/aplicaciones/redes, 50 contenedores por red, 50 instantaneas por VM (recientes primero), 60 capas por disco, 20 avisos por clase, registro de 1 a 200 lineas de 400 caracteres — coste: en un NAS mayor hay que pedir el detalle por nombre.
- Task 4: Ruling: vm_snapshots usa tambien VM_SNAP_VS (el plan no la listaba) y da por capa lo que ocupa y "desde" (fecha del nombre del fichero); no da "tamano de cada instantanea" porque con instantaneas externas no se puede atribuir — coste: el usuario tiene que casar instantanea y capa por la fecha.
- Task 4: Ruling: contenedores_uso sin espacio de imagenes (CT_ESPACIO retirada en la tarea 3); LXD solo se cuenta en el resumen por los nombres de sus carpetas — coste: sin cifra de espacio de Docker.
- Task 4: Ruling: avisos hacia el lado seguro: contenedor en cualquier estado distinto de running/exited/created (incluye paused) o unhealthy; VM en cualquier estado distinto de en marcha/apagada — coste: una pausa hecha a proposito sale como aviso.
- Task 5: Ruling: prueba nueva tests/test_plugin.py (version del plugin = la del paquete; cada servidor del manifiesto es un ejecutable del pyproject y no falta ninguno; mismo env en todos) — el plan no la pedia — coste: ninguno.
- Task 5: Ruling: efectos.py guarda los ficheros de cada candidato; la primera tanda en nas1 dio 7 candidatos (las 7 ordenes de docker) y 0 confirmados, la segunda 2 candidatos (/tmp/cmd_result_*, ruido conocido del NAS) y ninguno de docker: se da por ruido de fondo — coste si es un error: un efecto de docker que solo aparece a veces quedaria sin ver.
- Final: Ruling: I2 (la prueba de efectos no ve un efecto que solo ocurre la primera vez) — no se puede repetir con un usuario nuevo (crearlo es escribir en el NAS). En su lugar: (a) efectos.py vigila ahora tambien las carpetas y senala lo que aparece con una orden y sigue al final (tests/test_efectos.py, 3 RED→GREEN); (b) dos tandas mas en nas1 con las ordenes definitivas: 0 confirmadas, 0 nuevos que siguen, y los candidatos son temporales del propio NAS (/tmp/cmd_result_*, /tmp/zfs_cmd_err*, /tmp/smart/*, /tmp/phy_event*); (c) la carpeta del usuario de pruebas en nas1 y en nas3, tras cientos de consultas con docker, virsh y qemu-img, solo tiene .ssh y el enlace de la papelera; (d) el README dice ese limite — coste si es un error: un efecto de primera vez fuera de la carpeta del usuario y de las carpetas vigiladas quedaria sin ver.
- Final: Ruling: el Ruling 14 de la tarea 2 estaba mal redactado: una descripcion de VM de varias lineas no da "la primera linea" sino None (M3). Se deja asi y se dice en el README — coste: esa descripcion no se ve.
- Final: Ruling: el Ruling 16 (for sobre domblklist) y el 33 (heuristica de una linea) quedan sustituidos por los arreglos de I1 e I3; el 41 (candidatos de docker = ruido) queda respaldado por (b) y (c) de arriba.
- Final: Ruling: caracteres Unicode invisibles (bidi, ancho cero) en texto de terceros no se filtran; solo los de control ASCII (de "Declined to judge") — el texto llega como dato y las instrucciones del servidor lo dicen — coste: un nombre o una linea de registro puede llevar texto que no se ve.
- Final: Ruling: rendimiento con cientos de VMs no se acota mas (vm_snapshots ~0,9 KB por VM, tope 200 VMs) (de "Declined to judge") — un QNAP no tiene cientos de VMs — coste: ~180 KB en ese caso extremo.
- Final: Ruling: arnes del laboratorio: ro.py y captura.py ya no ofrecen la clave de pruebas a nas3 (donde no esta instalada): cuatro conexiones seguidas con ese intento fallido hicieron que el sshd del NAS (OpenSSH 10.3) cortara 1-2 minutos las conexiones nuevas de este PC; se recupero solo. tests/test_ro.py RED→GREEN. No afecta al producto: nas_alta entra por contrasena y guarda auth=contrasena si no instala la clave — coste: ninguno.

### Corregido tras la revision final (7)

- Final: fixed I1 (rutas de VM con espacios: el for partia la ruta; la VM salia sin instantaneas y un disco desaparecia de la lista) — tests/test_virtualizacion_shell.py (orden ejecutada en un sh real con virsh de pega: 3 RED→GREEN), test_una_vm_sin_carpeta_de_metadatos_sale_sin_instantaneas_conocidas_y_se_dice RED→GREEN, test_las_rutas_sacadas_de_una_vm_no_se_recorren_con_un_for; VM_IMAGENES y VM_SNAP_VS con "while read -r", marca "!!" si no esta la carpeta de metadatos, regla "read" en la guardia; suite 1560/1560.
- Final: fixed I3 (registro de un contenedor: la heuristica de una linea rechazaba "Error: boom" y aceptaba como dato un fallo de docker con otro texto) — CT_LOGS termina con "==rc N" (codigo de salida de docker); 30 pruebas RED→GREEN (parser, servidor y orden); comprobado en nas1 con un contenedor que existe (==rc 0) y otro que no (==rc 1 con el mensaje de docker); suite 1580/1580.
- Final: fixed I4 (UUID reales de nas1 escritos como ejemplo en tests/test_comandos.py, test_virtualizacion_comandos.py y test_anonimiza.py) — tests/test_higiene.py::test_los_uuid_escritos_en_las_pruebas_son_de_ejemplo RED→GREEN, y la revision de los 130 ficheros de datos pasa a ser una prueba; busqueda de identificadores reales (30 UUID, 282 MAC, 333 IP y 15 nombres sacados de pruebas/resultados) en todo lo versionado: 0; suite 1714/1714.
- Final: fixed M10 subido a importante (los datos de prueba delataban el programa de un contenedor por la ruta de sus montajes) — test_el_destino_de_un_montaje_dentro_del_contenedor_se_sustituye RED→GREEN; regla Destination del anonimizador y los dos ct_detalle rehechos; suite 1715/1715.
- Final: fixed M1 subido a importante (contenedor_detalle con un rango de 2000 puertos daba 138 KB) — test_un_contenedor_con_miles_de_puertos_o_cientos_de_montajes_llega_acotado_con_su_cuenta RED→GREEN; puertos y montajes como {filas,total,truncado}, 50 cada uno.
- Final: fixed M6 subido a importante (una VM con ajuste NUMA, modulos de memoria o vCPU en caliente tumbaba vm_lista, vm_detalle y vm_snapshots de todas) — test_los_elementos_de_numa_y_de_cpu_en_caliente_no_son_la_memoria_ni_las_vcpu_de_la_vm RED→GREEN.
- Final: fixed perfil en cache (de "Declined to judge", subido a importante: tras activar un paquete la herramienta seguia diciendo activo=false hasta reiniciar) — test_un_paquete_activado_despues_de_conectar_se_ve_sin_reiniciar y test_un_paquete_desactivado_despues_de_conectar_no_sale_como_servicio_parado RED→GREEN; Flota.perfil(nas, refrescar=True) antes de decir "no esta" o "servicio parado"; suite 1719/1719.

### Menores aplazados (11)

Resueltos en la 0.4.1 (2026-10-14): M5 (un contenedor sin medir no suma como cero: 'sin_medir'), M6 (una VM con una definicion que no se entiende sale con su 'error'), M9 (vm_uso comprueba el libvirt en cada lectura), M12 (la cadena se recorre capa a capa y solo sigue bases locales; 'base_sin_leer' y 'cortada'; en nas1, las 10 cadenas iguales que con --backing-chain).

Resueltos despues (2026-10-14, validados en nas1): M8 (visto en real: "prueba-base,prueba-enlace/base"; el nombre es el que no lleva barra). Validado en real sin cambios: Container Station detenido desde App Center (activo=false), arrancando (servicio=false, aviso, y la lista da error), contenedor reiniciandose (aviso; contenedor_detalle da salida y reinicios) y contenedor que no pasa su comprobacion de salud.

- Final: minor (deferred): M2 — atributos del XML de una VM (conmutador, modelo, interfaz, bus, formato, maquina, escucha) y driver/ambito de las redes de docker sin acotar en longitud.
- Final: minor (deferred): M3 — una descripcion de VM de varias lineas sale sin valor (documentado en el README).
- Final: minor (deferred): M4 — vcpus_en_marcha y memoria_en_marcha cuentan tambien las VMs en pausa o apagandose, y usan la memoria actual (balloon), no la maxima de vm_lista (documentado en el README).
- Final: minor (deferred): M5 — contenedores_uso suma CPU y memoria tratando una cifra ausente ("--") como 0, y "0B / 0B" da memoria_limite 0 en vez de sin valor.
- Final: minor (deferred): M6 (resto) — un elemento del XML que el parser no sepa leer sigue tumbando todas las VMs (falla en voz alta); falta aislar el error por VM.
- Final: minor (deferred): M7 — si un dominio de libvirt no se llama como su UUID (no pasa con las VMs creadas por VS) el cruce falla siempre y el error dice "repite la consulta"; un apostrofo en el nombre rompe la lectura de domstats.
- Final: minor (deferred): M8 — un contenedor con enlaces heredados (--link) sale en docker ps como "web,otro/web" y no se encuentra por "web".
- Final: minor (deferred): M9 — VM_USO no lleva la linea uri=: si falla solo la primera lectura salen vms=[] con ok.
- Final: minor (deferred): M11 — en LXD, "no existe la carpeta" y "carpeta vacia" dan lo mismo (ninguna instancia).
- Final: minor (deferred): M12 — qemu-img info --backing-chain sigue la imagen base declarada en la cabecera, que podria ser una URL (conexion saliente desde el NAS si alguien pone una imagen asi).
- Final: minor (deferred): M13 — "cortadas" cuenta tambien las lineas de exactamente 400 caracteres.

### VMs suspendidas tras reiniciar el NAS (2026-10-14, despues de publicar la 0.4.2)

- Visto al reiniciar nas1 desde la web con dos VMs en marcha: Virtualization Station
  las SUSPENDIO (guarda la memoria en `<qvs:meta_path>/<uuid>.state`: 3,25 y 1,84 GB) y, ya
  arrancado el NAS, libvirt las da por apagadas con motivo 0 (pierde el "saved" = 5 que da
  mientras no se reinicia). VS sigue diciendo "Suspendida" porque mira ese fichero. El plugin
  (0.4.2) las daba por apagadas.
- Arreglo: orden nueva VM_GUARDADAS (dumpxml de cada VM -> meta_path -> `stat -c 'guardada %s %Y'`
  del `<uuid>.state` si existe; `!! sin carpeta` si falta la carpeta) y parser `vm_guardadas`. En
  `_vms` es dato accesorio (`_extra`, clave `memoria_guardada` en `errores`): una VM apagada con
  memoria guardada sale `suspendida`; en marcha manda libvirt. `vm_detalle` da `memoria_guardada`
  {bytes, fecha UTC} y el aviso dice cuanto ocupa y desde cuando.
- Comprobado al reanudarlas desde la web: VS BORRA el `.state` (no queda un fichero viejo) y
  libvirt da en marcha con motivo 5 (restaurada), como la VM 2 del dato de QTS.
- La guardia del laboratorio no admite `$( )` dentro de comillas dobles: el texto va en el formato
  de `stat -c`. Pruebas RED->GREEN (parser, servidor y shell con carpeta con espacios); los datos
  `vm_guardadas_*.txt` no tienen ninguna guardada (el de QTS, escrito a mano con las UUID de
  `vm_snap_vs_qts.txt`); la captura real queda en `pruebas/resultados/nas1/`.
