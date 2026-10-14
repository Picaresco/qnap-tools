# -*- coding: utf-8 -*-
"""Parsers de la pata de redes: texto de una orden -> estructura.

Funciones puras, una por orden de redes/comandos.py. Las claves van en castellano sin
acentos. Una salida que no se reconoce lanza ValueError: nunca se devuelven datos inventados
ni una lista vacia por no haber entendido el texto. Solo devuelven vacio las ordenes en las
que "no hay nada" es una respuesta valida (sin agregaciones, sin VLAN, sin vecinos, sin
servidor DHCP, sin rutas estaticas).
"""
import ipaddress
import re

from .comandos import LINEAS_LEASES, SERVICIOS_BLOQUEO

MAC = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
ESTADO = re.compile(r"^[A-Z][A-Z_-]*$")
DESTINO = re.compile(r"^(?:default|[0-9a-fA-F:.]+(?:/[0-9]+)?)$")
TIPOS_RUTA = ("unicast", "local", "broadcast", "multicast", "throw", "unreachable", "prohibit",
              "blackhole", "nat", "anycast")
CLAVES_RUTA = {"via": "via", "dev": "interfaz", "proto": "protocolo", "scope": "ambito",
               "src": "origen", "metric": "metrica"}
SI = ("true", "1", "yes", "on", "enable", "enabled")
NO = ("false", "0", "no", "off", "disable", "disabled")
# nombres de contador de ethtool -S que indican un problema si no estan a cero
CONTADOR_DE_ERROR = re.compile(
    r"err|drop|miss|collision|abort|underrun|overrun|runt|too_long|discard|crc|fifo|bad|fail")
# lo que no cabe en un nombre de equipo, y su longitud maxima
FUERA_DE_NOMBRE = re.compile(r"[^A-Za-z0-9._-]")
MAX_NOMBRE = 63


# --- utilidades -----------------------------------------------------------------------------

def _no_reconocida(que, linea=""):
    return ValueError("salida de %s no reconocida%s" % (que, (": %r" % linea[:80]) if linea else ""))


def _lineas(texto):
    return [linea for linea in texto.splitlines() if linea.strip()]


def _si_no(valor, que="valor"):
    v = valor.strip().lower()
    if v in SI:
        return True
    if v in NO:
        return False
    if not v:
        return None                   # el campo no existe en la configuracion de este NAS
    raise ValueError("%s no es un si/no: %r" % (que, valor[:40]))


def _numero(valor, que="valor"):
    v = valor.strip()
    if not v:
        return None
    if not v.isdigit():
        raise ValueError("%s no es un numero: %r" % (que, valor[:40]))
    return int(v)


def _dos_puntos(texto):
    """Lineas 'Clave: valor'. Una linea sin dos puntos continua el valor de la anterior."""
    campos, clave = {}, None
    for linea in _lineas(texto):
        nombre, sep, valor = linea.partition(":")
        if sep:
            clave = nombre.strip()
            campos[clave] = valor.strip()
        elif clave is not None:
            campos[clave] = (campos[clave] + " " + linea.strip()).strip()
    return campos


def _campos(lineas, que):
    """Lineas 'Seccion/Clave = valor' (las que emite comandos._campos) -> diccionario."""
    campos = {}
    for linea in lineas:
        if not linea.strip():
            continue
        clave, sep, valor = linea.partition("=")
        if not sep or "/" not in clave:
            raise _no_reconocida(que, linea)
        campos[clave.strip()] = valor.strip()
    return campos


def _campo(campos, clave, que):
    if clave not in campos:
        raise ValueError("salida de %s incompleta: falta %r" % (que, clave))
    return campos[clave]


def _secciones(texto, marcas, que):
    """Trocea por lineas '==marca'. Lo anterior a la primera marca queda bajo la clave ''."""
    partes, actual = {"": []}, ""
    for linea in texto.splitlines():
        if linea.startswith("==") and linea[2:].strip() in marcas:
            actual = linea[2:].strip()
            partes[actual] = []
        else:
            partes[actual].append(linea)
    if not all(marca in partes for marca in marcas):
        raise _no_reconocida(que)
    return partes


def _bloques(texto, que):
    """Trocea por lineas '== nombre' (un fichero o dispositivo por bloque)."""
    bloques = []
    for linea in _lineas(texto):
        if linea.startswith("== "):
            bloques.append((linea[3:].strip(), []))
        elif not bloques:
            raise _no_reconocida(que, linea)
        else:
            bloques[-1][1].append(linea.strip())
    return bloques


def _ini(texto, que):
    """Fichero de secciones '[nombre]' con lineas 'clave = valor'."""
    secciones = []
    for linea in _lineas(texto):
        linea = linea.strip()
        clave, sep, valor = linea.partition("=")
        if linea.startswith("[") and linea.endswith("]"):
            secciones.append((linea[1:-1], {}))
        elif sep and secciones:
            secciones[-1][1][clave.strip()] = valor.strip()
        else:
            raise _no_reconocida(que, linea)
    return secciones


def _breve(texto, que):
    """Lineas de 'ip -br': (nombre, par, estado, resto de campos)."""
    filas = []
    for linea in _lineas(texto):
        campos = linea.split()
        if len(campos) < 2 or not ESTADO.match(campos[1]):
            raise _no_reconocida(que, linea)
        nombre, _, par = campos[0].partition("@")      # las veth salen como nombre@ifN
        filas.append((nombre, par or None, campos[1], campos[2:]))
    if not filas:
        raise _no_reconocida(que)
    return filas


def _interfaz_de(fichero):
    return re.sub(r"^dhcpd_|\.(?:conf|leases)$", "", fichero)


def _sin_valores(campos, que):
    """Con getcfg sin poder leer la configuracion, todos los campos llegan vacios: es un fallo
    de lectura, no una configuracion en blanco."""
    if not any(campos.values()):
        raise ValueError("no se pudo leer %s: ningun campo tiene valor" % que)


def _nombre_de_equipo(texto):
    """Nombre que anuncia un cliente DHCP. Lo elige el cliente (una maquina virtual, un
    contenedor): se reduce a los caracteres de un nombre de equipo y se acota, para que no
    pueda meter texto libre en la respuesta."""
    return FUERA_DE_NOMBRE.sub("_", texto)[:MAX_NOMBRE] or None


# --- interfaces -----------------------------------------------------------------------------

def enlaces(texto):
    salida = []
    for nombre, par, estado, resto in _breve(texto, "ip -br link"):
        marcas = [campo for campo in resto if campo.startswith("<")]
        salida.append({
            "interfaz": nombre, "par": par, "estado": estado,
            "mac": resto[0].lower() if resto and MAC.match(resto[0]) else None,
            "marcas": marcas[0].strip("<>").split(",") if marcas else []})
    return salida


def direcciones(texto):
    salida = []
    for nombre, _, estado, resto in _breve(texto, "ip -br addr"):
        # en un enlace punto a punto sale "local peer remota/32": la remota no es del NAS
        propias = [d for i, d in enumerate(resto) if d != "peer" and (i == 0 or resto[i - 1] != "peer")]
        salida.append({"interfaz": nombre, "estado": estado,
                       "ipv4": [d for d in propias if ":" not in d],
                       "ipv6": [d for d in propias if ":" in d]})
    return salida


def sys_red(texto):
    salida = []
    for linea in _lineas(texto):
        nombre, *pares = linea.split()
        campos = dict(par.split("=", 1) for par in pares if "=" in par)
        if not {"estado", "vel", "dup", "mtu", "mac", "carrier"} <= set(campos):
            raise _no_reconocida("/sys/class/net", linea)
        if not campos["mtu"]:
            continue                  # bonding_masters y otros ficheros que no son interfaces
        salida.append({
            "interfaz": nombre, "estado": campos["estado"] or None,
            # el kernel da -1 (o nada) cuando no hay enlace
            "velocidad_mbps": int(campos["vel"]) if campos["vel"].isdigit() else None,
            "duplex": campos["dup"] if campos["dup"] in ("full", "half") else None,
            "mtu": _numero(campos["mtu"], "mtu"), "mac": campos["mac"].lower() or None,
            "portadora": {"1": True, "0": False}.get(campos["carrier"])})
    if not salida:
        raise _no_reconocida("/sys/class/net")
    return salida


def contadores(texto):
    salida = []
    for linea in _lineas(texto):
        nombre, sep, resto = linea.rpartition(":")
        if not sep:
            continue                  # las dos lineas de cabecera de /proc/net/dev
        cifras = resto.split()
        if len(cifras) != 16 or not all(c.isdigit() for c in cifras):
            raise _no_reconocida("/proc/net/dev", linea)
        n = [int(c) for c in cifras]
        salida.append({
            "interfaz": nombre.strip(), "rx_bytes": n[0], "rx_paquetes": n[1], "rx_errores": n[2],
            "rx_descartes": n[3], "tx_bytes": n[8], "tx_paquetes": n[9], "tx_errores": n[10],
            "tx_descartes": n[11], "colisiones": n[13]})
    if not salida:
        raise _no_reconocida("/proc/net/dev")
    return salida


def trafico(texto):
    """Dos lecturas de /proc/net/dev separadas por '==Ns': los contadores de la segunda y el
    caudal (bits por segundo) entre ambas."""
    marca = re.search(r"^==([0-9]+)s$", texto, re.M)
    if not marca:
        raise _no_reconocida("la muestra de trafico")
    segundos = int(marca.group(1))
    antes = {c["interfaz"]: c for c in contadores(texto[:marca.start()])}
    salida = []
    for despues in contadores(texto[marca.end():]):
        previo = antes.get(despues["interfaz"])

        def bps(clave):
            # sin lectura previa (interfaz recien creada) o con el contador reiniciado no hay
            # caudal que dar
            if previo is None or despues[clave] < previo[clave]:
                return None
            return (despues[clave] - previo[clave]) * 8 // segundos

        salida.append(dict(despues, rx_bps=bps("rx_bytes"), tx_bps=bps("tx_bytes")))
    return salida


def ethtool(texto):
    cabecera = re.search(r"^Settings for (\S+):", texto, re.M)
    if not cabecera:
        raise _no_reconocida("ethtool")
    campos = _dos_puntos(texto)
    velocidad = re.match(r"([0-9]+)Mb/s", campos.get("Speed", ""))
    admitidas = [int(v) for v in re.findall(r"([0-9]+)base", campos.get("Supported link modes", ""))]
    duplex = campos.get("Duplex", "").lower()
    return {
        "interfaz": cabecera.group(1),
        "velocidad_mbps": int(velocidad.group(1)) if velocidad else None,
        "velocidad_maxima_mbps": max(admitidas) if admitidas else None,
        "duplex": duplex if duplex in ("full", "half") else None,
        "autonegociacion": {"on": True, "off": False}.get(campos.get("Auto-negotiation")),
        "enlace": {"yes": True, "no": False}.get(campos.get("Link detected")),
        "puerto": campos.get("Port") or None}


def ethtool_driver(texto):
    campos = _dos_puntos(texto)
    if not campos.get("driver"):
        raise _no_reconocida("ethtool -i")
    return {"driver": campos["driver"], "version": campos.get("version") or None,
            "firmware": campos.get("firmware-version") or None, "bus": campos.get("bus-info") or None}


def ethtool_errores(texto):
    """De ethtool -S: cuantos contadores hay y cuales de error no estan a cero. Sin
    contadores (interfaz virtual, o no se pudieron leer) disponible es False: no hay
    estadisticas, que no es lo mismo que no haber errores."""
    todos = {}
    for linea in _lineas(texto):
        nombre, sep, valor = linea.rpartition(":")
        if sep and valor.strip().isdigit():
            todos[nombre.strip()] = int(valor)
    return {"disponible": bool(todos), "contadores": len(todos),
            "errores": {n: v for n, v in todos.items() if v and CONTADOR_DE_ERROR.search(n)}}


def bonding(texto):
    salida = []
    for nombre, lineas in _bloques(texto, "/proc/net/bonding"):
        bond = {"interfaz": nombre, "modo": None, "estado_mii": None, "activa": None,
                "politica_hash": None, "lacp": None, "miembros": []}
        miembro = None
        for linea in lineas:
            clave, sep, valor = linea.partition(":")
            clave, valor = clave.strip(), valor.strip()
            if not sep:
                continue              # titulos de apartado, como "802.3ad info"
            if clave == "Slave Interface":
                miembro = {"interfaz": valor, "estado_mii": None, "velocidad_mbps": None,
                           "duplex": None, "fallos_enlace": None}
                bond["miembros"].append(miembro)
            elif miembro is not None:
                if clave == "MII Status":
                    miembro["estado_mii"] = valor
                elif clave == "Speed":
                    cifra = re.match(r"[0-9]+", valor)
                    miembro["velocidad_mbps"] = int(cifra.group(0)) if cifra else None
                elif clave == "Duplex":
                    miembro["duplex"] = valor if valor in ("full", "half") else None
                elif clave == "Link Failure Count":
                    miembro["fallos_enlace"] = _numero(valor, "fallos de enlace")
            elif clave == "Bonding Mode":
                bond["modo"] = valor
            elif clave == "MII Status":
                bond["estado_mii"] = valor
            elif clave == "Currently Active Slave":
                bond["activa"] = None if valor == "None" else valor
            elif clave == "Transmit Hash Policy":
                bond["politica_hash"] = valor
            elif clave == "LACP rate":
                bond["lacp"] = valor
        salida.append(bond)
    return salida


def vlan(texto):
    salida = []
    for linea in _lineas(texto):
        campos = [campo.strip() for campo in linea.split("|")]
        if len(campos) == 3 and campos[1].isdigit():
            salida.append({"interfaz": campos[0], "id": int(campos[1]), "padre": campos[2]})
        elif not linea.startswith(("VLAN Dev name", "Name-Type:")):
            raise _no_reconocida("/proc/net/vlan/config", linea)
    return salida


# --- conmutadores virtuales -------------------------------------------------------------------

def puentes(texto):
    lineas = _lineas(texto)
    if not lineas or not lineas[0].startswith("bridge name"):
        raise _no_reconocida("brctl show")
    salida = []
    for linea in lineas[1:]:
        campos = linea.split()
        if linea[0] in " \t" and salida and len(campos) == 1:
            salida[-1]["interfaces"].append(campos[0])      # otra interfaz del puente anterior
        elif linea[0] not in " \t" and len(campos) in (3, 4) and campos[2] in ("yes", "no"):
            salida.append({"puente": campos[0], "id": campos[1], "stp": campos[2] == "yes",
                           "interfaces": campos[3:]})
        else:
            raise _no_reconocida("brctl show", linea)
    return salida


def puentes_mac(texto):
    lineas = _lineas(texto)
    if not lineas or not lineas[0].startswith("port no"):
        raise _no_reconocida("brctl showmacs")
    salida = []
    for linea in lineas[1:]:
        campos = linea.split()
        if len(campos) != 4 or not MAC.match(campos[1]) or campos[2] not in ("yes", "no"):
            raise _no_reconocida("brctl showmacs", linea)
        salida.append({"puerto": int(campos[0]), "mac": campos[1].lower(), "local": campos[2] == "yes",
                       "antiguedad_s": float(campos[3])})
    return salida


# --- rutas ----------------------------------------------------------------------------------------

def rutas(texto):
    """Las claves 'tipo' y 'saltos' solo aparecen en las rutas que los tienen."""
    salida = []
    for linea in _lineas(texto):
        campos = linea.split()
        if linea[0] in " \t":
            if not salida:
                raise _no_reconocida("ip route", linea)
            salida[-1].setdefault("saltos", []).append(" ".join(campos))    # ruta con varias salidas
            continue
        ruta = {"destino": None, "via": None, "interfaz": None, "protocolo": None, "ambito": None,
                "origen": None, "metrica": None, "sin_enlace": "linkdown" in campos}
        if campos[0] in TIPOS_RUTA:
            ruta["tipo"] = campos.pop(0)
        if not campos or not DESTINO.match(campos[0]):
            raise _no_reconocida("ip route", linea)
        ruta["destino"] = campos[0]
        for clave, valor in zip(campos[1:], campos[2:]):
            if clave in CLAVES_RUTA:
                ruta[CLAVES_RUTA[clave]] = valor
        if ruta["metrica"] is not None:
            ruta["metrica"] = _numero(ruta["metrica"], "metrica")
        salida.append(ruta)
    if not salida:
        raise _no_reconocida("ip route")
    return salida


def reglas(texto):
    salida = []
    for linea in _lineas(texto):
        prioridad, sep, resto = linea.partition(":")
        campos = resto.split()
        if not sep or not prioridad.strip().isdigit() or not campos:
            raise _no_reconocida("ip rule", linea)
        tabla = None
        if "lookup" in campos[:-1]:
            corte = campos.index("lookup")
            tabla, campos = campos[corte + 1], campos[:corte]
        salida.append({"prioridad": int(prioridad), "selector": " ".join(campos), "tabla": tabla})
    if not salida:
        raise _no_reconocida("ip rule")
    return salida


def vecinos(texto):
    salida = []
    for linea in _lineas(texto):
        campos = linea.split()
        if len(campos) < 4 or campos[1] != "dev":
            raise _no_reconocida("ip neigh", linea)
        mac = campos[campos.index("lladdr") + 1].lower() if "lladdr" in campos[:-1] else None
        salida.append({"ip": campos[0], "interfaz": campos[2], "mac": mac, "estado": campos[-1]})
    return salida


def rutas_estaticas(texto):
    """Rutas de staticroute.conf (una seccion por ruta, salvo la general). 'interfaz' es el
    nombre interno de QNAP del adaptador (interface0, ...) y 'activa' su campo status."""
    que = "staticroute.conf"
    rutas = []
    for nombre, campos in _ini(texto, que):
        if nombre == "global":
            continue
        try:
            red = ipaddress.ip_interface("%s/%s" % (campos["ip"], campos["netmask"]))
            via = campos.get("nexthop_address") or None
            metrica = campos.get("metric") or None
            rutas.append({
                "destino": "%s/%d" % (red.ip, red.network.prefixlen),
                "via": str(ipaddress.ip_address(via)) if via else None,
                "interfaz": _nombre_de_equipo(campos.get("nexthop_if") or ""),
                "metrica": int(metrica) if metrica else None,
                "activa": campos.get("status") == "1"})
        except (KeyError, ValueError):
            raise _no_reconocida(que, nombre)
    return rutas


# --- DNS y DHCP -------------------------------------------------------------------------------------

def dns(texto):
    partes = _secciones(texto, ("resolv", "superiores"), "la configuracion de DNS")
    servidores, busqueda, superiores = [], [], []
    for linea in partes["resolv"]:
        campos = linea.split()
        if campos[:1] == ["nameserver"] and len(campos) > 1:
            servidores.append(campos[1])
        elif campos[:1] in (["search"], ["domain"]):
            busqueda.extend(campos[1:])
    for linea in partes["superiores"]:
        campos = linea.split()
        if campos[:1] == ["nameserver"] and len(campos) > 1:
            servidor, _, interfaz = campos[1].partition("@")      # dnsmasq anota por donde sale
            superiores.append({"servidor": servidor, "interfaz": interfaz or None})
    return {"servidores": servidores, "busqueda": busqueda, "superiores": superiores}


def dhcp_servidor(texto):
    salida = []
    for fichero, lineas in _bloques(texto, "dhcpd.conf"):
        cuerpo = "\n".join(lineas)

        def uno(patron):
            hallado = re.search(patron, cuerpo, re.M)
            return hallado.group(1) if hallado else None

        subred = re.search(r"^subnet (\S+) netmask ([0-9.]+)", cuerpo, re.M)
        if not subred:
            raise _no_reconocida("dhcpd.conf", fichero)
        rango = re.search(r"^range (\S+) (\S+);", cuerpo, re.M)
        servidores = uno(r"^option domain-name-servers ([^;]+);") or ""
        salida.append({
            "interfaz": uno(r'^interface "([^"]+)";') or _interfaz_de(fichero),
            "subred": subred.group(1), "mascara": subred.group(2),
            "rango": list(rango.groups()) if rango else [],
            "puerta_enlace": uno(r"^option routers ([^;, ]+)"),
            "dns": [s.strip() for s in servidores.split(",") if s.strip() not in ("", "0.0.0.0")],
            "concesion_s": _numero(uno(r"^default-lease-time ([0-9]+);") or "", "tiempo de concesion")})
    return salida


def dhcp_concesiones(texto):
    """Una concesion por direccion: dhcpd anade un bloque en cada renovacion y vale el ultimo.
    Las horas son UTC, como las escribe dhcpd. 'recortado' lista las redes cuyo fichero tiene
    mas lineas de las que se leen: ahi pueden faltar concesiones antiguas."""
    vigentes, recortado = {}, []
    for fichero, lineas in _bloques(texto, "dhcpd.leases"):
        interfaz, actual = _interfaz_de(fichero), None
        for linea in lineas:
            campos = linea.rstrip(";").split()
            if not campos:
                continue
            if campos[0] == "==lineas":
                if len(campos) == 2 and campos[1].isdigit() and int(campos[1]) > LINEAS_LEASES:
                    recortado.append(interfaz)
            elif campos[0] == "lease" and len(campos) == 3 and campos[2] == "{":
                actual = {"interfaz": interfaz, "ip": campos[1], "mac": None, "estado": None,
                          "inicio_utc": None, "fin_utc": None, "equipo": None}
            elif linea == "}":
                if actual is not None:
                    vigentes.pop((interfaz, actual["ip"]), None)
                    vigentes[(interfaz, actual["ip"])] = actual
                actual = None
            elif actual is None:
                continue              # lineas generales del fichero, fuera de una concesion
            elif campos[0] in ("starts", "ends"):
                # "starts 4 2026/09/24 18:56:59" (dia de la semana, fecha, hora) o "ends never"
                momento = " ".join(campos[2:4]) if len(campos) >= 4 else " ".join(campos[1:])
                actual["inicio_utc" if campos[0] == "starts" else "fin_utc"] = momento or None
            elif campos[:2] == ["binding", "state"] and len(campos) == 3:
                actual["estado"] = campos[2]
            elif campos[:2] == ["hardware", "ethernet"] and len(campos) == 3:
                actual["mac"] = campos[2].lower()
            elif campos[0] == "client-hostname" and linea.count('"') >= 2:
                actual["equipo"] = _nombre_de_equipo(linea.split('"')[1])
    return {"concesiones": list(vigentes.values()), "recortado": recortado}


# --- servicios ----------------------------------------------------------------------------------------

def escucha(texto):
    """netstat -tlnp o -ulnp: un puerto en escucha por linea, con su proceso si se pudo ver."""
    lineas = _lineas(texto)
    if not any(linea.startswith("Proto") for linea in lineas):
        raise _no_reconocida("netstat")
    salida = []
    for linea in lineas:
        campos = linea.split()
        if campos[0] not in ("tcp", "udp", "tcp6", "udp6"):
            # cabeceras, y el aviso "netstat: showing only processes with your user ID"
            if linea.startswith(("Active", "Proto", "netstat:")):
                continue
            raise _no_reconocida("netstat", linea)
        # la direccion puede ser IPv6: el puerto es lo que sigue a los ultimos dos puntos
        direccion, sep, puerto = campos[3].rpartition(":") if len(campos) > 3 else ("", "", "")
        if not sep or not puerto.isdigit():
            raise _no_reconocida("netstat", linea)
        pid = proceso = None
        for campo in campos[5:]:
            hallado = re.match(r"^([0-9]+)/(.*)$", campo)
            if hallado:
                pid = int(hallado.group(1))
                # solo el nombre del programa: lo que sigue es el titulo que algunos procesos
                # se ponen ("proftpd: (accepting...)"), que netstat corta a la anchura de la columna
                proceso = hallado.group(2).rstrip(":") or None
                break
        salida.append({"protocolo": campos[0][:3], "direccion": direccion, "puerto": int(puerto),
                       "pid": pid, "proceso": proceso})
    return salida


def servicios(texto):
    campos = _campos(texto.splitlines(), "la configuracion de servicios")
    _sin_valores(campos, "la configuracion de servicios")

    def valor(clave):
        return _campo(campos, clave, "la configuracion de servicios")

    def activo(clave):
        return _si_no(valor(clave), clave)

    def puerto(clave):
        return _numero(valor(clave), clave)

    return {
        "nombre": valor("System/Server Name") or None,
        "web": {"puerto": puerto("System/Web Access Port"), "forzar_ssl": activo("System/Force SSL"),
                "https": activo("Stunnel/Enable"), "puerto_https": puerto("Stunnel/Port")},
        "ssh": {"activo": activo("LOGIN/SSH Enable"), "puerto": puerto("LOGIN/SSH Port")},
        "telnet": {"activo": activo("LOGIN/TELNET Enable"), "puerto": puerto("LOGIN/TELNET Port")},
        "ftp": {"activo": activo("FTP/Enable"), "puerto": puerto("FTP/Port")},
        "smb": {"activo": activo("Samba/Enable"), "grupo": valor("Samba/Workgroup") or None},
        "afp": {"activo": activo("Appletalk/Enable")},
        "nfs": {"activo": activo("NFS/Enable")},
        "snmp": {"activo": activo("SNMP/Service Enable"), "puerto": puerto("SNMP/Listen Port")},
        "servidor_web": {"activo": activo("QWEB/Enable"), "puerto": puerto("QWEB/Port"),
                         "puerto_ssl": puerto("QWEB/SSL_Port")},
        "iscsi": {"activo": activo("iSCSI/Enable"), "puerto": puerto("iSCSI/Port")},
        "upnp": {"activo": activo("UPnP Service/Enable")},
        "bonjour": {"activo": activo("Bonjour Service/Enable")},
        "tftp": {"activo": activo("TFTP Server/Enable"), "puerto": puerto("TFTP Server/PORT")},
    }


# --- cortafuegos ----------------------------------------------------------------------------------------

def iptables_resumen(texto):
    """De iptables-save: por tabla, sus cadenas con la politica y el numero de reglas."""
    tablas, tabla, cadenas = [], None, {}
    for linea in _lineas(texto):
        campos = linea.split()
        if linea.startswith("#") or linea == "COMMIT":
            continue
        if linea.startswith("*"):
            tabla, cadenas = {"tabla": linea[1:].strip(), "reglas": 0, "cadenas": []}, {}
            tablas.append(tabla)
        elif tabla is not None and linea.startswith(":") and len(campos) >= 2:
            cadena = {"cadena": campos[0][1:], "politica": None if campos[1] == "-" else campos[1],
                      "reglas": 0}
            cadenas[cadena["cadena"]] = cadena
            tabla["cadenas"].append(cadena)
        elif tabla is not None and campos[0] == "-A" and len(campos) >= 2 and campos[1] in cadenas:
            cadenas[campos[1]]["reglas"] += 1
            tabla["reglas"] += 1
        else:
            raise _no_reconocida("iptables-save", linea)
    if not tablas:
        raise _no_reconocida("iptables-save")
    return tablas


def bloqueo_ip(texto):
    que = "la proteccion de acceso por IP"
    partes = _secciones(texto, ("permitidas", "denegadas"), que)
    campos = _campos(partes[""], que)
    _sin_valores(campos, que)

    def activo(clave):
        return _si_no(_campo(campos, "Ban Engine/" + clave, que), clave)

    return {"activo": activo("Ban Enabled"), "bloqueo_cuentas": activo("Account Ban Enabled"),
            "servicios": {nombre: activo(clave) for nombre, clave in SERVICIOS_BLOQUEO},
            # las listas se devuelven tal cual: en los NAS de pruebas estaban vacias
            "permitidas": [linea.strip() for linea in partes["permitidas"] if linea.strip()],
            "denegadas": [linea.strip() for linea in partes["denegadas"] if linea.strip()]}


def _activo(texto, que):
    """Linea 'activo=valor' de las ordenes que solo dicen si algo esta encendido."""
    hallado = re.search(r"^activo=(.*)$", texto, re.M)
    if not hallado:
        raise _no_reconocida(que)
    return {"activo": _si_no(hallado.group(1), que)}


def qufirewall(texto):
    """Si el paquete esta activo, si el cortafuegos esta encendido y si tiene un perfil en uso
    (sin QuFirewall.conf, las dos ultimas no se saben)."""
    que = "QuFirewall"
    estado = dict(_activo(texto, que), cortafuegos=None, perfil_activo=None)
    encendido = re.search(r"^cortafuegos=(.*)$", texto, re.M)
    if encendido:
        valor = encendido.group(1).strip()
        if valor not in ("", "0", "1"):
            raise _no_reconocida(que, encendido.group(0))
        estado["cortafuegos"] = None if valor == "" else valor == "1"
    perfil = re.search(r"^perfil=(.*)$", texto, re.M)
    if perfil:
        estado["perfil_activo"] = bool(perfil.group(1).strip())
    return estado


# --- acceso remoto ----------------------------------------------------------------------------------------

def ddns(texto):
    partes = _secciones(texto, ("myqnapcloud", "ddns"), "la configuracion de DDNS")
    campos = _campos(partes["myqnapcloud"], "la configuracion de DDNS")

    def valor(clave):
        return _campo(campos, "QNAP DDNS Service/" + clave, "la configuracion de DDNS")

    proveedores = [
        {"proveedor": nombre, "activo": _si_no(seccion["enable"], "enable"),
         "nombre": seccion.get("hostname") or None}
        for nombre, seccion in _ini("\n".join(partes["ddns"]), "ddns.conf") if "enable" in seccion]
    return {"myqnapcloud": {"activo": _si_no(valor("Enable"), "Enable"), "nombre": valor("Host Name") or None,
                            "dominio": valor("Domain Name Server") or None},
            "proveedores": proveedores}


def upnp(texto):
    return _activo(texto, "UPnP")


def vpn_presencia(texto):
    """Solo si el servicio QVPN esta activo; nada de la configuracion de las VPN."""
    return {"qvpn_activo": _activo(texto, "QVPN")["activo"]}


# --- diagnostico ----------------------------------------------------------------------------------------------

def ping(texto):
    resumen = re.search(
        r"([0-9]+) packets transmitted, ([0-9]+) (?:packets )?received.*?([0-9.]+)% packet loss", texto)
    if not resumen:
        raise _no_reconocida("ping", texto.strip().splitlines()[0] if texto.strip() else "")
    destino = re.search(r"^PING (\S+)", texto, re.M)
    tiempos = re.search(r"min/avg/max(?:/[a-z]+)? = ([0-9.]+)/([0-9.]+)/([0-9.]+)", texto)
    perdida = float(resumen.group(3))
    minimo, media, maximo = (float(t) for t in tiempos.groups()) if tiempos else (None, None, None)
    return {"destino": destino.group(1) if destino else None, "enviados": int(resumen.group(1)),
            "recibidos": int(resumen.group(2)),
            "perdida_pct": int(perdida) if perdida.is_integer() else perdida,
            "min_ms": minimo, "media_ms": media, "max_ms": maximo}


def traceroute(texto):
    cabecera = re.search(r"^traceroute to (\S+) \(([^)]+)\)", texto, re.M)
    if not cabecera:
        raise _no_reconocida("traceroute", texto.strip().splitlines()[0] if texto.strip() else "")
    saltos = []
    for linea in _lineas(texto):
        campos = linea.split()
        if not campos[0].isdigit():
            continue                  # la cabecera
        responde = len(campos) > 1 and campos[1] != "*"
        tiempo = campos[2] if responde and len(campos) > 3 and campos[3] == "ms" else None
        saltos.append({"salto": int(campos[0]), "ip": campos[1] if responde else None,
                       "ms": float(tiempo) if tiempo else None})
    return {"destino": cabecera.group(1), "alcanzado": any(s["ip"] == cabecera.group(2) for s in saltos),
            "saltos": saltos}


def nslookup(texto):
    servidor = nombre = None
    hallados = []
    for linea in _lineas(texto):
        clave, sep, valor = linea.partition(":")
        valor = valor.split()
        if not sep or not valor:
            continue
        if clave == "Server":
            servidor = servidor or valor[0]
        elif clave == "Name":
            nombre = valor[0]
        elif clave.startswith("Address") and nombre is not None:
            hallados.append(valor[0])         # las "Address" anteriores a "Name" son del servidor
    if servidor is None and nombre is None:
        raise _no_reconocida("nslookup", texto.strip().splitlines()[0] if texto.strip() else "")
    return {"servidor": servidor, "nombre": nombre, "resuelto": bool(hallados), "direcciones": hallados}
