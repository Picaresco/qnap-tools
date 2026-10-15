# -*- coding: utf-8 -*-
"""Ordenes de la pata de redes. Todas de solo lectura y validas en QTS y en QuTS hero.

Salen de la exploracion hecha contra NAS reales (pruebas/catalogo/redes.json) y ninguna
modifica ficheros (pruebas/efectos.py). La red NO se lee de las secciones [Network]/[ethX]
de uLinux.conf, que estan obsoletas: se lee del kernel (ip, /proc, /sys).
"""
import shlex

from ..comandos import Comando, no_vacia, rc_cero

ULINUX = "/etc/config/uLinux.conf"


def _campos(fichero, campos):
    """Orden que imprime 'Seccion/Clave = valor' para cada campo, leido con getcfg."""
    return "; ".join(
        "echo %s = $(getcfg %s %s -f %s)" % (
            shlex.quote("%s/%s" % (seccion, clave)), shlex.quote(seccion), shlex.quote(clave), fichero)
        for seccion, clave in campos)


# --- interfaces ---------------------------------------------------------------------

ENLACES = Comando("enlaces", "ip -br link")
DIRECCIONES = Comando("direcciones", "ip -br addr")
SYS_RED = Comando(
    "sys_red",
    "for i in /sys/class/net/*; do echo ${i##*/} estado=$(cat $i/operstate 2>/dev/null) "
    "vel=$(cat $i/speed 2>/dev/null) dup=$(cat $i/duplex 2>/dev/null) mtu=$(cat $i/mtu 2>/dev/null) "
    "mac=$(cat $i/address 2>/dev/null) carrier=$(cat $i/carrier 2>/dev/null); done")
# dos lecturas de los contadores separadas 2 s: de ahi sale el caudal actual por interfaz
TRAFICO = Comando("trafico", "cat /proc/net/dev; sleep 2; echo ==2s; cat /proc/net/dev")

# ethtool puede terminar con codigo distinto de 0 aun dando datos (p. ej. sin permiso para
# Wake-on-LAN): se exige salida, no codigo. Una interfaz virtual no tiene estadisticas.
ETHTOOL = Comando("ethtool", "ethtool {iface}", {"iface": "interfaz"}, valida=no_vacia)
ETHTOOL_DRIVER = Comando("ethtool_driver", "ethtool -i {iface}", {"iface": "interfaz"}, valida=no_vacia)
ETHTOOL_STATS = Comando("ethtool_stats", "ethtool -S {iface}", {"iface": "interfaz"}, valida=None)

# Validado con una agregacion de dos puertos sin cable (active-backup) y con las de 802.3ad de
# un QTS; una agregacion con enlace no se ha visto en real (el formato es el del kernel).
BONDING = Comando(
    "bonding",
    "for f in /proc/net/bonding/*; do [ -f $f ] && echo == ${f##*/} && cat $f; done; true",
    valida=None)
# El fichero de VLAN solo existe con el modulo cargado y solo lo lee root: si no existe no
# hay VLAN (salida vacia); si existe y no se puede leer, es un error y no "no hay".
VLAN = Comando("vlan", "[ ! -e /proc/net/vlan/config ] || cat /proc/net/vlan/config",
               sudo=True, valida=rc_cero)

# --- conmutadores virtuales -------------------------------------------------------------

PUENTES = Comando("puentes", "brctl show")
PUENTES_MAC = Comando("puentes_mac", "brctl showmacs {iface}", {"iface": "interfaz"})

# --- rutas --------------------------------------------------------------------------------

RUTAS = Comando("rutas", "ip route")
REGLAS = Comando("reglas", "ip rule")
VECINOS = Comando("vecinos", "ip neigh", valida=rc_cero)
# La carpeta de la configuracion de red, como la elige el guion de red del NAS: con
# /etc/QTS_ZFS_HA (QuTS hero) es /etc/config.local, y en /etc/config quedan copias viejas.
CARPETA_RED = "c=/etc/config; [ ! -e /etc/QTS_ZFS_HA ] || c=/etc/config.local; "
# Si el fichero no existe no hay rutas estaticas (salida vacia); si existe y no se puede leer
# es un error, no "no hay". El kernel las pone en la tabla custom_table_id, no en la principal.
RUTAS_ESTATICAS = Comando(
    "rutas_estaticas", CARPETA_RED + "[ ! -e $c/staticroute.conf ] || cat $c/staticroute.conf",
    valida=rc_cero)

# --- DNS y DHCP -----------------------------------------------------------------------------

# resolv.dnsmasq (los servidores a los que reenvia el dnsmasq del NAS) es opcional; resolv.conf
# no: si no se puede leer la orden termina con error, en vez de dar "sin servidores DNS".
DNS = Comando(
    "dns",
    "echo ==superiores && cat /etc/resolv.dnsmasq 2>/dev/null || [ ! -e /etc/resolv.dnsmasq ] && "
    "echo ==resolv && cat /etc/resolv.conf")
DHCP_SERVIDOR = Comando(
    "dhcp_servidor",
    "for f in /etc/dhcp/dhcpd_*.conf; do [ -f $f ] && echo == ${f##*/} && grep -v -E '^#|^$' $f; "
    "done; true", valida=None)
# Cada renovacion anade un bloque al fichero: se acota a las ultimas lineas, y antes se dice
# cuantas tiene para saber si lo que llega esta recortado.
LINEAS_LEASES = 1000
DHCP_LEASES = Comando(
    "dhcp_leases",
    "for f in /var/state/dhcp/*.leases; do [ -f $f ] && echo == ${f##*/} && "
    "echo ==lineas $(grep -c -v -E '^#|^$' $f) && "
    "grep -v -E '^#|^$' $f | tail -n %d; done; true" % LINEAS_LEASES, valida=None)

# --- servicios --------------------------------------------------------------------------------

# con sudo, netstat dice que proceso escucha en cada puerto
ESCUCHA_TCP = Comando("escucha_tcp", "netstat -tlnp", sudo=True)
ESCUCHA_UDP = Comando("escucha_udp", "netstat -ulnp", sudo=True)

CAMPOS_SERVICIOS = (
    ("System", "Web Access Port"), ("System", "Force SSL"),
    ("Stunnel", "Enable"), ("Stunnel", "Port"),
    ("LOGIN", "SSH Enable"), ("LOGIN", "SSH Port"),
    ("LOGIN", "TELNET Enable"), ("LOGIN", "TELNET Port"),
    ("FTP", "Enable"), ("FTP", "Port"),
    ("Samba", "Enable"), ("Samba", "Workgroup"),
    ("Appletalk", "Enable"), ("NFS", "Enable"),
    ("SNMP", "Service Enable"), ("SNMP", "Listen Port"),
    ("QWEB", "Enable"), ("QWEB", "Port"), ("QWEB", "SSL_Port"),
    ("iSCSI", "Enable"), ("iSCSI", "Port"),
    ("UPnP Service", "Enable"), ("Bonjour Service", "Enable"),
    ("TFTP Server", "Enable"), ("TFTP Server", "PORT"),
    ("System", "Server Name"),
)
SERVICIOS = Comando("servicios", _campos(ULINUX, CAMPOS_SERVICIOS))

# --- cortafuegos --------------------------------------------------------------------------------

# iptables-save solo vuelca las tablas cargadas (iptables -L puede cargar modulos)
IPTABLES = Comando("iptables", "iptables-save", sudo=True, timeout=30)

# Los nombres de clave llevan esos espacios en el fichero del NAS
SERVICIOS_BLOQUEO = (
    ("ssh", "SSH   Ban Enabled"), ("telnet", "TelnetBan Enabled"), ("ftp", "FTP   Ban Enabled"),
    ("http", "Http  Ban Enabled"), ("smb", "Samba Ban Enabled"), ("afp", "AFP   Ban Enabled"),
    ("nfs", "NFS   Ban Enabled"), ("rtrr", "RTRR  Ban Enabled"), ("rsync", "Rsync Ban Enabled"),
)
# Las listas son ficheros opcionales (ausente = vacia), pero si existen y no se pueden leer la
# orden termina con error en vez de dar una lista vacia. Cada fichero va en un subshell
# encadenado con &&: el codigo de salida de la orden es el del primero que falle.
BLOQUEO_IP = Comando(
    "bloqueo_ip",
    _campos(ULINUX, [("Ban Engine", "Ban Enabled"), ("Ban Engine", "Account Ban Enabled")]
            + [("Ban Engine", clave) for _, clave in SERVICIOS_BLOQUEO])
    + "; echo ==permitidas; ( [ ! -e /etc/config/ipsec_allow.conf ] || cat /etc/config/ipsec_allow.conf )"
    + " && echo ==denegadas && ( [ ! -e /etc/config/ipsec_deny.conf ] || cat /etc/config/ipsec_deny.conf )")

# Que el paquete QuFirewall este activo no quiere decir que el cortafuegos este encendido:
# recien instalado sigue apagado y sin perfil (validado en el NAS de laboratorio). Eso lo dice
# QuFirewall.conf ([Global] firewall_status y enable_profile); sus reglas salen en IPTABLES.
QUFIREWALL_CONF = "/etc/config/QuFirewall.conf"
QUFIREWALL = Comando(
    "qufirewall",
    "echo activo=$(getcfg QuFirewall Enable -f /etc/config/qpkg.conf); "
    "[ ! -e %(f)s ] || echo cortafuegos=$(getcfg Global firewall_status -f %(f)s); "
    "[ ! -e %(f)s ] || echo perfil=$(getcfg Global enable_profile -f %(f)s)" % {"f": QUFIREWALL_CONF})

# --- acceso remoto ----------------------------------------------------------------------------------

# De ddns.conf solo se leen los nombres de proveedor y sus campos enable y hostname:
# el resto (usuario, URL de actualizacion) no sale del NAS. Ausente o sin coincidencias (grep
# termina con 1) no es un error; ilegible (grep termina con 2) si.
DDNS = Comando(
    "ddns",
    CARPETA_RED + "echo ==myqnapcloud; "
    + _campos("/etc/config/qnapddns.conf", [
        ("QNAP DDNS Service", "Enable"), ("QNAP DDNS Service", "Host Name"),
        ("QNAP DDNS Service", "Domain Name Server")])
    + "; echo ==ddns; [ ! -e $c/ddns.conf ] || ( grep -E '^\\[|^(enable|hostname) *=' $c/ddns.conf;"
    + " [ $? -le 1 ] )")
UPNP = Comando("upnp", "echo activo=$(getcfg 'UPnP Service' Enable -f %s)" % ULINUX)
# Solo si el paquete QVPN esta activo. Los tuneles levantados salen de ENLACES; la
# configuracion de las VPN son claves y no se lee.
VPN_PRESENCIA = Comando(
    "vpn_presencia", "echo activo=$(getcfg QVPN Enable -f /etc/config/qpkg.conf)")

# --- diagnostico ligero -------------------------------------------------------------------------------

# ping y traceroute necesitan root en el NAS. Con perdida total ping termina con codigo 1
# pero da sus estadisticas: se exige salida, no codigo.
PING = Comando("ping", "ping -c 3 -W 2 {destino}", {"destino": "destino"},
               sudo=True, timeout=15, valida=no_vacia)
TRACEROUTE = Comando("traceroute", "traceroute -n -w 2 -m 15 -q 1 {destino}", {"destino": "destino"},
                     sudo=True, timeout=40, valida=no_vacia)
NSLOOKUP = Comando("nslookup", "nslookup {destino}", {"destino": "destino"}, valida=no_vacia)
