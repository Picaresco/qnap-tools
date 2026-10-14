# Qnap-Tools, entrega 1: base y redes. Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dejar instalable en local el plugin `qnap-tools` con el núcleo común, el servidor de
administración `qnap-flota` y el servidor `qnap-redes` con sus 9 herramientas de solo lectura.

**Architecture:** un paquete Python (`src/qnap_tools`) con un núcleo compartido (configuración,
inventario, transporte SSH, comandos de plantilla fija, detección del sistema, ejecutor) y un
subpaquete por servidor MCP. Cada servidor es un entry point de consola que el plugin lanza con
`uvx`; la credencial llega por variables de entorno desde el `userConfig` del plugin.

**Tech Stack:** Python >= 3.11, `mcp[cli]>=1,<2` (FastMCP), `paramiko>=3.4`, `cryptography`
(ya dependencia de paramiko), `hatchling`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-13-qnap-tools-design.md`

## Global Constraints

- Python: solo ASCII en comentarios y cadenas; `# -*- coding: utf-8 -*-`; `open(..., encoding="utf-8")`.
- Venv del proyecto en `.venv`; ejecutar siempre con `.venv\Scripts\python.exe`.
- `mcp[cli]>=1,<2` (mcp 2.0 elimina `mcp.server.fastmcp`).
- Ningún comando libre: todo lo que se ejecuta en un NAS sale de un `Comando` definido en código.
- La contraseña nunca se escribe en disco, en un log ni en un mensaje de error.
- Nunca degradar en silencio: un fallo devuelve `{"ok": false, "error": ...}`, no datos vacíos.
- Utilidades de log sin `sudo`; `virsh` con `-r -c qemu:///system`; `qcli_storage` sin `sudo`.
- No versionar: `.env`, `pruebas/claves/`, `pruebas/resultados/`, `CLAUDE.md`, `.remember/`, `.claude/`, `.venv/`.
- Los ficheros de prueba (`tests/datos/`) no llevan IP, MAC, nombres ni series reales: se
  sustituyen por valores de ejemplo (`192.0.2.x`, `00:11:22:33:44:5x`, `NAS-EJEMPLO`).
- Pruebas contra un NAS real: solo `nas1`, y solo con `QNAP_TOOLS_PRUEBA_REAL=1`.
- Commits pequeños, uno por tarea como mínimo. No hacer `git push` ni publicar en esta entrega.

## Review Focus

1. Parámetro con metacaracteres de shell (`eth0; reboot`, `$(x)`, comillas) en `red_interfaces`
   o `red_diagnostico`: se rechaza antes de conectar. Prueba en la tarea 4.
2. NAS inalcanzable o con credencial errónea dentro de `nas="todos"`: los demás NAS responden y
   ese devuelve su error. Prueba en la tarea 7.
3. Comando que devuelve código 0 y salida vacía: error explícito. Prueba en la tarea 4 y 7.
4. Clave de host cambiada respecto a la fijada en el alta: conexión rechazada con mensaje claro,
   sin caer a contraseña. Prueba en la tarea 5.
5. Nombre de NAS que no está en el inventario: error que lista los nombres válidos. Prueba en
   la tarea 7.

---

## Estructura de ficheros

```
pyproject.toml                      paquete, dependencias, entry points
README.md                           instalacion y uso
.claude-plugin/plugin.json          manifiesto y userConfig
.claude-plugin/marketplace.json     marketplace con source "./"
.mcp.json                           los servidores MCP del plugin
skills/alta/SKILL.md                guia para dar de alta un NAS (usa qnap-flota)
skills/enrolar/SKILL.md             guia para enrolar un ordenador nuevo
src/qnap_tools/__init__.py          version
src/qnap_tools/config.py            entorno y rutas de datos
src/qnap_tools/inventario.py        lista de NAS (TOML)
src/qnap_tools/comandos.py          Comando, tipos de parametro, validadores de salida
src/qnap_tools/transporte.py        conexion SSH, sudo, clave de host
src/qnap_tools/deteccion.py         perfil del NAS (sistema, modelo, firmware, paquetes)
src/qnap_tools/ejecutor.py          ejecuta un Comando en uno o todos los NAS
src/qnap_tools/servidor.py          fabrica de servidores FastMCP
src/qnap_tools/flota/servidor.py    herramientas de administracion
src/qnap_tools/redes/comandos.py    comandos de la pata de redes
src/qnap_tools/redes/parsers.py     texto del NAS -> estructuras
src/qnap_tools/redes/servidor.py    las 9 herramientas
tests/                              una carpeta por modulo, mas tests/datos/
```

---

### Task 1: comprobar la mecánica del plugin con un plugin mínimo

Reduce el riesgo antes de construir: todo lo demás depende de que la credencial llegue al servidor.

**Files:**
- Create: `ensayo/plugin-minimo/.claude-plugin/plugin.json`, `ensayo/plugin-minimo/.claude-plugin/marketplace.json`, `ensayo/plugin-minimo/.mcp.json`, `ensayo/plugin-minimo/eco.py`

- [ ] **Step 1:** escribir `eco.py`, un servidor FastMCP con una herramienta `eco()` que devuelve
  `{"usuario": os.environ.get("QNAP_TOOLS_USER"), "hay_contrasena": bool(os.environ.get("QNAP_TOOLS_PASSWORD")), "longitud": len(...), "datos": os.environ.get("QNAP_TOOLS_DATA"), "plugin_data": os.environ.get("CLAUDE_PLUGIN_DATA")}`. Nunca devuelve la contraseña.
- [ ] **Step 2:** `plugin.json` con `name: "ensayo-qnap"` y `userConfig`:
  `ssh_user` (`type: string`, `title`, `description`, `required: true`) y `ssh_password`
  (igual, con `sensitive: true`).
- [ ] **Step 3:** `.mcp.json` con un servidor `eco`: `command: "uv"`, `args: ["run", "--with", "mcp[cli]~=1.0", "${CLAUDE_PLUGIN_ROOT}/eco.py"]`, `env` con `QNAP_TOOLS_USER: "${user_config.ssh_user}"`, `QNAP_TOOLS_PASSWORD: "${user_config.ssh_password}"`, `QNAP_TOOLS_DATA: "${CLAUDE_PLUGIN_DATA}"`.
- [ ] **Step 4:** instalar: `claude plugin marketplace add ./ensayo/plugin-minimo` y
  `claude plugin install ensayo-qnap@<marketplace>`. El usuario lo activa y teclea valores de prueba.
- [ ] **Step 5:** llamar a `eco` y anotar en `CLAUDE.md`: si llegan usuario, contraseña y carpeta
  de datos; si la ruta de datos existe; cómo se cambia después la contraseña (probar `/plugin` y
  desactivar/activar).
- [ ] **Step 6:** desinstalar el plugin de ensayo y borrar `ensayo/`. Las notas quedan en
  `CLAUDE.md`, que no se versiona; si algo contradice el diseño, corregir tambien la spec.

**Criterio de salida:** los tres valores llegan al proceso. Si no llegan, PARAR y replantear el
paso de credenciales antes de seguir.

---

### Task 2: esqueleto del paquete

**Files:**
- Create: `pyproject.toml`, `src/qnap_tools/__init__.py`, `tests/test_paquete.py`, `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Produces: paquete importable `qnap_tools` con `__version__ = "0.1.0"`; entry points
  `qnap-tools-flota = qnap_tools.flota.servidor:main` y `qnap-tools-redes = qnap_tools.redes.servidor:main`.

- [ ] **Step 1:** `git init`; ampliar `.gitignore` con todo lo de "No versionar".
- [ ] **Step 2:** prueba `test_version`: `import qnap_tools; assert qnap_tools.__version__ == "0.1.0"`.
  Ejecutar `pytest tests/test_paquete.py -v`: falla (módulo inexistente).
- [ ] **Step 3:** `pyproject.toml` (hatchling, `requires-python = ">=3.11"`, dependencias
  `mcp[cli]>=1,<2`, `paramiko>=3.4`; extra `dev` con `pytest`), `__init__.py`.
  `pip install -e ".[dev]"` en el venv. La prueba pasa.
- [ ] **Step 4:** commit `chore: esqueleto del paquete qnap-tools`.

---

### Task 3: configuración e inventario

**Files:**
- Create: `src/qnap_tools/config.py`, `src/qnap_tools/inventario.py`, `tests/test_config.py`, `tests/test_inventario.py`

**Interfaces:**
- Produces:
  - `config.Config` (dataclass): `usuario: str`, `contrasena: str`, `datos: Path`,
    `inventario: Path`, `clave: Path`, `known_hosts: Path`.
  - `config.cargar(entorno: Mapping[str, str] = os.environ) -> Config`. Lee `QNAP_TOOLS_USER`,
    `QNAP_TOOLS_PASSWORD`, `QNAP_TOOLS_DATA` (si falta, `CLAUDE_PLUGIN_DATA`; si falta,
    `~/.qnap-tools`), `QNAP_TOOLS_INVENTARIO` (si falta, `<datos>/inventario.toml`). Lanza
    `ConfigError` si faltan usuario o contraseña. `repr(Config)` no muestra la contraseña.
  - `inventario.Nas` (dataclass): `nombre: str`, `host: str`, `port: int = 22`,
    `user: str | None = None`, `auth: str = "auto"` (`auto` | `clave` | `contrasena`).
  - `inventario.cargar(ruta: Path) -> dict[str, Nas]` (fichero inexistente = `{}`).
  - `inventario.guardar(ruta: Path, nas: dict[str, Nas]) -> None`.
  - `inventario.resolver(nas: dict[str, Nas], nombre: str) -> list[Nas]`: `"todos"` devuelve
    todos por orden alfabético; un nombre desconocido lanza `NasDesconocido` con los válidos.
  - `inventario.NOMBRE_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")`.

- [ ] **Step 1:** pruebas de `config`: faltan credenciales -> `ConfigError`; precedencia de
  `QNAP_TOOLS_DATA` sobre `CLAUDE_PLUGIN_DATA`; `"secreto" not in repr(cfg)`.
- [ ] **Step 2:** ejecutar, ver fallar, implementar `config.py`, ver pasar.
- [ ] **Step 3:** pruebas de `inventario` con `tmp_path`: ida y vuelta guardar/cargar con
  campos opcionales; fichero inexistente; `resolver("todos")` ordenado; `resolver("nope")`
  lanza `NasDesconocido` y su mensaje contiene los nombres válidos; nombre `"Mal Nombre"` y
  host `"a b"` rechazados al guardar; puerto fuera de 1-65535 rechazado.
- [ ] **Step 4:** implementar: lectura con `tomllib`, escritura con un emisor propio (tablas
  `[nas.<nombre>]`, cadenas con `json.dumps`), escritura atómica (fichero temporal + `os.replace`).
- [ ] **Step 5:** `pytest tests/test_config.py tests/test_inventario.py -v` en verde. Commit
  `feat: configuracion e inventario`.

---

### Task 4: comandos de plantilla fija

**Files:**
- Create: `src/qnap_tools/comandos.py`, `tests/test_comandos.py`

**Interfaces:**
- Produces:
  - `comandos.TIPOS: dict[str, re.Pattern]` con, como mínimo:
    `interfaz` `^[A-Za-z0-9_.@:-]{1,32}$`, `destino` `^[A-Za-z0-9]([A-Za-z0-9.:-]{0,251}[A-Za-z0-9])?$`,
    `entero` `^[0-9]{1,6}$`, `bahia` `^[0-9]{1,3}$`, `uuid` (formato UUID), `nombre`
    `^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`, `fecha` `^[0-9]{4}-[0-9]{2}-[0-9]{2}$`.
  - `comandos.Comando` (dataclass congelada): `id: str`, `plantilla: str` (con `{param}`),
    `params: dict[str, str] = {}` (nombre -> tipo), `sudo: bool = False`, `timeout: int = 20`,
    `sistema: str = "ambos"` (`ambos` | `hero` | `qts`), `valida: Callable[[int, str], str | None] | None = None`,
    `no_probado: bool = False`.
  - `Comando.render(valores: dict[str, str]) -> str`: valida cada valor contra su tipo y lo
    sustituye pasado por `shlex.quote`. Lanza `ParametroInvalido` si falta, sobra o no casa.
  - Validadores: `no_vacia(rc, salida)`, `rc_cero(rc, salida)`, `sin_centinela(*centinelas)`.
    Devuelven `None` si la salida vale o el texto del error.

- [ ] **Step 1:** pruebas:
  - `Comando("x", "ip -s link show {iface}", {"iface": "interfaz"}).render({"iface": "eth0"}) == "ip -s link show eth0"`.
  - Cada uno de `"eth0; reboot"`, `"$(reboot)"`, `"eth0 && x"`, `"a'b"`, `"a b"`, `""`,
    una cadena de 300 caracteres -> `ParametroInvalido`.
  - Parámetro que falta y parámetro de más -> `ParametroInvalido`.
  - `no_vacia(0, "") is not None`; `no_vacia(0, "x") is None`; `rc_cero(1, "x") is not None`;
    `sin_centinela("0 C", "--")(0, "0 C") is not None`.
  - Una plantilla que contiene `sudo` lanza `ValueError` al crear el `Comando` (el `sudo` lo
    pone el transporte).
- [ ] **Step 2:** ver fallar, implementar, ver pasar. Commit `feat: comandos de plantilla fija`.

---

### Task 5: transporte SSH

**Files:**
- Create: `src/qnap_tools/transporte.py`, `tests/test_transporte.py`, `tests/falsos.py`

**Interfaces:**
- Consumes: `config.Config`, `inventario.Nas`.
- Produces:
  - `transporte.Resultado` (dataclass): `rc: int`, `salida: str`, `error: str`, `agotado: bool`.
  - `transporte.Conexion(nas: Nas, cfg: Config, fabrica=paramiko.SSHClient)`:
    - `conectar(fijar_host: bool = False) -> str`: devuelve `"clave"` o `"contrasena"`. Orden
      según `nas.auth`: `auto` intenta clave (si existe el fichero) y luego contraseña.
      Clave de host: carga `cfg.known_hosts`; con `fijar_host=False` usa `RejectPolicy`; con
      `True` añade la clave nueva y la guarda. Una clave de host distinta de la fijada lanza
      `HostCambiado` y NO se intenta la contraseña.
    - `ejecutar(orden: str, sudo: bool = False, timeout: int = 20) -> Resultado`: con `sudo`
      envuelve en `sudo -S -p '' sh -c <shlex.quote(orden)>` y escribe la contraseña y un salto
      de línea por stdin. Quita del stderr el aviso inicial de `sudo`. Al vencer el tiempo
      cierra el canal y devuelve `agotado=True`.
    - `cerrar()`.
  - Excepciones: `ErrorConexion(mensaje)`, `HostCambiado`, `AutenticacionFallida`. Ningún
    mensaje incluye la contraseña.
  - `tests/falsos.py`: `ClienteFalso`, un sustituto de `paramiko.SSHClient` que registra las
    órdenes recibidas y devuelve salidas programadas; reutilizado por las tareas 6 a 10.

- [ ] **Step 1:** pruebas con `ClienteFalso`:
  - con `auth="auto"` y clave rechazada (`AuthenticationException`) cae a contraseña y devuelve `"contrasena"`;
  - con `auth="clave"` y clave rechazada lanza `AutenticacionFallida`;
  - con `nas.user = "otro"` la conexion usa `otro`; sin el, `cfg.usuario`;
  - `ejecutar("id", sudo=True)` envía `sudo -S -p '' sh -c id` y escribe la contraseña en stdin;
  - `ejecutar("id")` no escribe nada en stdin;
  - una `BadHostKeyException` se convierte en `HostCambiado` y no hay segundo intento;
  - el texto de cualquier excepción lanzada no contiene la contraseña;
  - tiempo agotado -> `Resultado.agotado is True`.
- [ ] **Step 2:** ver fallar, implementar, ver pasar.
- [ ] **Step 3:** prueba real opcional (`@pytest.mark.skipif(os.environ.get("QNAP_TOOLS_PRUEBA_REAL") != "1")`):
  conectar a `nas1` leyendo host y credencial del `.env`, ejecutar `id` con y sin `sudo` y
  comprobar `uid=0` solo con `sudo`. Ejecutarla una vez a mano.
- [ ] **Step 4:** commit `feat: transporte SSH con sudo y clave de host fijada`.

---

### Task 6: detección del sistema

**Files:**
- Create: `src/qnap_tools/deteccion.py`, `tests/test_deteccion.py`, `tests/datos/deteccion_hero.txt`, `tests/datos/deteccion_qts.txt`

**Interfaces:**
- Consumes: `transporte.Conexion`.
- Produces:
  - `deteccion.Perfil` (dataclass): `sistema: str` (`hero` | `qts`), `modelo: str`,
    `firmware: str`, `build: str`, `nombre: str`, `paquetes: dict[str, str]` (nombre -> `Install_Path`
    de los activos: `QKVM`, `container-station`).
  - `deteccion.detectar(con: Conexion) -> Perfil`: UNA sola orden que imprime líneas `clave=valor`:
    `sistema` por `[ -x /sbin/zpool ]`, modelo, versión y build con `getcfg ... -f /etc/default_config/uLinux.conf`,
    nombre con `hostname`, y por cada paquete `Enable` e `Install_Path` de `/etc/config/qpkg.conf`.
    Lanza `DeteccionFallida` si falta `sistema` o `firmware`.

- [ ] **Step 1:** ficheros de datos con la salida esperada para un QuTS hero y un QTS (valores
  de ejemplo). Pruebas: `detectar` devuelve `sistema == "hero"` y `"qts"`; paquete con
  `Enable=FALSE` no entra en `paquetes`; salida vacía -> `DeteccionFallida`.
- [ ] **Step 2:** ver fallar, implementar, ver pasar. Commit `feat: deteccion del sistema del NAS`.

---

### Task 7: ejecutor

**Files:**
- Create: `src/qnap_tools/ejecutor.py`, `tests/test_ejecutor.py`

**Interfaces:**
- Consumes: `Config`, `inventario`, `Comando`, `Conexion`, `detectar`.
- Produces:
  - `ejecutor.Flota(cfg: Config, fabrica_conexion=Conexion)`:
    - `perfil(nas: Nas) -> Perfil` (detecta una vez y guarda).
    - `lanzar(nas: Nas, comando: Comando, valores: dict[str, str] = {}) -> str`: devuelve la
      salida. Lanza `ErrorComando(mensaje)` si el comando no vale para el sistema del NAS, si
      vence el tiempo, o si `comando.valida` devuelve un error. Un candado por NAS serializa
      las órdenes; la conexión se reutiliza y se reabre una vez si se ha caído.
    - `por_nas(nombre: str, funcion: Callable[[Nas], Any]) -> list[dict]`: resuelve `nombre`
      (`todos` o uno), ejecuta `funcion` por NAS en un `ThreadPoolExecutor(max_workers=4)` y
      devuelve, por NAS, `{"nas": n, "ok": True, "datos": ...}` o
      `{"nas": n, "ok": False, "error": "<texto>"}`. Captura `ErrorConexion`, `ErrorComando`,
      `ParametroInvalido` y `NasDesconocido`; cualquier otra excepción también se convierte en
      error con el nombre de su clase.
    - `cerrar()`.
  - `ejecutor.recortar(filas: list, maximo: int = 200) -> dict`: devuelve
    `{"filas": filas[:maximo], "total": len(filas), "truncado": len(filas) > maximo}`. Lo usan
    las herramientas que devuelven listas largas (vecinos, puertos, reglas, MAC).

- [ ] **Step 1:** pruebas con `ClienteFalso` e inventario de dos NAS:
  - `recortar(list(range(300)), 200)` devuelve 200 filas, `total == 300` y `truncado is True`;
    con 10 filas, `truncado is False`;
  - `por_nas("todos", f)` devuelve dos entradas en orden alfabético;
  - si un NAS lanza `ErrorConexion`, su entrada es `ok: False` y la del otro `ok: True`;
  - `por_nas("nope", f)` devuelve una sola entrada `ok: False` cuyo error lista los nombres válidos;
  - comando `sistema="hero"` contra un perfil `qts` -> `ErrorComando` que lo dice;
  - comando con `valida=no_vacia` y salida vacía -> `ErrorComando`;
  - dos `lanzar` seguidos al mismo NAS abren una sola conexión;
  - `Resultado.agotado` -> `ErrorComando` que menciona el tiempo máximo.
- [ ] **Step 2:** ver fallar, implementar, ver pasar. Commit `feat: ejecutor por NAS y por flota`.

---

### Task 8: servidor de flota

**Files:**
- Create: `src/qnap_tools/servidor.py`, `src/qnap_tools/flota/__init__.py`, `src/qnap_tools/flota/servidor.py`, `src/qnap_tools/claves.py`, `tests/test_flota.py`, `tests/test_claves.py`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces:
  - `servidor.crear(nombre: str, instrucciones: str) -> tuple[FastMCP, Flota]`: carga la
    configuración; si falla, el servidor arranca igual y cada herramienta devuelve el error de
    configuración (así el fallo se ve en el chat y no como "servidor caído").
  - `claves.asegurar(cfg: Config) -> str`: crea el par ed25519 si no existe (formato OpenSSH,
    comentario `qnap-tools@<nombre del equipo>`, permisos solo del usuario) y devuelve la línea
    pública.
  - Herramientas de `qnap-flota` (funciones puras probables sin MCP, registradas en `main`):
    - `nas_lista() -> list[dict]`: nombre, host, puerto, auth.
    - `nas_comprobar(nas: str = "todos") -> list[dict]`: conecta y devuelve método de acceso,
      si `sudo` da root, y el `Perfil`.
    - `nas_alta(nombre: str, host: str, port: int = 22, instalar_clave: bool = True) -> dict`:
      valida, conecta con `fijar_host=True` por contraseña, comprueba `id` (pertenece a
      `administrators`), instala la clave pública si `instalar_clave` (orden fija:
      `mkdir -p ~/.ssh && chmod 700 ~/.ssh && { grep -qF <pub> ~/.ssh/authorized_keys 2>/dev/null || echo <pub> >> ~/.ssh/authorized_keys; } && chmod 600 ~/.ssh/authorized_keys`),
      reconecta para comprobar el método, detecta el perfil y guarda la entrada. Si la clave no
      queda aceptada guarda `auth = "contrasena"` y lo dice. No guarda nada si la conexión falla.
    - `nas_enrolar() -> list[dict]`: instala la clave de este ordenador en todos los NAS del
      inventario con `auth != "contrasena"`; un resultado por NAS.
    - `nas_baja(nombre: str) -> dict`: quita la entrada del inventario (no toca el NAS).
    - `inventario_exportar(ruta: str) -> dict`, `inventario_importar(ruta: str, sobrescribir: bool = False) -> dict`.

- [ ] **Step 1:** pruebas de `claves`: genera el par en `tmp_path`, la pública empieza por
  `ssh-ed25519 `, una segunda llamada no la regenera.
- [ ] **Step 2:** pruebas de flota con `ClienteFalso`: `nas_alta` guarda la entrada y envía la
  orden de instalación exacta; con `instalar_clave=False` no la envía y guarda `auth="contrasena"`;
  nombre inválido o ya existente -> error sin conectar; conexión fallida -> inventario intacto;
  `nas_baja` de un nombre inexistente -> error con los válidos; exportar e importar ida y
  vuelta; importar sin `sobrescribir` no pisa una entrada existente.
- [ ] **Step 3:** ver fallar, implementar, ver pasar.
- [ ] **Step 4:** arranque real: `.venv\Scripts\qnap-tools-flota.exe` con las variables de
  entorno puestas; hacer el handshake MCP a mano (`initialize` + `tools/list`) y comprobar que
  salen las 7 herramientas.
- [ ] **Step 5:** commit `feat: servidor qnap-flota`.

---

### Task 9: comandos y parsers de redes

**Files:**
- Create: `src/qnap_tools/redes/__init__.py`, `src/qnap_tools/redes/comandos.py`, `src/qnap_tools/redes/parsers.py`, `tests/test_redes_parsers.py`, `tests/datos/redes/*.txt`

**Interfaces:**
- Consumes: `Comando` y validadores.
- Produces: en `redes/comandos.py`, una constante `Comando` por orden, tomadas de
  `pruebas/catalogo/redes.json` (ya probadas en los tres NAS):

  | Constante | Orden | sudo |
  |---|---|---|
  | `ENLACES` | `ip -br link` | no |
  | `DIRECCIONES` | `ip -br addr` | no |
  | `DETALLE` | `ip -s -d link show` | no |
  | `SYS_RED` | bucle sobre `/sys/class/net/*/{speed,duplex,carrier,mtu}` | no |
  | `ETHTOOL` / `ETHTOOL_DRIVER` / `ETHTOOL_STATS` | `ethtool {iface}`, `-i`, `-S` | no |
  | `BONDING` | `cat /proc/net/bonding/*` (`no_probado`) | no |
  | `VLAN` | `cat /proc/net/vlan/config` (`no_probado`) | sí |
  | `PUENTES` / `PUENTES_MAC` | `brctl show`, `brctl showmacs {iface}` | no |
  | `RUTAS` / `REGLAS` / `VECINOS` | `ip route`, `ip rule`, `ip neigh` | no |
  | `RUTAS_ESTATICAS` | `cat /etc/config/staticroute.conf` | no |
  | `DNS` | `cat /etc/resolv.conf` y `resolv.dnsmasq` | no |
  | `DHCP_SERVIDOR` / `DHCP_LEASES` | ficheros de `dhcpd` | no |
  | `ESCUCHA_TCP` / `ESCUCHA_UDP` | `netstat -tlnp`, `-ulnp` | sí |
  | `SERVICIOS` | `getcfg` campo a campo de puertos y activaciones | no |
  | `IPTABLES` | `iptables-save` | sí |
  | `BLOQUEO_IP` | `getcfg` de la sección de bloqueo | no |
  | `DDNS` / `UPNP` | ficheros de configuración | no |
  | `VPN_PRESENCIA` | `ip -br link` filtrado por `tun`, `wg`, `ppp` | no |
  | `PING` | `ping -c 3 -W 2 {destino}` | sí, timeout 15 |
  | `TRACEROUTE` | `traceroute -n -w 2 -m 15 {destino}` | sí, timeout 40 |
  | `NSLOOKUP` | `nslookup {destino}` | no |

  En `redes/parsers.py`, funciones puras `texto -> estructura`: `enlaces`, `direcciones`,
  `contadores`, `sys_red`, `ethtool`, `puentes`, `rutas`, `vecinos`, `dns`, `escucha`,
  `servicios`, `iptables_resumen`, `ping`, `traceroute`. Cada una devuelve listas o
  diccionarios con claves en castellano sin acentos (`interfaz`, `estado`, `mac`, `ipv4`,
  `velocidad_mbps`...). Una entrada irreconocible lanza `ValueError` (no se inventan datos).

- [ ] **Step 1:** crear `tests/datos/redes/` copiando las salidas reales de
  `pruebas/resultados/nas1/redes/` y `pruebas/resultados/nas3/redes/`, **anonimizadas**
  (IP `192.0.2.x`, MAC `00:11:22:33:44:5x`). Un fichero por orden y sistema donde difieran.
- [ ] **Step 2:** una prueba por parser con valores concretos esperados (p. ej. `enlaces` de
  `enlaces_hero.txt` contiene `{"interfaz": "eth0", "estado": "UP", "mac": "00:11:22:33:44:50"}`;
  `escucha` asocia el puerto 22 al proceso `sshd`; `ping` devuelve `perdida_pct == 0` y
  `media_ms` como número), más una prueba de entrada vacía -> `ValueError` por parser.
- [ ] **Step 3:** prueba de coherencia sobre `redes/comandos.py`: ninguna plantilla contiene
  `>` (salvo `2>/dev/null`), `sudo`, `uLinux.conf` fuera de `getcfg`, `qvpn`, `openvpn`;
  todo `{param}` está declarado en `params`.
- [ ] **Step 4:** ver fallar, implementar, ver pasar. Commit `feat: comandos y parsers de redes`.

---

### Task 10: las 9 herramientas de redes

**Files:**
- Create: `src/qnap_tools/redes/servidor.py`, `tests/test_redes_servidor.py`

**Interfaces:**
- Consumes: `servidor.crear`, `Flota`, comandos y parsers de la tarea 9.
- Produces, todas con `nas: str` y retorno `list[dict]` (sobre uniforme por NAS):
  - `red_resumen(nas)`: interfaces activas con IP, velocidad, puerta de enlace y DNS.
  - `red_interfaces(nas, interfaz: str | None = None)`: contadores, errores, driver, firmware;
    `trunking` y `vlan` con `no_probado: true`.
  - `red_conmutadores(nas)`: puentes, puertos y, por puente, sus MAC.
  - `red_rutas(nas)`: rutas, reglas, estáticas y vecinos.
  - `red_servicios(nas)`: servicios configurados y puertos en escucha con su proceso.
  - `red_dhcp_dns(nas)`: DNS, servidor DHCP y concesiones (`null` si el NAS no sirve DHCP).
  - `red_cortafuegos(nas)`: resumen de tablas y cadenas con número de reglas, y bloqueo por IP;
    `qufirewall` con `no_probado: true`.
  - `red_acceso_remoto(nas)`: DDNS, UPnP y presencia de VPN (sin contenido).
  - `red_diagnostico(nas, destino: str, prueba: str = "ping")`: `ping` | `traceroute` | `dns`.

- [ ] **Step 1:** pruebas con `ClienteFalso` cargado con los ficheros de `tests/datos/redes/`:
  - `red_resumen("todos")` devuelve una entrada por NAS con `ok: True` y la IP esperada;
  - `red_interfaces(..., interfaz="eth0; reboot")` devuelve `ok: False` y el cliente falso no
    ha recibido ninguna orden;
  - `red_diagnostico(..., prueba="otra")` devuelve `ok: False`;
  - `red_servicios` envía `netstat` con `sudo` y `getcfg` sin él;
  - una herramienta cuyo comando devuelve salida vacía da `ok: False`, no datos vacíos;
  - `red_cortafuegos` incluye `no_probado: True` en el bloque de QuFirewall.
- [ ] **Step 2:** ver fallar, implementar, ver pasar.
- [ ] **Step 3:** handshake MCP real de `qnap-tools-redes`: salen las 9 herramientas con sus
  descripciones.
- [ ] **Step 4:** prueba real opcional contra `nas1` (`QNAP_TOOLS_PRUEBA_REAL=1`): las 9
  herramientas devuelven `ok: True`; comparar a ojo con `pruebas/resultados/nas1/redes/`.
- [ ] **Step 5:** commit `feat: servidor qnap-redes`.

---

### Task 11: plugin instalable y verificación final

**Files:**
- Create: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.mcp.json`, `skills/alta/SKILL.md`, `skills/enrolar/SKILL.md`
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1:** `plugin.json` (`name: "qnap-tools"`, `userConfig` como en la tarea 1) y
  `.mcp.json` con `qnap-flota` y `qnap-redes`. Mientras no esté en PyPI:
  `command: "uvx"`, `args: ["--from", "${CLAUDE_PLUGIN_ROOT}", "qnap-tools-redes"]`. `env` con
  las tres variables. `marketplace.json` con `source: "./"`.
- [ ] **Step 2:** `skills/alta/SKILL.md` y `skills/enrolar/SKILL.md`: guían a Claude para pedir
  nombre, IP y puerto, llamar a `nas_alta` o `nas_enrolar` y mostrar el resultado. Recuerdan el
  requisito previo: usuario en `administrators` con SSH permitido.
- [ ] **Step 3:** instalar en local (`claude plugin marketplace add .` e instalar), activar y
  comprobar en una sesión nueva: `/mcp` muestra los dos servidores; `/qnap-tools:alta` da de
  alta `nas1`; `red_resumen` responde.
- [ ] **Step 4:** prueba de no escritura: adaptar `pruebas/efectos.py` para lanzar las órdenes
  de `redes/comandos.py` contra `nas1` y confirmar que ninguna modifica ficheros.
- [ ] **Step 5:** `pytest -v` completo en verde; `python -c` que recorra `src/` y compruebe
  `isascii()` en todos los `.py`.
- [ ] **Step 6:** README (requisitos, instalación, alta de un NAS, aviso de que la carpeta de
  datos se borra al desinstalar y cómo exportar el inventario) y `CLAUDE.md` al día.
  Commit `feat: plugin qnap-tools instalable en local (base y redes)`.

---

## Anexo: registro de la ejecucion

Ejecutado el 2026-10-13/14 en la rama `entrega-1-base-redes` (ejecucion en linea, una revision
independiente al final). Copia del registro de trabajo: lo que se decidio al apartarse del plan,
lo que corrigio la revision final y lo que queda aplazado.

### Tareas

- Task 1: complete (commits 70787ed..7526cc5, tests: bash -c 'test ! -e ensayo && git diff --quiet HEAD -- docs && echo "ensayo retirado y spec confirmada: credencial y carpeta de datos llegan al servidor MCP"' → ensayo retirado y spec confirmada: credencial y carpeta de datos llegan al servidor MCP)
- Task 2: complete (commits 7526cc5..ab8215f, tests: .venv/Scripts/python.exe -m pytest -q → 1 passed in 0.01s)
- Task 3: complete (commits ab8215f..e185860, tests: .venv/Scripts/python.exe -m pytest -q → 49 passed in 0.07s)
- Task 4: complete (commits e185860..9d484d6, tests: .venv/Scripts/python.exe -m pytest -q → 131 passed in 0.13s)
- Task 5: complete (commits 9d484d6..bdea356, tests: .venv/Scripts/python.exe -m pytest -q → 165 passed, 5 skipped in 0.62s)
- Task 6: complete (commits bdea356..84d2379, tests: .venv/Scripts/python.exe -m pytest -q → 179 passed, 6 skipped in 1.64s)
- Task 7: complete (commits 84d2379..cf91748, tests: .venv/Scripts/python.exe -m pytest -q → 211 passed, 6 skipped in 3.48s)
- Task 8: complete (commits cf91748..1e6b2d1, tests: .venv/Scripts/python.exe -m pytest -q → 255 passed, 7 skipped in 4.02s)
- Task 9: complete (commits 1e6b2d1..7e06014, tests: .venv/Scripts/python.exe -m pytest -q → 464 passed, 7 skipped in 4.19s)
- Task 10: complete (commits 7e06014..619864c, tests: .venv/Scripts/python.exe -m pytest -q → 507 passed, 8 skipped in 4.48s)
- Task 11: complete (commits 619864c..bd54852, tests: .venv/Scripts/python.exe -m pytest -q → 507 passed, 8 skipped in 4.45s)

### Verificaciones contra el NAS de laboratorio

- Task 8: verificado: handshake MCP real de qnap-tools-flota.exe (7 herramientas, llamada a nas_lista, y sin credencial la herramienta lo dice); tests/test_real_flota.py contra nas1 con instalar_clave=False (1 passed): alta, lista, comprobar, alta repetida, baja.
- Task 9: verificado: los parsers recorren sin error las salidas guardadas de nas1, nas2 y nas3 (enlaces, direcciones, puentes, rutas, reglas, vecinos, escucha tcp/udp, iptables, contadores, nslookup, ping, traceroute, bonding, vlan); anonimiza.py --revisar sobre los 38 ficheros de tests/datos/redes: 0 dudas.
- Task 10: verificado: saludo MCP real de qnap-tools-redes.exe (9 herramientas con descripcion; sin credencial la herramienta lo dice); tests/test_real_redes.py contra nas1 (1 passed, 9,4 s): las 9 herramientas ok, detalle de eth0, ping y traceroute a la puerta de enlace, dns, y rechazo de un destino con orden dentro. Tamanos en nas1: red_servicios 9 KB, red_interfaces 7 KB, el resto < 5 KB.
- Task 10: PENDIENTE DE CONTAR: las herramientas solo se han lanzado en real contra nas1 (hero). Contra QTS se han pasado los parsers por las salidas guardadas, pero las ordenes cuya plantilla es nueva (SYS_RED, TRAFICO, SERVICIOS, BLOQUEO_IP, DDNS, UPNP, VPN_PRESENCIA, DNS, DHCP_*, BONDING, VLAN, QUFIREWALL) no se han ejecutado en un QTS: el plan limita las pruebas reales a nas1.
- Final: verificado: prueba de no escritura repetida en nas1 con las plantillas ya corregidas (pruebas/efectos.py --producto redes): 30 ordenes, 0 confirmadas, 0 cambios en /mnt/ext. Hubo 9 coincidencias con ruido de fondo (la pasada cayo a medianoche, con tareas periodicas del NAS: 80 ficheros de ruido frente a 33) que no se repitieron en ninguno de los dos reintentos de cada una; en la primera pasada, veinte minutos antes, no hubo ninguna. Las 8 pruebas reales contra nas1 (transporte, deteccion, flota y redes) pasan con el codigo corregido.

### Decisiones tomadas (66)

- Setup: Ruling: rama en la misma carpeta en vez de worktree — el repo se acaba de crear y las pruebas necesitan .env, .venv y pruebas/ (ignorados, no viajan a un worktree) — coste si me equivoco: main y la rama comparten carpeta; no hay otro trabajo en paralelo que proteger.
- Setup: Ruling: git init adelantado desde la tarea 2 al arranque — los scripts del ledger exigen repo — coste: ninguno, la tarea 2 ya no lo repite.
- Setup: Ruling: pruebas/*.py, reglas y catalogos SI se versionan (el plan solo excluye claves y resultados); comprobado con git grep que no llevan IP, MAC ni nombres reales; el usuario de laboratorio se saco de efectos.py — coste: si se quisiera el repo publico sin laboratorio, un git rm.
- T2 entry points flota/redes apuntan a modulos que no existen hasta T8/T10: Ruling: se declaran en T2 como dice el plan (pip -e no los valida al instalar) — coste: los .exe fallan si se lanzan antes de T8/T10.
- Task 1: Ruling: ensayo hecho SIN el usuario, en un CLAUDE_CONFIG_DIR aislado y por la CLI (`claude plugin configure --values-stdin` + `claude mcp list`), en vez de que el usuario active el plugin y teclee valores — la CLI lo permite y no toca su configuracion real — coste si me equivoco: el flujo interactivo de /plugin configure no se ha visto; se vera en la tarea 11 al instalar el plugin real.
- Task 2: Ruling: pyproject sin campo de licencia — la licencia es decision del usuario y solo hace falta al publicar (entrega 4) — coste: hay que anadirla antes de subir a PyPI.
- Task 3: Ruling: validacion en Nas.__post_init__ (no solo "al guardar" como dice el plan) — asi tambien se valida lo leido del fichero y lo que llega de nas_alta — coste: ninguno conocido.
- Task 3: Ruling: resolver() con inventario vacio lanza NasDesconocido ("inventario vacio") en vez de devolver [] — la spec prohibe degradar en silencio — coste: quien quiera "todos" sobre vacio recibe error, que es lo buscado.
- Task 3: Ruling: extras no pedidos por el plan, todos con prueba: 'todos' reservado como nombre; claves y tablas desconocidas en el TOML son error; BOM tolerado; marcador ${...} sin sustituir = ausente — coste: un inventario escrito a mano con erratas falla con mensaje en vez de leerse a medias.
- Task 4: Ruling: el tipo `interfaz` exige primer caracter alfanumerico (el plan admitia "-" inicial) — un valor como "-s" o "--help" se colaria como opcion del comando — coste: ninguna interfaz real empieza por "-".
- Task 4: Ruling: Comando.valida por defecto es `estricta` (codigo 0 y salida no vacia), no None como decia el plan; valida=None lo desactiva — la spec exige que todo comando lleve validador y asi olvidarlo no degrada en silencio — coste: los comandos cuya salida vacia es legitima deben declararlo (valida=rc_cero o None). CARRY: tareas 7, 9 y 10 lo tienen en cuenta.
- Task 4: Ruling: la comprobacion de redirecciones a fichero se hace al DEFINIR cualquier Comando (el plan la ponia como prueba solo de redes en la tarea 9) — protege a las cuatro patas — coste: una comparacion ">" dentro de awk hay que escribirla de otra forma.
- Task 4: Ruling: render() acepta int ademas de str (bahia=3) y rechaza bool/float/None; anadido el validador `todas` — coste: ninguno.
- Task 5: Ruling: excepcion extra HostSinFijar (subclase de ErrorConexion) para "host no fijado", distinta de HostCambiado — el plan solo nombraba tres; el mensaje guia a nas_alta — coste: ninguno.
- Task 5: Ruling: un intento de conexion por metodo (clave, luego contrasena) en vez de una sola conexion con ambos — asi se sabe con cual entro — coste: con auth=auto y clave rechazada son dos conexiones TCP; nas_alta guarda auth=contrasena para evitarlo.
- Task 5: Ruling: lectura por sondeo de stdout y stderr con plazo TOTAL (el timeout de paramiko es por lectura y leer una tras otra puede bloquearse) — coste: 10 ms de latencia de sondeo.
- Task 5: Ruling: sudo que rechaza la contrasena se convierte en AutenticacionFallida (no estaba en el plan) — si no, saldria como un fallo generico del comando — coste: depende de los textos de sudo ("incorrect password attempt", "Sorry, try again").
- Task 5: Ruling: una orden que agota el tiempo NO se mata en el NAS (medido en nas1: sigue viva hasta acabar; el NAS no tiene `timeout`). No se anade vigilante en el NAS en esta entrega — seria un cambio de diseno sin probar en QTS — coste: una orden colgada de verdad quedaria en el NAS hasta el reinicio. Anotado en la spec (Sin resolver) y a contar al usuario.
- Task 6: Ruling: Perfil lleva un campo extra `avisos` (tuple) — una ruta de paquete no valida se descarta sin romper el resto del NAS, pero no en silencio — coste: ninguno.
- Task 7: Ruling: el inventario se relee en cada por_nas() y, si la entrada de un NAS cambia, se reabre la conexion y se redetecta — qnap-flota y qnap-redes son procesos distintos y solo comparten el fichero — coste: una lectura de fichero por consulta.
- Task 7: Ruling: sudo rechazado (AutenticacionFallida) no se reintenta; cualquier otro ErrorConexion durante ejecutar reabre la conexion UNA vez — coste: una orden puede ejecutarse dos veces si la conexion cae justo despues de enviarla (son lecturas).
- Task 7: Ruling: la deteccion solo se hace si el comando no es sistema="ambos" — ahorra un viaje en las patas iguales en los dos sistemas — coste: ninguno.
- Task 7: Ruling: por_nas tambien convierte DeteccionFallida e InventarioInvalido en error (el plan no los listaba); anadida la propiedad Nas.destino, usada por Conexion — coste: ninguno.
- Task 8: Ruling: servidor.crear() devuelve (FastMCP, Contexto) y no (FastMCP, Flota) — el Contexto carga la configuracion al primer uso, que es lo que permite arrancar sin credencial — coste: las patas usan ctx.flota y ctx.por_nas. CARRY: tarea 10.
- Task 8: Ruling: las herramientas son metodos de una clase Herramientas(ctx) registrados con mcp.add_tool; las que no son por NAS devuelven dict {"ok", ...} (el plan decia list para nas_lista) — asi pueden llevar un error — coste: ninguno.
- Task 8: Ruling: la orden que instala la clave publica NO es un Comando (un Comando no puede redirigir a fichero); vive aislada en flota/servidor.py (orden_instalar_clave) con la clave validada por expresion regular y entrecomillada — es la unica excepcion a "todo sale de un Comando" y es la unica escritura del plugin — coste: una orden fuera del mecanismo comun, cubierta por prueba de texto exacto.
- Task 8: Ruling: orden del alta: conectar -> id -> detectar -> sudo -> instalar clave -> guardar. Detectar va ANTES de instalar para no escribir en algo que no sea un QNAP — coste: ninguno.
- Task 8: Ruling: nas_enrolar fija la clave de host en TODOS los NAS (tambien los de solo contrasena) porque en un ordenador nuevo ninguno esta fijado; el plan solo hablaba de instalar la clave — coste: enrolar es una primera conexion de confianza por NAS; devuelve la huella para cotejarla.
- Task 8: Ruling: nas_alta y nas_enrolar devuelven la huella SHA256 de la clave de host; nas_baja olvida la clave de host (salvo que otra entrada use el mismo equipo) para poder volver a dar de alta un NAS reinstalado — no estaban en el plan — coste: ninguno.
- Task 8: Ruling: inventario_exportar exige extension .toml y no pisa ficheros existentes — una herramienta que escribe en una ruta arbitraria del ordenador debe estar acotada — coste: para reexportar hay que dar otra ruta o borrar el fichero.
- Task 8: Ruling: la clave privada se protege con los permisos de la carpeta de datos (perfil del usuario); 0600 solo en POSIX, sin icacls en Windows — la contrasena ya vive en claro en el mismo perfil (.credentials.json) — coste: no hay endurecimiento adicional en Windows.
- Task 9: Ruling: no hay DETALLE (ip -s -d link show); en su lugar CONTADORES (/proc/net/dev) y TRAFICO (dos lecturas a 2 s con la marca ==2s) — el formato de /proc/net/dev es estable y da caudal real; ip -s -d cambia entre versiones de iproute2 — coste: no se ven atributos de detalle de ip (tipo de enlace, promiscuidad).
- Task 9: Ruling: ethtool va parametrizado por interfaz ({iface}, tipo interfaz) y no en bucle; ETHTOOL y ETHTOOL_DRIVER validan no_vacia y ETHTOOL_STATS no valida (una interfaz virtual no tiene estadisticas) — coste: red_interfaces lanza 3 ordenes por interfaz fisica. CARRY: tarea 10.
- Task 9: Ruling: TRACEROUTE lleva -q 1 (una sonda por salto; el plan no lo ponia) — con 3 sondas, 15 saltos a 2 s no caben en el timeout de 40 s — coste: menos precision en el tiempo por salto.
- Task 9: Ruling: DDNS solo lee de ddns.conf los nombres de proveedor y sus campos enable y hostname (grep anclado); VPN_PRESENCIA solo lee getcfg QVPN Enable de qpkg.conf y los tuneles tun/tap/ppp/wg de ip -br link, nunca /etc/config/qvpn — el plan pedia que ninguna plantilla contuviera "qvpn"; la prueba lo acota a rutas (qvpn/, openvpn, claves) — coste: ninguno.
- Task 9: Ruling: mas parsers que los 14 del plan (29): trafico, ethtool_driver, ethtool_errores, bonding, vlan, puentes_mac, reglas, rutas_estaticas, dhcp_servidor, dhcp_concesiones, bloqueo_ip, ddns, upnp, vpn_presencia, nslookup — las 9 herramientas los necesitan — coste: mas superficie; cada uno tiene prueba con dato real o texto marcado como escrito a mano.
- Task 9: Ruling: devuelven vacio (y no ValueError) con entrada vacia los parsers de ordenes donde "no hay nada" es valido: ethtool_errores, bonding, vlan, vecinos, rutas_estaticas, dhcp_servidor, dhcp_concesiones; los otros 22 lanzan ValueError con entrada vacia o irreconocible (prueba parametrizada) — el plan pedia ValueError en todos — coste: en esos 7 un fallo silencioso de la orden se veria como "no hay"; lo cubre el validador del Comando donde aplica.
- Task 9: Ruling: servicios/bloqueo_ip/ddns lanzan ValueError si un campo si/no trae un valor desconocido o un puerto no es numerico (no se adivina); campo vacio -> None ("no consta en este NAS", p. ej. iSCSI en hero) — coste: un firmware con un valor nuevo hace fallar la herramienta entera con un mensaje que nombra el campo.
- Task 9: Ruling: rutas devuelve las claves "tipo" y "saltos" solo en las rutas que las tienen (descarte, multisalida); rutas_estaticas y las listas de bloqueo_ip se devuelven tal cual (sin validar con datos reales: vacias en los 3 NAS). CARRY: tarea 10, marcar no_probado.
- Task 9: Ruling: datos de prueba: los *_hero.txt se capturaron en nas1 con los Comando del producto (pruebas/captura_redes.py) y no copiando pruebas/resultados; los *_qts.txt (8) se derivan de pruebas/resultados/nas3 sin trafico nuevo a produccion (pruebas/deriva_redes_qts.py). No se incluye el mapa de puertos del NAS de produccion (escucha_*_qts) — coste: escucha solo tiene dato versionado de hero (verificado a mano contra las salidas guardadas de los 3 NAS).
- Task 9: Ruling: MAC de ejemplo 00:11:22:33:44:NN correlativas desde 00 (el plan decia 5x) e IP 192.0.2.N por orden de aparicion: una red real pasa a ser una direccion cualquiera del rango (p. ej. 192.0.2.37/24) — coste: los datos no son coherentes como red, solo como formato.
- Task 9: Ruling: la guardia del laboratorio (pruebas/guardia.py) ignoraba todo lo que seguia a un '#' (shlex.commenters); corregido con lex.commenters = "" y prueba que comprueba que sigue bloqueando escrituras — coste: ninguno.
- Task 9: Ruling: escucha ignora la linea "netstat: showing only processes with your user ID" (vista en nas2 incluso con sudo) — coste: ninguno.
- Task 10: Ruling: nas es obligatorio en las 9 herramientas (sin valor por defecto), como dice el plan; 'todos' hay que pedirlo — evita lanzar por descuido un traceroute o 9 consultas a toda la flota — coste: con un solo NAS hay que nombrarlo.
- Task 10: Ruling: dos clases de fallo. Orden principal que falla o salida irreconocible -> la entrada del NAS sale ok=false (ErrorComando que nombra NAS y consulta). Dato accesorio que falla (ethtool/-i/-S de una interfaz, MAC de un puente, bloques no_probado) -> {"error": ...} en su sitio y el resto se conserva; un fallo de conexion o de sudo tumba siempre la entrada entera — coste: quien lea debe mirar "error" dentro de esos bloques.
- Task 10: Ruling: red_interfaces sin interfaz NO lanza ethtool (serian 3 ordenes por interfaz); el detalle (ip -br link, ethtool, -i, -S) solo con interfaz; el nombre se valida antes de conectar y se comprueba que existe antes de lanzar ethtool — coste: para ver el driver de todas hay que pedirlas una a una.
- Task 10: Ruling: parsers.trafico devuelve los contadores de la segunda lectura mas rx_bps/tx_bps (antes solo el caudal) y el comando CONTADORES desaparece (TRAFICO lo cubre); ENLACES se usa en el detalle de una interfaz (marcas y par). Prueba nueva: ningun Comando definido queda sin usar y el servidor solo lanza Comandos definidos — coste: red_interfaces tarda 2 s por NAS (la muestra de trafico).
- Task 10: Ruling: VLAN pasa a "[ ! -e /proc/net/vlan/config ] || cat ..." con valida=rc_cero (antes cat con valida=None): sin modulo cargado -> vacio; fichero ilegible -> error y no "no hay VLAN" — coste: ninguno (pasa la guardia).
- Task 10: Ruling: comando nuevo QUFIREWALL (getcfg QuFirewall Enable de qpkg.conf), no_probado: en nas1 el paquete no esta instalado (0 apariciones de "firewall" en qpkg.conf), asi que el nombre de la seccion esta sin verificar — coste: en un NAS con QuFirewall podria dar null si la seccion se llama de otro modo; sus reglas salen igualmente en iptables.
- Task 10: Ruling: red_servicios agrupa netstat por protocolo+puerto+proceso (direcciones, pids, alcance todas/local/concretas); red_conmutadores solo pide las MAC de los puentes con puertos y devuelve como mucho 50 aprendidas por puente; red_resumen considera activas las interfaces con direccion y no caidas mas los puertos fisicos con enlace; "tipo" se deduce del nombre (eth, bond, br/qvs/docker/lxc, veth/vnet/tap, tun/ppp/wg) — coste: el tipo es una etiqueta por convencion de nombres de QNAP, no un dato del kernel.
- Task 10: Ruling: red_dhcp_dns da dhcp_servidor y dhcp_concesiones a null si no hay ningun ambito; red_acceso_remoto solo lista los proveedores DDNS activos y cuenta los disponibles.
- Task 11: Ruling: los servidores MCP van EN LINEA en plugin.json (mcpServers) y no en un .mcp.json en la raiz (el plan pedia .mcp.json) — en la raiz del repositorio Claude Code lo cargaria como servidores de proyecto, con ${CLAUDE_PLUGIN_ROOT} y ${user_config.*} sin sustituir — coste: ninguno; verificado con claude plugin validate y con la instalacion aislada. Spec actualizada.
- Task 11: Ruling: el paso 3 (instalar, activar y probar en una sesion nueva) se ha hecho en un perfil aislado (CLAUDE_CONFIG_DIR temporal) con una copia limpia del arbol versionado, sin interfaz: marketplace add, install --config, configure --values-stdin, claude mcp list (los dos servidores Connected), y saludo MCP a mano con uvx --from: nas_alta (instalar_clave=false) por qnap-flota y red_resumen/red_diagnostico por qnap-redes comparten inventario y known_hosts. NO se ha instalado en el perfil real del usuario ni se han lanzado /qnap-tools:alta ni /mcp en una sesion interactiva — instalarlo ahi guarda su contrasena en claro en .credentials.json y eso lo decide el usuario — coste: el flujo interactivo y las dos skills quedan sin ver en vivo.
- Task 11: Ruling: efectos.py gana --producto redes (ordenes del plugin, solo en el modo en que el plugin las lanza) en vez de un catalogo; resultado en nas1: 30 ordenes, 0 candidatos, 0 confirmados, 0 cambios en /mnt/ext.
- Task 11: Ruling: plugin.json sin "license" ni "repository" (licencia sin decidir, repositorio sin publicar); marketplace con nombre qnap-tools (se instala como qnap-tools@qnap-tools).
- Task 11: Ruling: el README recomienda instalar desde un clon limpio: la instalacion local copia la carpeta a plugins/cache y la carpeta de trabajo tiene .env, claves y resultados — no comprobado que copie los ficheros sin versionar; es una cautela.
- Final: Ruling: I3 (nas_alta y nas_enrolar envian la contrasena comun antes de que se pueda cotejar la huella) NO se corrige en el codigo — es el orden que fija el diseno aprobado (confianza en la primera conexion) y cambiarlo a un alta en dos pasos altera el flujo y la lista de herramientas: lo decide el usuario. Se mitiga con avisos en las instrucciones de los dos servidores, en las dos skills y en el README, y queda en "Sin resolver" de la spec — coste si me equivoco: una IP tecleada mal (o un modelo manipulado) entrega la contrasena de toda la flota a otro equipo.
- Final: Ruling: (apartado por el revisor) correccion de pruebas/guardia.py, ro.py y efectos.py como herramientas de laboratorio — no son producto; la guardia se usa en una prueba del producto y tiene su propia prueba de que sigue bloqueando — coste: un hueco en la guardia dejaria pasar una plantilla de escritura a la prueba; lo cubre ademas la prueba de efectos real.
- Final: Ruling: (apartado) sintaxis de /plugin install y si Claude Code copia la carpeta — la linea de instalacion la da el propio validador de Claude Code 2.1.296; la copia a plugins/cache se observo en la instalacion aislada — coste: ninguno conocido.
- Final: Ruling: (apartado) contrasena en claro en .credentials.json en Windows — es comportamiento de Claude Code; documentado en README y spec y se cuenta al usuario.
- Final: Ruling: (apartado) si el bloqueo por IP del NAS cuenta los rechazos de clave publica con auth=auto — sin verificar; nas_alta guarda auth=contrasena cuando la clave no entra, asi que solo afectaria a una clave que deja de valer — coste: en ese caso, intentos fallidos repetidos hasta que el usuario lo vea en nas_comprobar.
- Final: Ruling: (apartado) comportamiento real de netstat, brctl e iptables-save en QTS mas alla de los datos guardados — pendiente de una pasada real por un QTS, que el plan excluia.
- Final: Ruling: (apartado) confianza en la primera conexion como modelo — lo fija la spec; ver I3.
- Final: Ruling: (apartado) proceso que sigue vivo en el NAS tras agotar el tiempo — decision ya tomada (Task 5) y en la spec.
- Final: Ruling: (apartado) licencia, publicacion e identidad git de los commits — decisiones del usuario antes de publicar.
- Final: Ruling: (apartado) ping y traceroute con sudo hacia cualquier destino — lo aprobo el usuario como diagnostico ligero (spec, apartado 4).

### Corregido tras la revision final (9)

- Final: fixed I1 (instalar la clave la pegaba a la ultima linea de authorized_keys si no acababa en salto de linea) — test_la_orden_de_instalar_la_clave_no_estropea_lo_que_ya_habia[otra-clave-sin-salto-final] RED→GREEN (la orden se ejecuta con sh sobre un HOME de prueba, 6 casos), suite 542/542. tail -c1 | wc -l verificado en nas1.
- Final: fixed I2 (alta fallida dejaba la clave de host fijada y nas_baja no podia quitarla) — test_alta_fallida_no_deja_fijada_la_clave_de_host[contrasena|no_administrador|no_qnap] RED→GREEN; test_alta_fallida_conserva_una_clave_de_host_que_ya_estaba_fijada; suite 542/542.
- Final: fixed I4 (sin latidos y conexion reutilizada tras un tiempo agotado) — test_al_conectar_se_piden_latidos_para_detectar_una_conexion_muerta y test_tras_un_tiempo_agotado_la_siguiente_consulta_abre_una_conexion_nueva RED→GREEN, suite 542/542.
- Final: fixed I5 (el final de la salida podia perderse al llegar despues del codigo de salida) — test_la_salida_que_llega_despues_del_codigo_de_salida_no_se_pierde y test_si_el_fin_de_la_salida_no_llega_no_se_espera_para_siempre RED→GREEN, suite 542/542; las 8 pruebas reales contra nas1 pasan con el bucle nuevo.
- Final: fixed I6 (fallos que salian como dato vacio o normal): servicios y bloqueo_ip con todos los campos vacios -> error (test_servicios_con_todos_los_campos_vacios..., test_bloqueo_ip_con_todos_los_campos_vacios..., y bloqueo_ip pasa a bloque con su error: test_cortafuegos_si_no_se_puede_leer_el_bloqueo_por_ip...); DNS falla si no puede leer resolv.conf (test_la_orden_de_dns_falla_si_no_puede_leer_resolv_conf, ejecutada con sh); RUTAS_ESTATICAS con el patron de VLAN (test_rutas_estaticas_distingue...); ethtool_errores lleva "disponible" (test_ethtool_errores_sin_estadisticas_no_es_lo_mismo_que_sin_errores); concesiones DHCP con cuenta de lineas y aviso de recorte, limite 1000 (test_dhcp_concesiones_avisa_de_los_ficheros_que_llegan_recortados, test_dhcp_dns_avisa_si_las_concesiones_llegan_recortadas); VPN_PRESENCIA solo pregunta por QVPN y los tuneles salen de ENLACES sin tapN (test_acceso_remoto_saca_los_tuneles_de_las_interfaces_del_nas) — todos RED→GREEN, suite 542/542. Ordenes nuevas verificadas en nas1 con el arnes de solo lectura.
- Final: fixed I7 (texto libre del NAS hacia el modelo) — test_dhcp_concesiones_no_deja_pasar_texto_libre_en_el_nombre_del_equipo y test_las_instrucciones_avisan_de_que_el_texto_del_nas_no_son_ordenes RED→GREEN, suite 542/542. Queda riesgo residual: un nombre con caracteres validos sigue llegando (acotado a 63).
- Final: fixed M2, regraduado a importante (el aviso de host sin fijar mandaba a nas_alta, que se niega si el NAS ya esta en el inventario) — test_el_aviso_de_host_sin_fijar_indica_enrolar_y_alta RED→GREEN, suite 542/542.
- Final: fixed M3, regraduado a importante (un sudo rechazado en el bloque de VLAN o un nombre de puente raro tumbaban la herramienta entera, contra lo que promete el alta) — test_interfaces_si_sudo_no_acepta_la_contrasena_solo_falla_el_bloque_que_lo_necesita y test_conmutadores_con_un_puente_de_nombre_no_admitido_lo_dice_en_ese_puente RED→GREEN, suite 542/542.
- Final: fixed M4 de paso (IndexError con una linea ";" suelta en las concesiones) al reescribir ese bucle — test_dhcp_concesiones_tolera_lineas_sueltas RED→GREEN.

### Menores aplazados (10)

Resueltos en la 0.4.1 (2026-10-14): M1 (las herramientas corren en un hilo), M7 (cryptography declarada), M10 (ToolAnnotations: readOnlyHint en las de consulta). Ya no aplican: M9 (se lanza desde PyPI) y M13 (la publicacion cambia esos datos).

- Final: minor (deferred): M1 las herramientas son sincronas y FastMCP las ejecuta en su bucle principal: el servidor no atiende otra cosa mientras dura una consulta larga.
- Final: minor (deferred): M5 rutas con "via inet6 <ip>" dan via="inet6"; eth0.10 y bond0.10 salen como tipo "otra".
- Final: minor (deferred): M6 listas sin tope: permitidas/denegadas de bloqueo_ip, interfaces por puente, agregaciones, vlan; tampoco hay tope de memoria para la salida de una orden.
- Final: minor (deferred): M7 pyproject no declara cryptography, que claves.py importa (llega por paramiko).
- Final: minor (deferred): M9 uvx --from una carpeta puede servir una construccion cacheada si cambia el codigo sin cambiar la version (anotado en CLAUDE.md).
- Final: minor (deferred): M10 las herramientas no llevan ToolAnnotations (readOnlyHint).
- Final: minor (deferred): M11 con sudo -S, si sudo no consume la contrasena (credencial en cache), queda en la entrada de la orden; hoy ninguna plantilla lee de la entrada. A tener en cuenta en las entregas 2 a 4.
- Final: minor (deferred): M12 inventario_exportar comprueba que el destino no existe y luego escribe, sin reserva atomica.
- Final: minor (deferred): M13 datos versionados con identificadores reales de bajo riesgo: nombres de redes docker (br-xxxx), el volumen ZFS600_DATA, modelos y firmware, alias de los NAS de laboratorio en pruebas/ y el correo del autor en los commits. Decidir antes de publicar.
- Final: minor (deferred): M14 el tipo "destino" no admite ::1 ni nombres con "_".
