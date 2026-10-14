# -*- coding: utf-8 -*-
"""Ordenes de la pata de virtualizacion y contenedores. Todas de solo lectura.

Salen de la exploracion hecha contra NAS reales (pruebas/catalogo/virtualizacion*.json).
Valen igual en QTS y en QuTS hero: lo que cambia entre NAS es si Virtualization Station y
Container Station estan instalados y activos, y eso lo dice el perfil del NAS.

virsh va SIEMPRE con -r (libvirt rechaza cualquier escritura en esa conexion) y con
-c qemu:///system: sin el, un usuario que no es root arranca un libvirt propio, que escribe
en su carpeta y devuelve una lista vacia sin dar error.
"""
from ..comandos import Comando, no_vacia, rc_cero

VIRSH = "LD_LIBRARY_PATH=/QVS/usr/lib:/QVS/usr/lib64:/QVS/lib /QVS/usr/bin/virsh -r -c qemu:///system"
QEMU_IMG = "LD_LIBRARY_PATH=/QVS/usr/lib:/QVS/usr/lib64:/QVS/lib /QVS/usr/bin/qemu-img"
# Las ordenes que recorren las VMs empiezan diciendo a que libvirt hablan: si la conexion
# falla, la lista sale vacia y el bucle no da error, y sin esa linea pareceria "no hay VMs".
URI = "echo uri=$(%s uri); " % VIRSH
TODAS = "$(%s list --all --uuid)" % VIRSH

# --- anfitrion ----------------------------------------------------------------------------------

# CPU y memoria del NAS, y que servicios de virtualizacion tienen su socket abierto.
ANFITRION = Comando(
    "anfitrion",
    "echo hilos=$(grep -c ^processor /proc/cpuinfo); grep -m1 'model name' /proc/cpuinfo; "
    "echo virt=$(grep -m1 -o -E 'vmx|svm' /proc/cpuinfo); echo carga=$(cat /proc/loadavg); "
    "grep -E '^(MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo; "
    "for s in /QVS/var/run/libvirt/libvirt-sock-ro /var/run/docker.sock /var/run/system-docker.sock; "
    "do if [ -e $s ]; then echo socket=$s; fi; done")

# --- maquinas virtuales (Virtualization Station) ------------------------------------------------

# Estado, CPU, memoria, discos y red de todas las VMs, tambien de las apagadas.
VM_ESTADISTICAS = Comando("vm_estadisticas", URI + "%s domstats" % VIRSH, timeout=30)

# De la definicion de cada VM, solo las lineas de estos elementos: nombre y descripcion, sistema,
# memoria, vCPU, firmware, arranque, discos, interfaces de red y consola. Nunca con
# --security-info, ni los metadatos de VS (que repiten la consola). El patron no puede llevar el
# signo "mayor que" (una plantilla con el se rechaza): se cierra con "lo que no sea letra".
ELEMENTOS_XML = ("qvs:name", "qvs:os", "qvs:auto_start_delay", "qvs:snapshot", "description", "memory",
                 "currentMemory", "vcpu", "type arch", "loader", "boot dev", "/?disk", "/?backingStore",
                 "source (file|dev|bridge|network)", "target dev", "driver name", "/?interface",
                 "mac address", "model type", "graphics", "/?hostdev", "tpm")
VM_XML = Comando(
    "vm_xml",
    URI + "for d in %s; do echo \"== $d\"; %s dumpxml $d | grep -E '<(%s)[^A-Za-z:]'; done"
    % (TODAS, VIRSH, "|".join(ELEMENTOS_XML)),
    timeout=40)

# Direcciones de una VM en marcha segun la tabla ARP del NAS (el agente del invitado no se
# puede consultar en solo lectura). Puede no dar ninguna.
VM_IP = Comando("vm_ip", "%s domifaddr {uuid} --source arp" % VIRSH, {"uuid": "uuid"})

# Dos lecturas de las VMs en marcha separadas 5 segundos, cada una con el reloj del NAS, diciendo
# antes a que libvirt habla y despues como termino domstats: sin eso, una lectura fallida
# pareceria "ninguna en marcha".
_LECTURA = (URI + "cat /proc/uptime; %s domstats --list-running --cpu-total --vcpu --balloon --interface --block; "
            "echo ==rc $?" % VIRSH)
VM_USO = Comando("vm_uso", "%s; sleep 5; echo ==5s; %s" % (_LECTURA, _LECTURA), timeout=40)

# La cadena de imagenes de cada disco (cada instantanea de VS es una capa): formato, tamano
# virtual y lo que ocupa cada capa. -U abre la imagen sin bloquearla aunque la VM este en marcha.
# La ruta va de la primera barra al final de la linea y se lee con 'while read': la carpeta de
# una VM lleva su nombre, que puede tener espacios, y un 'for' la partiria.
# La cadena se recorre capa a capa y no con --backing-chain: info solo abre el fichero que se le
# da, y de cada capa se sigue su base solo si esta en las carpetas compartidas ("/share/...",
# donde VS guarda las imagenes). Una base que fuera otra cosa (nbd://, http://...) haria que el
# NAS se conectara a donde dijera la imagen, y un dispositivo o una tuberia podria colgar la
# orden. Como mucho
# MAX_CAPAS_IMAGEN capas; si quedan mas, "!! cadena cortada".
MAX_CAPAS_IMAGEN = 64
VM_IMAGENES = Comando(
    "vm_imagenes",
    URI + "for d in %s; do echo \"== $d\"; "
    "%s domblklist --details $d | grep ' disk ' | grep -o -E '/.*[^ ]' | while read -r f; do "
    "echo \"-- $f\"; for i in %s; do if [ -n \"$f\" ]; then "
    "j=$(%s info -U --output=json \"$f\"); printf '%%s\\n' \"$j\"; "
    "f=$(printf '%%s\\n' \"$j\" | grep -o -E '\"full-backing-filename\": \"/share/[^\"]*\"' | cut -d'\"' -f4); "
    "fi; done; [ -z \"$f\" ] || echo '!! cadena cortada'; done; done"
    % (TODAS, VIRSH, " ".join(str(i) for i in range(1, MAX_CAPAS_IMAGEN + 1)), QEMU_IMG),
    timeout=60, valida=no_vacia)

# Instantaneas que conoce libvirt. VS usa las suyas (externas): lo normal es que no haya.
VM_SNAP_LIBVIRT = Comando(
    "vm_snap_libvirt",
    URI + "for d in %s; do echo \"== $d\"; %s snapshot-list $d --parent; done" % (TODAS, VIRSH),
    timeout=40, valida=rc_cero)

# Instantaneas de VS: un fichero por instantanea en la carpeta de metadatos de cada VM, con su
# momento (epoch) por nombre. La carpeta sale de la definicion de la VM, no se fija. Si esa
# carpeta no esta, se dice ("!!"): no es lo mismo que no tener instantaneas.
VM_SNAP_VS = Comando(
    "vm_snap_vs",
    URI + "for d in %s; do echo \"== $d\"; "
    "%s dumpxml $d | grep -o -E '<qvs:meta_path.[^<]+' | cut -c16- | while read -r m; do "
    "[ -d \"$m\" ] || echo '!! sin carpeta de metadatos'; "
    "[ ! -d \"$m/snapshot\" ] || ls \"$m/snapshot\"; done; done" % (TODAS, VIRSH),
    timeout=40, valida=rc_cero)

# Memoria guardada de cada VM: la "suspension" de VS la guarda en <carpeta de metadatos>/<uuid>.state.
# libvirt dice "apagada, guardada" mientras no se reinicia; tras un reinicio del NAS solo dice
# "apagada" y lo unico que queda es ese fichero (visto en el NAS de laboratorio).
VM_GUARDADAS = Comando(
    "vm_guardadas",
    URI + "for d in %s; do echo \"== $d\"; "
    "%s dumpxml $d | grep -o -E '<qvs:meta_path.[^<]+' | cut -c16- | while read -r m; do "
    "[ -d \"$m\" ] || echo '!! sin carpeta de metadatos'; "
    "[ ! -f \"$m/$d.state\" ] || stat -c 'guardada %%s %%Y' \"$m/$d.state\"; done; done"
    % (TODAS, VIRSH),
    timeout=40, valida=rc_cero)

# --- contenedores (Container Station) -----------------------------------------------------------

# La carpeta de Container Station cambia de un NAS a otro: sale de la configuracion del paquete.
DOCKER = "$(getcfg container-station Install_Path -f /etc/config/qpkg.conf)/bin/docker"
# Salto de linea y tabulador escritos como texto de una plantilla de Go: info e inspect no
# traducen "\t" como hacen ps y stats, y una plantilla de orden no puede llevar saltos reales.
_NL = '{{"\\n"}}'
_TAB = '{{"\\t"}}'


def _campos(pares):
    return _NL.join("%s=%s" % par for par in pares)


CT_INFO = Comando(
    "ct_info",
    DOCKER + " info --format '" + _campos((
        ("version", "{{.ServerVersion}}"), ("driver", "{{.Driver}}"), ("raiz", "{{.DockerRootDir}}"),
        ("contenedores", "{{.Containers}}"), ("en_marcha", "{{.ContainersRunning}}"),
        ("en_pausa", "{{.ContainersPaused}}"), ("parados", "{{.ContainersStopped}}"),
        ("imagenes", "{{.Images}}"), ("cpus", "{{.NCPU}}"), ("memoria", "{{.MemTotal}}"))) + "'",
    timeout=30)

# Sin el campo Size: con el, docker ps no termina en 40 s en un NAS con 45 contenedores.
CT_LISTA = Comando(
    "ct_lista",
    DOCKER + " ps -a --no-trunc --format '{{.Names}}\\t{{.Image}}\\t{{.State}}\\t{{.Status}}\\t{{.Ports}}\\t"
    "{{.Networks}}\\t{{.CreatedAt}}\\t{{.Label \"com.docker.compose.project\"}}'",
    timeout=30, valida=rc_cero)

CT_COMPOSE = Comando("ct_compose", DOCKER + " compose ls -a --format json", timeout=30)

# De un contenedor, campos concretos y cada uno en JSON. Nunca sus variables de entorno ni su
# orden de arranque (suelen llevar contrasenas), ni las etiquetas enteras: solo las de compose.
# Las palabras de la plantilla de Go van con espacios ({{ end }}): pegadas a las llaves se
# confundirian con un parametro de la orden.
CAMPOS_DETALLE = (
    ("nombre", "{{json .Name}}"), ("imagen", "{{json .Config.Image}}"), ("creado", "{{json .Created}}"),
    ("estado", "{{json .State.Status}}"), ("salida", "{{json .State.ExitCode}}"),
    ("sin_memoria", "{{json .State.OOMKilled}}"), ("error", "{{json .State.Error}}"),
    ("inicio", "{{json .State.StartedAt}}"), ("fin", "{{json .State.FinishedAt}}"),
    ("reinicios", "{{json .RestartCount}}"),
    # un contenedor sin comprobacion de salud no tiene esa clave, y pedirla sin mas es un error
    ("salud", "{{ with (index .State \"Health\") }}{{json .Status}}{{ else }}null{{ end }}"),
    ("reinicio", "{{json .HostConfig.RestartPolicy.Name}}"), ("memoria", "{{json .HostConfig.Memory}}"),
    ("nanocpus", "{{json .HostConfig.NanoCpus}}"), ("privilegiado", "{{json .HostConfig.Privileged}}"),
    ("modo_red", "{{json .HostConfig.NetworkMode}}"),
    # de cada red, solo su direccion, su puerta de enlace y su MAC (ni alias ni identificadores)
    ("redes", "{{range $r, $v := .NetworkSettings.Networks}}{{$r}}={{$v.IPAddress}}/{{$v.IPPrefixLen}} "
              "{{$v.Gateway}} {{$v.MacAddress}};{{ end }}"),
    ("puertos", "{{json .NetworkSettings.Ports}}"), ("montajes", "{{json .Mounts}}"),
    ("proyecto", "{{json (index .Config.Labels \"com.docker.compose.project\")}}"),
    ("servicio", "{{json (index .Config.Labels \"com.docker.compose.service\")}}"),
    ("compose", "{{json (index .Config.Labels \"com.docker.compose.project.config_files\")}}"))
CT_DETALLE = Comando(
    "ct_detalle", DOCKER + " inspect --format '" + _campos(CAMPOS_DETALLE) + "' {contenedor}",
    {"contenedor": "nombre"})

# Una sola muestra de los contenedores en marcha.
CT_STATS = Comando(
    "ct_stats",
    DOCKER + " stats --no-stream --format '{{.Name}}\\t{{.CPUPerc}}\\t{{.MemUsage}}\\t{{.MemPerc}}\\t{{.NetIO}}\\t"
    "{{.BlockIO}}\\t{{.PIDs}}'",
    timeout=40, valida=rc_cero)

# No hay orden para el espacio que ocupan imagenes y contenedores: 'docker system df' recorre
# el disco para calcularlo y no termina en 60 s en un NAS con 137 imagenes (igual que el campo
# Size de 'docker ps').

# Las ultimas lineas del registro de un contenedor, cada una cortada a 500 caracteres. Lleva las
# dos salidas del contenedor (2>&1), y con ellas vendria mezclado un error del propio docker:
# por eso la ultima linea es el codigo de salida de docker ("==rc N"). El programa de un
# contenedor puede escribir lo que quiera, tambien algo que empiece como un error de docker.
CT_LOGS = Comando(
    "ct_logs",
    "(" + DOCKER + " logs --tail {lineas} {contenedor} 2>&1; rc=$?; echo; echo ==rc $rc) | cut -c1-500",
    {"lineas": "entero", "contenedor": "nombre"}, timeout=30, valida=rc_cero)

# Todas las redes en una sola consulta: driver, ambito, subredes y contenedores conectados.
CT_REDES = Comando(
    "ct_redes",
    DOCKER + " network inspect --format '" + _TAB.join((
        "{{.Name}}", "{{.Driver}}", "{{.Scope}}", "{{.Internal}}", "{{json .IPAM.Config}}",
        "{{range .Containers}}{{.Name}}={{.IPv4Address}} {{ end }}")) + "' $(" + DOCKER
    + " network ls --format '{{.Name}}')",
    timeout=40)

# Contenedores del docker interno de Container Station (los de servicio del propio paquete).
CT_INTERNOS = Comando(
    "ct_internos",
    DOCKER + " -H unix:///var/run/system-docker.sock ps -a --format '{{.Names}}\\t{{.Image}}\\t{{.State}}'",
    valida=rc_cero)

# Si hay instancias de LXD: solo los nombres de sus carpetas (las lee root). El cliente lxc no
# se ejecuta: la primera vez crea su configuracion y un certificado en la carpeta del usuario.
CT_LXD = Comando(
    "ct_lxd",
    "for d in /var/lib/lxd/containers /var/lib/lxd/virtual-machines; do echo \"== $d\"; "
    "[ ! -d $d ] || ls $d; done",
    sudo=True)
