# Patrones de error vistos en las revisiones de qnap-tools

Mecanismos, no instancias: cada uno se ha dado al menos una vez y conviene buscarlo en sitio
nuevo cada vez que se anade una orden, un parser o una herramienta. Las instancias concretas
estan en `docs/review-findings.md` (2026-10-15) y en los anexos de los planes de cada entrega.

## 1. "No se pudo leer" disfrazado de "no hay"
- **Senal**: `2>/dev/null`, `; true`, `|| true`, `valida=None`, un `for` que no casa nada y
  devuelve `[]`, un `continue` ante una linea rara, un `.get(x, [])`.
- **Trampa**: el fichero existe pero no se puede leer (permisos, ruta de otra version) y la
  herramienta responde "lista vacia" con `ok: true`. Peor en datos de seguridad (IPs bloqueadas).
- **Ejemplo**: `BLOQUEO_IP` y `DDNS` de redes (2026-10-15); antes, `; true` en varias ordenes
  de la entrega 1. Patron correcto: `[ ! -e f ] || cat f` con `rc_cero`, y el parser exige el
  marcador (`==lineas N` con numero).

## 2. El valor vacio que no es `None`
- **Senal**: `if x is None:` como guardia y un llamador que pasa `[]`, `{}` o `""` tras un
  `except`.
- **Trampa**: el "no lo se" se convierte en "no hay ninguno" y el calculo siguiente afirma algo
  falso con todos los elementos (p. ej. "faltan todos los discos").
- **Ejemplo**: `almacenamiento_resumen` pasa `{}` a `_raid_qts(bahias=None)` cuando la lista de
  discos fallo (HIGH, 2026-10-15). Regla: lo desconocido viaja como `None` hasta el final y el
  consumidor lo trata ("no se ha podido determinar"), nunca como coleccion vacia.

## 3. Final de canal sin codigo de salida
- **Senal**: `recv_exit_status()` de paramiko devuelve -1 si el canal se cerro sin estado;
  `exit_status_ready()` es cierto con el canal cerrado.
- **Trampa**: una caida del transporte a mitad de orden no es `ErrorConexion` ni timeout: es un
  `Resultado(rc=-1, salida_parcial)`, y los validadores que no miran el rc lo aceptan.
- **Ejemplo**: `transporte.ejecutar` + `_comprobar` (2026-10-15). Regla: rc -1 es siempre error;
  si el transporte ya no esta activo, es `ErrorConexion` (reintento).

## 4. Cache que sobrevive a la conexion
- **Senal**: un `dict` por NAS que solo se vacia en la baja; `_soltar` que no lo toca; docstring
  que dice "una vez por conexion" y codigo que hace "una vez por proceso".
- **Trampa**: el NAS cambia (firmware, reinstalacion) y el servidor sigue contestando lo viejo
  con `ok: true` durante dias.
- **Ejemplo**: `Flota._perfiles` (2026-10-15). Regla: invalidar al crear una conexion nueva.

## 5. Estado leido antes de la accion que lo cambia
- **Senal**: `datos["x"] = leer_estado()` seguido de una operacion que puede reconectar o
  cambiar ese estado.
- **Trampa**: la herramienta de diagnostico informa del estado anterior al diagnostico.
- **Ejemplo**: `nas_comprobar` lee `flota.metodo(n)` antes de `lanzar` (2026-10-15). Regla: leer
  despues, y avisar cuando lo configurado (`auth`) y lo ocurrido (`metodo`) no coinciden.

## 6. `except` demasiado ancho que decide algo permanente
- **Senal**: `except ErrorConexion: return False` donde `False` se escribe en un fichero de
  configuracion.
- **Trampa**: un corte de red se graba como "el NAS rechaza la clave" para siempre, y ninguna
  herramienta lo reintenta.
- **Ejemplo**: `_acepta_clave` en `nas_alta` (2026-10-15). Regla: tres resultados (si, no, no se
  pudo probar) y lo permanente solo con "no".

## 7. Codigo numerico con un solo valor especial tratado
- **Senal**: `if codigo == X and motivo == Y:` con una tabla de motivos de la que solo se usa
  uno.
- **Trampa**: los demas motivos caen en el caso "normal" sin aviso (VM caida = VM apagada).
- **Ejemplo**: `state.reason` de libvirt: solo `SAVED` (2026-10-15). Regla: tabla completa de
  motivos, con los que son problema marcados.

## 8. Fila entera a numero cuando el origen escribe `-`
- **Senal**: `_entero(f[i])` sobre columnas de `zpool list`, `zfs list`, `df`, SMART; existe un
  `_tamano` que ya admite `-`/`none` y no se usa en todos los sitios.
- **Trampa**: un pool UNAVAIL tira la herramienta entera, justo cuando mas falta hace; y se
  pierden los avisos ya calculados antes de esa lectura.
- **Ejemplo**: `pools()` (2026-10-15). Regla: todo lo que un comando de consulta puede dar como
  `-` se parsea a `None`, y las lecturas obligatorias van antes de las accesorias o estas van con
  `_extra`.

## 9. Sin aislamiento de fallo en una coleccion
- **Senal**: un parser que recorre N elementos (discos, VMs, contenedores) y lanza `ValueError`
  al primero que no entiende.
- **Trampa**: el elemento roto (fichero SMART vacio del disco moribundo) oculta los datos de
  los N-1 sanos.
- **Ejemplo**: `smart_todos`, `discos_salud` (2026-10-15). Regla: error por elemento en
  `errores`, con su identificador, y `None` solo en ese elemento.

## 10. La misma funcion en dos patas con distinta marca
- **Senal**: dos herramientas que leen la misma `Comando` con el mismo parser y una la marca
  (`no_probado`, `_extra`) y la otra no.
- **Trampa**: la marca vive en el servidor y no en la orden, asi que se olvida al reutilizarla.
- **Ejemplo**: `SMART_UMBRALES` en `disco_smart` (con `no_probado`) y en `alertas_config` (sin)
  (2026-10-15). Regla: la propiedad va en la `Comando` y `Base` la aplica sola.

## 11. Mensaje que manda a una herramienta que no puede hacerlo
- **Senal**: un texto de error que dice "ejecuta X" sin que X tenga el parametro o la entrada
  que ese caso necesita.
- **Trampa**: callejon sin salida (huella huerfana: `HostCambiado` -> `nas_baja` -> "no hay
  ningun NAS").
- **Ejemplo**: 2026-10-15. Regla: cada remedio citado en un mensaje se prueba en el escenario que
  lo provoca; si hace falta tocar un fichero a mano, el mensaje da la ruta.

## 12. Dato real copiado "de ejemplo" a una prueba
- **Senal**: un UUID, serie, nombre de VM o de contenedor con pinta real en `tests/`.
- **Trampa**: se versiona y se publica. Paso tres veces en la entrega 3 y una en la 0.4.2.
- **Regla**: `tests/test_higiene.py` y `prepara_publicacion.py` lo cazan; los ejemplos son
  siempre los de documentacion (`12345678-9abc-4def-...`, 192.0.2.x).
