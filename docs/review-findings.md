# Revision de codigo: qnap-tools 0.4.4 (main 9012206)

Fecha: 2026-10-15. Metodo: skill `revisa-codigo` (cinco revisores especializados en paralelo:
propagacion de errores, estado y ciclo de vida, paridad entre patas, integridad de datos y
parsers, flujos de uso), mas verificacion a mano de cada hallazgo en el codigo por el
orquestador. Punto de partida sano: `pytest` 2238 passed / 11 skipped, `claude plugin validate .`
pasa (solo avisa de este CLAUDE.md), version 0.4.4 coherente en `__init__.py` y en las cinco
entradas de `plugin.json`.

Este documento es para que OTRO agente lo revise antes de tocar codigo. Cada hallazgo lleva
fichero:linea, el fragmento, un escenario concreto, quien lo encontro (cruce entre revisores)
y una propuesta de arreglo. Lo que se descarto como falso positivo o decision de diseno va al
final, para no volver a abrirlo.

Reglas del proyecto que condicionan los arreglos (CLAUDE.md): TDD (prueba que falla antes del
cambio), solo ASCII en `.py`, nada que escriba en un NAS, `*_log_tool` nunca con sudo, cambios
quirurgicos, y las decisiones ya tomadas por el usuario no se reabren (contrasena antes de la
huella en `nas_alta`, bond0, `zpool history`).

El revisor de parsers y limites ademas paso un fuzz (truncado, lineas borradas, numeros
cambiados por `-`, `N/A`, vacio) a todos los ficheros de `tests/datos/**` contra todos los
parsers: ni un `IndexError`, `KeyError` ni `TypeError`; todo cae en `ValueError`. Y reviso las
~110 plantillas de los cuatro `comandos.py`: ninguna escribe (sin `tee`, `cp`, `mv`, `touch`,
`mkdir`, `sed -i`, `dd`, `>>`; todo `virsh` con `-r -c qemu:///system`; `qemu-img info -U`;
ningun `docker` mutante ni `inspect` sin `--format`; ningun `*_log_tool` con sudo).

---

## Resumen

| Gravedad | Cuantos |
|----------|---------|
| Critica  | 0 |
| Alta     | 1 |
| Media    | 10 |
| Baja     | 22 |

**Valoracion: NEEDS FIXES.** Nada critico: ninguna herramienta puede escribir en un NAS fuera de
las dos de `qnap-flota` ya documentadas y la contrasena no sale por ningun camino (salvo el
matiz del hallazgo 20). Pero hay un dato falso en el peor momento (RAID degradado) y varios
casos en que una caida de conexion o un fichero ilegible se presentan como "no hay".

Orden recomendado de arreglo: 1 (HIGH) -> 2 y 3 (nucleo: una vez cada uno arreglan varios
sintomas) -> 9, 10 y 11 (datos falsos o problema real sin aviso en discos y VMs) -> 4, 5 y 8
(flota) -> 6 y 7 -> los bajos que compartan fichero con lo anterior.

---

## [HIGH] 1. `almacenamiento_resumen` (QTS): si falla la lista de discos, un RAID degradado dice que faltan TODOS los discos del grupo

**Encontrado por**: revisores de errores, paridad y parsers (tres de cinco; los tres lo
reprodujeron con los dobles de prueba). Verificado por el orquestador.

**File**: `src/qnap_tools/discos/servidor.py:449-467` y `:313-342`

**Bug**:
```python
try:
    discos, externos, errores = self._discos(n)
    ...
except servidor.FALLOS_DE_CONSULTA as e:
    discos, externos, resumen = [], [], None
    errores = {"discos": self.ctx.sanear(str(e))}
...
raid = self._raid_qts(n, {corto(d["dispositivo"]): (d["cabina"], d["bahia"])
                          for d in discos + externos})          # <- {} cuando _discos fallo
```
y en `_raid_qts`:
```python
if bahias is None:          # {} no es None: no se vuelve a leer DISCOS_DETALLE
    bahias = {...}
...
cabina, bahia = bahias.get(m["disco"], (None, None))
presentes = {(m["cabina"], m["bahia"]) for m in miembros if not m["fallado"]}   # {(None, None)}
faltan = [x for x in c["miembros"] if (x["cabina"], x["bahia"]) not in presentes] if c and g["degradado"] else []
```
Con el mapa vacio todos los miembros vivos quedan en `(None, None)` y `faltan` devuelve todos
los discos configurados en `raid.conf`. El mismo mecanismo, en parcial: un miembro vivo cuyo
dispositivo no esta en el mapa (disco que no aparece en `enclosure_*.conf`) hace que su entrada
configurada salga como "falta".

**Scenario**: QTS con `md1` degradado (6 de 7). `qcli_storage -d` (30 s) o la lectura de
`enclosure_*` agotan el tiempo porque el NAS esta cargado (justo lo normal con un RAID
reconstruyendose; nas2 ya ha dado cargas de 13-22). El aviso dice "grupo md1 degradado:
6 de varios discos ([UUU_UUU]); falta el disco de la cabina 0, bahia 1 y el de la bahia 2 y ... y
el de la bahia 7". Solo falta uno. `raid_estado` no lo sufre porque pasa `bahias=None`.
El test `test_el_resumen_con_un_grupo_degradado_y_sin_lista_de_discos_avisa_del_grupo` solo
comprueba que aparezca "md1" y "degradado".

**Impact**: sistematico mientras falle la lectura; dato falso en el momento en que alguien
decide que disco sacar. Mitigante: `errores["discos"]` y el aviso generico salen igual.

**Blast radius**: modulo discos.

**Fix propuesto** (dos capas, para que el fallo no dependa del llamador):
1. En `almacenamiento_resumen`, pasar `None` cuando `_discos` fallo:
   ```python
   mapa = None if "discos" in errores else {corto(d["dispositivo"]): (d["cabina"], d["bahia"]) for d in discos + externos}
   raid = self._raid_qts(n, mapa)
   ```
   OJO: con `None`, `_raid_qts` relanza `DISCOS_DETALLE`, que es lo que acaba de fallar; mejor
   que `_raid_qts` acepte "mapa desconocido" sin releer (ver 2).
2. En `_raid_qts`, no afirmar lo que no se sabe: si algun miembro vivo tiene `(None, None)`,
   `faltan = None` y aviso "no se ha podido determinar que disco falta (sin lista de discos)".
   `avisos_md` debe tratar `faltan is None` como "degradado, disco desconocido" y no como lista.
3. Prueba (antes del cambio, debe fallar): resumen de QTS con mdstat degradado y
   `DISCOS_DETALLE` fallando -> el aviso NO contiene "bahia 1 y ... bahia 7"; `faltan is None` o
   el texto dice "no se ha podido determinar". Otra con un miembro vivo fuera del mapa.

---

## [MEDIUM] 2. Un canal SSH cerrado sin codigo de salida se devuelve como `rc=-1, agotado=False`: ni `ErrorConexion` ni reintento, y los validadores que no miran el rc aceptan salida truncada

**Encontrado por**: revisores de errores, estado y flujos (tres de cinco). Verificado: paramiko
5.0.0 `Channel.exit_status_ready()` es `self.closed or self.status_event.is_set()` y
`recv_exit_status()` devuelve -1 si el canal se cerro sin estado.

**File**: `src/qnap_tools/transporte.py:226-251` y `src/qnap_tools/ejecutor.py:29-42, 98-112`

**Bug**: si el transporte muere con la orden en curso (reinicio del NAS, caida de la VPN) o el
proceso remoto muere por senal, el bucle ve `terminada=True` y `sin_mas_salida=True`, sale, y
`ejecutar` devuelve `Resultado(rc=-1, salida_parcial, error, agotado=False)`. `_ejecutar` solo
reintenta con `ErrorConexion`; `_comprobar` solo rechaza rc != 0 cuando el validador lo mira.
- `valida=None` (redes: `BONDING`, `DHCP_SERVIDOR`, `DHCP_LEASES`, `ETHTOOL_STATS`) y
  `valida=no_vacia` (`ETHTOOL`, `NSLOOKUP`, `OCUPACION`, `PING`, `TRACEROUTE`, ...): la salida
  truncada pasa por buena (reproducido: `red_dhcp_dns` da `ok: true, dhcp_servidor: null`).
- `valida=estricta`: sale "la consulta X fallo: el comando termino con codigo -1", que culpa a
  la orden y no a la red, y la conexion muerta sigue en `_conexiones` hasta la siguiente llamada.
- `detectar` (deteccion.py:48) ni mira el rc: una salida cortada tras `firmware=` pasa la guardia
  y se cachea un `Perfil` con `build`, `nombre` y `paquetes` vacios (ver tambien hallazgo 3).

**Scenario**: los dos incidentes ya vividos (reinicio de nas1 el 14-oct; VPN caida a las
05:00 del 14-oct) con una consulta en vuelo.

**Impact**: esporadico; cuando pasa, el dato falso se presenta como real.

**Blast radius**: modulo (todas las patas).

**Fix propuesto**:
1. `transporte.Conexion.ejecutar`: tras el bucle, si `not agotado and rc == -1`:
   - si `self._cli.get_transport() is None or not transport.is_active()` -> `raise ErrorConexion(
     "%s: se perdio la conexion durante la orden")` (entra en el reintento de `_ejecutar`);
   - si el transporte sigue vivo (proceso remoto matado por senal), devolver el `Resultado`
     con rc -1 tal cual.
2. `ejecutor._comprobar`: rc == -1 es siempre error, independientemente de `valida`:
   `raise ErrorComando("%s: la consulta %s termino sin codigo de salida (orden interrumpida)")`.
   Asi `valida=None` sigue significando "el rc distinto de cero es normal", no "cualquier cosa".
3. `deteccion.detectar`: comprobar `r.rc == 0` antes de parsear.
4. Pruebas con `tests/falsos.py`: anadir un doble que devuelva `rc=-1, agotado=False` (hoy solo
   existe `CUELGA`); una prueba por cada capa (transporte lanza `ErrorConexion` si el transporte
   no esta activo; `_comprobar` rechaza rc -1 con `valida=None`; `_ejecutar` reabre una vez).

---

## [MEDIUM] 3. El perfil del NAS se cachea para siempre: tras reconectar, firmware, build, modelo, nombre y paquetes son los viejos

**Encontrado por**: revisores de estado, paridad y flujos. Verificado.

**File**: `src/qnap_tools/ejecutor.py:79-82` (`_soltar`), `:84-95` (`_conexion`), `:114-123` (`perfil`)

**Bug**: el docstring de `perfil` dice "Se detecta una vez por conexion", pero `_perfiles[nombre]`
solo se borra cuando cambia la entrada del inventario o en `olvidar`. `_soltar` (caida, orden
agotada) no lo toca. Solo virtualizacion pasa `refrescar=True`. El test
`test_el_perfil_se_detecta_una_sola_vez` fija el comportamiento actual.

**Scenario**: el usuario actualiza el firmware desde la web y el NAS se reinicia con Claude Code
abierto. La conexion se reabre, pero `nas_comprobar` (flota/servidor.py:139-145),
`almacenamiento_resumen` (discos/servidor.py:446-448) y `sistema_estado` (logs/servidor.py:348,
`modelo`) siguen dando lo viejo. Dentro de `sistema_estado`, `firmware` (leido en vivo) y
`modelo` (cacheado) discrepan. Hay cinco procesos, cada uno con su cache.

**Impact**: sistematico hasta reiniciar Claude Code; `sistema` (hero/qts) no cambia, asi que lo
grave (ordenes por sistema) no se ve afectado salvo reinstalacion.

**Blast radius**: sistema (cinco servidores).

**Fix propuesto**: en `_conexion`, al crear una conexion nueva (`con is None` tras el `get`),
`self._perfiles.pop(nas.nombre, None)`. Cumple el docstring: una deteccion por conexion. Ajustar
el test existente (sigue siendo "una vez por conexion") y anadir uno: tras `ErrorConexion` y
reapertura, `perfil()` vuelve a lanzar `DETECCION`. Alternativa menor: `refrescar=True` en
`nas_comprobar` (es la herramienta de diagnostico), pero no cubre `almacenamiento_resumen`.

---

## [MEDIUM] 4. `nas_comprobar` informa del acceso de la conexion cacheada, leido antes de ejecutar nada, y no avisa cuando un NAS con clave entra por contrasena

**Encontrado por**: revisores de estado y flujos. Verificado.

**File**: `src/qnap_tools/flota/servidor.py:136-147`; `src/qnap_tools/ejecutor.py:138-141`

**Bug**:
```python
datos = {"acceso": flota.metodo(n), "sudo_root": False}   # con.metodo de la conexion que haya
perfil = flota.perfil(n)
...
datos["sudo_root"] = flota.lanzar(n, SUDO_UID).strip() == "0"   # puede reabrir con OTRO metodo
```
`metodo()` no comprueba que la conexion siga viva y se lee antes de la primera orden. Y con
`auth="auto"`, `_conectar` cae de clave a contrasena en silencio: nadie lo marca.

**Scenario** (real, nas3): se rehizo el usuario y se perdio `authorized_keys`. `nas_comprobar`
devolvio `acceso: "contrasena"` y `avisos: []`; solo se detecto porque el modelo comparo con lo
esperado. Al reves: una sesion vieja conserva `acceso: "clave"` aunque una conexion nueva ya no
podria entrar por clave.

**Impact**: sistematico. Es la herramienta cuyo docstring promete "diagnosticar problemas de
acceso".

**Blast radius**: local (`nas_comprobar`).

**Fix propuesto**: en `uno`, leer `acceso = flota.metodo(n)` DESPUES de `perfil` y `lanzar`
(si la conexion estaba muerta ya se ha reabierto). Y anadir aviso:
```python
if n.auth != "contrasena" and acceso == "contrasena":
    avisos.append("este NAS esta configurado para entrar por clave y ha entrado por contrasena: "
                  "la clave de este ordenador no vale alli; nas_enrolar la reinstala")
```
Prueba: inventario `auto`, doble que rechaza la clave y acepta la contrasena -> aviso presente.

---

## [MEDIUM] 5. `_acepta_clave` toma cualquier fallo de conexion por "el NAS no acepta la clave" y el alta lo graba para siempre como `auth="contrasena"`

**Encontrado por**: revisores de flujos y errores. Verificado.

**File**: `src/qnap_tools/flota/servidor.py:102-110`, `:192-197`, `:232-237`

**Bug**:
```python
def _acepta_clave(self, nas):
    con = self.ctx.conexion(dataclasses.replace(nas, auth="clave"))
    try:
        con.conectar(); return True
    except ErrorConexion:      # incluye timeouts, banner, red: no solo AutenticacionFallida
        return False
```
`nas_alta` guarda entonces `Nas(..., auth="contrasena")` con el aviso "el NAS no acepta la
clave SSH de este ordenador". `nas_enrolar` salta los `auth == "contrasena"` (linea 226), asi
que nunca lo reintenta; la unica salida es `nas_baja` + `nas_alta`, y ninguna herramienta ni
skill lo dice.

**Scenario**: `nas_alta` instala bien la clave; la segunda conexion (la prueba) falla por un
corte transitorio. CLAUDE.md documenta que el sshd de nas3 corto conexiones nuevas 1-2 min
tras varios intentos seguidos: es exactamente la situacion del alta (contrasena + clave).

**Impact**: poco frecuente; degradacion permanente y silenciosa (y cada conexion posterior ya no
prueba la clave).

**Blast radius**: local (un NAS).

**Fix propuesto**: tres resultados, no dos:
```python
except AutenticacionFallida: return False        # rechazada: contrasena
except ErrorConexion as e:   return None         # no se pudo probar
```
En `nas_alta`: `None` -> `auth="auto"` (la conexion normal probara clave y caera a contrasena
sola) y aviso "no se pudo comprobar la clave (%s); se probara en la siguiente conexion".
`False` -> como ahora. Lo mismo en `nas_enrolar`. Prueba: doble que lanza `ErrorConexion`
generica en la prueba de clave -> inventario con `auth="auto"`.

---

## [MEDIUM] 6. `alertas_config` entrega los umbrales SMART configurados SIN la marca `no_probado` que si lleva `disco_smart`; `Comando.no_probado` no lo lee nadie

**Encontrado por**: revisor de paridad. Verificado.

**File**: `src/qnap_tools/logs/servidor.py:367` frente a `src/qnap_tools/discos/servidor.py:540`;
`src/qnap_tools/servidor.py:96-101`; `src/qnap_tools/comandos.py:94`

**Bug**: `disco_smart` envuelve `SMART_UMBRALES` con `_no_probado(...)`; `alertas_config` lee la
misma orden con el mismo parser via `_extra(...)` y la entrega como dato validado. El README
dice que los avisos SMART configurados son un bloque `no_probado`. Ademas el campo
`Comando.no_probado` existe pero `Base._no_probado` no lo consulta: la marca se pone a mano en
cada herramienta, y por eso se olvida.

**Scenario**: `alertas_config` en un NAS con avisos SMART por valor: el modelo los presenta como
validados; el formato de `/tmp/smart_warning.conf` nunca se ha visto en un NAS que los use.

**Impact**: sistematico; caracteristica presente en discos y ausente en logs.

**Blast radius**: modulo (logs y discos).

**Fix propuesto**: una sola fuente de verdad. Marcar `SMART_UMBRALES` (y `ISCSI_QTS`) con
`no_probado=True` en `comandos.py`, y en `Base._opcional`/`_extra`/`_leer` anadir
`no_probado: True` al dict devuelto cuando `comando.no_probado` (si el parser devuelve lista,
envolver en `{"filas": ...}` como ya hace `_no_probado`). Dejar `_no_probado` como alias o
retirarlo. Prueba: `alertas_config` -> `datos["smart"]["no_probado"] is True`; y una prueba
generica: todo Comando con `no_probado=True` produce la marca sin que el servidor lo pida.

---

## [MEDIUM] 7. `red_cortafuegos` y `red_acceso_remoto`: `cat ... 2>/dev/null; true` convierte "no se pudo leer" en "lista vacia"

**Encontrado por**: revisores de errores y paridad. Verificado (redes/comandos.py:130-131, 153).

**File**: `src/qnap_tools/redes/comandos.py:126-131` (`BLOQUEO_IP`), `:147-153` (`DDNS`);
`src/qnap_tools/redes/parsers.py:640-644`

**Bug**: es el mismo mecanismo que la revision de la entrega 1 ya quito en otras ordenes
(patron acordado: `[ ! -e f ] || cat f` con `rc_cero`).
```
"; echo ==permitidas; cat /etc/config/ipsec_allow.conf 2>/dev/null"
"; echo ==denegadas; cat /etc/config/ipsec_deny.conf 2>/dev/null; true"
"; echo ==ddns; grep -E '...' $c/ddns.conf 2>/dev/null; true"
```
El parser solo valida el bloque de getcfg; las listas se devuelven tal cual ("en los NAS de
pruebas estaban vacias", dice el comentario: nunca se ha comprobado que se lean de verdad).

**Scenario**: fichero con permisos 600 para el usuario no root, o ruta distinta en una version.
`bloqueo_ip.denegadas: []` con IPs bloqueadas reales; `proveedores_disponibles: 0`.

**Impact**: sistematico en ese NAS; dato de seguridad como "ninguno".

**Blast radius**: modulo redes.

**Fix propuesto**: `; echo ==permitidas; [ ! -e F ] || cat F; echo ==denegadas; [ ! -e G ] || cat G`
sin `; true` y con el validador por defecto (`rc_cero`); lo mismo para `ddns.conf` (en hero la
carpeta viva es `config.local`: ya se resuelve con `$c`). Prueba de shell real como en
`tests/test_virtualizacion_shell.py`: fichero ilegible -> rc != 0 -> `ErrorComando`; fichero
ausente -> rc 0 y lista vacia. Mismo tratamiento para `DHCP_LEASES` (hallazgo 13).

---

## [MEDIUM] 8. Huella de host huerfana en `known_hosts` sin herramienta que la quite: `HostCambiado` manda a `nas_baja`, que exige una entrada de inventario

**Encontrado por**: revisor de flujos (callejon) y revisor de errores (orden en `nas_baja`).
Verificado.

**File**: `src/qnap_tools/flota/servidor.py:242-261` (`nas_baja`), `:282-313`
(`inventario_importar`), `src/qnap_tools/transporte.py:63-75, 161-166`

**Bug**: la huella solo se olvida en `nas_baja` (y en la limpieza del alta fallido). Dos vias
dejan huellas huerfanas:
- `nas_baja` hace `inventario.guardar(...)` ANTES de `transporte.olvidar_host(...)`: si lo
  segundo falla (`PermissionError` con known_hosts abierto por otro proceso en Windows), el NAS
  ya no esta y la huella se queda; repetir `nas_baja` dice "no hay ningun NAS".
- `inventario_importar(sobrescribir=true)` cambia host/port de una entrada sin olvidar la
  huella del host viejo.
Despues, un equipo nuevo en esa IP da `HostCambiado` -> "dalo de baja (nas_baja)" -> "no hay
ningun NAS llamado X". Sin salida con las herramientas del plugin; hay que editar
`~/.claude/plugins/data/qnap-tools-qnap-tools/known_hosts` a mano y el mensaje no da la ruta.

**Impact**: raro, pero sin salida.

**Blast radius**: local.

**Fix propuesto**:
1. `nas_baja`: olvidar la huella ANTES de guardar el inventario (si falla, el NAS sigue dado de
   alta y se puede repetir); o tolerar el fallo y devolverlo como `aviso` con la ruta.
2. `inventario_importar` con `sobrescribir`: si cambian host/port y ningun otro NAS usa el host
   viejo, `olvidar_host` del viejo.
3. Mensaje `HostCambiado`: anadir la ruta de `known_hosts` ("si el NAS ya no esta en el
   inventario, borra a mano la linea de HOST en RUTA").
Pruebas: baja con `olvidar_host` que lanza -> el inventario conserva el NAS; importar con host
cambiado -> `host_fijado(viejo)` es False.

---

## [MEDIUM] 9. `almacenamiento_resumen` (hero) se cae entera cuando un pool no se puede abrir: `zpool list` imprime `-` y `pools()` exige numeros

**Encontrado por**: revisor de parsers (reproducido con el arnes de pruebas). Verificado:
`pools()` usa `_entero` y no `_tamano`, que ya trata `-`/`none` como `None`.

**File**: `src/qnap_tools/discos/parsers.py:405-413`; `src/qnap_tools/discos/servidor.py:457-462`

**Bug**:
```python
return [{"pool": f[0], "bytes": _entero(f[1], "el tamano"), "usado": _entero(f[2], "lo ocupado"),
         "libre": _entero(f[3], "lo libre"), "ocupacion_pct": _entero(f[4].rstrip("%"), "la ocupacion"),
```
Para un pool FAULTED/UNAVAIL (discos perdidos tras un reinicio) `zpool list -H -p` da `-` en
tamano, ocupado, libre, cap y dedup (lectura del codigo de OpenZFS; no visto en un NAS). El
resumen lee `POOLS` con `_leer` DESPUES de haber calculado los avisos de `zpool status`, asi que
el `ValueError` tira la entrada entera y se pierde el aviso "pool X en estado UNAVAIL" que ya
estaba calculado. `raid_estado` no lo sufre (solo `zpool status`).

**Scenario**: `zpool1\t-\t-\t-\t-\t-\tUNAVAIL` -> `ok: false, error: "la consulta pools dio una
salida inesperada: el tamano no es un numero: '-'"`.

**Impact**: sistematico en ese escenario; error opaco en el punto de partida de la flota, justo
con un pool caido.

**Blast radius**: modulo (hero).

**Fix propuesto**: en `pools()` usar `_tamano` para bytes/usado/libre y admitir `-` en
`ocupacion_pct` y `dedup` (`None`); en el resumen, el filtro `ocupacion_pct >= UMBRAL` debe
saltar los `None`. Prueba: fila con guiones -> pool con `salud: "UNAVAIL"` y cifras `None`, aviso
de `_raid_hero` conservado.

---

## [MEDIUM] 10. Una VM apagada por caida (`crashed`) o fallo (`failed`) sale como "apagada" normal, sin aviso

**Encontrado por**: revisor de parsers (reproducido con `estadisticas_con(..., state_state=5,
state_reason=3)` y `=6`). Verificado.

**File**: `src/qnap_tools/virtualizacion/parsers.py:163-165`; `src/qnap_tools/virtualizacion/servidor.py:131-133`

**Bug**: solo se mira `state.reason` para distinguir `SAVED` (5):
```python
if codigo == APAGADA and _numero(c, "state.reason", ...) == GUARDADA:
    estado = "suspendida"
```
`shut off` con motivo 3 (CRASHED) o 6 (FAILED) queda en "apagada", y `avisos_de_vms` solo avisa
si `estado_codigo not in (EN_MARCHA, APAGADA)`. Lo validado en la 0.4.x cubre los estados
(pausa, caida = `state.state` 3 y 6), no los motivos del apagado.

**Scenario**: el invitado hace panic con `on_crash=destroy` o muere el proceso qemu. `vm_lista`
da `apagada`; `virtualizacion_resumen` no avisa. Indistinguible de un apagado a proposito.

**Impact**: problema real silencioso.

**Blast radius**: modulo (`virtualizacion_resumen`, `vm_lista`, `vm_detalle`).

**Fix propuesto**: tabla de motivos de `shut off` (libvirt `virDomainShutoffReason`: 0 unknown,
1 shutdown, 2 destroyed, 3 crashed, 4 migrated, 5 saved, 6 failed, 7 from_snapshot, 8 daemon):
3 -> estado "apagada (caida)" y 6 -> "apagada (fallo al arrancar)", ambos con aviso; el resto
sigue "apagada". Prueba: motivos 3 y 6 -> aviso presente; 0, 1, 2 -> sin aviso. Validar en real
si se puede provocar (una VM de pruebas con `on_crash` y un `echo c > /proc/sysrq-trigger`
dentro del invitado).

---

## [MEDIUM] 11. En hero, un volumen cifrado bloqueado (o sin montar) desaparece del resumen sin aviso; `volumenes` lo da con `clave: unavailable` y tampoco avisa

**Encontrado por**: revisor de parsers (reproducido) y, como nota de diseno, el de errores.
Verificado: `_volumenes_hero` devuelve `clave` por volumen pero no tiene `avisos`.

**File**: `src/qnap_tools/discos/servidor.py:360-392` (`_volumenes_hero`), `:474-492` (resumen)

**Bug**: en hero los volumenes del resumen salen solo de `df -P -k /share/*_DATA`, nunca se
cruzan con `zfs list` (`DATASETS`, que trae `keystatus`). En QTS si existe el aviso equivalente
("no esta montado: esta cifrado y puede estar bloqueado", `avisos_de_volumenes`). Asimetria
entre sistemas, y justo el caso "volumen cifrado bloqueado" que CLAUDE.md da por sin validar.

**Scenario**: se bloquea `zpool1/zfs2`; `keystatus` pasa a `unavailable` y deja de montarse.
`almacenamiento_resumen` no menciona ZFS2 (avisos: solo ocupaciones); `volumenes` lo lista con
`clave: "unavailable"` y `avisos` vacio. Una carpeta inaccesible para los usuarios no genera
nada.

**Impact**: sistematico en ese caso.

**Blast radius**: modulo (hero).

**Fix propuesto**: en el resumen de hero, leer `DATASETS` con `_extra` y avisar de todo dataset
de volumen con `clave == "unavailable"` o que no este entre los montajes de `df`; mismo aviso en
`volumenes`. Prueba: dataset con `keystatus unavailable` ausente de df -> aviso "volumen X no
esta montado: esta cifrado y bloqueado". Esto cierra ademas la nota de diseno sobre `OCUPACION`.

---

## Hallazgos de gravedad baja

### [LOW] 9. `nas_enrolar` deja `auth="auto"` cuando el NAS no acepta la clave
`flota/servidor.py:232-237`. `nas_alta` guarda `contrasena` en ese caso; `nas_enrolar` solo pone
`aviso`. Cada reconexion posterior prueba la clave, falla y cae a contrasena (un intento fallido
por conexion y proceso; la skill avisa del bloqueo por IP de QTS). Fix: actualizar el inventario
como hace el alta (o dejar `auto` a proposito y decirlo en el aviso). Junto con el hallazgo 5.

### [LOW] 10. `nas_enrolar` no admite un NAS concreto: recuperar uno reescribe en todos
`flota/servidor.py:215-240`. `HostSinFijar` y la clave perdida (nas3) remiten a `nas_enrolar`,
que siempre va a `TODOS`: reenvia la contrasena y ejecuta `mkdir/chmod/grep/echo` en
`authorized_keys` de los NAS de produccion que no lo necesitan (idempotente, pero es escritura).
Fix: `nas_enrolar(nas: str = "todos")`, con `por_nas(nas, uno)`. Actualizar skill `enrolar`.

### [LOW] 11. `nas_alta` solo comprueba el nombre, no host:port: el mismo NAS dos veces
`flota/servidor.py:164-167`. `todos` consulta el equipo dos veces. Fix: si `(host, port)` ya esta,
error "ese equipo ya esta en el inventario como X".

### [LOW] 12. `nas_alta` no pasa el `perfil` ni `huella_host` por `_sin_contrasena`
`flota/servidor.py:202-204`. Solo sanea `avisos`; `nas_comprobar` si sanea los mismos campos
(pasa por `por_nas`). Un hostname que contuviera la contrasena llegaria al modelo. Fix:
`return self.ctx.flota._sin_contrasena({...})` o exponer `sanear_datos` en `Contexto`.

### [LOW] 13. `DHCP_LEASES`: `==lineas` sin numero se ignora y el bloque sale como "sin concesiones"
`redes/comandos.py:86-90`, `redes/parsers.py:512-514`. Si `grep -c` falla, `echo ==lineas $(...)`
imprime `==lineas` solo; el parser exige `len(campos) == 2 and isdigit()` y si no, sigue. Con
`valida=None` nada lo detecta. Fix: `==lineas` sin numero -> `ValueError`; y quitar `; true`
(hallazgo 7).

### [LOW] 14. `por_nas` no atrapa los errores de E/S del inventario
`ejecutor.py:165-170`, `inventario.py:63-69`. `cargar` captura `FileNotFoundError` y
`TOMLDecodeError`; `PermissionError`, `IsADirectoryError`, `UnicodeDecodeError` salen de `por_nas`
como excepcion cruda (error de herramienta MCP) en las 36 consultas. Fix: en `cargar`,
`except OSError as e: raise InventarioInvalido("no se pudo leer el inventario %s: %s")`; idem
`UnicodeDecodeError`.

### [LOW] 15. `nas_alta`: `olvidar_host` en el `finally` puede convertir un error normal en excepcion cruda
`flota/servidor.py:207-213`. Si `olvidar_host` lanza (fichero bloqueado), se pierde el
`{"ok": false, "error"}` ya calculado. Fix: `try/except OSError` alrededor, con el motivo en el
error devuelto.

### [LOW] 16. `carpetas_compartidas` pone `nfs_exportadas = 0` y `sin_smb = []` cuando esos bloques fallaron
`discos/servidor.py:646-648`. Las INSTRUCCIONES prometen "sus campos salen sin valor, que no es
lo mismo que cero". Fix: `None` cuando `nfs`/`enlaces` es `None` (ya esta en `errores`).

### [LOW] 17. `almacenamiento_resumen` solo avisa de `errores` en tres claves
`discos/servidor.py:495`. Si fallan `DM_ESTADO`, `LVM_CONF` o `VOLUMENES_CONF`, se omiten en
silencio los avisos de pool ligero en fallo, volumen sucio o solo lectura; solo queda la clave
en `errores`. Fix: `if errores:` -> aviso "no se ha podido comprobar del todo: ver 'errores'".

### [LOW] 18. `rendimiento_discos` pierde la medicion si `qcli_storage -d` agota el tiempo
`discos/servidor.py:677` (`_mapa` con `_leer`). La lista solo aporta etiquetas (puerto, bahia,
modelo) y /proc/diskstats ya esta leido; justo con el NAS cargado (el caso de uso) `qcli_storage`
tarda. Fix: `_extra` y etiquetas `None`.

### [LOW] 19. `red_servicios` y `red_cortafuegos` caen enteras si sudo falla
`redes/servidor.py` (netstat e iptables-save con `_leer`). Se pierden tambien `configurados`,
`bloqueo_ip` y `qufirewall`, que no necesitan sudo. Las demas patas usan `_extra`. Fix: `_extra`
para los bloques con sudo.

### [LOW] 20. Convenciones de error distintas en redes y clave `errores` con otro significado
`redes/servidor.py:19-29, 148`. Redes pone `{"error": ...}` en el sitio del dato y no tiene
`errores`/`avisos`; sus INSTRUCCIONES no lo explican (solo el README). En
`red_interfaces(interfaz=...)`, `errores` son contadores del controlador (datos), el mismo nombre
que en las otras patas significa "no se pudo leer". Fix minimo: explicarlo en INSTRUCCIONES y
renombrar los contadores (`contadores_error`).

### [LOW] 21. `accesos` de tipo aviso cuenta como "intento fallido" cualquier fila
`logs/servidor.py:111-121, 237-248`. `por_origen` agrupa todas las filas `-e 2` por IP/usuario/
servicio sin filtrar por `accion` (9 = inicio fallido). Fix: filtrar `accion == 9` para
`intentos` o renombrar a `avisos_por_origen`. Verificar con datos reales si hay avisos que no
sean fallos de login.

### [LOW] 22. Mensajes de parametro con el nombre interno o el tipo
`redes/servidor.py:289` + `redes/comandos.py:37` ("parametro iface no valido (se esperaba
interfaz)"), `discos/servidor.py:521` ("cabina ... se esperaba bahia"), `comandos.py:28`
(`palabra` exige 2-40 caracteres, sin documentar). Fix: validar en el servidor con el nombre
externo, o que `render` acepte un mapa de nombres; documentar los limites en los docstrings.

### [LOW] 23. `vm_detalle`, `contenedor_detalle` y `contenedor_logs` con `nas="todos"` dan `ok:false` donde el nombre no existe
`virtualizacion/servidor.py:223-247`. Las INSTRUCCIONES dicen "un error no significa 'no hay'",
y aqui si lo significa. Fix: con `todos`, devolver `ok: true, datos: {"encontrada": false}` o
documentar que esas tres son por NAS.

### [LOW] 24. `VM_GUARDADAS` y `VM_SNAP_VS`: una VM cuyo `dumpxml` falla o sin `qvs:meta_path` no escribe nada
`virtualizacion/comandos.py:93-112`, `parsers.py:195`. El bucle `while read` no emite ni la marca
`!!`: esa VM sale "no suspendida" / "sin instantaneas" sin error. Fix: emitir `uuid !!` tambien
cuando `dumpxml` falla o no hay `meta_path`, y que el parser lo apunte en `errores`.

### [LOW] 25. Ciclo de vida del proceso: `Flota.cerrar()` nunca se llama, el timeout no mata la orden remota, `auth=auto` reintenta la clave en cada reconexion
- `ejecutor.py:186-189`: sin `atexit`/`finally` tras `run()`: al cerrar Claude Code, hasta cinco
  sesiones SSH por NAS mueren sin `DISCONNECT` (cierres sucios en `conn.log`). Fix: `atexit`
  o `try/finally` en `main()` de cada pata.
- `transporte.py:255-256`: cerrar el canal no mata el proceso remoto (p. ej. `log_tool` en
  nas2 tras los 40 s). Fix: envolver con `timeout N` si el NAS lo trae (comprobar en
  BusyBox de QTS/hero antes).
- `transporte.py:154-176`: con la clave retirada del NAS, cada proceso y cada reapertura hace un
  publickey fallido antes de la contrasena (5 por arranque). Se mitiga con 4 y 9.

### [LOW] 26. Entre procesos: candado de flota y `_FIJANDO` solo valen dentro de un proceso; `known_hosts` se reescribe truncando
`servidor.py:126`, `transporte.py:24, 111-121`, `flota/servidor.py:102-110`. Dos sesiones de
Claude Code con `nas_alta`/`nas_enrolar` a la vez pueden perder una huella (paramiko guarda
known_hosts entero desde su copia en memoria con `open(..., "w")`); `_acepta_clave` conecta sin
`_FIJANDO`; un lector de otro proceso puede ver el fichero a medias -> `HostSinFijar` falso
(se corrige en la siguiente llamada). Falla cerrado. Si el proceso muere a mitad de la
escritura se pierden las huellas de TODA la flota (se recuperan con `nas_enrolar`). Ademas
`claves.asegurar` (`claves.py:25-36`): si un cierre deja `id_ed25519` vacio, `exists()` es cierto
y `load_ssh_private_key` falla para siempre hasta borrarlo a mano. Fix opcional: candado de
fichero (`msvcrt.locking`/`fcntl`) alrededor de fijar y olvidar host, escritura atomica propia de
known_hosts en vez de `cli.save_host_keys`, y en `asegurar` escribir la privada en temporal +
`os.replace` (o tratar fichero vacio como inexistente con mensaje claro).

### [LOW] 27. Codigo muerto o solo de pruebas
`comandos.py:66` `sin_centinela` (sin llamadores en `src/`); `comandos.py:24-25` `TIPOS["md"]`,
`TIPOS["nvme"]` (ninguna Comando los usa); `config.py:25` `Config.datos` (nunca leido);
`deteccion.py:67-70` valida y guarda la ruta de cada paquete pero nadie la usa (virtualizacion
fija `/QVS/...` en `virtualizacion/comandos.py:14-15, 29`, lo que contradice la regla "rutas de
paquetes de Install_Path, nunca fijas" de CLAUDE.md; funciona porque VS siempre va en /QVS, pero
conviene decidir: usar la ruta del perfil o quitar la validacion). Ver tambien `Comando.no_probado`
en el hallazgo 6.

### [LOW] 29. Un solo fichero SMART vacio (o un bay con temperatura rara) anula el SMART de todos los discos
`discos/parsers.py:206-207` (`_smart`), `:237-253` (`smart_todos`), `:181-184` (`discos_salud`).
Sin aislamiento por disco: `_smart([])` lanza `ValueError` y `smart_todos` lo propaga entero;
`TEMPERATURA.match` se exige incluso en bays vacios. Reproducido con un `smart_0_99.info` vacio:
los varios discos salen con `temperatura: None` y sin avisos SMART propios (queda en `errores`). Un
fichero vacio es plausible: el NAS lo reescribe cada pocos minutos y un disco moribundo puede no
responder. Fix: por disco, `errores["smart"]` con la bahia y `None` solo en ese disco.

### [LOW] 30. `dm_estado`: `Error`/`Fail` de dm-cache y `Error` de thin-pool rompen todo el parseo; `needs_check` se ignora
`discos/parsers.py:954-964`. Solo se reconoce `Fail` en `thin-pool`; una cache en `Fail`/`Error` o
un thin-pool en `Error` (`DMEMIT("Error")` del kernel) da `ValueError` -> `errores.pools_ligeros`
y se pierden todos los pools y la cache. `needs_check` (corrupcion de metadatos) no genera aviso.
Deducido del formato del kernel (dm-thin, dm-cache), no visto en un NAS. Fix: reconocer
`Fail`/`Error` en ambos tipos como estado del pool con aviso, y `needs_check` como aviso.

### [LOW] 31. Un contenedor parado con codigo de salida distinto de cero no genera aviso
`virtualizacion/servidor.py:70, 146-153`. `CONTENEDOR_NORMAL = ("running", "exited", "created")`;
el parser ya extrae `salida` (`Exited (137)`), pero no se usa. Puede ser decision de diseno
(`exited` es normal en trabajos puntuales). Fix minimo: avisar de `exited` con codigo != 0.

### [LOW] 32. `vm_ip` rechaza la segunda direccion de una misma interfaz
`virtualizacion/parsers.py:355`. Exige MAC en cada fila; `virsh domifaddr` imprime `-  -  ipv4 ...`
en las filas sucesivas de una interfaz con varias direcciones (documentacion de libvirt; camino
marcado como sin validar: en los dos NAS `--source arp` sale vacio). Fix: admitir `-` heredando
la MAC de la fila anterior.

### [LOW] 33. `evt_recuento` da por bueno un recuento de 0 cuando `log_tool` solo devuelve `Done`
`logs/parsers.py:208-214`; `logs/comandos.py:41-46`. Solo se rechaza `n == 0`; con `n == 1` (solo
la linea final) se informa `por_gravedad = 0`. El recuento va sin `-l 0 -o N`; CLAUDE.md documenta
que `conn_log_tool` sin esas opciones no devuelve filas con ~850k; no se ha comprobado si
`log_tool` hace lo mismo a partir de algun tamano. Fix barato: contrastar `sum(por_gravedad)` con
`ultimo.id - primero.id + 1` (ya se leen los dos) y marcar error si no cuadra.

### [LOW] 28. Empaquetado
- `pyproject.toml:12` `mcp[cli]>=1,<2`: el codigo usa `ToolAnnotations` y
  `add_tool(annotations=)`, que no existen en los primeros 1.x. Fijar el minimo real (comprobar
  en que 1.x aparecen; el venv tiene 1.30.0).
- `tests/test_paquete.py:6` repite `"0.4.4"` a mano aunque `tests/test_plugin.py` ya coteja
  `plugin.json` con `__version__`: una comprobacion redundante que obliga a tocar dos sitios.
- `sdist.include` no lista `LICENSE`; hatchling lo mete por `license-files`, pero no se ha
  comprobado con `tar tzf` del sdist (no hay `dist/`). Verificar en la proxima publicacion.

---

## Puntos fuertes (lo que esta bien y conviene conservar)

- Lista cerrada de ordenes con plantilla fija, tipos con `fullmatch` y prohibicion de `>` y
  `sudo` en la plantilla; `virsh -r -c qemu:///system` y `docker inspect --format` en todas.
- Candado por NAS reentrante, sin retencion cruzada: no hay interbloqueo posible; `Nas` es
  inmutable y su igualdad completa; la reapertura unica ante `ErrorConexion` es correcta.
- La contrasena se sanea en errores, avisos y DATOS (`_sin_contrasena`), y nunca va en la orden
  (sudo por stdin).
- Inventario con escritura atomica (`mkstemp` + `os.replace`), clave privada con `O_EXCL`,
  limpieza de huella huerfana si el alta falla, duplicado por nombre rechazado antes de conectar.
- `todos` tarda lo que el NAS mas lento, no la suma; un NAS caido da su error sin tapar a los
  demas.
- Anotaciones MCP correctas: solo `nas_lista` y `nas_comprobar` son de solo lectura en flota;
  `nas_baja` e `inventario_importar` destructivas.
- Paridad verificada: version en 6 sitios, scripts frente a `mcpServers` frente a `main()`,
  variables de entorno, ninguna Comando ni parser huerfano, skills con nombres reales.

---

## Notas de diseno (no accionables, para no reabrirlas)

- `OCUPACION` en hero con `df` sin coincidencias (solo cabecera, rc 1) se acepta a proposito
  (comentario en `discos/comandos.py:184-187`). La consecuencia (volumen bloqueado sin aviso)
  esta en el hallazgo 11; la orden en si no hay que tocarla.
- Heuristica de columnas de los registros (descripcion y agente con comas): el revisor de
  parsers no encontro ninguna particion mal elegida; un recurso con comas y varias cifras
  (`/Docs/a,1,2,b.txt`) hace la fila ambigua y rompe `accesos` de ese NAS mientras este en la
  ventana, pero es la decision declarada (fila ambigua = error).
- Desinstalar o reinstalar deja claves publicas `qnap-tools@<equipo>` huerfanas en los NAS; el
  plugin no las borra por diseno (no escribe). Bastaria devolver el comentario de la clave en
  `nas_alta`/`nas_enrolar` y documentar como quitarla a mano.
- Las skills piden cotejar la huella "con la del NAS" sin decir donde verla (consola SSH del
  NAS: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`). Una linea de documentacion.
- El mensaje de sudo rechazado no dice que la contrasena es la de `/plugin configure` ni que los
  servidores en marcha no la releen hasta reiniciar. Una linea.
- Primer arranque: cinco `uvx` descargando a la vez; en la 0.2.0 dos servidores agotaron el
  tiempo en `claude mcp list` sin separar la causa. No verificado; el README podria avisar del
  reintento.
- `Contexto.sanear` lee `_flota` sin candado: benigno.
- `zpool history`/`zfs userspace`, contrasena antes de la huella en `nas_alta`, bond0: decisiones
  del usuario, no se tocan.

---

## Descartado como falso positivo

- Interbloqueo entre `lanzar -> perfil -> detectar`: RLock reentrante, un solo candado por hilo.
- Carrera entre los cinco procesos al generar la clave: solo flota la genera, con `O_EXCL`.
- Reaparicion de un NAS tras `nas_baja` en otro proceso: `por_nas` relee el inventario en cada
  llamada; solo queda una sesion SSH ociosa hasta reiniciar.
- Colision de `_extra` con un parser que devuelva `{"error": ...}`: ningun parser lo hace.
- `Comando.render` con bool/float: rechazados (`type(valor) is int`).
- `huella_host()` devolviendo `None`: inalcanzable tras una conexion correcta.

---

## Segunda revision (independiente)

Fecha: 2026-10-15, sobre el commit 39246ed (codigo 0.4.4). Otro agente, sin acceso a las notas de
los cinco revisores: cada hallazgo se ha cotejado leyendo el fichero y la linea citados y, donde
hacia falta, reproduciendolo en el scratchpad con los dobles de `tests/falsos.py`, con los parsers
sobre salidas escritas a mano o con el `sh` de Git (guion `reproduce.py`, fuera del repositorio).
No se ha tocado `src/` ni `tests/` y no se ha conectado con ningun NAS. Lo que se afirma "por
lectura" no se ha ejecutado; lo que se afirma "reproducido" si.

Veredictos: CONFIRMADO (el bug existe tal como se describe), REFUTADO (no es un bug o la premisa
es falsa), DUDOSO (mecanismo real pero sin prueba de que ocurra, o fix discutible).

### Tabla hallazgo -> veredicto

| N | Hallazgo | Veredicto | Nota |
|---|----------|-----------|------|
| 1 | RAID degradado con mapa vacio: "faltan todos" | CONFIRMADO (reproducido) | Con `DISCOS_DETALLE` fallando el aviso dice "falta el disco de la bahia 1 y ... y el de la bahia 7"; `raid_estado` con el mismo mdstat dice "falta el de la bahia 4". HIGH justificado: `qcli_storage -d` (30 s) es parte de `_mapa` y es lo que se agota con el NAS cargado. |
| 2 | Canal cerrado sin codigo: rc -1 sin `ErrorConexion` | CONFIRMADO (reproducido) | Con un canal falso que cierra sin estado, `ejecutar` devuelve `Resultado(rc=-1, salida parcial, agotado=False)`; `_comprobar` lo acepta con `valida=None` y con `no_vacia`, y con `estricta` culpa a la orden ("codigo -1"). paramiko 5.0.0: `exit_status_ready` es `closed or status_event`, `_set_closed` pone `status_event` y `exit_status` queda en -1. |
| 3 | Perfil cacheado para siempre | CONFIRMADO (lectura) | `_soltar` no toca `_perfiles`; solo `_conexion` (entrada cambiada) y `olvidar`. El test `test_el_perfil_se_detecta_una_sola_vez` no reconecta: el fix no lo rompe. |
| 4 | `nas_comprobar` lee `metodo` antes de lanzar y no avisa de la caida a contrasena | CONFIRMADO (lectura) | `metodo()` devuelve el de la conexion que haya, viva o no; `_conectar` con `auto` pasa de clave a contrasena sin dejar rastro. |
| 5 | `_acepta_clave` toma cualquier `ErrorConexion` por rechazo | CONFIRMADO (lectura) | `except ErrorConexion` cubre `AutenticacionFallida`, `HostCambiado`, `HostSinFijar` y la generica (timeout, banner). Gravedad justa: MEDIA-baja (raro, pero queda grabado). |
| 6 | `alertas_config` sin `no_probado`; `Comando.no_probado` sin lector | CONFIRMADO, gravedad a BAJA | Es una etiqueta: el dato leido es el mismo y el README ya lo declara `no_probado`. No cambia lo que el NAS responde ni lo que el usuario decide. |
| 7 | `cat ... 2>/dev/null; true` en `BLOQUEO_IP` y `DDNS` | CONFIRMADO (lectura) | Mecanismo identico al corregido en la entrega 1. OJO al fix: ver "Matices" (el `grep` sin coincidencias devuelve 1). |
| 8 | Huella huerfana sin herramienta que la quite | CONFIRMADO, gravedad a BAJA | El callejon es real: `nas_alta` tambien falla con `BadHostKeyException` porque `_cliente` carga known_hosts antes de la politica. Pero es raro y los dos arreglos utiles (orden en `nas_baja`, ruta en el mensaje) son triviales. |
| 9 | `pools()` con guiones tira el resumen de hero | CONFIRMADO (reproducido) | `pools("zpool1\t-\t-\t-\t-\t-\tUNAVAIL")` -> `ValueError: el tamano no es un numero: '-'`; `_tamano("-")` ya da `None`. La salida con guiones es la de `zpool_get_prop` de OpenZFS para un pool `POOL_STATE_UNAVAIL` (leido en el codigo, no visto en un NAS). |
| 10 | `shut off` por `crashed`/`failed` sale "apagada" | CONFIRMADO (reproducido) | `state.state=5, state.reason=3` -> `("apagada", 5)` sin aviso. La tabla de motivos del informe es la de libvirt (`virDomainShutoffReason` 0..8). |
| 11 | Volumen cifrado bloqueado invisible en hero | CONFIRMADO (lectura) | `_volumenes_hero` no tiene `avisos`; el resumen de hero solo lee `OCUPACION` (df). En QTS si existe el aviso. |
| L9 | `nas_enrolar` deja `auto` cuando la clave no vale | CONFIRMADO (lectura) | Lineas 232-237: aviso y nada mas. Es una decision (dejar que `auto` lo reintente); lo que falta es decirlo. |
| L10 | `nas_enrolar` siempre a todos | CONFIRMADO (lectura) | `por_nas(inventario.TODOS, uno)`. Reinstalar la clave en un NAS obliga a escribir en todos. |
| L11 | `nas_alta` no comprueba host:port repetido | CONFIRMADO (lectura) | Linea 164: solo el nombre. |
| L12 | `nas_alta` no sanea `perfil` ni `huella_host` | CONFIRMADO (lectura) | Solo `avisos` pasa por `sanear`; `nas_alta` no va por `por_nas`. Mecanismo cierto, caso inverosimil. |
| L13 | `==lineas` sin numero se ignora | CONFIRMADO (reproducido) | `dhcp_concesiones("== dhcpd_br0.leases\n==lineas\n")` -> `{"concesiones": [], "recortado": []}`. |
| L14 | `por_nas` no atrapa E/S del inventario | CONFIRMADO (reproducido) | Inventario que es una carpeta -> `PermissionError` crudo fuera de `por_nas`. |
| L15 | `olvidar_host` en el `finally` de `nas_alta` | CONFIRMADO (lectura) | Una excepcion en `finally` sustituye al `return` del `except`. |
| L16 | `nfs_exportadas = 0` y `sin_smb = []` con el bloque fallido | CONFIRMADO (lectura) | `sum(1 for f in filas if f["nfs"])` con `nfs=None` da 0. La prueba de la linea 723 (`== 0`) es con NFS leido y vacio: no se rompe con el fix. |
| L17 | El resumen solo avisa de tres claves de `errores` | CONFIRMADO (lectura) | Linea 495. Con `LVM_CONF` fallido, `avisos_de_volumenes(conf, None, ...)` calla los umbrales. |
| L18 | `rendimiento_discos` pierde la medida si `qcli_storage` se agota | CONFIRMADO (lectura) | `_mapa` va con `_leer` despues de los 5 s de medida. |
| L19 | `red_servicios`/`red_cortafuegos` caen enteras sin sudo | CONFIRMADO (lectura) | `_leer` de `ESCUCHA_*` e `IPTABLES`; `AutenticacionFallida` es `ErrorConexion` y `por_nas` la convierte en `ok: false`. En redes el patron es `_opcional` (error en el sitio), no `_extra`. |
| L20 | Convenciones de error distintas en redes; `errores` = contadores | CONFIRMADO (lectura) | `red_interfaces(interfaz=...)` devuelve `"errores": ethtool_errores`. Documentacion. |
| L21 | `por_origen` cuenta cualquier fila de aviso como intento fallido | DUDOSO | Mecanismo cierto (no filtra `accion == 9`), pero en los datos reales guardados (pasada por nas3: 2 filas de aviso, las dos accion 9) y en los de prueba no hay ningun aviso que no sea un inicio fallido; el docstring ya dice "sobre todo". Fix barato y sin riesgo: filtrar 9 y dar el resto como `otros`. |
| L22 | Mensajes con el nombre interno del parametro | CONFIRMADO (lectura) | `render` dice "parametro iface ... se esperaba interfaz" y "parametro cabina ... se esperaba bahia". Cosmetico. |
| L23 | `vm_detalle` y companeras con `todos` | CONFIRMADO (lectura) | `_vm`/`_contenedor` lanzan `ParametroInvalido` por NAS. Decision de diseno; documentar en INSTRUCCIONES es suficiente. |
| L24 | `VM_GUARDADAS`/`VM_SNAP_VS` con `dumpxml` roto no escriben nada | CONFIRMADO (reproducido en `sh` real) | Con un virsh de pega cuyo `dumpxml` falla: rc 0 y salida `uri=...\n== <uuid>\n`; el parser da `{uuid: None}` ("no suspendida") sin error. |
| L25 | `cerrar()` nunca se llama; timeout no mata la orden; `auto` reintenta la clave | CONFIRMADO parcial | Lo primero y lo segundo, ciertos por lectura. `timeout N` obligaria a tocar las ~110 plantillas y no se ha comprobado que el BusyBox de QTS/hero lo traiga: no aplicar. Lo tercero es el diseno de `auto`. |
| L26 | Candados solo dentro del proceso; known_hosts truncado; clave privada vacia | CONFIRMADO (lectura, teorico) | `claves.asegurar`: `O_EXCL` + `write` en dos pasos; un fichero vacio hace fallar `load_ssh_private_key` para siempre. Ninguno visto en real. |
| L27 | Codigo muerto; ruta `/QVS` fija | CONFIRMADO (grep) | `sin_centinela`, `TIPOS["md"]`, `TIPOS["nvme"]` y `Config.datos` sin lectores en `src/`; `deteccion` guarda rutas que nadie lee. `/QVS` fijo esta validado en los tres NAS: es una decision, no un bug. |
| L28 | Empaquetado | CONFIRMADO parcial / REFUTADO en parte | `ToolAnnotations` y `add_tool(annotations=)` aparecen en mcp **1.7.0** (comprobado descargando las ruedas 1.6.0 a 1.9.0): el minimo real es `mcp[cli]>=1.7,<2`. **LICENSE: REFUTADO**, el sdist de la 0.4.4 construido en el scratchpad (`pyproject-build --sdist`) lleva `LICENSE` (hatchling lo mete por `license-files`). `test_paquete` redundante: cierto, trivial. |
| L29 | Un fichero SMART vacio anula el SMART de todos | CONFIRMADO (reproducido) | `smart_todos(captura + "== /tmp/smart/smart_0_99.info\n")` -> `ValueError` del bloque 0/99 y `_discos` deja `temperatura: None` en los ocho. `discos_salud` exige `TEMPERATURA` tambien en bahias vacias (linea 181, antes de descartarlas en la 184). |
| L30 | `dm_estado` con `Error`/`Fail` fuera de thin-pool | CONFIRMADO (reproducido) | `thin-pool Error` y `cache Fail` -> `ValueError` (se pierde todo el bloque). `pool_status` de dm-thin y `cache_status` de dm-cache emiten `Fail` y, en sus caminos de error, `Error`. `needs_check` no se mira. No visto en un NAS. |
| L31 | Contenedor `exited` con codigo != 0 sin aviso | CONFIRMADO (lectura) | `salida` se parsea y no se usa. Decision de diseno; el fix minimo puede dar ruido con trabajos puntuales que terminan con codigo distinto de 0. |
| L32 | `vm_ip` rechaza la segunda direccion de una interfaz | CONFIRMADO (reproducido) | La fila ` -  -  ipv6 2001:db8::10/64` da `ValueError`. Es el formato de `cmdDomIFAddr` de virsh (nombre y MAC como `-` en las filas sucesivas). |
| L33 | `evt_recuento` da por bueno 0 con solo `Done` | **REFUTADO** | `n == 1` (solo la linea final) es la cuenta correcta de una gravedad sin eventos: reproducido con el dato real de hero (`error: 0` junto a `informacion: 3720`). La premisa (que `log_tool` sin `-l 0 -o N` deje de dar filas a partir de un tamano) no esta demostrada, y la pasada real por nas3 (47.575 eventos, `eventos_resumen` ok) la contradice a esa escala; lo documentado es de `conn_log_tool` con ~850k. El fix propuesto supone `event_id` contiguos (no comprobado) y podria fabricar errores falsos. No aplicar; como mucho un `aviso` si la suma no cuadra con el intervalo de ids. |

### Cambios de gravedad propuestos

- **6 (alertas_config sin `no_probado`): MEDIA -> BAJA.** Etiqueta de paridad, no un dato falso.
- **8 (huella huerfana): MEDIA -> BAJA.** Caso raro; se arregla con dos lineas (orden en `nas_baja`
  y ruta en el mensaje de `HostCambiado`).
- **33 (recuento de eventos): BAJA -> nota de diseno (REFUTADO).**
- **28 (LICENSE en el sdist): REFUTADO** (comprobado con el sdist real); el resto del 28 se queda.
- El resto conserva la gravedad asignada. El 1 merece la HIGH: `qcli_storage -d` forma parte de
  `_mapa` y es la orden que se agota con el NAS cargado, que es justo cuando hay un RAID
  reconstruyendose.

### Matices sobre los arreglos propuestos

- **1.** Mejor que el fix 1 del informe (pasar `None` y que `_raid_qts` relea `DISCOS_DETALLE`, que
  acaba de fallar): que `_raid_qts(n, bahias)` NUNCA lea el mapa, y que `raid_estado` lo lea con
  `_extra` (asi `raid_estado` tambien degrada en vez de caer entero). En `_raid_qts`, si algun
  miembro vivo queda en `(None, None)`, `faltan = None`; `avisos_md` con `faltan is None` dice
  "degradado; no se ha podido determinar que disco falta (sin lista de discos)". Esto cubre
  tambien el caso parcial (un miembro vivo que no esta en `enclosure_*.conf`). Hay que cambiar el
  test `test_el_resumen_con_un_grupo_degradado_y_sin_lista_de_discos_avisa_del_grupo` para que
  exija ese texto y rechace "bahia 1".
- **2.** Fix correcto. Detalles: `ClienteFalso.get_transport()` devuelve el propio cliente y no
  tiene `is_active()`: anadirselo al doble (y una opcion `canal_sin_codigo`) antes del cambio en
  `transporte`. En `_comprobar`, rc -1 con `agotado=False` como `ErrorComando` propio ("termino sin
  codigo de salida") es lo que toca: `valida=None` sigue significando "rc distinto de 0 es normal".
  `detectar` debe exigir `r.rc == 0` (hoy ni lo mira): con la salida cortada tras `firmware=` pasa
  la guardia.
- **3.** `self._perfiles.pop(nas.nombre, None)` al crear la conexion en `_conexion`. No rompe el
  test existente. Anadir el test de reapertura con `mundo.cortar()`.
- **4.** Fix correcto. El aviso propuesto (`n.auth != "contrasena" and acceso == "contrasena"`)
  es exactamente el caso real de nas3.
- **5.** Fix correcto (tres resultados). Con `None` -> `auth="auto"`: `_metodos` ya cae a contrasena
  si la clave no se puede leer, asi que no hay bucle. Lo mismo en `nas_enrolar` (L9): si se decide
  dejar `auto`, que el aviso lo diga ("se seguira probando la clave en cada conexion").
- **6.** No hace falta rehacer `_no_probado`: basta que `_opcional` (y por tanto `_extra`) anada
  `no_probado: True` cuando `comando.no_probado` y el parser devuelve un dict. `smart_umbrales`
  devuelve dict, asi que la prueba de la linea 593 de `test_logs_servidor` (`d["smart"]["avisos"]`)
  sigue pasando. Marcar `SMART_UMBRALES` con `no_probado=True` en `discos/comandos.py`.
- **7 y L13.** El patron `[ ! -e f ] || grep ... f` con `rc_cero` tiene una trampa que `cat` no
  tiene: `grep` termina con 1 cuando el fichero existe y no hay coincidencias (reproducido en el
  `sh` de Git). En `DDNS` el patron lleva `^\[`, asi que cualquier INI con una seccion casa; pero
  un `ddns.conf` sin secciones (solo comentarios, o vacio con `-e`) daria un error falso. Usar
  `[ ! -s f ]` (no `-e`) y mantener `^\[` en el patron, o cerrar con `|| [ $? -eq 1 ]`. Para
  `DHCP_LEASES`: `==lineas` sin numero -> `ValueError` en el parser, y quitar el `; true`.
- **8.** Fix 1 (olvidar la huella ANTES de guardar) deja, si falla `guardar`, un NAS en el
  inventario sin huella: `HostSinFijar` -> `nas_enrolar` la vuelve a fijar. Recuperable, mejor que
  hoy. Fix 3 (ruta en el mensaje) es el que de verdad quita el callejon. Fix 2 (importar con
  `sobrescribir`) es opcional.
- **9.** Ademas de `_tamano` en tres columnas: `_veces` tambien rechaza `-` (dedup) y el filtro
  `ocupacion_pct >= UMBRAL` del resumen tiene que saltar `None`.
- **10.** Que el estado siga con `estado_codigo` 5 (asi `con_proceso` y la suma de memoria no
  cambian) y el aviso salga del motivo, no del codigo. `con_memoria_guardada` compara `estado ==
  "suspendida"`: no le afecta.
- **11.** Correcto; anade una lectura de `zfs list` al resumen de hero (30 s de tope, rapida en la
  practica).
- **L16.** `None` en los dos campos cuando su bloque es `None`. La prueba 723 no se rompe.
- **L19.** En redes, `_opcional` (error en el sitio), que es su convencion; no `_extra`.
- **L28.** `mcp[cli]>=1.7,<2`. No tocar `sdist.include` por LICENSE: ya va.
- **L31.** Si se aplica, limitar el aviso a `exited` con codigo != 0 y mantener `exited` 0 como
  normal; aceptar que un trabajo puntual que falla a proposito dara aviso.
- Ninguno de los arreglos recomendados escribe en un NAS, usa sudo donde no lo habia, ni reabre
  una decision del usuario (contrasena antes de la huella, bond0, `zpool history`). Todos van con
  TDD y ASCII.

### Sobre `docs/review-patterns.md`

Los doce patrones estan bien formulados y los doce se han visto en este codigo. Dos anadidos:
- **Patron 1**: el patron correcto `[ ! -e f ] || cat f` NO se traslada tal cual a `grep`: `grep`
  devuelve 1 sin coincidencias y `rc_cero` lo tomaria por fallo. Con `grep`, o el patron casa
  cualquier fichero no vacio (`^\[` en un INI) y se guarda con `-s`, o se cierra con
  `|| [ $? -eq 1 ]` (2 = error de lectura sigue siendo error).
- **Patron 3**: el doble de prueba (`ClienteFalso.get_transport()`) tiene que ofrecer `is_active()`
  para que la regla "transporte inactivo = `ErrorConexion`" sea comprobable.
- Y una matizacion al **patron 1** por el hallazgo 33: "vacio" no siempre es "no se pudo leer";
  cuando la utilidad imprime su linea de cierre (`Done`), vacio con cierre ES "no hay". No convertir
  eso en error sin una prueba de que la utilidad miente.

### Arreglos recomendados en orden

1. **H1** `discos/servidor.py`: `_raid_qts` sin releer; mapa desconocido -> `faltan = None` y aviso
   "no se ha podido determinar"; `raid_estado` lee el mapa con `_extra`. Test nuevo + ajustar el
   existente.
2. **H2** `transporte.ejecutar` (rc -1 con transporte inactivo -> `ErrorConexion`), `ejecutor._comprobar`
   (rc -1 siempre `ErrorComando`), `deteccion.detectar` (exigir rc 0); doble `canal_sin_codigo` e
   `is_active()` en `tests/falsos.py`.
3. **H9** `pools()` con `_tamano`/`None` en tamanos, ocupacion y dedup; filtro del resumen tolerante.
4. **H10** tabla de motivos de `shut off` en `virtualizacion/parsers.py` y aviso por motivo 3 y 6.
5. **H3** `_perfiles.pop` al crear conexion en `Flota._conexion`.
6. **H4** `nas_comprobar`: `acceso` despues de lanzar; aviso clave->contrasena.
7. **H11** resumen y `volumenes` de hero: aviso por dataset de volumen con `keystatus unavailable` o
   ausente de df.
8. **H7 + L13** `BLOQUEO_IP`, `DDNS`, `DHCP_LEASES` sin `2>/dev/null; true`, con la trampa del
   `grep` resuelta; prueba en `sh` real.
9. **H5 + L9** `_acepta_clave` con tres resultados; aviso explicito en `nas_enrolar`.
10. **L16, L17, L18, L14** (discos y ejecutor, cambios de una o dos lineas cada uno).
11. **L29, L30, L32, L24** (parsers: aislamiento por disco, `Error`/`Fail`/`needs_check`, segunda
    direccion, `!!` cuando `dumpxml` falla).
12. **H8 (fixes 1 y 3) + L15** en `flota/servidor.py` y `transporte.py`.
13. **H6 como baja**: `no_probado` aplicado por `_opcional`; `SMART_UMBRALES` marcada.
14. **L28** `mcp[cli]>=1.7,<2`; quitar la cadena fija de `test_paquete`.
15. Documentar o decidir, sin prisa: L10, L11, L19, L20, L21, L22, L23, L25, L26, L27, L31.
16. **No aplicar**: L33 (refutado), la parte de LICENSE del L28, y `timeout N` del L25.
