# Qnap-Tools: diseño

Plugin de Claude Code para consultar una flota de NAS QNAP en **solo lectura**, con cuatro
servidores MCP temáticos y uno de administración de la flota. Este documento consolida lo
decidido el 2026-10-13 tras las pruebas contra tres NAS (detalle y evidencias en `CLAUDE.md`,
`pruebas/catalogo/`, `pruebas/reglas/` y `pruebas/resultados/`).

## 1. Identidad y distribución

- Plugin: `qnap-tools` (kebab-case obligatorio). Repo: `picaresco/qnap-tools`.
- Paquete Python `qnap-tools` en PyPI (nombre libre a 2026-10-13), lanzado con `uvx`.
- El repo es a la vez raíz del plugin y de su marketplace (`source: "./"`).
- No se publican: `.env`, `pruebas/claves/`, `pruebas/resultados/`, `CLAUDE.md`, `.remember/`,
  `.claude/` (contienen IP, nombres y números de serie reales).

## 2. Servidores MCP

| Servidor | Entry point | Herramientas |
|---|---|---|
| `qnap-redes` | `qnap-tools-redes` | 9 |
| `qnap-discos` | `qnap-tools-discos` | 9 |
| `qnap-virtualizacion` | `qnap-tools-virtualizacion` | 10 |
| `qnap-logs` | `qnap-tools-logs` | 8 |
| `qnap-flota` | `qnap-tools-flota` | administración: inventario, alta, enrolado |

`qnap-flota` existe porque el alta necesita la credencial, y la credencial solo llega a los
servidores MCP (por `env`), no a un comando lanzado desde una skill. Es el único servidor que
escribe algo en un NAS: la clave pública en `~/.ssh/authorized_keys` del usuario, y solo en
`nas_alta` y `nas_enrolar`. Los otros cuatro no escriben nunca.

### Herramientas aprobadas

- **Redes:** `red_resumen`, `red_interfaces`, `red_conmutadores`, `red_rutas`, `red_servicios`,
  `red_dhcp_dns`, `red_cortafuegos`, `red_acceso_remoto`, `red_diagnostico`.
- **Discos:** `almacenamiento_resumen`, `discos_fisicos`, `disco_smart`, `raid_estado`,
  `volumenes`, `snapshots`, `carpetas_compartidas`, `iscsi`, `rendimiento_discos`.
- **Virtualización:** `virtualizacion_resumen`, `vm_lista`, `vm_detalle`, `vm_uso`,
  `vm_snapshots`, `contenedores_lista`, `contenedor_detalle`, `contenedores_uso`,
  `contenedor_logs`, `contenedores_redes`.
- **Logs:** `eventos`, `eventos_resumen`, `accesos`, `avisos`, `kernel`, `salud_hardware`,
  `sistema_estado`, `alertas_config`.
- **Flota:** `nas_lista`, `nas_comprobar`, `nas_alta`, `nas_enrolar`, `nas_baja`,
  `inventario_exportar`, `inventario_importar`.

Todas las herramientas de consulta llevan `nas`: un nombre del inventario o `todos`.

## 3. Acceso a los NAS

- Transporte único: SSH. Usuario común de la flota, miembro de `administrators` con SSH permitido.
- Autenticación mixta: se intenta la clave del ordenador; si el NAS no la admite, contraseña.
  El inventario puede fijar `auth = "contrasena"` para no intentar la clave.
- `sudo` siempre pide contraseña: `sudo -S -p '' sh -c '<comando>'` con la contraseña por stdin.
  Solo en los comandos marcados; la mayoría va sin `sudo`.
- Clave de host: se fija en el alta (primera conexión) en un `known_hosts` propio; si cambia,
  se rechaza la conexión con un error que lo dice.
- Una conexión por NAS, reutilizada; los comandos contra un mismo NAS van en serie; `todos`
  reparte entre NAS en paralelo (máximo 4).
- Tiempo máximo por comando: 20 s por defecto, configurable por comando.

## 4. Solo lectura

- Lista **fija** de comandos: cada herramienta ejecuta plantillas definidas en el código. No
  hay comando libre ni exploración (`--help` no es inocuo: `md_checker --help` escribió).
- Los parámetros que entran en una plantilla se validan con una expresión regular estricta por
  tipo (interfaz, IP o nombre de host, bahía, UUID de VM, nombre de contenedor, fecha, entero)
  y se pasan entrecomillados.
- Criterio del usuario: que un comando anote su propia ejecución en un log no es modificación
  (`zpool history`, `zfs userspace` permitidos; inicio de sesión y `sudo` dejan rastro).
- Reglas medidas (pruebas de efectos en QuTS hero y QTS):
  - `log_tool`, `conn_log_tool`, `notice_log_tool`: nunca con `sudo` y siempre con `-q -v`.
  - `virsh`: siempre `-r -c qemu:///system`.
  - `qcli_storage`: nunca con `sudo`.
  - `docker ps`: nunca con el campo `Size`.
  - `docker inspect`: siempre con `--format` de campos concretos.
- Nunca se lee: `/etc/shadow`, `smbpasswd`, claves de host, `/etc/config/qvpn/`, `ipsec.*`,
  `openvpn`, `uLinux.conf` entero (solo `getcfg` campo a campo), `virsh --security-info`,
  `dmsetup table`.
- Excluido: familia `qcli_*` salvo `qcli_storage`, `get_hd_smartinfo`, `md_checker`,
  `lvs`/`pvs`/`vgs`, API HTTP de Virtualization Station.
- Diagnóstico ligero permitido (`ping -c`, `traceroute`, `nslookup`, muestreos cortos); pruebas
  activas excluidas (autotest SMART, velocidad de discos, iperf).

## 5. Fiabilidad

- **Nunca degradar en silencio:** cada comando lleva un validador de salida. Código 0 con
  salida vacía o centinela (`0 C`, `--`, lista vacía de `virsh`) es un error, no un dato.
- Respuesta uniforme por NAS: `{"nas", "ok", "datos"}` o `{"nas", "ok": false, "error"}`.
  Con `todos`, una lista con una entrada por NAS; el fallo de uno no tapa a los demás.
- Salidas largas se recortan a un máximo de filas y se marca `"truncado": true`.
- Las funciones no validadas con datos reales (port trunking, VLAN, QuFirewall, SAI) se
  incluyen con `"no_probado": true`.

## 6. Diferencias entre sistemas

- Detección por NAS, una vez por sesión: sistema (`hero` si existe `zpool`, si no `qts`),
  modelo y firmware (de `/etc/default_config/uLinux.conf`; el de `/etc/config` puede estar
  obsoleto), y rutas de paquetes (de `Install_Path` en `/etc/config/qpkg.conf`).
- Cada comando declara para qué sistema vale (`ambos`, `hero`, `qts`).
- No se fija ninguna ruta que cambie entre NAS: carpeta de VMs, dispositivos NVMe, sensores
  `hwmon`, carpeta de cada paquete.
- Las secciones `[Network]` y `[ethX]` de `uLinux.conf` son falsas: no se usan.

## 7. Configuración

- `userConfig` del plugin (se pide al activarlo): `ssh_user` (texto) y `ssh_password`
  (texto, `sensitive`). Llegan a cada servidor por `env` con `${user_config.CLAVE}`.
  Comprobado el 2026-10-13 con un plugin mínimo en Claude Code 2.1.296 sobre Windows:
  - Los valores llegan exactos al proceso, también con espacios, comillas, `$`, `%` y `ñ`.
  - Mientras falte una opción obligatoria, los servidores del plugin no se cargan.
  - El usuario queda en `settings.json` (`pluginConfigs`) y la contraseña en
    `.credentials.json` (`pluginSecrets`) de la carpeta de configuración de Claude Code.
    **En Windows ese fichero está en texto claro**, protegido solo por los permisos del perfil.
  - Se cambia con `/plugin configure qnap-tools` o, sin interfaz, con
    `claude plugin configure qnap-tools@<marketplace> --values-stdin` (un objeto JSON; las
    opciones que no se mandan se conservan). Hay que reiniciar Claude Code para aplicarlo.
  - Al desinstalar se borran la carpeta de datos, la contraseña y el usuario guardados.
- Carpeta de datos: `${CLAUDE_PLUGIN_DATA}` (`<config>/plugins/data/<plugin>-<marketplace>/`;
  llega sustituida en la definición de los servidores y como variable de entorno del proceso), con
  `inventario.toml`, `id_ed25519`,
  `id_ed25519.pub` y `known_hosts`. Se borra al desinstalar el plugin: `inventario_exportar`
  existe para eso, y el README lo avisa.
- Los servidores MCP se definen en línea en `plugin.json` (`mcpServers`), no en un `.mcp.json`
  en la raíz: ese fichero lo cargaría Claude Code como servidores de proyecto al trabajar en el
  repositorio, con las variables del plugin sin sustituir.
- Inventario, una copia por ordenador, sin secretos:

  ```toml
  [nas.nas1]
  host = "192.0.2.10"
  port = 22
  ```

  Campos opcionales por NAS: `user` (excepción al usuario común) y `auth`.
- La ruta del inventario es configurable (`QNAP_TOOLS_INVENTARIO`) para poder apuntar más
  adelante a un fichero común.

## 8. Entregas

1. **Base y redes:** núcleo, `qnap-flota`, `qnap-redes`, plugin instalable en local.
2. **Discos y carpetas.**
3. **Virtualización y contenedores.**
4. **Logs y avisos**, y publicación (PyPI y GitHub).

Cada entrega deja un plugin que funciona con lo que lleva hasta ese momento.

## 9. Sin resolver

- El flujo interactivo de `/plugin configure` (lo que ve el usuario al activar el plugin) no
  se ha visto: la comprobación se hizo por la CLI, que según su ayuda guarda por la misma vía.
  Se verá al instalar el plugin real.
- Orden que agota su tiempo: el plugin deja de esperarla y cierra su canal, pero el proceso
  sigue vivo en el NAS hasta que termina por sí solo (medido en QuTS hero con `sleep`, con y
  sin `sudo`; el NAS no tiene la utilidad `timeout`). Todas las órdenes del plugin son lecturas
  acotadas, así que acaban; una que se colgara de verdad quedaría hasta el reinicio. Posible
  mejora: un vigilante en el propio NAS (`setsid` + `kill` al grupo), sin probar.
- Persistencia de la clave SSH tras un reinicio del NAS: pendiente del próximo reinicio.
- Orden de la primera conexión (revisión final de la entrega 1): `nas_alta` y `nas_enrolar`
  fijan la clave de host y envían la contraseña común en la misma conexión, así que la huella
  se coteja cuando la contraseña ya ha salido. **Decidido por el usuario (2026-10-14): se
  mantiene así, con avisos** (instrucciones del servidor, skills y README); no se hace el alta
  en dos pasos.
- Texto del NAS como entrada del modelo: lo que devuelve un NAS (nombres de equipo, de proceso,
  de servicio) puede contener texto escrito por terceros. El nombre de cliente DHCP se reduce
  a caracteres de nombre de equipo y se acota a 63; el resto no se filtra.
- Las herramientas no declaran anotaciones MCP (`readOnlyHint`); el servidor atiende cada
  llamada en su bucle principal, así que no responde a otras mientras dura una consulta larga.
