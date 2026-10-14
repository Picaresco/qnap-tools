# Mejoras propuestas para qnap-tools (2026-10-14)

Ideas para que el plugin ayude mas en la resolucion de problemas y en los procesos de IT. Todas
mantienen el plugin en SOLO LECTURA (decision del usuario del 2026-10-13). Ninguna esta hecha.

Orden recomendado: 1 y 2 primero; despues 3 y 4; el resto segun haga falta.

| # | Mejora | Problema que resuelve | Esfuerzo |
|---|---|---|---|
| 1 | Revision de la flota (skill `/qnap-tools:revision`) | "Que NAS necesita atencion hoy" | Bajo |
| 2 | Copias de seguridad | "Se hicieron los backups?" | Medio |
| 3 | "El NAS va lento" | Que disco o proceso genera la carga | Bajo-medio |
| 4 | Cronologia de un incidente | "Que paso anoche a las 3" | Medio |
| 5 | Tendencia de espacio | Cuanto crece cada volumen y cuando se llena | Medio |
| 6 | Acceso a carpetas | "No puedo entrar" / "no puedo borrar, esta en uso" | Medio |
| 7 | Que ha cambiado | Control de cambios y causa de una averia | Medio-alto |
| 8 | Seguridad y caducidades | Certificado, servicios expuestos, firmware | Medio |

## 1. Revision de la flota

- Skill del plugin que llama a las herramientas que ya existen, en todos los NAS: almacenamiento
  (`almacenamiento_resumen`, `raid_estado`), discos (`discos_fisicos`, avisos SMART), hardware
  (`salud_hardware`), sistema (`sistema_estado`: motores, volcados, firmware), virtualizacion
  (`virtualizacion_resumen`), accesos fallidos (`accesos`) y kernel (`kernel`, nivel 3).
- Devuelve una lista priorizada: que pide accion hoy, que vigilar, que esta bien. Con fecha y
  NAS en cada punto, y lo que no se pudo leer (los `errores` de cada herramienta) aparte.
- Se puede programar a diario (tarea programada de Claude Code) y mandar el resultado por
  correo o Telegram.
- Sin codigo nuevo en el NAS: solo la skill (y quiza una herramienta que agrupe los avisos si
  la skill resulta lenta con muchos NAS).

## 2. Copias de seguridad

- Hoy el plugin no dice si los backups funcionan. Dar los trabajos de Hybrid Backup Sync (HBS 3)
  y de la replicacion de instantaneas: nombre, origen y destino, ultimo resultado, fecha, fallos
  y si esta programado.
- Sin explorar: donde guarda HBS su estado y su historial (base propia o ficheros), y que se
  puede leer sin abrir sesion en QTS. En `/etc/logs` hay una carpeta `qsnaprep` (replicacion de
  instantaneas). Explorar en el NAS de laboratorio creando un trabajo de prueba desde la web y
  deshaciendolo despues; validar luego en un QTS.
- Cuidado: no leer credenciales de destinos remotos (nube, rsync, NAS remoto).

## 3. "El NAS va lento"

- Convertir `pruebas/diag_carga.py` en herramienta (pata discos o logs): dos muestras de /proc
  separadas unos segundos -> E/S por disco y por proceso, latencias, procesos en estado D.
- Caso real que ya resolvio: un QTS con carga 13-22 por un RAID 5 con cinco discos SMR que
  respondian en segundos frente a milisegundos de los CMR del mismo grupo.

## 4. Cronologia de un incidente

- `cronologia(nas, desde, hasta)`: eventos, kernel, accesos y avisos del escritorio en una sola
  linea de tiempo ordenada, con la fuente de cada linea. Hoy hay que pedir cuatro herramientas y
  cruzarlas a mano.
- Ojo con las horas: eventos, accesos y kernel van en hora local del NAS; avisos en UTC.
  Unificar (UTC con Z, o local con el desfase de cada fecha).

## 5. Tendencia de espacio

- En `/etc/logs/storage_usage_history` (carpeta) el NAS guarda un historial de ocupacion; formato
  sin mirar. Con el: crecimiento por volumen o pool y dias hasta llenarse.
- Si no sirve: guardar la ocupacion en la carpeta de datos del plugin en cada consulta y
  calcular la tendencia con eso (menos datos al principio).

## 6. Acceso a carpetas

- Usuarios y grupos, permisos efectivos de un usuario en una carpeta (Samba + ACL si las hay),
  cuotas, y sesiones SMB abiertas con sus ficheros (quien tiene abierto un fichero).
- Sin explorar en el producto: `smbstatus` (si existe y si es inocuo), ACL avanzadas de QNAP.
  No leer `smbpasswd`, `shadow` ni nada con hashes.

## 7. Que ha cambiado

- Guardar una foto de la configuracion (carpetas y sus permisos, usuarios y grupos, red,
  cortafuegos, tareas, aplicaciones y versiones) en `${CLAUDE_PLUGIN_DATA}` y compararla con la
  anterior: "que cambio desde ayer / desde la ultima revision".
- Es la unica que guarda estado del NAS en el ordenador: decidir cuanto se guarda y cuanto
  tiempo, y que nunca incluya secretos.

## 8. Seguridad y caducidades

- Caducidad del certificado de la web (solo la parte del certificado, nunca la clave privada),
  servicios expuestos (UPnP, SSH, Telnet, FTP, puertos abiertos), firmware atrasado, cuenta
  `admin` activa, bloqueo automatico de IP, Security Counselor si esta instalado.

## Como validar cada una

Igual que las validaciones del 2026-10-14: configurar la funcion desde la web del NAS de
laboratorio (QuTS hero), leerla con el plugin, deshacerla y comprobarlo por SSH; prueba de no
escritura (`pruebas/efectos.py --producto <pata>`); y despues una pasada de solo lectura por un
QTS (en los QTS de produccion solo lectura, nunca cambios).
