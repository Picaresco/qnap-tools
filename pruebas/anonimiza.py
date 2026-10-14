# -*- coding: utf-8 -*-
"""Anonimiza salidas reales de un NAS para usarlas como datos de prueba versionables.

Sustituye de forma coherente (el mismo valor real da siempre el mismo valor de ejemplo):
  - IPv4 -> rangos de documentacion (192.0.2.x, 198.51.100.x, 203.0.113.x)
  - MAC  -> 00:11:22:33:44:NN (tambien dentro de los identificadores de puente 8000.xxxx)
  - IPv6 de enlace local y globales -> valores de ejemplo
  - IPv4 escrita con guiones (nombres inversos de proveedor) -> 192-0-2-N
  - numeros de serie de disco -> SERIE000N; WWN -> 5000000000000NNN; IQN -> ...example:destino-N
  - el identificador de disco de los miembros de un pool ZFS (disk_0x3_<WWN o serie>_3) y el
    guid de un pool
  - el comentario de una carpeta compartida (salvo los de fabrica) y el fsid de una exportacion NFS
  - los UUID (montajes remotos, maquinas virtuales)
  - nombres de equipo en concesiones DHCP
  - con comillas=True (registros del NAS): el texto entre comillas dobles, y el usuario y el
    equipo de cada fila de los registros de eventos, accesos y avisos (tambien donde se repitan)
  - "palabras": se sustituyen alli donde aparezcan, tambien dentro de otras (nombres de equipo)
  - "nombres": solo como palabra entera (nombres de carpeta, de usuario, de pool)

La sustitucion es idempotente: aplicarla sobre un texto ya anonimizado no lo cambia.

Uso como programa:
  python anonimiza.py ORIGEN DESTINO [--saltar N] [--palabra REAL=EJEMPLO ...] [--nombre REAL=EJEMPLO ...]
  python anonimiza.py --revisar FICHERO [FICHERO ...] [--palabra REAL=x ...] [--nombre REAL=x ...]
"""
import re
import sys

IPV4 = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?!\.?[0-9])")
IPV4_GUIONES = re.compile(r"(?<![0-9])(?<![0-9]-)(?:[0-9]{1,3}-){3}[0-9]{1,3}(?!-?[0-9])")
MAC = re.compile(r"(?<![0-9a-fA-F:])(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}(?![0-9a-fA-F:])")
PUENTE = re.compile(r"\b8000\.([0-9a-f]{12})\b")
# puente de una red de Docker (lleva el identificador de la red) y extremo veth de un contenedor
RED_DOCKER = re.compile(r"(?<![0-9A-Za-z])br-([0-9a-f]{12})(?![0-9A-Za-z])")
RED_DOCKER_EJEMPLO = re.compile(r"0000[0-9]{8}")
VETH = re.compile(r"(?<![0-9A-Za-z])veth([0-9a-f]{7})(?![0-9A-Za-z])")
VETH_EJEMPLO = re.compile(r"000[0-9]{4}")
# texto entre comillas dobles en la descripcion de un evento (usuarios, maquinas, carpetas)
ENTRE_COMILLAS = re.compile(r'"([^"\n]+)"')
ENTRE_COMILLAS_EJEMPLO = re.compile(r"texto[0-9]+")
# los tres registros del NAS: una cabecera con los nombres de columna y una fila por linea, que
# empieza por su numero; el usuario y el equipo van antes de la descripcion (texto libre)
CABECERA_REGISTRO = re.compile(r"(?:event_id|conn_id|id,severity),")
FILA_REGISTRO = re.compile(r" *[0-9]+,")
COLUMNAS_USUARIO = ("event_user", "conn_user", "user")
COLUMNAS_EQUIPO = ("event_comp", "conn_comp", "client")
# carpeta y fichero que se abrio en un acceso: cada parte de la ruta pasa a rutaN
COLUMNAS_RECURSO = ("conn_res",)
# lo que no dice nada de nadie: celdas vacias y cuentas o equipos que trae todo NAS
SIN_VALOR = ("", "---", "(null)", "localhost", "System", "admin", "guest")
USUARIO_EJEMPLO = re.compile(r"usuario[0-9]+")
EQUIPO_EJEMPLO = re.compile(r"equipo[0-9]+")
V6_LOCAL = re.compile(r"fe80::(?:[0-9a-f]{1,4}:){3}[0-9a-f]{1,4}")
V6_GLOBAL = re.compile(r"\b2[0-9a-f]{3}:(?:[0-9a-f]{0,4}:){1,6}[0-9a-f]{1,4}\b")
DUID = re.compile(r'\b(uid|server-duid) "[^\n]*";')
EQUIPO = re.compile(r'client-hostname "[^"\n]*"')
# el numero de serie como valor de un campo, y como segunda columna de "nvme list"
SERIE_CAMPO = re.compile(r"(?im)^([ \t]*(?:serial_no|serial number|serialnumber|serial|sn)[ \t]*[=:][ \t]*)(\S+)")
SERIE_NVME = re.compile(r"(?m)^(/dev/nvme[0-9]+n[0-9]+[ \t]+)(\S+)")
# miembro de un pool en QuTS hero: qzfs/enc_0/disk_0x3_<WWN o numero de serie>_<particion>
DISCO_ZFS = re.compile(r"(?<![A-Za-z0-9])(disk_0x[0-9a-fA-F]+_)([A-Za-z0-9-]+)(?=_[0-9]+(?![A-Za-z0-9]))")
GUID = re.compile(r"(?i)(\bguid(?:[ \t]*=[ \t]*|\t))([0-9]{15,20})\b")
GUID_EJEMPLO = re.compile(r"1000000000000000[0-9]{3}")
# comentario de una carpeta en smb.conf: texto libre del usuario
COMENTARIO = re.compile(r"(?m)^([ \t]*comment[ \t]*=[ \t]*)(\S[^\n]*?)[ \t]*$")
COMENTARIOS_DE_FABRICA = ("System default share", "undefined")
# descripcion de una maquina virtual (texto libre) en su XML
DESCRIPCION = re.compile(r"(<description>)([^<\n]+)(</description>)")
DESCRIPCION_EJEMPLO = "descripcion de ejemplo "
# servicio de compose de un contenedor, tal como lo saca la orden de detalle del plugin
SERVICIO = re.compile(r'(?m)^(servicio=")([^"\n]+)(")')
SERVICIO_EJEMPLO = re.compile(r"servicio[0-9]+")
# rutas de carpetas y ficheros del usuario bajo /share (discos de VM, montajes de contenedor)
# (una ruta acaba donde empieza la flecha "->" con la que Docker separa origen y destino)
RUTA_SHARE = re.compile(r"(?<![A-Za-z0-9_.-])/share/((?:(?!->)[^\s\"'<>(),;])+)")
# componentes que pone el propio NAS o sus paquetes: no dicen nada de nadie
RUTA_DE_SISTEMA = re.compile(r"[A-Za-z0-9]+_DATA|[.].*|QKVM|container-station(-data)?|docker|lib|volumes|overlay2"
                             r"|_data|merged|external|[0-9a-f]{64}|[0-9]+")
RUTA_EJEMPLO = re.compile(r"(carpeta|volumen|usuario|grupo|vm|disco|contenedor|imagen|red|proyecto|ruta)[0-9]+")
# lo unico que se conserva de un nombre de fichero: su ultima extension, si es corta o es un
# momento (la marca de tiempo que VS pone a cada capa de un disco)
EXTENSION = re.compile(r"(.+)[.]([0-9]+(?:_[0-9]+)?|[A-Za-z0-9]{1,5})")
# nombre de un volumen de Docker (o de lo que sea) en una salida en JSON
NOMBRE_JSON = re.compile(r'("Name":")([^"]+)(")')
# donde se monta algo DENTRO de un contenedor: la ruta delata el programa que corre en el
DESTINO_JSON = re.compile(r'("Destination":")([^"]+)(")')
DESTINO_EJEMPLO = re.compile(r"/destino[0-9]+")
IMAGEN_BASE_JSON = re.compile(r'("backing-filename": ")([^"/]+)(")')
IMAGEN_BASE = re.compile(r"(backing file: )(\S+)( \(actual path: )(\S+)(\))")
COMENTARIO_EJEMPLO = "comentario de ejemplo "
# el primer grupo puede traer una cifra de mas (identificadores de montaje de QNAP)
UUID = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8,9}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])")
UUID_EJEMPLO = re.compile(r"0{8}(?:-0{4}){3}-[0-9]{12}")
FSID = re.compile(r"\bfsid=([0-9a-fA-F]{32})\b")
FSID_EJEMPLO = re.compile(r"0{24}[0-9]{8}")
# identificador de una capa o de un contenedor de Docker (rutas de overlay2 en df)
CAPA = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])")
CAPA_EJEMPLO = re.compile(r"0{52}[0-9]{12}")
WWN = re.compile(r"(?<![0-9A-Za-z])(0x|naa\.|eui\.)([0-9a-fA-F]{16,32})(?![0-9a-fA-F])")
IQN = re.compile(r"\biqn\.[0-9]{4}-[0-9]{2}\.[A-Za-z0-9.-]+(?::[^\s\"',;\]]+)?")
BLOQUES = ("192.0.2", "198.51.100", "203.0.113")
MAC_FIJAS = ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff")
MAC_EJEMPLO = "00:11:22:33:"
V6_EJEMPLO = ("fe80::200:5eff:fe00:53", "2001:db8::")
SERIE_EJEMPLO = "SERIE"
WWN_EJEMPLO = re.compile(r"5000000000000[0-9a-f]{3}")
IQN_EJEMPLO = "iqn.2004-04.com.example:"
MIN_SERIE = 5      # un valor mas corto no es un numero de serie


def _ipv4_fija(ip):
    o = [int(x) for x in ip.split(".")]
    return any(x > 255 for x in o) or o[0] in (0, 127) or o[0] >= 224 or ip.rsplit(".", 1)[0] in BLOQUES


def _entero(real):
    """Patron que encuentra una palabra solo si no forma parte de otra mas larga."""
    return re.compile(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(real), re.I)


def _nombre_entero(real):
    """Como _entero, pero el guion bajo tambien es parte de la palabra: una carpeta "Backup" no
    debe tocar Power_Fail_Backup_Health, ni un usuario "NAS" el NAS_HOST de qcli_storage."""
    return re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(real), re.I)


def _celdas_de_registro(texto):
    """(linea, columna, clase, valor) del usuario, el equipo y el recurso de cada fila de un
    registro, en orden."""
    columnas = None
    for n, linea in enumerate(texto.split("\n")):
        if CABECERA_REGISTRO.match(linea):
            nombres, columnas = linea.split(","), {}
            for clase, grupo in (("usuario", COLUMNAS_USUARIO), ("equipo", COLUMNAS_EQUIPO),
                                 ("recurso", COLUMNAS_RECURSO)):
                for columna in grupo:
                    if columna in nombres:
                        columnas[nombres.index(columna)] = clase
                        break
        elif columnas and FILA_REGISTRO.match(linea):
            campos = linea.split(",")
            for i, clase in columnas.items():
                if i < len(campos):
                    yield n, i, clase, campos[i].strip()


def _celda_real(clase, valor):
    """Si la celda trae un dato de alguien (no vacia, no de fabrica, no una direccion, que ya
    se tapa aparte, ni un valor de ejemplo)."""
    if valor in SIN_VALOR:
        return False
    if clase == "recurso":
        return not all(_ruta_limpia(parte) for parte in valor.split("/"))
    ejemplo = USUARIO_EJEMPLO if clase == "usuario" else EQUIPO_EJEMPLO
    return not (IPV4.fullmatch(valor) or ":" in valor or ejemplo.fullmatch(valor))


def _es_serie(valor):
    return len(valor) >= MIN_SERIE and not valor.startswith(SERIE_EJEMPLO)


class Anonimizador:
    def __init__(self, palabras=None, nombres=None, rutas=False, comillas=False):
        self.con_rutas, self.rutas, self.descripciones, self.servicios = rutas, {}, {}, {}
        self.destinos = {}
        self.con_comillas, self.citas, self.redes_docker, self.veths = comillas, {}, {}, {}
        self.de_registro = {"usuario": {}, "equipo": {}}
        self.ips, self.macs, self.v6, self.equipos = {}, {}, {}, {}
        self.series, self.wwn, self.iqn, self.guid = {}, {}, {}, {}
        self.comentarios, self.fsid, self.uuid, self.capas = {}, {}, {}, {}
        # las mas largas primero: asi "NASX2" no queda a medias por "NASX"
        self.palabras = sorted((palabras or {}).items(), key=lambda p: -len(p[0]))
        self.nombres = sorted((nombres or {}).items(), key=lambda p: -len(p[0]))

    def _ip(self, m):
        ip = m.group(0)
        if _ipv4_fija(ip):
            return ip
        if ip not in self.ips:
            n = len(self.ips)
            self.ips[ip] = "%s.%d" % (BLOQUES[(n // 254) % 3], n % 254 + 1)
        return self.ips[ip]

    def _mac_de(self, real):
        real = real.lower()
        if real in MAC_FIJAS or real.startswith(MAC_EJEMPLO):
            return real
        if real not in self.macs:
            n = len(self.macs)
            self.macs[real] = "00:11:22:33:%02x:%02x" % (0x44 + n // 256, n % 256)
        return self.macs[real]

    def _puente(self, m):
        h = m.group(1)
        real = ":".join(h[i:i + 2] for i in range(0, 12, 2))
        return "8000." + self._mac_de(real).replace(":", "")

    def _v6(self, prefijo):
        def cambia(m):
            real = m.group(0).lower()
            if real.startswith(V6_EJEMPLO):
                return real
            if real not in self.v6:
                self.v6[real] = prefijo % (len(self.v6) + 1)
            return self.v6[real]
        return cambia

    def _ip_guiones(self, m):
        return IPV4.sub(self._ip, m.group(0).replace("-", ".")).replace(".", "-")

    def _equipo(self, m):
        real = m.group(0)
        if real not in self.equipos:
            self.equipos[real] = 'client-hostname "equipo-%d"' % (len(self.equipos) + 1)
        return self.equipos[real]

    def _serie(self, m):
        real = m.group(2)
        if not _es_serie(real):
            return m.group(0)
        if real not in self.series:
            self.series[real] = "%s%04d" % (SERIE_EJEMPLO, len(self.series) + 1)
        return m.group(1) + self.series[real]

    def _guid(self, m):
        real = m.group(2)
        if GUID_EJEMPLO.fullmatch(real):
            return m.group(0)
        if real not in self.guid:
            self.guid[real] = "1000000000000000%03d" % (len(self.guid) + 1)
        return m.group(1) + self.guid[real]

    def _comentario(self, m):
        real = m.group(2)
        if real in COMENTARIOS_DE_FABRICA or real.startswith(COMENTARIO_EJEMPLO):
            return m.group(0)
        if real not in self.comentarios:
            self.comentarios[real] = "%s%d" % (COMENTARIO_EJEMPLO, len(self.comentarios) + 1)
        return m.group(1) + self.comentarios[real]

    def _descripcion(self, m):
        real = m.group(2)
        if real.startswith(DESCRIPCION_EJEMPLO):
            return m.group(0)
        if real not in self.descripciones:
            self.descripciones[real] = "%s%d" % (DESCRIPCION_EJEMPLO, len(self.descripciones) + 1)
        return m.group(1) + self.descripciones[real] + m.group(3)

    def _servicio(self, m):
        real = m.group(2)
        if SERVICIO_EJEMPLO.fullmatch(real):
            return m.group(0)
        if real not in self.servicios:
            self.servicios[real] = "servicio%d" % (len(self.servicios) + 1)
        return m.group(1) + self.servicios[real] + m.group(3)

    def _componente(self, parte):
        """Una carpeta o un fichero del usuario pasa a rutaN, conservando su extension."""
        if not parte or RUTA_DE_SISTEMA.fullmatch(parte):
            return parte
        m = EXTENSION.fullmatch(parte)
        base, extension = (m.group(1), "." + m.group(2)) if m else (parte, "")
        if RUTA_EJEMPLO.fullmatch(base):
            return parte
        if base not in self.rutas:
            self.rutas[base] = "ruta%d" % (len(self.rutas) + 1)
        return self.rutas[base] + extension

    def _ruta(self, m):
        return "/share/" + "/".join(self._componente(parte) for parte in m.group(1).split("/"))

    def _uuid(self, m):
        real = m.group(0).lower()
        if UUID_EJEMPLO.fullmatch(real):
            return m.group(0)
        if real not in self.uuid:
            self.uuid[real] = "00000000-0000-0000-0000-%012d" % (len(self.uuid) + 1)
        return self.uuid[real]

    def _fsid(self, m):
        real = m.group(1).lower()
        if FSID_EJEMPLO.fullmatch(real):
            return m.group(0)
        if real not in self.fsid:
            self.fsid[real] = "%032d" % (len(self.fsid) + 1)
        return "fsid=" + self.fsid[real]

    def _capa(self, m):
        real = m.group(0)
        if CAPA_EJEMPLO.fullmatch(real):
            return real
        if real not in self.capas:
            self.capas[real] = "%064d" % (len(self.capas) + 1)
        return self.capas[real]

    def _wwn(self, m):
        real = m.group(2).lower()
        if WWN_EJEMPLO.fullmatch(real):
            return m.group(0)
        if real not in self.wwn:
            self.wwn[real] = "5000000000000%03x" % (len(self.wwn) + 1)
        return m.group(1) + self.wwn[real]

    def _iqn(self, m):
        real = m.group(0).lower()
        if real.startswith(IQN_EJEMPLO):
            return m.group(0)
        if real not in self.iqn:
            self.iqn[real] = "%sdestino-%d" % (IQN_EJEMPLO, len(self.iqn) + 1)
        return self.iqn[real]

    def aplicar(self, texto):
        texto = DESCRIPCION.sub(self._descripcion, texto)
        texto = SERVICIO.sub(self._servicio, texto)
        texto = IQN.sub(self._iqn, texto)
        texto = SERIE_CAMPO.sub(self._serie, texto)
        texto = SERIE_NVME.sub(self._serie, texto)
        texto = DISCO_ZFS.sub(self._serie, texto)
        texto = GUID.sub(self._guid, texto)
        texto = COMENTARIO.sub(self._comentario, texto)
        texto = FSID.sub(self._fsid, texto)
        texto = UUID.sub(self._uuid, texto)
        texto = CAPA.sub(self._capa, texto)
        # un numero de serie ya conocido se quita tambien de donde salga suelto
        for real, ejemplo in sorted(self.series.items(), key=lambda p: -len(p[0])):
            texto = _entero(real).sub(lambda _, e=ejemplo: e, texto)
        texto = WWN.sub(self._wwn, texto)
        texto = DUID.sub(lambda m: '%s "...";' % m.group(1), texto)
        texto = EQUIPO.sub(self._equipo, texto)
        texto = V6_LOCAL.sub(self._v6("fe80::200:5eff:fe00:53%02x"), texto)
        texto = V6_GLOBAL.sub(self._v6("2001:db8::%x"), texto)
        texto = PUENTE.sub(self._puente, texto)
        texto = RED_DOCKER.sub(lambda m: "br-" + self._de(self.redes_docker, m.group(1), RED_DOCKER_EJEMPLO,
                                                           "%012d"), texto)
        texto = VETH.sub(lambda m: "veth" + self._de(self.veths, m.group(1), VETH_EJEMPLO, "%07d"), texto)
        texto = MAC.sub(lambda m: self._mac_de(m.group(0)), texto)
        texto = IPV4.sub(self._ip, texto)
        texto = IPV4_GUIONES.sub(self._ip_guiones, texto)
        if self.con_comillas:
            texto = self._registros(texto)
        for real, ejemplo in self.palabras:
            texto = re.sub(re.escape(real), lambda _, e=ejemplo: e, texto, flags=re.I)
        for real, ejemplo in self.nombres:
            texto = _nombre_entero(real).sub(lambda _, e=ejemplo: e, texto)
        if self.con_comillas:
            texto = self._recursos(texto)
        if self.con_rutas:
            texto = RUTA_SHARE.sub(self._ruta, texto)
            # qemu-img repite suelto el nombre del fichero base: es el final de su ruta
            texto = IMAGEN_BASE.sub(lambda m: m.group(1) + m.group(4).rsplit("/", 1)[-1] + m.group(3)
                                    + m.group(4) + m.group(5), texto)
            texto = IMAGEN_BASE_JSON.sub(lambda m: m.group(1) + self._componente(m.group(2)) + m.group(3), texto)
            texto = NOMBRE_JSON.sub(lambda m: m.group(1) + self._componente(m.group(2)) + m.group(3), texto)
            texto = DESTINO_JSON.sub(self._destino, texto)
        if self.con_comillas:
            texto = ENTRE_COMILLAS.sub(
                lambda m: '"%s"' % self._de(self.citas, m.group(1), ENTRE_COMILLAS_EJEMPLO, "texto%d"), texto)
        return texto

    def _registros(self, texto):
        """El usuario y el equipo de cada fila pasan a usuarioN y equipoN, alli donde salgan (las
        descripciones los repiten); los mas largos primero: "PC-PEPE" antes que "pepe"."""
        for _, _, clase, valor in _celdas_de_registro(texto):
            if clase in self.de_registro and _celda_real(clase, valor):
                self._de(self.de_registro[clase], valor, re.compile(r"(?!)"), clase + "%d")
        reales = [p for tabla in self.de_registro.values() for p in tabla.items()]
        for real, ejemplo in sorted(reales, key=lambda p: -len(p[0])):
            texto = _nombre_entero(real).sub(lambda _, e=ejemplo: e, texto)
        return texto

    def _recursos(self, texto):
        """Cada parte de la ruta del recurso de un acceso pasa a rutaN (va al final: antes se
        han puesto ya los nombres de carpeta y de usuario que se conocen)."""
        lineas = texto.split("\n")
        for n, i, clase, valor in list(_celdas_de_registro(texto)):
            if clase == "recurso" and _celda_real(clase, valor):
                campos = lineas[n].split(",")
                campos[i] = "/".join(self._componente(parte) for parte in campos[i].split("/"))
                lineas[n] = ",".join(campos)
        return "\n".join(lineas)

    @staticmethod
    def _de(tabla, real, ejemplo, formato):
        """El valor de ejemplo de un valor real, siempre el mismo; uno de ejemplo se deja."""
        if ejemplo.fullmatch(real):
            return real
        if real not in tabla:
            tabla[real] = formato % (len(tabla) + 1)
        return tabla[real]

    def _destino(self, m):
        real = m.group(2)
        if not DESTINO_EJEMPLO.fullmatch(real) and real not in self.destinos:
            self.destinos[real] = "/destino%d" % (len(self.destinos) + 1)
        return m.group(1) + self.destinos.get(real, real) + m.group(3)


def _ruta_limpia(parte):
    m = EXTENSION.fullmatch(parte)
    return bool(not parte or RUTA_DE_SISTEMA.fullmatch(parte)
                or RUTA_EJEMPLO.fullmatch(m.group(1) if m else parte))


def revisar(texto, palabras=(), nombres=(), rutas=False, comillas=False):
    """Lo que aun parece un dato real en un texto ya anonimizado. Con rutas=True, ademas, cada
    carpeta o fichero bajo /share que no sea del sistema ni un nombre de ejemplo."""
    dudas = []
    if rutas:
        for m in RUTA_SHARE.finditer(texto):
            dudas += ["ruta " + parte for parte in m.group(1).split("/") if not _ruta_limpia(parte)]
        dudas += ["nombre " + m.group(2) for m in NOMBRE_JSON.finditer(texto) if not _ruta_limpia(m.group(2))]
        dudas += ["destino " + m.group(2) for m in DESTINO_JSON.finditer(texto)
                  if not DESTINO_EJEMPLO.fullmatch(m.group(2))]
    for ip in set(IPV4.findall(texto)):
        if not _ipv4_fija(ip):
            dudas.append("ip " + ip)
    for ip in set(IPV4_GUIONES.findall(texto)):
        if not _ipv4_fija(ip.replace("-", ".")):
            dudas.append("ip " + ip)
    for mac in set(MAC.findall(texto)):
        if mac.lower() not in MAC_FIJAS and not mac.lower().startswith(MAC_EJEMPLO):
            dudas.append("mac " + mac)
    for v6 in set(V6_LOCAL.findall(texto)) | set(V6_GLOBAL.findall(texto)):
        if not v6.startswith(V6_EJEMPLO):
            dudas.append("ipv6 " + v6)
    for patron in (SERIE_CAMPO, SERIE_NVME):
        for m in patron.finditer(texto):
            if _es_serie(m.group(2)):
                dudas.append("serie " + m.group(2))
    for m in DISCO_ZFS.finditer(texto):
        if _es_serie(m.group(2)):
            dudas.append("disco " + m.group(2))
    for m in GUID.finditer(texto):
        if not GUID_EJEMPLO.fullmatch(m.group(2)):
            dudas.append("guid " + m.group(2))
    for m in COMENTARIO.finditer(texto):
        if m.group(2) not in COMENTARIOS_DE_FABRICA and not m.group(2).startswith(COMENTARIO_EJEMPLO):
            dudas.append("comentario " + m.group(2))
    for m in SERVICIO.finditer(texto):
        if not SERVICIO_EJEMPLO.fullmatch(m.group(2)):
            dudas.append("servicio " + m.group(2))
    for m in DESCRIPCION.finditer(texto):
        if not m.group(2).startswith(DESCRIPCION_EJEMPLO):
            dudas.append("descripcion " + m.group(2))
    for m in IMAGEN_BASE_JSON.finditer(texto):
        if not _ruta_limpia(m.group(2)):
            dudas.append("imagen base " + m.group(2))
    for m in UUID.finditer(texto):
        if not UUID_EJEMPLO.fullmatch(m.group(0).lower()):
            dudas.append("uuid " + m.group(0))
    dudas += ["puente br-" + m.group(1) for m in RED_DOCKER.finditer(texto) if not RED_DOCKER_EJEMPLO.fullmatch(m.group(1))]
    dudas += ["veth veth" + m.group(1) for m in VETH.finditer(texto) if not VETH_EJEMPLO.fullmatch(m.group(1))]
    if comillas:
        dudas += ["entre comillas " + m.group(1) for m in ENTRE_COMILLAS.finditer(texto)
                  if not ENTRE_COMILLAS_EJEMPLO.fullmatch(m.group(1))]
        for _, _, clase, valor in _celdas_de_registro(texto):
            if clase == "recurso":
                if valor not in SIN_VALOR:
                    dudas += ["recurso " + parte for parte in valor.split("/") if not _ruta_limpia(parte)]
            elif _celda_real(clase, valor):
                dudas.append("%s %s" % (clase, valor))
    for m in FSID.finditer(texto):
        if not FSID_EJEMPLO.fullmatch(m.group(1).lower()):
            dudas.append("fsid " + m.group(1))
    for m in CAPA.finditer(texto):
        if not CAPA_EJEMPLO.fullmatch(m.group(0)):
            dudas.append("capa " + m.group(0))
    for m in WWN.finditer(texto):
        if not WWN_EJEMPLO.fullmatch(m.group(2).lower()):
            dudas.append("wwn " + m.group(0))
    for m in IQN.finditer(texto):
        if not m.group(0).lower().startswith(IQN_EJEMPLO):
            dudas.append("iqn " + m.group(0))
    for palabra in palabras:
        if re.search(re.escape(palabra), texto, flags=re.I):
            dudas.append("palabra " + palabra)
    for nombre in nombres:
        if _nombre_entero(nombre).search(texto):
            dudas.append("nombre " + nombre)
    return sorted(set(dudas))


def _pares(args, opcion):
    pares = {}
    while opcion in args:
        i = args.index(opcion)
        real, ejemplo = args[i + 1].split("=", 1)
        pares[real] = ejemplo
        del args[i:i + 2]
    return pares


def _palabras(args):
    return _pares(args, "--palabra")


def _nombres(args):
    return _pares(args, "--nombre")


def main():
    args = sys.argv[1:]
    palabras, nombres = _palabras(args), _nombres(args)
    if args and args[0] == "--revisar":
        mal = 0
        rutas = "--rutas" in args          # mirar tambien carpetas y ficheros bajo /share
        if rutas:
            args.remove("--rutas")
        for ruta in args[1:]:
            with open(ruta, encoding="utf-8") as f:
                dudas = revisar(f.read(), palabras, nombres, rutas)
            if dudas:
                mal += 1
                print("%s: %s" % (ruta, "; ".join(dudas[:12])))
        print("ficheros revisados: %d, con dudas: %d" % (len(args) - 1, mal))
        sys.exit(1 if mal else 0)
    saltar = 0
    if "--saltar" in args:
        i = args.index("--saltar")
        saltar = int(args[i + 1])
        del args[i:i + 2]
    origen, destino = args
    with open(origen, encoding="utf-8") as f:
        lineas = f.read().splitlines(True)[saltar:]
    texto = Anonimizador(palabras, nombres).aplicar("".join(lineas))
    with open(destino, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)
    print("%s -> %s (%d lineas); dudas: %s" % (
        origen, destino, len(lineas), revisar(texto, palabras, nombres) or "ninguna"))


if __name__ == "__main__":
    main()
