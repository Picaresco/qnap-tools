# Qnap-Tools, entrega 2: discos y carpetas

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** añadir al plugin el servidor MCP `qnap-discos` con las 9 herramientas aprobadas de discos y carpetas, de solo lectura, para QuTS hero (ZFS) y QTS (md/LVM).

**Architecture:** misma forma que la pata de redes: `discos/comandos.py` (plantillas fijas, cada una declara `sistema` = `ambos`, `hero` o `qts`), `discos/parsers.py` (texto -> estructura, `ValueError` si no reconoce la salida) y `discos/servidor.py` (`Herramientas` con `_leer` y `_opcional`). Cada herramienta mira el sistema detectado del NAS y lanza las órdenes de ese sistema; la respuesta lleva siempre el mismo sobre por NAS.

**Tech Stack:** Python >= 3.11, `mcp[cli]>=1,<2`, `paramiko`, `pytest`. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-10-13-qnap-tools-design.md`. Órdenes exploradas y límites: `pruebas/catalogo/discos.json`, `discos_hero.json`, `discos_qts.json`.

## Global Constraints

- Solo lectura. Toda orden es un `Comando` de `discos/comandos.py`; cada una pasa `pruebas/guardia.py` en una prueba y se lanza en `pruebas/efectos.py --producto discos`.
- Excluido por el diseño (no se usa aunque exista): familia `qcli_*` salvo `qcli_storage`; `get_hd_smartinfo`; `md_checker`; `lvs`/`pvs`/`vgs`/`lvdisplay`; `dmsetup table`; `smartctl` (no existe); cualquier orden recursiva sobre `/share` (`du`, `find`, `ls -R`); autotest SMART, escaneos y pruebas de velocidad.
- `qcli_storage` siempre **sin** sudo. `getsysinfo hd*` siempre **con** sudo y validando los centinelas (`0 C`, `--`).
- De los ficheros de configuración se leen **campos concretos** (lista blanca con `grep -E '^(a|b|c) ='` o `getcfg`), nunca el fichero entero ni "todo menos lo secreto". No se leen claves CHAP ni de iniciador, ni contraseñas de réplica, ni `smbpasswd`.
- Lo aprendido en la revisión de la entrega 1: una orden con `; true` o `2>/dev/null` no puede convertir "no se pudo leer" en "no hay" (patrón `[ ! -e f ] || cat f` con `valida=rc_cero`); todo recorte con `head`/`tail` lleva su cuenta (`==lineas N`) y sale marcado; un bloque de campos todo vacío es un fallo de lectura; el texto que escribe un tercero (comentario de una carpeta, alias de un iniciador) se acota.
- Ninguna ruta que cambie entre NAS va fija: los dispositivos NVMe y los grupos `md` se enumeran en el NAS; el nombre de pool o de volumen no entra nunca como parámetro libre.
- Datos de prueba (`tests/datos/discos/`): sin IP, MAC, números de serie, WWN, nombres de carpeta, de usuario, de pool de usuario ni IQN reales. El anonimizador los sustituye; `anonimiza.py --revisar` debe dar 0 dudas.
- Pruebas reales: `nas1` (hero) con `QNAP_TOOLS_PRUEBA_REAL=1`. Pasada final de solo lectura por un QTS (`nas3`), como la que el usuario autorizó en redes. Nada contra `nas2` (cargado).
- No se publica (ni push ni PyPI). Commits con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Python: solo ASCII en `.py`, cabecera `# -*- coding: utf-8 -*-`, `open(..., encoding='utf-8')`.

## Review Focus

1. Un NAS QTS recibe una herramienta cuyas órdenes son de hero (o al revés): no se lanza ninguna orden del otro sistema; la herramienta usa las del suyo. Prueba en la tarea 6.
2. `disco_smart` con una bahía que no existe, o con `bahia="1; reboot"`: error claro sin lanzar nada con ese valor. Prueba en la tarea 6.
3. `getsysinfo` que devuelve los centinelas (`0 C`, `--`) porque sudo no ha dado privilegios: error o dato marcado como no disponible, nunca "0 grados". Prueba en las tareas 2 y 6.
4. Pool o grupo RAID degradado o reconstruyéndose: `raid_estado` y `almacenamiento_resumen` lo destacan (no se pierde entre los que están bien). Prueba en las tareas 3, 4 y 6.
5. Un fichero de configuración que no existe en ese NAS (sin iSCSI, sin instantáneas, sin caché SSD): bloque vacío o `null`, no un error; uno que existe y no se puede leer: error. Prueba en las tareas 3, 4 y 5.

---

## Estructura de ficheros

```
src/qnap_tools/discos/__init__.py
src/qnap_tools/discos/comandos.py     ordenes: comunes, hero, qts
src/qnap_tools/discos/parsers.py      un parser por orden
src/qnap_tools/discos/servidor.py     las 9 herramientas
tests/test_discos_comandos.py
tests/test_discos_parsers.py
tests/test_discos_servidor.py
tests/test_real_discos.py             opcional, contra nas1
tests/datos/discos/*_hero.txt, *_qts.txt
pruebas/captura.py                    captura generica (sustituye a captura_redes.py)
```

## Herramientas y órdenes

| Herramienta | Qué da | hero | qts | común |
|---|---|---|---|---|
| `almacenamiento_resumen(nas)` | pools o grupos RAID con estado y ocupación, volúmenes con % de uso, discos por estado, y una lista de `avisos` (degradado, reconstrucción, disco con aviso, volumen por encima del 80 %) | `zpool list`, `zpool status` | `/proc/mdstat`, `volume.conf` | `qcli_storage -d`, `df` de `/share` |
| `discos_fisicos(nas)` | un disco por bahía: modelo, serie, capacidad, tipo (HDD/SSD/NVMe), temperatura, estado SMART, vida del SSD, a qué pool o grupo pertenece | | | `qcli_storage -d`, `/etc/enclosure_*.conf` (campos), `getsysinfo` por bahía (sudo), `/tmp/disk/disk_*.info` (SSD_LIFE), `nvme list` |
| `disco_smart(nas, bahia)` | atributos SMART de un disco con valor, peor, umbral y crudo; los que están en aviso; para NVMe, su registro de salud | | | `/tmp/smart/smart_<bahia>.info` (sudo), `/tmp/smart_warning.conf`, `nvme smart-log` del dispositivo de esa bahía |
| `raid_estado(nas)` | estado de la redundancia: por pool o grupo, nivel, miembros con su estado, errores, reconstrucción o verificación en curso y su progreso, última verificación | `zpool status -v` | `/proc/mdstat`, `/sys/block/md*/md/*`, `mdadm --detail` de los grupos de datos (sudo), `raid.conf` (campos) | |
| `volumenes(nas)` | volúmenes y carpetas-volumen: tamaño, usado, libre, sistema de ficheros, compresión, deduplicación, cifrado (sí/no y si está desbloqueado), caché SSD | `zfs list`, `zfs get` de cifrado, `qzfs.conf` (campos) | `volume.conf` (campos), `qlvm.conf` (campos), `dmsetup status` (pools ligeros y caché), `ssdcache.conf` (campos) | `df` de `/share` |
| `snapshots(nas)` | instantáneas (las más recientes, con su cuenta total), espacio que retienen y programación | `zfs list -t snapshot`, `zsnapshotSchedule.conf` (campos) | `snapshot.conf` (campos), `snapshotSchedule.conf` (campos) | |
| `carpetas_compartidas(nas)` | carpetas con ruta, volumen, comentario, quién accede (SMB), exportación NFS, uso que cachea el NAS, papelera | | | `smb.conf` (campos), `volumeStatus.conf`, `/etc/exports`, `ls -l /share/` |
| `iscsi(nas)` | servicio, destinos y LUN con tamaño y estado; nunca claves CHAP | `hero_zfs_lun.json`, `hero_iscsi_scst.json` (campos) | `iscsi_trgt.conf` (campos) | |
| `rendimiento_discos(nas)` | por disco, durante 5 s: operaciones por segundo, MB/s, espera media y % de ocupación; qué disco va más cargado | | | dos lecturas de `/proc/diskstats`, `qcli_storage -d` para nombrar las bahías |

Las órdenes exactas se fijan en cada tarea a partir del catálogo y de la salida real; lo que cambie respecto a esta tabla se anota como decisión.

---

### Task 1: base de la pata y herramientas de captura

**Files:**
- Create: `src/qnap_tools/discos/__init__.py`, `src/qnap_tools/discos/comandos.py` (vacío de órdenes), `pruebas/captura.py`
- Modify: `pyproject.toml` (script `qnap-tools-discos = qnap_tools.discos.servidor:main`, versión 0.2.0 en `__init__`), `src/qnap_tools/comandos.py` (tipos de parámetro nuevos), `pruebas/anonimiza.py`, `pruebas/efectos.py`, `pruebas/captura_redes.py` (se retira)
- Test: `tests/test_comandos.py`, `tests/test_anonimiza.py`

**Interfaces:**
- Consumes: `comandos.TIPOS`, `Comando`.
- Produces: tipos `md` (`md[0-9]{1,3}`) y `nvme` (`nvme[0-9]{1,2}`) en `TIPOS`; `anonimiza.Anonimizador` con reglas de número de serie, WWN e IQN y con palabras a ocultar calculadas en la captura; `pruebas/captura.py <pata> <nas> <sufijo>` que lanza los `Comando` de `qnap_tools.<pata>.comandos` válidos para el sistema de ese NAS y guarda `tests/datos/<pata>/<id>_<sufijo>.txt`; `efectos.py --producto <pata>`.

- [ ] **Step 1:** pruebas de los tipos nuevos en `tests/test_comandos.py`: `md` acepta `md1`, `md321`; rechaza `md`, `md1;x`, `sda`, `-md1`. `nvme` acepta `nvme0`, `nvme12`; rechaza `nvme0n1p1`, `nvme`, `nvme0 x`. Ver fallar.
- [ ] **Step 2:** añadir los tipos. Ver pasar.
- [ ] **Step 3:** `tests/test_anonimiza.py`: números de serie tras `serial_no =`, `Serial Number:`, `sn:` y columnas `Serial` se sustituyen por `SERIE0001`... de forma coherente; un WWN (`0x5000...` o `naa.5000...`) y un IQN (`iqn.2004-04.com.qnap:...`) se sustituyen; las palabras dadas se sustituyen sin tocar subcadenas de otras más largas; aplicar dos veces da lo mismo. Ver fallar, implementar, ver pasar.
- [ ] **Step 4:** `pruebas/captura.py`: genérico por pata; salta las órdenes de otro sistema; los valores de los parámetros los da una función por pata (`valores_reales`). Mover ahí lo de redes y borrar `captura_redes.py`; `efectos.py` pasa a usarlo y admite `--producto discos`. Comprobar con `captura.py redes nas1 hero --simular` (no escribe: compara el número de órdenes y nombres con los ficheros existentes).
- [ ] **Step 5:** commit `feat: base de la pata de discos y captura generica`.

### Task 2: discos físicos y SMART (órdenes comunes)

**Files:**
- Modify: `src/qnap_tools/discos/comandos.py`
- Create: `src/qnap_tools/discos/parsers.py`, `tests/test_discos_comandos.py`, `tests/test_discos_parsers.py`, `tests/datos/discos/`

**Interfaces:**
- Produces: `DISCOS_LISTA` (`qcli_storage -d`, sin sudo), `DISCOS_DETALLE` (campos de `/etc/enclosure_*.conf`), `DISCO_SALUD` (`getsysinfo hdmodel/hdtmp/hdsmart/hdstatus {bahia}`, sudo, valida centinelas), `SSD_VIDA`, `NVME_LISTA`, `NVME_SMART` (`nvme smart-log /dev/{dev}`, tipo `nvme`), `SMART_ATRIBUTOS` (`/tmp/smart/smart_{bahia}.info`, sudo), `SMART_UMBRALES`, `DISKSTATS` (dos lecturas de `/proc/diskstats` separadas 5 s con marca `==5s`). Parsers: `discos_lista`, `discos_detalle`, `disco_salud`, `ssd_vida`, `nvme_lista`, `nvme_smart`, `smart_atributos`, `smart_umbrales`, `diskstats`.

- [ ] **Step 1:** `tests/test_discos_comandos.py` (copia del de redes adaptado): cada orden pasa la guardia; ids únicos; ninguna toca rutas con secretos; `qcli_storage` nunca con sudo; `getsysinfo` siempre con sudo; ninguna contiene `du `, `find `, `ls -R`, `smartctl`, `lvs`, `pvs`, `vgs`, `dmsetup table`, `get_hd_smartinfo`, `md_checker`; toda orden con `sistema` distinto de `ambos` está en la lista esperada. Ver fallar.
- [ ] **Step 2:** escribir las órdenes; ver pasar. Capturar en `nas1` (`captura.py discos nas1 hero`) y derivar las de QTS de `pruebas/resultados/nas3/discos/` (formato comprobado; sin tráfico nuevo). `anonimiza.py --revisar`: 0 dudas.
- [ ] **Step 3:** una prueba por parser con valores concretos de los datos (bahía, modelo, capacidad en bytes, temperatura como número, atributo SMART 5 y 197 con valor/peor/umbral/crudo), más: `disco_salud` con `0 C` y `--` lanza `ValueError`; `diskstats` calcula IOPS, MB/s, espera y % de ocupación entre las dos lecturas y no inventa nada si un contador retrocede; entrada vacía o irreconocible -> `ValueError` en los que exigen datos. Ver fallar.
- [ ] **Step 4:** implementar los parsers; ver pasar toda la batería.
- [ ] **Step 5:** commit `feat: ordenes y parsers de discos fisicos y SMART`.

### Task 3: redundancia, volúmenes, instantáneas e iSCSI en QuTS hero

**Files:**
- Modify: `src/qnap_tools/discos/comandos.py`, `src/qnap_tools/discos/parsers.py`, `tests/test_discos_parsers.py`, `tests/test_discos_comandos.py`

**Interfaces:**
- Produces (todas `sistema="hero"`): `POOLS` (`zpool list -H -p -o name,size,alloc,free,frag,cap,dedup,health`), `POOLS_ESTADO` (`zpool status -v`), `DATASETS` (`zfs list -H -p -t filesystem,volume -o name,type,used,avail,refer,quota,refquota,compressratio,mountpoint`), `DATASETS_CIFRADO` (`zfs get -H -o name,property,value encryption,keystatus -t filesystem,volume`), `DATASETS_CONF` (campos de `qzfs.conf`), `SNAPSHOTS_HERO` (`zfs list -H -p -t snapshot -o name,used,refer,creation -s creation`, con cuenta y recorte marcado), `SNAPSHOTS_PROG_HERO` (campos), `LUNS_HERO` (campos de los dos JSON, sin CHAP). Parsers: `pools`, `pools_estado`, `datasets`, `datasets_cifrado`, `datasets_conf`, `snapshots_hero`, `snapshots_prog`, `luns_hero`.

- [ ] **Step 1:** pruebas de los parsers con los datos de `nas1`: pool con tamaño y ocupación en bytes y `salud`; `pools_estado` devuelve el árbol de vdevs con el estado de cada disco, contadores de error, y `tarea` (scrub o resilver con su progreso o fecha de fin). Texto escrito a mano y marcado para lo que `nas1` no tiene: pool `DEGRADED` con un disco `FAULTED`, `resilver in progress` con porcentaje, errores de datos. Ver fallar.
- [ ] **Step 2:** órdenes y parsers; ver pasar. Añadir a `test_discos_comandos.py` que `zpool`/`zfs` solo aparecen con subórdenes de consulta (`list`, `status`, `get`).
- [ ] **Step 3:** commit `feat: almacenamiento de QuTS hero`.

### Task 4: redundancia, volúmenes, instantáneas e iSCSI en QTS

**Files:** los mismos que la tarea 3.

**Interfaces:**
- Produces (todas `sistema="qts"`): `MDSTAT` (`cat /proc/mdstat`), `MD_SYS` (bucle sobre `/sys/block/md*/md/`), `MD_DETALLE` (`mdadm --detail /dev/{md}`, sudo, tipo `md`), `RAID_CONF` (campos), `VOLUMENES_CONF` (campos de `volume.conf`), `LVM_CONF` (campos de `qlvm.conf`), `DM_ESTADO` (`dmsetup status` filtrado a `thin-pool`, `cache`, `flashcache`, `crypt`, sudo), `CACHE_SSD` (campos), `SNAPSHOTS_QTS` y `SNAPSHOTS_PROG_QTS` (campos), `ISCSI_QTS` (campos, sin `InitiatorKey`). Parsers: `mdstat`, `md_sys`, `md_detalle`, `raid_conf`, `volumenes_conf`, `lvm_conf`, `dm_estado`, `cache_ssd`, `snapshots_qts`, `iscsi_qts`.

- [ ] **Step 1:** pruebas con datos derivados de `pruebas/resultados/nas3/discos/` y, para lo que allí no hay, de `nas2` (ya guardados): `mdstat` da por grupo nivel, miembros y `[UU_]`; reconoce `recovery = 12.3%` y `resync` con su velocidad y tiempo estimado (texto a mano marcado si los datos no lo tienen); `md_sys` da `degradado` y `discrepancias`; `dm_estado` da el % de uso de datos y metadatos de cada pool ligero. Ver fallar.
- [ ] **Step 2:** órdenes y parsers; ver pasar.
- [ ] **Step 3:** commit `feat: almacenamiento de QTS`.

### Task 5: carpetas compartidas y ocupación

**Files:** los mismos.

**Interfaces:**
- Produces (`sistema="ambos"`): `OCUPACION` (`df -P -k` de los montajes bajo `/share`), `CARPETAS_SMB` (campos de `smb.conf`: `path`, `comment`, `valid users`, `invalid users`, `read list`, `write list`, `browseable`, `guest ok`, `recycle bin`), `CARPETAS_USO` (`volumeStatus.conf`), `CARPETAS_NFS` (`/etc/exports` si existe), `CARPETAS_ENLACES` (`ls -l /share/`, con cuenta). Parsers: `ocupacion`, `carpetas_smb`, `carpetas_uso`, `carpetas_nfs`, `carpetas_enlaces`.

- [ ] **Step 1:** pruebas con datos anonimizados de los dos sistemas: una carpeta con su ruta, comentario (acotado a 120 caracteres y sin saltos), listas de usuarios y grupos (`@grupo`), `papelera`; uso en bytes y fecha del dato; exportaciones NFS con sus clientes y opciones; `ocupacion` en bytes con porcentaje. Sin `smb.conf` legible -> `ValueError`; sin `/etc/exports` -> lista vacía. Ver fallar.
- [ ] **Step 2:** órdenes y parsers; ver pasar.
- [ ] **Step 3:** commit `feat: carpetas compartidas y ocupacion`.

### Task 6: las 9 herramientas

**Files:**
- Create: `src/qnap_tools/discos/servidor.py`, `tests/test_discos_servidor.py`, `tests/test_real_discos.py`

**Interfaces:**
- Consumes: `servidor.crear`, `Flota` (incluida `perfil(nas).sistema`), órdenes y parsers de las tareas 2 a 5.
- Produces: `Herramientas` con `almacenamiento_resumen(nas)`, `discos_fisicos(nas)`, `disco_smart(nas, bahia: int)`, `raid_estado(nas)`, `volumenes(nas)`, `snapshots(nas)`, `carpetas_compartidas(nas)`, `iscsi(nas)`, `rendimiento_discos(nas)`; `construir()` y `main()`.

- [ ] **Step 1:** pruebas con dos NAS simulados (uno hero y uno QTS, cada uno con sus datos y su detección):
  - cada herramienta responde `ok` en los dos y solo lanza órdenes de su sistema (Review Focus 1);
  - `disco_smart` valida la bahía antes de conectar y dice qué bahías hay si no existe (Review Focus 2);
  - centinelas de `getsysinfo` -> la temperatura sale como error en su bloque, no como 0 (Review Focus 3);
  - pool `DEGRADED` y grupo md degradado -> aparecen en `avisos` de `almacenamiento_resumen` y destacados en `raid_estado` (Review Focus 4);
  - NAS sin iSCSI ni instantáneas -> bloques `null` o vacíos con `ok: true`; fichero ilegible -> error (Review Focus 5);
  - `sudo` solo en las órdenes marcadas; ningún `Comando` de discos queda sin usar; el servidor solo lanza `Comando` definidos; 9 herramientas registradas con descripción y `nas` obligatorio.
- [ ] **Step 2:** implementar; ver pasar.
- [ ] **Step 3:** saludo MCP real de `qnap-tools-discos`. Prueba real opcional contra `nas1` (`tests/test_real_discos.py`): las 9 herramientas `ok`.
- [ ] **Step 4:** commit `feat: servidor qnap-discos`.

### Task 7: integración en el plugin y verificación

**Files:**
- Modify: `.claude-plugin/plugin.json` (servidor `qnap-discos`, versión 0.2.0), `README.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-10-13-qnap-tools-design.md` (si algo cambia)

- [ ] **Step 1:** añadir `qnap-discos` a `mcpServers`; `claude plugin validate .`.
- [ ] **Step 2:** prueba de no escritura: `efectos.py nas1 --producto discos`. Ninguna orden confirmada.
- [ ] **Step 3:** pasada real de solo lectura por `nas3` con las 9 herramientas (alta sin clave en carpeta temporal). Corregir lo que salga, con prueba.
- [ ] **Step 4:** batería completa en verde; `isascii()` en todos los `.py`; `anonimiza.py --revisar` en `tests/datos/`.
- [ ] **Step 5:** README (tabla de `qnap-discos`, límites: sin tamaño real de subcarpetas, sin ACL recursivas, sin SMART en vivo) y `CLAUDE.md`. Commit `feat: qnap-discos en el plugin (entrega 2)`.

## Anexo: registro de la ejecucion

Ejecutado el 2026-10-14 en la rama `entrega-2-discos` (ejecucion en linea, una revision
independiente al final). Copia del registro de trabajo: lo que se decidio al apartarse del plan,
lo que corrigio la revision final y lo que queda aplazado.

### Tareas

- Task 1: complete (commits 96828c0..d6602fd, tests: .venv/Scripts/python.exe -m pytest -q → 571 passed, 8 skipped in 6.38s)
- Task 2: complete (commits d6602fd..42afce5, tests: .venv/Scripts/python.exe -m pytest -q → 724 passed, 8 skipped in 6.89s)
- Task 3: complete (commits 42afce5..1bbff99, tests: .venv/Scripts/python.exe -m pytest -q → 844 passed, 8 skipped in 7.70s)
- Task 4: complete (commits 1bbff99..97912fb, tests: .venv/Scripts/python.exe -m pytest -q → 988 passed, 8 skipped in 7.71s)
- Task 5: complete (commits 97912fb..be29018, tests: .venv/Scripts/python.exe -m pytest -q → 1066 passed, 8 skipped in 7.92s)
- Task 6: complete (commits be29018..35d3f16, tests: .venv/Scripts/python.exe -m pytest -q → 1137 passed, 9 skipped in 9.45s)
- Task 7: complete (commits 35d3f16..cd5d5a6, tests: .venv/Scripts/python.exe -m pytest -q → 1145 passed, 9 skipped in 9.27s)

### Verificaciones contra los NAS

- Task 1: verificado: captura.py redes nas1 hero --simular lista las 30 ordenes y encuentra sus 30 ficheros; anonimiza --revisar sobre los 41 ficheros versionados: 0 dudas.
- Task 2: verificado: captura real en nas1 (9 ordenes, 0 dudas); anonimiza --revisar sobre 63 ficheros versionados: 0 dudas; discos_salud de QTS reconstruido (la exploracion lo guardo con los valores pegados): se valida de verdad en la pasada de T7.
- Task 6: verificado: prueba real contra nas1 (QNAP_TOOLS_PRUEBA_REAL=1 tests/test_real_discos.py: las 9 herramientas ok, sin "errores", 11 s) y saludo MCP real de qnap-tools-discos.exe (9 herramientas).
- Task 7: verificado: plugin.json con qnap-discos (0.2.0), `claude plugin validate .` pasa; prueba de no escritura en nas1 de las 20 ordenes de hero: 0 confirmadas (resultados/nas1/efectos_producto_discos.json); pasada real de solo lectura por nas3 (alta sin clave): las 9 herramientas ok, sin "errores"; test_real_discos.py y test_real_redes.py contra nas1 en verde; anonimiza --revisar: 98 ficheros, 0 dudas; todos los .py ASCII.
- Final: verificado tras las correcciones: pasada real de solo lectura por nas3 (9 herramientas ok, sin avisos nuevos en un NAS sano) y prueba de no escritura en nas1 con la orden de ocupacion nueva.

### Decisiones tomadas (56)

- Setup: Ruling: el plan se ejecuta sin esperar revision expresa del usuario — dijo "seguimos" a "¿sigo con la entrega 2?", eligio ejecucion nativa en la entrega 1 y su norma es no pedir confirmaciones tecnicas; las 9 herramientas son las aprobadas en el diseno — coste: si quisiera otro reparto de datos por herramienta, se rehace esa herramienta.
- Task 1: Ruling: el anonimizador separa "palabras" (subcadena, como hasta ahora: nombres de equipo) de "nombres" (palabra entera: carpetas, usuarios) — un nombre corto de usuario no debe morder otras palabras, y un nombre de equipo aparece pegado a prefijos — coste: quien capture debe elegir bien la clase.
- Task 1: Ruling: un numero de serie visto en su campo se sustituye tambien donde aparezca suelto en el mismo texto o captura — coste: ninguno conocido.
- Task 1: Ruling: efectos.py --producto detecta el sistema del NAS y solo prueba las ordenes de ese sistema; falla si a una orden con parametros le falta su valor en captura.py — coste: ninguno.
- Task 2: Ruling: un disco se identifica por (cabina, bahia), los dos numeros de los ficheros del NAS (enclosure_<c>.conf, smart_<c>_<b>.info); SMART_ATRIBUTOS lleva {cabina} y {bahia} (el encargo decia solo {bahia}) — las cabinas de expansion y las ranuras PCIe repiten numero de bahia — coste: T6 debe traducir el puerto que ve el usuario (P2-1, EXDR#1 3) cruzando por dispositivo.
- Task 2: Ruling: DISCO_SALUD {bahia} pasa a ser DISCOS_SALUD, un solo bucle con sudo sobre las bahias 1..hdnum (lista fija hasta 32, sin depender de seq) — un sudo en vez de uno por bahia — coste: un NAS con mas de 32 bahias en la cabina principal perderia el veredicto de las ultimas.
- Task 2: Ruling: no se definen NVME_LISTA ni NVME_SMART — el fichero SMART que el NAS mantiene para cada NVMe (smart_23_N.info) trae su registro de salud (los mismos 15 campos que nvme smart-log, refrescado cada pocos minutos, comprobado en nas1) y enclosure_23.conf da modelo, serie, firmware y dispositivo — coste: el dato puede tener unos minutos; si algun NAS no escribe ese fichero para NVMe, se anade nvme smart-log.
- Task 2: Ruling: se anade SMART_TODOS (todos los ficheros SMART en una lectura con sudo): da la temperatura de TODOS los discos, tambien expansion y NVMe (noveno campo de la cabecera, cotejado con getsysinfo en varios discos de los tres NAS y con nvme smart-log) — coste: el resto de campos de la cabecera no se conocen y no se usan.
- Task 2: Ruling: se anade DISCOS_REPARTO (qcli_storage -p, sin sudo): disco -> grupo (vdev o md) y pool en los dos sistemas; los nombres de carpeta/volumen de su ultima columna no se devuelven — coste: ninguno conocido.
- Task 2: Ruling: DISCOS_DETALLE no pide link_speed/max_link_speed (codigos sin significado comprobado) y devuelve "estado" tal cual (0 en los varios discos sanos vistos; significado sin documentar); bus = sata/usb/nvme por el codigo type visto (0/2/4), None si es otro — coste: un disco SAS saldria sin bus.
- Task 2: Ruling: DISKSTATS filtra en el NAS los discos enteros (sd*, nvme*n*; en hero el fichero pasa de 800 lineas por los zd) y lleva /proc/uptime en cada lectura para el intervalo real; MB = 1024x1024 — coste: no da cifras de md ni de volumenes.
- Task 2: Ruling: bajo_umbral = regla del propio SMART (umbral > 0 y valor <= umbral); el septimo campo de cada linea de atributo (0 en las 764 lineas vistas) no se conoce y se ignora; smart_umbrales se parsea pero el sentido de "value" no se ha podido validar (T6 lo marca no_probado).
- Task 2: Ruling: segundo juego de datos QTS (_qts2) derivado de las salidas ya guardadas de nas2 (cabina de expansion, ficheros _del): sin trafico hacia ese NAS — coste: ninguno.
- Task 3: Ruling: POOLS sin "frag" (el ZFS de QNAP no tiene esa propiedad: zpool list falla con ella, comprobado en nas1) — coste: no se da la fragmentacion.
- Task 3: Ruling: DATASETS_CIFRADO y DATASETS_CONF no se definen: compression, dedup, encryption y keystatus salen en la misma orden zfs list -o (comprobado en nas1) — coste: no se lee el umbral de aviso de qzfs.conf.
- Task 3: Ruling: SNAPSHOTS_HERO no recorta en el NAS (sin tuberia, para que el codigo de salida sea el de zfs y un fallo no parezca "no hay"); el recorte con su cuenta lo hara el servidor — coste: un NAS con decenas de miles de instantaneas manda varios MB.
- Task 3: Ruling: LUNS_HERO saca con grep -o solo clave y valor escalar de una lista blanca de claves (si el JSON viniera en una linea no sale nada y la orden falla, en vez de salir entero con sus CHAP) y queda no_probado: nas1 no tiene destinos ni LUN — coste: de un LUN en hero solo se sabra nombre y alias (el tamano saldra de los zvol de DATASETS) hasta validarlo con un NAS que tenga.
- Task 3: Ruling: snapshots_prog devuelve los campos con el nombre y el valor del NAS (Schedule, schedule_status...): su significado no se ha podido validar — coste: quien lo lea interpreta; el servidor lo dira.
- Task 3: Ruling: identificadores zfs_snapshots, zfs_snapshots_prog y zfs_iscsi (los nombres Python siguen siendo SNAPSHOTS_HERO, SNAPSHOTS_PROG_HERO, LUNS_HERO) para que el fichero de datos no salga con el sufijo doblado; el parser de la programacion se llama snapshots_prog y el de iSCSI zfs_iscsi.
- Task 3: Ruling: pools_estado devuelve los dispositivos como lista plana con nivel, papel (datos/logs/cache/spares) y grupo; cabina y bahia salen del nombre del miembro (enc_N/disk_0xHHHH: la parte alta del numero es la cabina; visto para 0 y 23, el caso de expansion esta escrito a mano) — coste: si otra cabina numera distinto, el cruce con discos_fisicos falla para ella.
- Task 3: Ruling: el anonimizador oculta tambien el identificador de disco de los miembros de un pool (WWN o serie) y el guid de un pool — aparecieron al mirar zpool status.
- Task 4: Ruling: no se define MD_DETALLE (mdadm --detail con sudo, uno por grupo): mdstat da nivel, miembros con sus marcas (S)/(F), mapa [UU_] y progreso; /sys da accion, degradado y discrepancias; raid.conf da los miembros configurados por bahia (para saber cual falta) — coste: no se ve el texto de estado por miembro de mdadm; se anade si un caso real degradado lo pide.
- Task 4: Ruling: no se define CACHE_SSD: volume.conf dice que volumenes usan cache y dmsetup status da su ocupacion — coste: no se informa del modo ni del algoritmo de la cache.
- Task 4: Ruling: RAID_CONF usa grep -o para sacar de cada miembro solo el numero de disco (hexadecimal, cabina en la parte alta: cotejado con los varios discos de nas2 y su cabina de expansion), sin WWN ni serie; no se lee el uuid. Los md que no estan en raid.conf son del sistema (md9, md13, intercambio) y sus huecos son normales: el parser los cuenta y el servidor decide.
- Task 4: Ruling: DM_ESTADO es "dmsetup status" entero con sudo (sin tuberia) y el parser se queda con pools ligeros, cache y cifrado — coste: unas decenas de lineas de mas por la red.
- Task 4: Ruling: en QTS el volumen de una instantanea sale de su identificador (id // 10000; cotejado con el tamano de dos volumenes de nas3 y con los seis volumenes de replica de nas2) y su tamano es el del volumen: snapshot.conf no dice el espacio que retiene cada una — coste: "espacio que retienen" no existe por instantanea en QTS.
- Task 4: Ruling: ISCSI_QTS queda no_probado: ningun QTS de pruebas tiene destinos ni LUN, y los nombres de seccion y de campo de destinos y LUN son supuestos (patron de la seccion de iniciadores) — coste: en un NAS con LUN podrian salir vacios; nunca saldran claves (lista blanca).
- Task 4: Ruling: identificadores lvm_snapshots, lvm_snapshots_prog, lvm_iscsi (nombres Python SNAPSHOTS_QTS, SNAPSHOTS_PROG_QTS, ISCSI_QTS); la programacion de QTS usa el mismo parser snapshots_prog que hero.
- Task 4: Ruling: datos de prueba: mdstat, md_sys, raid_conf, volumenes_conf, lvm_conf, programacion e iSCSI derivados de lo guardado con el mismo patron de la orden; dm_estado derivado de una salida filtrada y cortada a 300 caracteres; instantaneas reconstruidas a partir de un bloque real. Todo se valida en la pasada real de T7.
- Task 5: Ruling: OCUPACION es "df -P -k" entero (sin tuberia) y se valida por su salida, no por el codigo: en nas1 df termina con 1 estando todo bien (un montaje interno de samba no deja mirar); el parser exige la cabecera y se queda con lo montado bajo /share que no sea tmpfs — coste: si df falla a medias, un volumen puede faltar en la lista (el servidor lo vera sin ocupacion, no con una cifra falsa).
- Task 5: Ruling: CARPETAS_SMB falla si smb.conf no existe o no se puede leer (no hay "ninguna carpeta" sin ese fichero); devuelve las cuatro listas de Samba separando usuarios y grupos, y el comentario acotado a 120 caracteres — coste: ninguno conocido.
- Task 5: Ruling: CARPETAS_ENLACES es "ls -l /share/" sin recorte en el NAS (una linea por carpeta); el recorte, si hace falta, lo pone el servidor.
- Task 5: Ruling: el anonimizador oculta ademas comentarios de carpeta (salvo los de fabrica), fsid de NFS y UUID, y no sustituye un nombre dentro de un identificador con guiones bajos (una carpeta "Backup" tocaba Power_Fail_Backup_Health y un usuario "NAS" el NAS_HOST); los nombres a ocultar salen de smb.conf, volumeStatus.conf y los enlaces de /share, incluidas las carpetas remotas "Nombre (usuario@equipo)".
- Task 5: Ruling: de QTS no hay df con -P -k guardado (la exploracion uso df -h filtrado): el caso QTS de ocupacion esta escrito a mano con el formato de la captura real de hero; se valida en la pasada de T7.
- Task 6: Ruling: disco_smart(nas, bahia, cabina=0): se anade la cabina (el encargo decia solo bahia) porque las cabinas de expansion y las ranuras internas repiten numero de bahia; los dos numeros se validan al componer la orden, antes de conectar, y solo se admite un disco que el NAS gestione — coste: para un NVMe o una expansion hay que pasar la cabina que da discos_fisicos.
- Task 6: Ruling: lo comun a las herramientas (_leer, _opcional, _no_probado) pasa a servidor.Base y redes hereda de ella (mismo codigo, sin cambios de comportamiento; la bateria de redes sigue en verde) — coste: ninguno.
- Task 6: Ruling: iscsi lee su fichero con _leer (un fichero ilegible tumba la entrada con su error) y marca el resultado no_probado=true; no usa _no_probado porque ese bloque es toda la herramienta.
- Task 6: Ruling: almacenamiento_resumen incluye el estado de los discos (ficheros SMART y getsysinfo, con sudo) para no dar por bueno un NAS con un disco fallando; si sudo no responde lo dice en "errores" y en un aviso — coste: dos ordenes con sudo en la herramienta de entrada.
- Task 6: Ruling: en QTS solo los grupos md que estan en raid.conf son de datos; los demas (md9, md13, intercambio) se resumen y nunca se marcan como degradados, porque nacen con huecos; un grupo configurado que el kernel no tiene montado sale como "ausente" con su aviso — coste: un problema en un grupo del sistema no genera aviso.
- Task 6: Ruling: en hero un volumen es un dataset montado en /share/<X>_DATA (tamano = cuota de referencia, o usado + disponible si no tiene); las instantaneas ":init:" que crea el NAS se cuentan como internas y no se listan; pool interno = zpoolExt* o zpool con numero >= 256 (la cache) — visto solo en nas1.
- Task 6: Ruling: umbrales de aviso: ocupacion >= 80 % (pools y volumenes, como pedia el plan) y vida de SSD >= 90 %; no hay avisos por temperatura (no se ha querido inventar un umbral) — coste: un disco muy caliente no se avisa, aunque su temperatura si se da.
- Task 6: Ruling: los contadores de sectores (atributos 5, 197, 198) solo se leen en discos ATA: en el fichero de un NVMe esos numeros son otros campos (el 5 es el desgaste). Lo cazaron las pruebas con los datos reales de nas1.
- Task 7: Ruling: visto en la pasada real: en QTS el volumen de una instantanea (snapshotId // 10000) es el lvId de qlvm.conf, no el volId de volume.conf (en nas3 el volumen de id 2 es el lv 3). `volumenes` anade el campo `lv` y la descripcion de `snapshots` dice que su `volumen` es ese `lv`; no se renombra el campo de las instantaneas — coste si mal: quien cruce por numero sin leer la descripcion confunde volumenes, aunque el nombre va siempre al lado.
- Task 7: Ruling: la carpeta de smb.conf con `path = %H` (carpeta personal de quien entra) sale con volumen sin valor en vez de "%H" — coste: ninguno.
- Task 7: Ruling: `ocupacion` descarta tambien las lineas `overlay` (capas de contenedores montadas bajo /share: 35 de 94 lineas en nas3), que no son volumenes — coste si mal: ninguno conocido; ninguna herramienta las usaba.
- Task 7: Ruling: el anonimizador tapa los identificadores de 64 cifras hexadecimales (capas de Docker), que no estaban en la lista del plan, para poder versionar la captura real de df — coste: ninguno.
- Task 7: Ruling: las seis capturas reales de nas3 hechas con las ordenes del producto se guardan como `*_qtsreal.txt` con una prueba por parser (pasan a la primera a proposito: fijan el formato real); el NAS simulado de QTS sigue usando las salidas escritas a mano, que casan con sus nombres de ejemplo — coste: datos duplicados para tres ordenes.
- Task 7: Ruling: la prueba de no escritura con `--producto discos` se lanza solo en nas1, como dice el plan; las 9 ordenes propias de QTS (lecturas de ficheros de configuracion, /proc, /sys y `dmsetup status`) quedan cubiertas por la prueba del catalogo en nas3 y no se repiten en un NAS de pruebas — coste si mal: un efecto no detectado de una lectura de fichero, improbable.
- Final: Ruling: M2 (una seccion de iscsi_trgt.conf con datos y nombre no previsto se descartaba y la respuesta decia "sin destinos ni LUN") sube a importante: iSCSI es habitual en QTS y los nombres de seccion son supuestos; ahora esas secciones salen en `sin_reconocer` — fixed, test_una_seccion_de_iscsi_con_datos_que_no_se_conoce_no_pasa_por_no_hay RED->GREEN — coste si mal: ninguno.
- Final: Ruling: M6 (un disco que falta en un pool ZFS sale con su identificador y la bahia solo en la nota) sube a importante: saber que bahia ha caido es lo primero que se pregunta; la bahia se saca tambien de la nota — fixed, test_un_disco_que_falta_en_un_pool_conserva_su_bahia y test_el_aviso_de_un_disco_que_falta_en_un_pool_dice_su_bahia RED->GREEN — coste si mal: el formato de ese caso esta escrito a mano (ZFS estandar), no visto en un QNAP.
- Final: Ruling: M1 (una linea de df con capacidad "-" bajo /share tumbaba resumen y volumenes) queda sin efecto con el cambio de I4: df ya solo devuelve los montajes de volumen y el tmpfs de /share — coste si mal: un volumen con 0 bloques daria error (ruidoso, no un dato falso).
- Final: Ruling: con df por argumentos sobra el filtro de lineas `overlay` anadido en la tarea 7: se retira (ese Ruling de la tarea 7 queda sin efecto); las capturas de df se rehacen con la orden nueva (hero: derivada de la captura existente, para que siga casando con la de datasets; QTS: la salida real de nas3); la regla del anonimizador para identificadores de capa se conserva para la entrega 3.
- Final: Ruling: no se avisa por ocupacion de datos >= 80 % de un pool ligero (lo proponia el revisor en I3): en QTS los volumenes gruesos reservan su espacio en el pool y un pool sano esta siempre alto (73-90 % en los cuatro de nas2); se usan el umbral del propio NAS (overThreshold), los metadatos >= 80 %, el modo y el fallo — coste si mal: un pool de volumenes ligeros casi lleno y sin umbral configurado no avisa (su porcentaje si se da).
- Final: Ruling: rulings que el revisor no comparte: (a) grupos md del sistema: corregido en I2; (b) sin avisos por temperatura: se mantiene, no se inventa un umbral, y ahora lo dice la descripcion de discos_fisicos — coste: un disco muy caliente no sale en avisos; (c) SNAPSHOTS_HERO sin recorte en el NAS: se mantiene para no perder el codigo de salida de zfs — coste: en un NAS con decenas de miles de instantaneas la orden es pesada; (d) aviso por estado distinto de 0: se mantiene con el texto "(0 es lo normal)" — coste: posible falsa alarma con un codigo sin documentar.
- Final: Ruling: M9 (`cat /etc/exports` entero frente a "nunca el fichero entero"): se mantiene; la norma protege ficheros de configuracion con secretos y /etc/exports es la lista de exportaciones, sin campos que filtrar — coste si mal: ninguno conocido.
- Final: Ruling: lo que el revisor dejo sin juzgar: (1) si un estado de disco distinto de 0 es un fallo: se avisa igual, ver (d); (2) df con un montaje remoto caido: resuelto en I4; (3) nombres reales de seccion y campo de iSCSI: sigue `no_probado`, mas `sin_reconocer`; (4) secciones de enclosure_*.conf que no sean de disco: se mantiene, las capturas de tres NAS pasan — coste: detalle de disco equivocado si un firmware las anade; (5) numeracion de cabinas de expansion en ZFS y cruce de getsysinfo con la bahia: se mantiene lo cotejado en varios discos — coste: bahia equivocada en una expansion con otra numeracion; (6) transporte y ejecutor: revisados en la entrega 1; (7) publicacion: decision del usuario.

### Revision final

- Final review: revisor independiente (subagente, modelo opus) sobre review-50ecb5d..cd5d5a6.diff: ningun critico, 4 importantes (I1-I4), 11 menores (M1-M11). Veredicto: fusionar con arreglos.

### Corregido tras la revision final (4)

- Final: fixed I1 (volumenes de QuTS hero calculaba usado y ocupacion con el "used" de ZFS, que cuenta instantaneas, reserva y descendientes: 109 % en un volumen que df da al 0 %; ahora usado = lo referido, tamano = referido + disponible, y lo que ocupa en el pool va aparte en `en_el_pool`, con `cuota`) — test_la_ocupacion_de_un_volumen_de_hero_no_cuenta_instantaneas_ni_reserva RED->GREEN, suite 1158/1158
- Final: fixed I2 (QTS: sin raid.conf, o con otra disposicion, todos los grupos md pasaban por "del sistema" y un RAID de datos degradado no avisaba; ahora solo son del sistema md9, md13 y md de tres cifras, y el resto se trata como de datos `sin_configuracion`) — test_un_grupo_de_datos_degradado_se_avisa_aunque_no_este_en_raid_conf RED->GREEN, suite 1158/1158
- Final: fixed I3 (QTS: volumen sin montar, en solo lectura, sucio o con estado distinto de 0, volumen o pool sobre su umbral, pool ligero en fallo, en modo distinto de rw o con metadatos >= 80 % no generaban avisos; ahora salen en `volumenes` y en `almacenamiento_resumen`) — test_un_volumen_en_solo_lectura_o_sucio_sale_en_los_avisos, test_un_volumen_con_un_estado_que_no_es_el_normal_sale_en_los_avisos, test_un_volumen_que_no_esta_montado_sale_en_los_avisos, test_un_volumen_o_un_pool_sobre_su_umbral_sale_en_los_avisos, test_un_pool_ligero_averiado_en_solo_lectura_o_sin_metadatos_sale_en_los_avisos RED->GREEN, suite 1158/1158
- Final: fixed I4 (df de todos los montajes puede colgarse con una carpeta remota caida) de otra forma que la propuesta: el df de QNAP es BusyBox 1.24.1 y no admite -l (comprobado en nas1 y nas3: "invalid option"); la orden pasa a `df -P -k /share/*_DATA`, que solo consulta los montajes de volumen (probada en los dos NAS; sin ningun volumen da la cabecera y rc=1); el parser cuenta cada montaje una vez — test_la_ocupacion_se_pide_solo_de_los_volumenes_en_kilobytes_y_sin_lineas_partidas, test_dos_rutas_del_mismo_volumen_cuentan_una_vez RED->GREEN, suite 1158/1158

### Menores aplazados (7)

Resueltos en la 0.4.1 (2026-10-14): M3 (sin ningun fichero de desgaste con SSD presentes, error en 'errores'), M5 (aviso de disco sin fichero SMART o sin veredicto del NAS), M7 (el resumen da pools y grupos aunque falle la lista de discos), M8 (lo retenido por instantaneas sale de usedbysnapshots, total y por volumen; en nas1 683 GB frente a los 620 de la suma de 'used'). Ya no aplica: M11 (la publicacion cambia esos nombres).

- Final: minor (deferred): M3 ssd_vida sin ficheros en /tmp/disk deja la vida de todos los SSD sin valor y sin entrada en `errores`.
- Final: minor (deferred): M4 un disco de enclosure_*.conf que qcli_storage -d no lista se clasifica como externo aunque sea SATA.
- Final: minor (deferred): M5 un disco sin fichero SMART o sin veredicto no genera aviso "sin datos SMART".
- Final: minor (deferred): M7 almacenamiento_resumen lee primero los discos con _leer: si qcli_storage o enclosure fallan se pierde tambien el estado del RAID.
- Final: minor (deferred): M8 SNAPSHOTS_HERO lista todas las instantaneas (60 s de tope); `retenido_bytes` suma el "used" de cada una, que infravalora lo recuperable.
- Final: minor (deferred): M10 `volumen` sale como "external" en enlaces a discos externos o remotos; ruta, destino y cliente NFS no pasan por el acotado.
- Final: minor (deferred): M11 las capturas de hero llevan nombres de volumen reales (ZFS1_DATA...ZFS531_DATA): cambiarlos por ejemplos antes de publicar (ya previsto para la entrega 4). La cita a captura_redes.py en un docstring de pruebas se ha corregido de paso.
