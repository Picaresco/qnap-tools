# Reglas comunes para los agentes de exploracion

Objetivo: averiguar, para UNA pata del plugin, toda la informacion que se puede obtener de
un QNAP en modo solo lectura, que parte necesita sudo, y que NO se puede obtener.

## NAS
- `nas1`: QuTS hero 5.2.9 (ZFS), TS-X85. Tiene /QVS (Virtualization Station) y Container Station.
- `nas2`: QTS clasico 5.2.10 (md/LVM), TS-X83XU, varios discos. Sin /QVS,
  solo python2.7. Tratarlo con cuidado.

## Unica via al NAS
`.venv\Scripts\python.exe pruebas\ro.py ...` desde la raiz del proyecto (ver su docstring).
- Prohibido cualquier otra via: ni ssh, ni paramiko propio, ni otros MCP (qnap-docker incluido).
- Prohibido editar `ro.py`, `guardia.py` y `reglas/comun.json`. Si la guardia rechaza algo que
  es claramente de lectura por un defecto suyo, anotarlo en el informe final; no rodearlo.
- Los comandos nunca llevan `sudo`: lo anade el arnes con `--sudo`.

## Anadir reglas
Solo en `pruebas/reglas/<pata>.json` (lista JSON, mismo formato que comun.json; campos en el
docstring de guardia.py). Cada regla lleva en `nota` la EVIDENCIA de que es de solo lectura
(texto de la ayuda del comando, o que solo lee un fichero). Lo mas cerrada posible: `sub`,
`solo_flags`, `max_posicionales`. La guardia ya deja pasar `<binario> --help` de cualquier
ejecutable para explorar. Si hay duda de si un comando o una opcion escribe: NO anadirla ni
ejecutarla; apuntarla como "no verificado".

## Limites de lo que se ejecuta
- Solo lectura de estado y ficheros, y diagnostico ligero (ping -c, traceroute, nslookup,
  muestreos cortos). Nada de pruebas activas: autotest SMART, pruebas de velocidad, iperf.
- Nada de `find`/`du` recursivos sobre `/share` ni bucles largos. Cada comando < 40 s.
- Secretos: no volcar ficheros con contrasenas o claves (uLinux.conf entero, etc.); leer campos
  sueltos con `getcfg`. Si aparece un secreto en una salida, no copiarlo a ningun fichero ni
  al informe; anotar solo que existe y donde.
- Hay otros tres agentes en paralelo, cada uno en su pata: tocar solo los ficheros propios.

## Consejo de comillas
En PowerShell, los `$` dentro de comillas dobles se escapan con acento grave. Para comandos
con comillas o `$`, lo mas comodo es meterlos en el catalogo JSON y lanzar `ro.py bateria`.

## Entregables
1. `pruebas/reglas/<pata>.json`
2. `pruebas/catalogo/<pata>.json`:
   `{"comandos": [{"id": "...", "cmd": "...", "da": "que informacion aporta", "nas": "ambos|hero|qts"}],
     "limites": [{"que": "...", "motivo": "..."}]}`
   Si un comando solo vale para un NAS, ponerlo en `<pata>_hero.json` o `<pata>_qts.json`.
3. Lanzar `ro.py bateria <nas> <catalogo>` en los dos NAS al terminar (deja las salidas en
   `pruebas/resultados/` y dice que necesita sudo).
4. Informe final como respuesta (maximo ~60 lineas, sin prosa): tabla de lo que se obtiene
   (dato, comando, NAS, sudo si/no); lo que NO se puede obtener en solo lectura y por que;
   diferencias hero/qts; comandos "no verificados"; defectos de la guardia. No crear mas
   documentos ni tocar CLAUDE.md.
