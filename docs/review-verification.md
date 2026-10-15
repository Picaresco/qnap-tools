# Verificacion de la revision de codigo (`docs/review-findings.md`)

Fecha: 2026-10-15. Verifica, hallazgo a hallazgo, la revision de qnap-tools 0.4.4 (main 9012206)
escrita por otro agente. Metodo: cuatro verificadores independientes por area (nucleo y flota,
discos, virtualizacion y logs, redes y empaquetado) mas el orquestador, que verifico a mano el
HIGH 1 y contrasto con el codigo las afirmaciones de las que depende cada veredicto. Cada
hallazgo se reprodujo con una prueba pytest sobre los dobles de `tests/falsos.py` y los datos de
`tests/datos/`, y los arreglos propuestos se probaron por monkeypatch o sobre una copia del
arbol. Las ordenes con tuberias se ejecutaron en un `sh` real (el de Git).

Hechos externos comprobados en su fuente: paramiko 5.0.0 instalado (`channel.py`,
`transport.py`, `client.py`, `hostkeys.py`), OpenZFS (`libzfs_pool.c`, `libzfs_config.c`), kernel
(`dm-thin.c`, `dm-cache-target.c`), libvirt (`libvirt-domain.h`, `qemu_driver.c`,
`qemu_process.c`, `virsh-domain-monitor.c`, `domain_conf.c`) y los wheels de `mcp` de PyPI.

No se ha cambiado codigo ni pruebas del repositorio y no se ha conectado a ningun NAS. Las
pruebas de reproduccion quedaron en la carpeta temporal de la sesion (no versionadas); aqui va lo
necesario para reescribirlas como pruebas TDD.

Nota de numeracion: el documento original dice "33 hallazgos" (1 alto, 10 medios, 22 bajos) pero
numera 36 (25 bajos) y repite los numeros 9, 10 y 11 en medios y bajos. Aqui se citan como M9 /
L9, etc.

---

## Resumen

| Veredicto | Cuantos | Hallazgos |
|-----------|---------|-----------|
| Confirmado | 22 | H1, M2, M3, M4, M5, M6, M8, M9, M10, M11, L10, L11, L12, L14, L15, L16, L17, L19, L20, L22, L27, L30 |
| Parcial (cierto en parte, o cierto con el arreglo mal planteado) | 13 | M7, L9, L13, L18, L21, L23, L24, L25, L26, L28, L29, L31, L33 |
| Falso positivo | 1 | L32 |

Cambios de gravedad: M6, M7 y M8 bajan a BAJA; L10 sube a MEDIA-BAJA (es lo que hay que lanzar
para reponer la clave de nas3); L21, L23, L31 y L33 bajan a INFORMATIVO.

Los arreglos del documento que NO valen tal cual (usar el de este informe):
- M2: comprobar `transport.is_active()` tiene una carrera dentro de paramiko.
- M7: la orden propuesta sigue tapando un fallo y da un falso error con `ddns.conf` vacio.
- M11: comparar `keystatus` con `"unavailable"` fallaria en silencio (QNAP dice `avail`).
- L9: pasar a `auth="contrasena"` crea el callejon que critica el propio M5.
- L13: quitar `; true` rompe el caso "sin concesiones".
- L24: emitir la marca tambien sin `meta_path` daria un error fijo en toda VM que no sea de VS.
- L25b: envolver con `timeout N` no esta probado en BusyBox y toca todas las ordenes.
- L31: avisar de todo `exited` con codigo != 0 rompe una prueba y ensucia los dos NAS de referencia.
- L33: cuadrar con el rango de ids es fragil (huecos, eventos que entran entre ordenes).

Valoracion global: la revision original es buena. Lo grave que dice es cierto, ningun hallazgo
afecta a la regla de solo lectura ni a la contrasena, y el HIGH 1 es incluso mas facil de
disparar de lo que describe.

---

## HIGH

### H1. `almacenamiento_resumen` (QTS) dice que faltan todos los discos de un grupo degradado
- **Veredicto:** CONFIRMADO, y peor de lo descrito: basta con que falle `qcli_storage -d`
  (`DISCOS_LISTA`, la orden lenta, 30 s) aunque `/etc/enclosure_*.conf` se haya leido bien,
  porque `_discos` tira el detalle ya leido y el resumen pasa `{}` a `_raid_qts`.
- **Reproduccion** (QTS simulado, `md1` degradado al que le falta la bahia 4):

  | Caso | Aviso |
  |---|---|
  | lista de discos leida | "falta el disco de la cabina 0, bahia 4" (bien) |
  | falla `DISCOS_DETALLE` | "falta ... bahia 1 y ... bahia 2 ... y bahia 7" (los 7) |
  | falla solo `DISCOS_LISTA` | igual: los 7 |
  | `raid_estado` con `DISCOS_LISTA` fallando | bahia 4 (bien: pasa `None` y relee) |

  La prueba existente `test_el_resumen_con_un_grupo_degradado_y_sin_lista_de_discos_avisa_del_grupo`
  pasa con el fallo porque solo busca "md1" y "degradado".
- **Gravedad:** ALTA (se mantiene).
- **Arreglo recomendado** (dos capas):
  1. `_raid_qts` (`discos/servidor.py:335-342`): si algun miembro VIVO no tiene bahia conocida,
     no se afirma cual falta: `faltan = None`. En `avisos_md`, `faltan is None` (y no
     `sin_configuracion`) anade "; no se ha podido determinar que disco falta". `faltan` solo lo
     leen `avisos_md` y las pruebas (comprobado con grep). Cubre tambien el caso parcial (un
     miembro vivo fuera del mapa).
  2. `almacenamiento_resumen` (`:466`): cuando `_discos` fallo, leer solo las bahias con
     `self._extra(n, {}, "bahias", dc.DISCOS_DETALLE, p.discos_detalle)` (grep de ficheros,
     barato) y construir el mapa con eso; si tambien falla, `{}` y la capa 1 hace el resto. No
     pasar `None` (como propone el documento): `_raid_qts` releeria con `_leer` y una segunda
     caida tumbaria la entrada entera.
- **Prueba TDD:** las tres filas de la tabla: con `DISCOS_LISTA` fallando el aviso dice
  "bahia 4"; con `DISCOS_LISTA` y `DISCOS_DETALLE` fallando, `faltan is None` y el aviso dice
  "no se ha podido determinar"; un miembro vivo fuera del mapa da lo mismo. Endurecer la prueba
  existente para que exija que NO aparezca "bahia 1".

---

## MEDIAS

### M2. Canal cerrado sin codigo de salida: `rc=-1, agotado=False`
- **Veredicto:** CONFIRMADO. En paramiko 5.0.0, `_set_closed` pone `status_event` y
  `recv_exit_status()` da -1. Reproducido: con `valida=None` o `no_vacia` la salida truncada pasa
  por buena con una sola conexion; con `estricta` sale "termino con codigo -1" sin reintento;
  `detectar` cachea un `Perfil` a medias.
- **Gravedad:** MEDIA.
- **Arreglo del documento, punto 1: NO.** En `Transport.run()` (`transport.py:2152-2155`) los
  canales se cierran (`chan._unlink()`) ANTES de `self.active = False`: justo en ese momento
  `is_active()` aun dice True y el fallo se colaria. Ademas una senal sobre el proceso remoto deja
  el transporte vivo.
- **Arreglo recomendado:** en `Conexion.ejecutar` (`transporte.py`), tras la comprobacion de sudo:
  `if rc == -1 and not agotado: raise ErrorConexion("%s: la orden termino sin codigo de salida
  (conexion perdida o proceso interrumpido)")`. `_ejecutar` ya reintenta una vez; `lanzar_en`
  (alta, enrolado) y `detectar` quedan cubiertos. Repetir una orden de lectura es inocuo. Como
  defensa opcional, `_comprobar` trata `rc == -1` como error con cualquier `valida`.
- **Prueba TDD:** `falsos.Mundo` que responde `(-1, "eth0", "")` con `Comando(valida=None)`:
  `ErrorConexion` y dos conexiones; primera respuesta -1 y segunda buena: devuelve la segunda;
  `CUELGA` sigue dando "tiempo agotado". Ninguna prueba existente cambia.

### M3. El perfil del NAS se cachea para siempre
- **Veredicto:** CONFIRMADO (tras `cortar()` y reabrir, firmware viejo y una sola deteccion).
- **Gravedad:** MEDIA-BAJA (`sistema` no cambia salvo reinstalacion).
- **Arreglo:** el del documento, valido y minimo: en `Flota._conexion`, al crear una conexion
  nueva, `self._perfiles.pop(nas.nombre, None)`. Cumple el docstring ("una vez por conexion").
  Hacerlo junto con M2 (los dos en `ejecutor.py`/`transporte.py`).
- **Prueba TDD:** tras `ErrorConexion` y reapertura, `perfil()` vuelve a lanzar `DETECCION`.
  `test_el_perfil_se_detecta_una_sola_vez` sigue pasando sin cambios.

### M4. `nas_comprobar` informa de un acceso desactualizado
- **Veredicto:** CONFIRMADO, los dos escenarios (clave perdida con `auto` -> "contrasena" sin
  aviso; conexion vieja por clave -> sigue diciendo "clave" tras reabrir por contrasena).
- **Gravedad:** MEDIA.
- **Arreglo:** el del documento, con un matiz de texto: el aviso solo puede salir con `auto` (con
  `clave` la conexion falla en vez de caer a contrasena). Leer `acceso = flota.metodo(n)` DESPUES
  de `perfil` y `lanzar`, y avisar "este NAS esta configurado para entrar por clave y ha entrado
  por contrasena: la clave de este ordenador no vale alli; nas_enrolar la reinstala".
- **Prueba TDD:** inventario `auto`, doble que rechaza la clave: aviso presente; las
  `test_comprobar_*` existentes no cambian.

### M5. `_acepta_clave` toma un corte transitorio por "no acepta la clave"
- **Veredicto:** CONFIRMADO (un `SSHException` de banner en la conexion de prueba deja el NAS en
  `auth="contrasena"` para siempre y `nas_enrolar` lo salta).
- **Gravedad:** MEDIA-BAJA.
- **Arreglo:** tres resultados, como dice el documento, con una correccion: `HostCambiado` y
  `HostSinFijar` tambien son `ErrorConexion` y deben PROPAGARSE (`HostCambiado` es una senal de
  seguridad), no convertirse en `None`:
  `except AutenticacionFallida: return False` / `except (HostCambiado, HostSinFijar): raise` /
  `except ErrorConexion: return None`. En `nas_alta`, `None` -> `auth="auto"` y aviso "no se pudo
  comprobar la clave (motivo); se probara en la siguiente conexion". En `nas_enrolar` (`:232`),
  `None` -> `datos["aviso"]`.
- **Prueba TDD:** helper con los tres casos; integracion en alta y enrolar con un doble que lanza
  `SSHException` en la conexion de prueba tras instalar la clave -> inventario `auto`.

### M6. `alertas_config` sin la marca `no_probado`
- **Veredicto:** CONFIRMADO. Matiz: `Comando.no_probado` no lo lee nada de `src/`, pero
  `tests/test_discos_comandos.py:34,118` lo coteja con `NO_PROBADO = {"ISCSI_QTS"}`.
- **Gravedad:** BAJA (los umbrales de fabrica estan validados; lo no visto es el `value` de un
  aviso puesto por el usuario). Lo que pesa es la incoherencia con `disco_smart`.
- **Arreglo:** una sola fuente de verdad. `no_probado=True` en `SMART_UMBRALES`; en `Base._leer`,
  `if comando.no_probado: datos = dict(datos, no_probado=True)` (las dos Comando marcadas dan
  `dict`; el envoltorio `{"filas": ...}` sobra); quitar la marca a mano de `iscsi`; dejar
  `_no_probado` para el caso con error dentro del bloque (`disco_smart`); copiar a las
  INSTRUCCIONES de logs la frase de las de discos. No cambia ninguna otra salida (redes no tiene
  ninguna Comando marcada).
- **Prueba TDD:** `alertas_config(...)["smart"]["no_probado"] is True`; prueba generica: todo
  Comando con `no_probado=True` produce la marca. Ajustar `NO_PROBADO` a
  `{"ISCSI_QTS", "SMART_UMBRALES"}`.

### M7. `cat ... 2>/dev/null; true` en `BLOQUEO_IP` y `DDNS`
- **Veredicto:** PARCIAL. El mecanismo es cierto (fichero ilegible -> rc 0 y lista vacia). El
  escenario no esta visto: en las capturas reales de los tres NAS, hechas sin root y con `2>&1`,
  `ipsec_allow.conf`, `ipsec_deny.conf` y `ddns.conf` se leen sin error.
- **Gravedad:** BAJA (defensivo).
- **El arreglo del documento falla dos veces** (probado en `sh` real):
  1. `[ ! -e F ] || cat F; echo ==denegadas; [ ! -e G ] || cat G` devuelve el rc de la ULTIMA
     orden: F ilegible y G legible da rc 0.
  2. `[ ! -e F ] || grep ...` da rc 1 con un `ddns.conf` vacio o sin coincidencias: falso error.
  Ademas, las llaves `{ ...; }` no valen: la guardia las rechaza ("comando sin regla: {"); los
  subshells `( ... )` si pasan la guardia y el constructor de `Comando`.
- **Arreglo recomendado:**
  - BLOQUEO_IP: `...; echo ==permitidas; ( [ ! -e F ] || cat F ) && echo ==denegadas && ( [ ! -e G ] || cat G )`,
    sin `2>/dev/null` ni `; true`, validador por defecto.
  - DDNS: `...; echo ==ddns; [ ! -e $c/ddns.conf ] || ( grep -E '...' $c/ddns.conf; [ $? -le 1 ] )`
    (sigue resolviendo `$c`, que en hero es `config.local`).
  - EN EL MISMO CAMBIO, `DDNS` pasa de `_leer` a `_opcional` en `red_acceso_remoto`
    (`redes/servidor.py:248`) y el resultado trata `{"error": ...}`; si no, una orden que ahora si
    falla tumba la herramienta entera y se pierden `upnp` y `vpn`.
- **Prueba TDD:** la plantilla en `sh` real (patron de `tests/test_virtualizacion_shell.py`):
  ausente o vacio -> rc 0; primera o segunda ilegible -> rc != 0 (en Windows, "ilegible" se
  simula con un directorio del mismo nombre). Servidor: DDNS respondiendo
  `(2, "", "grep: ...: Permission denied")` -> `ok: True` con `error` dentro de `ddns`.

### M8. Huella huerfana en `known_hosts` sin herramienta que la quite
- **Veredicto:** CONFIRMADO, las tres vias (baja con `olvidar_host` fallando, importar con host
  cambiado, mensaje de `HostCambiado` sin ruta).
- **Gravedad:** BAJA (raro y recuperable editando un fichero).
- **Arreglo:** el del documento: en `nas_baja`, olvidar la huella ANTES de guardar el inventario
  (calculando antes si otro NAS usa el mismo host); en `inventario_importar(sobrescribir)`, olvidar
  el host viejo si nadie mas lo usa; la ruta de `known_hosts` en el mensaje de `HostCambiado`.
- **Prueba TDD:** baja con `olvidar_host` que lanza -> el inventario conserva el NAS; importar con
  host cambiado -> `host_fijado(viejo)` es False. Vigilar `test_baja_conserva_la_clave_de_host...`
  y `test_dos_bajas_a_la_vez_por_el_servidor_no_se_pisan` (dependen del orden).

### M9. `almacenamiento_resumen` (hero) se cae con un pool que no se puede abrir
- **Veredicto:** CONFIRMADO, con una correccion: OpenZFS (`zpool_get_prop`, pool en
  `POOL_STATE_UNAVAIL`) solo rellena nombre, salud y guid; tamano, ocupado, libre, cap y dedup
  salen `-`, y la salud que imprime es `FAULTED`, no `UNAVAIL`. Reproducido:
  `zpool1\t-\t-\t-\t-\t-\tFAULTED` -> `ok:false` "el tamano no es un numero: '-'" y se pierde el
  aviso de `_raid_hero` ya calculado.
- **Gravedad:** MEDIA (falla en voz alta, pero justo en el caso para el que existe la herramienta).
- **Arreglo:** el del documento mas una guarda: en `pools()` usar `_tamano` para bytes, usado,
  libre y ocupacion, y `dedup=None` si es `-`; en el resumen (`discos/servidor.py:463-464`),
  `x["ocupacion_pct"] is not None and x["ocupacion_pct"] >= UMBRAL_OCUPACION` (si no, `TypeError`).
- **Prueba TDD:** el parser acepta la fila con guiones; el resumen con ese pool da `ok:true`, cifras
  `None` y conserva el aviso "pool zpool1 en estado ...". Ninguna prueba existente se rompe.
- **Sin validar en real** (no se ha visto un pool caido en un NAS).

### M10. VM apagada por caida o por fallo al arrancar: sale como "apagada" normal
- **Veredicto:** CONFIRMADO. `libvirt-domain.h`: motivo 3 = CRASHED, 6 = FAILED ("failed to
  start"). `qemu_driver.c`: si el proceso qemu desaparece sin evento SHUTDOWN, el dominio queda
  apagado con motivo CRASHED. En los datos reales de hero y QTS las apagadas solo traen motivo 0.
- **Gravedad:** MEDIA-BAJA (silencioso; lo que hace VS en una caida real es deducido).
- **Arreglo recomendado** (distinto del documento): NO cambiar el texto de `estado` (arrastra
  `por_estado` y todos los usos de `estado`). El parser anade `motivo_apagado` (int o None)
  cuando el estado es 5; `avisos_de_vms` avisa con motivo 3 ("se apago por una caida") o 6
  ("fallo al arrancar"). El 5 sigue siendo "suspendida".
- **Prueba TDD:** motivos 3 y 6 -> aviso en `virtualizacion_resumen`; 0, 1 y 2 -> sin aviso.

### M11. Hero: un volumen cifrado bloqueado desaparece del resumen sin aviso
- **Veredicto:** CONFIRMADO en lo mecanico (el resumen de hero solo mira `df`; `_volumenes_hero`
  no tiene `avisos`).
- **Correccion importante:** en QNAP la clave abierta sale como `avail` (validado en nas1 el
  14-oct, ver CLAUDE.md), no como el `available` de OpenZFS; el valor de una clave bloqueada no se
  ha visto. Comparar con `"unavailable"` fallaria en silencio.
- **Gravedad:** MEDIA (pasa cada vez que un volumen cifrado sin la clave guardada queda bloqueado
  tras un reinicio; en QTS ya existe el aviso equivalente).
- **Arreglo recomendado:** criterio independiente del texto de `keystatus`: "el dataset de volumen
  (tipo `filesystem`, `mountpoint` `/share/X_DATA`) no esta entre los montajes de `df`"; criterio
  secundario `cifrado and clave not in ("avail", "available")`. Funcion `avisos_de_volumenes_hero`;
  en el resumen leer `DATASETS` con `_extra` y reutilizar la `ocupacion` ya leida; en
  `_volumenes_hero` leer `OCUPACION` con `_extra` y devolver `avisos`. Con los datos reales (12
  volumenes en df, 12 datasets de volumen) sale 0 avisos.
  Alternativa mas directa pero con recaptura: anadir la propiedad `mounted` a `DATASETS`.
- **Prueba TDD:** dataset cifrado ausente de df -> aviso "volumen X no esta montado: esta cifrado
  y puede estar bloqueado" (con `keystatus` `unavailable`, `unavail` u otro texto); sin falsos
  positivos con los datos reales.
- **Sin validar en real:** bloquear un volumen de nas1 y mirar `keystatus` cerraria tambien el
  pendiente "carpeta cifrada bloqueada" del CLAUDE.md.

---

## BAJAS

| # | Veredicto | Gravedad | Arreglo recomendado (y diferencias con el documento) |
|---|---|---|---|
| L9 `nas_enrolar` deja `auto` | Hecho cierto; arreglo NO | BAJA | No cambiar el inventario: pasar a `contrasena` hace que `nas_enrolar` lo salte despues (el callejon de M5). Basta el aviso de enrolar mas el nuevo de M4. La raiz es que `auth` mezcla "no quiso clave" con "la clave fallo"; no merece un campo nuevo. |
| L10 `nas_enrolar` sin `nas` | CONFIRMADO | sube a MEDIA-BAJA | `nas_enrolar(nas: str = "todos")` con `por_nas(nas, uno)`; actualizar skill `enrolar` y README. Es lo que conviene usar para reponer la clave de nas3 sin escribir en los demas. Ninguna prueba cambia (el defecto conserva el comportamiento). |
| L11 mismo host:port dos veces | CONFIRMADO | BAJA | Antes de conectar, `(host, port)` ya presente -> error "ese equipo ya esta en el inventario como X" (solo coincidencia literal). |
| L12 `nas_alta` sin sanear `perfil` | CONFIRMADO (rebuscado) | MUY BAJA | Pasar el dict por `_sin_contrasena` (mejor con un metodo publico en `Contexto`). |
| L13 `==lineas` sin numero | PARCIAL | BAJA | Solo el parser: `==lineas` sin entero -> `ValueError`. NO quitar `; true`: sin ficheros `.leases` el `for` acaba en rc 1 (probado en `sh`). El disparador (grep -c ilegible) no es reproducible fuera de BusyBox. |
| L14 E/S del inventario | CONFIRMADO | BAJA | En `inventario.cargar`, tras el `except FileNotFoundError`: `except (OSError, UnicodeDecodeError) -> InventarioInvalido`. |
| L15 `olvidar_host` en el `finally` | CONFIRMADO | BAJA | `try/except OSError` alrededor y el motivo en el error ya calculado. |
| L16 `nfs_exportadas=0`, `sin_smb=[]` | CONFIRMADO | BAJA | `None` cuando `nfs`/`enlaces` es `None`. |
| L17 aviso global de `errores` | CONFIRMADO, peor de lo descrito | BAJA | Sin `volume.conf` (QTS) se pierden los avisos de volumen sin montar, solo lectura y sucio, y no sale el aviso generico. Anadir `elif errores:` con "no se ha podido comprobar del todo: ver 'errores'" sin tocar el texto actual. |
| L18 `rendimiento_discos` y `qcli_storage` | PARCIAL | BAJA | Cierto que se tira la medicion; impreciso: de `qcli_storage -d` solo sale `puerto` (bahia y modelo vienen de `enclosure_*`). En `rendimiento_discos` (sin tocar `_mapa`, que usan `_discos` y `disco_smart`): detalle y lista con `_extra`, etiquetas `None`, `con_errores`. |
| L19 sudo tumba `red_servicios`/`red_cortafuegos` | CONFIRMADO | BAJA | `en_escucha` e `iptables` con `_opcional`; `qufirewall["reglas"] = None` si `iptables` es un error; agrupar la escucha solo si TCP y UDP se leyeron. Va con M7. |
| L20 convencion de errores en redes | CONFIRMADO (nomenclatura) | BAJA | Explicar en INSTRUCCIONES de redes que el fallo parcial va como `{"error": ...}` en su bloque; renombrar `errores` de `red_interfaces(interfaz=...)` a `contadores_error`. Ajustar `test_redes_parsers.py:169,173`, `test_redes_servidor.py:174,204` y README. |
| L21 `accesos`: todo aviso es "fallido" | Cierto en codigo, no visto | INFORMATIVO | Filtrar solo la 9 dejaria fuera "montar NFS fallido" (7). Filtrar acciones 7 y 9, o aclarar el texto ("avisos de acceso, sobre todo inicios fallidos"). |
| L22 mensajes de parametro | CONFIRMADO | BAJA (cosmetico) | Redes: capturar `ParametroInvalido` en `red_interfaces` y relanzar con "interfaz". Discos: validar `cabina` en `disco_smart` con su nombre. Documentar "de 2 a 40 caracteres" en `eventos`. |
| L23 `todos` con `ok:false` | PARCIAL | INFORMATIVO | El mensaje ya dice que maquinas hay; devolver `ok:true` empeoraria el caso de un nombre mal escrito en un solo NAS. Solo documentarlo en INSTRUCCIONES y docstrings. |
| L24 `dumpxml` fallido sin marca | Cierto solo para `dumpxml` | BAJA | "Sin `meta_path`" es correcto (VM que no es de VS). Plantilla: `x=$(virsh dumpxml $d) \|\| echo '!! dumpxml fallo'; printf '%s\n' "$x" \| grep ...`; `vm_guardadas` lanza `ValueError` con `!! dumpxml fallo` y sigue ignorando `!! sin carpeta` (lo exige una prueba). Prototipo probado en `sh` real; comprobar la guardia y el escape de `\n` en la plantilla Python. |
| L25 ciclo de vida | a y c ciertas; b no verificable | BAJA | Solo `atexit.register(flota.cerrar)` en cada `main()`. NO envolver con `timeout N` (25b): cambia el texto de todas las ordenes, interactua con `sudo sh -c` y no esta probado en BusyBox. 25c se mitiga con M4. |
| L26 concurrencia entre procesos | Mayormente falso positivo | MUY BAJA | Premisa falsa: `SSHClient.save_host_keys` (paramiko 5.0.0, `client.py:138-141`) RECARGA el fichero antes de escribir y fusiona. El comentario de `transporte.py:145` es inexacto (el candado `_FIJANDO` sigue siendo inocuo). Real: `olvidar_host` no fusiona (ventana de microsegundos) y una clave privada de 0 bytes deja `claves.asegurar` fallando para siempre. Arreglo: solo tratar el fichero vacio como inexistente. |
| L27 codigo muerto | CONFIRMADO | BAJA | Borrar `sin_centinela`, `TIPOS["md"]`, `TIPOS["nvme"]` con sus pruebas (`test_comandos.py:185, 217-234`). CONSERVAR `Config.datos` (de el derivan inventario, clave y known_hosts; lo usan pruebas). `/QVS` fijo frente a `Install_Path`: decision del usuario (usar `perfil.paquetes["QKVM"]` exige validarlo en un NAS; o dejar `/QVS` como excepcion documentada y quitar la validacion de ruta del paquete). |
| L28 empaquetado | 2 de 3 | BAJA | Minimo real de `mcp`: 1.7.0 (1.6.0 no tiene `ToolAnnotations` ni `add_tool(annotations=)`; con 1.7.0 pasan las pruebas del servidor) -> `mcp[cli]>=1.7,<2`. `tests/test_paquete.py` redundante con `test_plugin.py`: borrar el literal. LICENSE en el sdist: FALSO POSITIVO (esta, con `License-File: LICENSE`; el wheel la lleva en `dist-info/licenses/`). |
| L29 un fichero SMART vacio anula todos | PARCIAL | BAJA | Reproducido con fichero vacio o linea cortada, pero no es silencioso (`errores.smart` y aviso global). Hoy lo fija a proposito `test_smart_todos_no_inventa_nada_si_no_reconoce_la_salida` (ultimo caso). Si se cambia: aislar por bloque en `smart_todos`, aviso por disco, y en `discos_salud` mover el `continue` de bahia vacia antes de `TEMPERATURA.match`. |
| L30 `dm_estado` con `Fail`/`Error`/`needs_check` | CONFIRMADO contra el kernel | BAJA (cache en `Fail` pesa mas) | `fallo = resto[:1] in (["Fail"], ["Error"])` en thin-pool y cache; `necesita_comprobar = "needs_check" in resto` (no por posicion: QNAP anade marcas propias); avisos en `avisos_de_volumenes`. Ajustar tres igualdades de dict en `test_discos_parsers.py` (~1002, ~1011, ~1031). |
| L31 contenedor `exited` con codigo != 0 | Conducta cierta; decision de diseno | INFORMATIVO | El "minimo" del documento rompe `test_virtualizacion_servidor.py:346` (los dos NAS de referencia tienen un `Exited (137)`). Si se quiere: avisar de codigos distintos de 0, 137 y 143 (los de `docker stop`/kill). |
| L32 `vm_ip` y la segunda direccion | FALSO POSITIVO | descartar | Con `--source arp`, libvirt crea una interfaz por entrada ARP (`naddrs = 1`); `virsh` solo imprime filas `-  -` para la segunda direccion de una misma interfaz. |
| L33 `evt_recuento` con n == 1 | PARCIAL | INFORMATIVO | n == 1 es "cero filas" y es legitimo (lo fija una prueba). En los tres NAS la suma de recuentos cuadra con el id maximo. Solo rechazar "suma 0 con primero o ultimo presentes". |

---

## Orden de arreglo recomendado

1. **H1** (dato falso en el peor momento).
2. **M2 + M3** (nucleo, mismo par de ficheros; arreglan varios sintomas).
3. **M9, M11, M10** (problema real sin aviso o herramienta caida en discos y VMs).
4. **Flota: L10, M4, M5, M8, L11, L14, L15, L12.** L10 primero si se va a reponer la clave de
   nas3 (escribir en el NAS: preguntar antes).
5. **Redes: M7 + L19 juntos, L13, L20, L22.**
6. **Discos menores: L17, L16, L18, L30, L22; L29 solo si se decide cambiar la prueba que lo fija.**
7. **Virtualizacion y logs: M6, L24, L21, L33, L23 (documentar), L31 (opcional).**
8. **Higiene: L28 (`mcp>=1.7`, `test_paquete.py`), L25a (`atexit`), L26 (clave vacia), L27.**

Descartado: L32; el arreglo del documento para L9, L13, L25b y L33; LICENSE (L28); la premisa de
L26.

Necesitan validacion en un NAS cuando se pueda (los arreglos son defensivos y se prueban con
dobles): pool `FAULTED` (M9), VM caida (M10), volumen cifrado bloqueado en hero (M11), cache o
pool ligero en `Fail` (L30).
