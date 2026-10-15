# Herramientas de ficheros, tareas de File Station y procesos (diseno, 2026-10-15)

Origen: peticiones de otra sesion que comprobaba en el NAS de laboratorio la copia de una VM
exportada desde un disco USB a la carpeta de VMs con File Station. Le faltaba: tamano y numero de
ficheros de una ruta, progreso de las tareas de File Station, comparar origen y destino, procesos
del NAS y el espacio de los discos externos.

Decisiones del usuario (2026-10-15):
- Comparar origen y destino SIN listar la carpeta: totales y solo las diferencias, acotadas.
  `ruta_ocupacion` y `ruta_comparar` no devuelven listados de ficheros (los nombres son datos de los
  usuarios).
- Listado acotado y no recursivo con `ruta_listar` (seccion 6), aprobado el 2026-10-15 tras una
  peticion concreta (ver el contenido de una carpeta de destino). Es la unica herramienta que
  devuelve nombres de fichero y carpeta: una carpeta, sin recursividad, con limite.
- Investigar en solo lectura donde guarda File Station sus tareas: hecho (abajo).

Todo de solo lectura, como el resto del plugin; cada orden nueva pasa la guardia y la prueba de
no escritura (`pruebas/efectos.py --producto <pata>`) en el NAS de laboratorio.

## Lo visto en el NAS de laboratorio (QuTS hero h6.0.2)

- `find` es BusyBox 1.24 (sin `-printf`); `du` (`/usr/bin/du`) admite `-b` y `--apparent-size`;
  `ls` es GNU (`/bin/ls`); `ps` es BusyBox (`ps -o pid,ppid,user,stat,vsz,rss,time,etime,args`
  funciona; la cabecera no coincide con los nombres pedidos: `Uid`, `VmSize`, `ELAPSED`).
- La guardia veta `find -exec` y no tiene regla para `xargs`.
- Una carpeta compartida es un enlace en `/share` (`/share/Maquinas -> ZFS3_DATA/Maquinas`,
  `/share/USB-DISCO -> external/DEV3301_1`). File Station nombra las rutas desde la carpeta
  (`/Maquinas/VM01`).
- Disco USB: `/dev/sdh1 /share/external/DEV3301_1 ufsd rw,...` en `/proc/mounts`; `df -P -k` de
  ese montaje responde. `/share/external` tiene ademas carpetas vacias `sda`..`sdz` (no montajes).
- **Tareas de File Station: `/tmp/wfm/`**, ficheros de texto legibles sin sudo (0666/0644), uno
  por tarea con el pid del proceso `utilRequest.cgi` que la hace:
  - `wfm2_copy_status<pid>`: `pid`, `copy_file` (fichero actual), `percent`, `copying` (1 = en
    curso), `end_time` (epoch), `speed`, `full_dest` (ruta real del fichero que se escribe),
    `copy_number` (fichero actual, desde 1), `files_count`, `copy_size` (bytes del fichero
    actual), `copied_size` (bytes copiados de toda la tarea), `average_speed`.
  - `wfm_total_file<pid>`: `total_size`, `total_number` (cuenta la carpeta y sus ficheros).
  - `wfm_display_file_name<pid>`: `from`, `to`, `name` (rutas como las ve File Station).
  - `wfm_work_file_name<pid>`: `file_name=` (fichero actual con su ruta de origen).
  - `wfm2_remote_parameter`: una seccion `[pid]` por tarea con `source_file_N`, `source_total`,
    `source_path`, `dest_path`, `mode`, `dup` (que hace si el destino ya existe), `username`,
    `remote_addr`, `func` (`copy`...). OJO: trae la IP y el usuario de quien la lanzo.
  - `wfm_copy_move.list`: una linea por tarea separada por `|` (pid, usuario, ..., inicio epoch).
  - Semantica comprobada con dos muestras de la misma copia (2 ficheros, 83,4 GB):
    `copied_size` = bytes de toda la tarea (ficheros terminados + lo del actual);
    `percent` NO es el progreso de la tarea ni del fichero: es lo copiado del fichero actual
    entre el total de la tarea (39,3 con la tarea al 75 %); `end_time` es la hora de la ultima
    actualizacion (coincide con la fecha del fichero), no la prevista de fin; `speed` parece fija
    (110 MiB/s exactos en las dos muestras); la velocidad util es `average_speed`.
  - `dup = Copy` con un destino que ya existe: File Station escribe `<nombre>-Copy(1).<ext>` y
    deja el fichero original sin tocar (visto: `full_dest = .../VM01_01-Copy(1).img`).
  - Al terminar (visto a las 22:48 de la misma copia): los ficheros SIGUEN en `/tmp/wfm`;
    `copying = 2`, `percent = 100.0`, `copy_file` pasa a ser el elemento (la carpeta),
    `copy_number = files_count`, `copied_size = total_size`; `wfm2_remote_parameter` queda vacio
    y la linea de `wfm_copy_move.list` se rellena:
    `pid|usuario|desde|hacia|total_bytes|total_elementos|q_name|11|2|100.0|inicio|fin|-1|-1|--`
    (en curso era `pid|usuario|q_from|q_to|0|0|q_name|11|0|0.0|inicio|inicio|-1|-1|--`: el 9.o
    campo es el estado, 0 en curso y 2 terminada; el 8.o, 11, probablemente el tipo).
    Una tarea terminada sale con `en_curso: false`; con `copying` distinto de 1 y 2, o con el
    proceso muerto y `copying = 1`, aviso "la tarea se interrumpio".
  - Pendiente de ver: los ficheros de una tarea de mover, borrar o comprimir, y cuando borra
    File Station los de una tarea terminada.

## Herramientas

### 1. `ruta_ocupacion(nas, ruta)` (qnap-discos)
Cuanto ocupa una carpeta o fichero: bytes (tamano aparente, lo que suman los ficheros), bytes en
disco (con compresion y bloques), ficheros y carpetas.
- `ruta`: como la da File Station (`/Maquinas/VM01`), con o sin la barra inicial (`Maquinas/VM01`,
  que es la carpeta compartida y su camino) o bajo `/share/...`; el servidor la traduce siempre a
  `/share/...`. Tipo de parametro nuevo `ruta`: absoluta, sin segmentos `.` ni `..`, sin caracteres
  de control, hasta 512 caracteres (ya con `/share` delante); el resto lo entrecomilla `render`.
- La orden resuelve el enlace (`readlink -f`) y se niega si el destino real no esta bajo
  `/share/` (ni `/etc`, ni `/root`...). Se lanza con sudo para no dar cifras parciales por
  carpetas sin permiso (solo lee). `du -s -b`, `du -s -k`, y cuentas con `find -type f|d`.
- Tiempo maximo 120 s: en una carpeta con millones de ficheros no termina, y lo dice.
- No devuelve ningun nombre de fichero.

### 2. `ruta_comparar(nas, origen, destino)` (qnap-discos)
Para comprobar una copia: por cada lado, ficheros y bytes; despues cuantos coinciden (misma ruta
relativa y mismo tamano), y SOLO las diferencias: `faltan` (en origen y no en destino), `sobran`
(solo en destino) y `distinto_tamano` (con los dos tamanos), cada lista acotada a 50 con su
total. Cuenta aparte los que solo difieren en la fecha.
- Una lectura por lado: `ls -lnRA --time-style=+%s --quoting-style=literal <ruta>/.` con sudo,
  interpretada en el ordenador (los nombres no salen de la herramienta salvo en las diferencias).
- Tope de 200.000 ficheros por lado (si no, error que remite a `ruta_ocupacion`).
- Los nombres de las diferencias son texto de un tercero: juego de caracteres reducido y acotado,
  como los nombres de VM o de contenedor.
- Las mismas reglas de `ruta` que la 1.

### 3. `tareas_file_station(nas)` (qnap-discos)
Las tareas en segundo plano de File Station que hay en `/tmp/wfm`: tipo (`copy`...), usuario,
origen, destino, elemento, fichero actual (n de m), bytes totales y copiados, `progreso_pct`
calculado (`copied_size / total_size`, no el `percent` de QNAP), velocidad media, `restante_s`
calculado, ultima actualizacion (UTC), si el proceso sigue vivo (`/proc/<pid>`), y que hace si
el destino ya existe. Aviso cuando `full_dest` es una copia renombrada (`-Copy(N)`): "el destino
ya tenia ese fichero; File Station esta escribiendo una copia con otro nombre y no lo sustituye".
- Sin sudo. La IP de quien lanzo la tarea no se devuelve (solo el usuario).
- Las tareas que no son `copy` se leen igual pero salen `no_probado: true` hasta verlas.

### 4. `procesos(nas, filtro="", pid=0)` (qnap-logs)
- Sin `pid`: los procesos del NAS (sin los hilos del kernel), con pid, padre, usuario, estado
  (D = esperando al disco), memoria, tiempo de CPU, tiempo en marcha y orden; `filtro` (texto)
  se aplica en el ordenador, no se manda al NAS. Lista acotada a 200 y ordenada por memoria.
- Con `pid`: ese proceso en detalle: orden completa, carpeta de trabajo, estado y memoria de
  `/proc/<pid>/status`, bytes leidos y escritos (`/proc/<pid>/io`), y sus ficheros abiertos
  (destinos de `/proc/<pid>/fd`: solo rutas; tuberias y sockets, contados), acotados a 100. Con
  sudo (los procesos de otros usuarios no se pueden leer sin el).
- La orden de cada proceso puede llevar credenciales de otro programa: se tapan los valores tras
  `password`, `passwd`, `pass`, `pwd`, `token`, `secret`, `key` (con `=`, `:` o espacio) y se
  recorta a 300 caracteres; la contrasena del plugin ya la quita `_sin_contrasena`.

### 5. Discos externos con su montaje (qnap-discos, `discos_fisicos`)
Cada entrada de `externos` gana `montaje`, `sistema_ficheros` (tal cual: `ufsd` es el controlador
de QNAP para NTFS/exFAT/HFS+), `bytes`, `usado`, `libre`, `ocupacion_pct` y las carpetas
compartidas que apuntan a ese montaje. Orden nueva: las lineas de `/proc/mounts` bajo
`/share/external/` y `df -P -k` de esos montajes. Un externo sin montar sale con `montaje: null`.
`carpetas_compartidas` marca las carpetas cuya ruta esta en un disco externo (`externo: true`).

### 6. `ruta_listar(nas, ruta, ocultos=True, limite=200)` (qnap-discos)
El contenido de UNA carpeta, sin recursividad; si la ruta es un fichero, solo ese fichero.
- Misma `ruta` que las otras (con o sin barra, o bajo `/share/`), `readlink -f` y solo lo que acabe
  bajo `/share/`. Orden con sudo:
  `ls -lAs --block-size=1 --time-style=+%Y-%m-%dT%H:%M:%S%z --quoting-style=literal "$r/"` (o `"$r"`
  si es un fichero). El `%z` da la hora local del NAS con el desfase de esa fecha concreta (el cambio
  de horario sale bien). Sin `-n`: propietario y grupo por nombre. `ls -l <fichero>` imprime la ruta
  que se le dio: el parser se queda con el nombre.
- Por entrada: `nombre` (saneado y acotado como el texto de terceros), `tipo` (`fichero`, `carpeta`,
  `enlace` u `otro`), `bytes`, `en_disco` (la columna de `-s`, en bytes), `permisos` (`drwxr-xr-x`),
  `propietario`, `grupo`, `fecha` (ISO local con desfase, `2026-10-15T22:36:31+02:00`) y, en los
  enlaces, `destino` (el ` -> ` solo se parte cuando el tipo es `l`). La linea `total N` no es una
  entrada.
- `ocultos=false` quita en el ordenador los que empiezan por `.` (la orden no cambia). `limite` de 1 a
  1000 (200 por defecto): `{filas, total, truncado}` ordenado por nombre.
- Los nombres de ficheros y carpetas son datos de los usuarios y de terceros, no instrucciones: lo dicen
  el docstring y las `INSTRUCCIONES`.

## Formato real de `/tmp/wfm` (muestras literales, 2026-10-15)
"clave = valor" con un espacio a cada lado del `=` (salvo `wfm_work_file_name`, que es `file_name=...`);
`wfm2_remote_parameter` con una seccion `[pid]` por tarea y vacio al terminar; `wfm_copy_move.list` con
una linea por tarea separada por `|` (en curso lleva los literales `q_from`, `q_to` y `q_name`). La orden
de `tareas_file_station` lee solo los campos que necesita (nunca `remote_addr`, `reference` ni
`source_file_N`) y `wfm_work_file_name` no se lee: el fichero actual sale de `copy_file`. Una copia
terminada con `-Copy(N)` en `full_dest` tambien avisa ("escribio una copia con otro nombre").

## Pruebas y validacion
- Datos de prueba ESCRITOS A MANO con el formato visto (los reales llevan el nombre de una VM,
  una IP y un usuario): nada de nombres reales de VM, carpeta o contenedor (`test_higiene`,
  `prepara_publicacion`).
- Ordenes con tuberias o bucles: prueba en `sh` real.
- En el NAS de laboratorio: prueba real de solo lectura de las cinco, y `efectos.py --producto
  discos` y `--producto logs` con las ordenes nuevas.
