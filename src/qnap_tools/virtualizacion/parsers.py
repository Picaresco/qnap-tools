# -*- coding: utf-8 -*-
"""Parsers de la pata de virtualizacion: texto de una orden -> estructura.

Funciones puras, una por orden de virtualizacion/comandos.py. Las claves van en castellano
sin acentos y los tamanos en bytes. Una salida que no se reconoce lanza ValueError: nunca se
devuelven datos inventados ni una lista vacia por no haber entendido el texto.

Las ordenes que recorren las VMs empiezan con "uri=qemu:///system": sin esa linea no hubo
respuesta del libvirt del sistema, y eso no es lo mismo que no tener maquinas.
"""
import json
import re
from datetime import datetime, timezone

KIB = 1024
URI_SISTEMA = "uri=qemu:///system"
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
MAX_NOMBRE = 255                    # texto que escribe un tercero: nombre de VM o de contenedor
MAX_DESCRIPCION = 300
MAX_RUTA = 400
SIN_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# virDomainState de libvirt
ESTADOS_VM = {0: "sin estado", 1: "en marcha", 2: "bloqueada", 3: "en pausa", 4: "apagandose",
              5: "apagada", 6: "caida", 7: "suspendida"}
MEMORIA = {"MemTotal": "total", "MemFree": "libre", "MemAvailable": "disponible",
           "SwapTotal": "intercambio", "SwapFree": "intercambio_libre"}
SOCKETS = {"/QVS/var/run/libvirt/libvirt-sock-ro": "libvirt", "/var/run/docker.sock": "docker",
           "/var/run/system-docker.sock": "docker_interno"}
ATRIBUTO = re.compile(r"""([A-Za-z_:][A-Za-z0-9_:.-]*)=(?:'([^']*)'|"([^"]*)")""")
ELEMENTO = re.compile(r"^<(/?)([A-Za-z:_]+)")
TEXTO_XML = re.compile(r">([^<]*)<")
ENTIDADES = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&"))
FICHERO_SNAP = re.compile(r"([0-9]{9,11})\.(xml|state)")
SIN_LEER = "!! "                    # lo que una orden escribe cuando no encuentra lo que iba a leer


# --- utilidades -----------------------------------------------------------------------------

def _no_reconocida(que, linea=""):
    return ValueError("salida de %s no reconocida%s" % (que, (": %r" % linea[:80]) if linea else ""))


def _lineas(texto):
    return [linea.rstrip() for linea in texto.splitlines() if linea.strip()]


def _entero(valor, que):
    v = str(valor).strip()
    if not re.fullmatch(r"-?[0-9]+", v):
        raise ValueError("%s no es un numero: %r" % (que, v[:40]))
    return int(v)


def _acotado(valor, maximo):
    return SIN_CONTROL.sub(" ", str(valor))[:maximo] if valor is not None else None


def fecha_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _de_libvirt(texto, que):
    """Las lineas de una orden que empieza diciendo a que libvirt habla, sin esa primera."""
    lineas = _lineas(texto)
    if not lineas or lineas[0] != URI_SISTEMA:
        raise ValueError("%s: no hubo respuesta del libvirt del sistema%s"
                         % (que, (" (%r)" % lineas[0][:60]) if lineas else ""))
    return lineas[1:]


def _por_vm(lineas, que):
    """[(uuid, [lineas])] de una salida partida con '== <uuid>' por maquina."""
    vms = []
    for linea in lineas:
        if linea.startswith("== "):
            uuid = linea[3:].strip()
            if not UUID.fullmatch(uuid):
                raise _no_reconocida(que, linea)
            vms.append((uuid.lower(), []))
        elif not vms:
            raise _no_reconocida(que, linea)
        else:
            vms[-1][1].append(linea)
    return vms


# ==== anfitrion =================================================================================

def anfitrion(texto):
    """CPU y memoria del NAS y que servicios de virtualizacion tienen su socket abierto."""
    que = "el anfitrion"
    campos, memoria, sockets = {}, dict.fromkeys(MEMORIA.values()), dict.fromkeys(SOCKETS.values(), False)
    for linea in _lineas(texto):
        if linea.startswith("model name"):
            campos["cpu"] = linea.partition(":")[2].strip() or None
        elif linea.split(":")[0] in MEMORIA:
            m = re.fullmatch(r"([A-Za-z]+):\s+([0-9]+) kB", linea)
            if not m:
                raise _no_reconocida(que, linea)
            memoria[MEMORIA[m.group(1)]] = int(m.group(2)) * KIB
        else:
            clave, sep, valor = linea.partition("=")
            if not sep:
                raise _no_reconocida(que, linea)
            if clave == "socket":
                if valor in SOCKETS:
                    sockets[SOCKETS[valor]] = True
            else:
                campos[clave] = valor.strip()
    if "hilos" not in campos or memoria["total"] is None:
        raise _no_reconocida(que)
    carga = campos.get("carga", "").split()[:3]
    try:
        carga = [float(c) for c in carga] if len(carga) == 3 else None
    except ValueError:
        raise _no_reconocida(que, campos["carga"])
    return dict({"hilos": _entero(campos["hilos"], "el numero de hilos"), "cpu": campos.get("cpu"),
                 "virtualizacion": campos.get("virt") or None, "carga": carga, "memoria": memoria}, **sockets)


# ==== estadisticas (virsh domstats) =============================================================

def _dominios(lineas, que):
    """[(uuid, {clave: valor})] de una salida de domstats."""
    dominios = []
    for linea in lineas:
        m = re.fullmatch(r"Domain: '([^']+)'", linea.strip())
        if m:
            dominios.append((m.group(1).lower(), {}))
            continue
        clave, sep, valor = linea.strip().partition("=")
        if not sep or not dominios:
            raise _no_reconocida(que, linea)
        dominios[-1][1][clave] = valor
    return dominios


def _numero(campos, clave, que="un contador"):
    return _entero(campos[clave], que) if clave in campos else None


def _kib(campos, clave):
    valor = _numero(campos, clave, "la memoria")
    return valor * KIB if valor is not None else None


def _indices(campos, grupo):
    return range(_numero(campos, grupo + ".count") or 0)


def vm_estadisticas(texto):
    """virsh domstats: estado, CPU, memoria, discos y red de todas las VMs (tambien apagadas)."""
    que = "las estadisticas de las VMs"
    vms = []
    for uuid, c in _dominios(_de_libvirt(texto, que), que):
        if "state.state" not in c:
            raise _no_reconocida(que, "VM %s sin estado" % uuid)
        codigo = _entero(c["state.state"], "el estado")
        vms.append({
            "uuid": uuid, "estado": ESTADOS_VM.get(codigo, "estado %d" % codigo), "estado_codigo": codigo,
            "cpu_ns": _numero(c, "cpu.time"), "vcpus": _numero(c, "vcpu.current"),
            "memoria": _kib(c, "balloon.current"), "memoria_max": _kib(c, "balloon.maximum"),
            "memoria_residente": _kib(c, "balloon.rss"),
            "discos": [{"dispositivo": c.get("block.%d.name" % i),
                        "fichero": _acotado(c.get("block.%d.path" % i), MAX_RUTA),
                        "capacidad": _numero(c, "block.%d.capacity" % i),
                        "asignado": _numero(c, "block.%d.allocation" % i),
                        "en_disco": _numero(c, "block.%d.physical" % i)} for i in _indices(c, "block")],
            "red": [{"interfaz": c.get("net.%d.name" % i),
                     "rx_bytes": _numero(c, "net.%d.rx.bytes" % i), "tx_bytes": _numero(c, "net.%d.tx.bytes" % i),
                     "rx_errores": _numero(c, "net.%d.rx.errs" % i), "tx_errores": _numero(c, "net.%d.tx.errs" % i),
                     "rx_descartados": _numero(c, "net.%d.rx.drop" % i),
                     "tx_descartados": _numero(c, "net.%d.tx.drop" % i)} for i in _indices(c, "net")]})
    return vms


# ==== definicion (lineas elegidas de virsh dumpxml) =============================================

def _atributos(linea):
    return {m.group(1): m.group(2) if m.group(2) is not None else m.group(3) for m in ATRIBUTO.finditer(linea)}


def _texto_de(linea):
    m = TEXTO_XML.search(linea)
    if not m:
        return None
    texto = m.group(1)
    for entidad, caracter in ENTIDADES:
        texto = texto.replace(entidad, caracter)
    return texto.strip() or None


def _memoria(linea, que):
    if _atributos(linea).get("unit") != "KiB":
        raise _no_reconocida(que, linea.strip())
    return _entero(_texto_de(linea) or "", "la memoria") * KIB


def _vm(uuid, lineas, que):
    vm = {"uuid": uuid, "nombre": None, "descripcion": None, "sistema": None, "arquitectura": None,
          "arranque_automatico": None, "instantaneas": None, "memoria": None, "memoria_actual": None,
          "vcpus": None, "maquina": None, "firmware": "bios", "tpm": None, "arranque": [], "discos": [],
          "interfaces": [], "consola": None, "dispositivos_pasados": 0}
    disco = interfaz = None
    fondo = 0                       # nivel de <backingStore> dentro de un disco
    for cruda in lineas:
        linea = cruda.strip()
        m = ELEMENTO.match(linea)
        if not m:
            raise _no_reconocida(que, linea)
        cierre, elemento, a = m.group(1) == "/", m.group(2), _atributos(linea)
        if elemento == "disk":
            if cierre:
                disco, fondo = None, 0
            else:
                disco = {"dispositivo": None, "bus": None, "clase": a.get("device"), "formato": None,
                         "fichero": None, "bases": []}
                vm["discos"].append(disco)
        elif elemento == "interface":
            if cierre:
                interfaz = None
            else:
                interfaz = {"tipo": a.get("type"), "mac": None, "conmutador": None, "interfaz": None, "modelo": None}
                vm["interfaces"].append(interfaz)
        elif disco is not None:
            if elemento == "backingStore":
                if cierre:
                    fondo -= 1
                elif not linea.endswith("/>"):
                    fondo += 1
            elif elemento == "source":
                fichero = _acotado(a.get("file") or a.get("dev"), MAX_RUTA)
                if fondo:
                    disco["bases"].append(fichero)
                else:
                    disco["fichero"] = fichero
            elif elemento == "target" and not fondo:
                disco["dispositivo"], disco["bus"] = a.get("dev"), a.get("bus")
            elif elemento == "driver" and not fondo:
                disco["formato"] = a.get("type")
        elif interfaz is not None:
            if elemento == "mac":
                interfaz["mac"] = a.get("address")
            elif elemento == "source":
                interfaz["conmutador"] = a.get("bridge") or a.get("network") or a.get("dev")
            elif elemento == "target":
                interfaz["interfaz"] = a.get("dev")
            elif elemento == "model":
                interfaz["modelo"] = a.get("type")
        elif elemento == "qvs:name":
            vm["nombre"] = _acotado(_texto_de(linea), MAX_NOMBRE)
        elif elemento == "description":
            vm["descripcion"] = _acotado(_texto_de(linea), MAX_DESCRIPCION)
        elif elemento == "qvs:os":
            vm["sistema"], vm["arquitectura"] = a.get("type"), a.get("arch")
        elif elemento == "qvs:auto_start_delay":
            retraso = _texto_de(linea)
            vm["arranque_automatico"] = {
                "modo": a.get("enable"), "retraso_s": _entero(retraso, "el retraso") if retraso else None}
        elif elemento == "qvs:snapshot":
            vm["instantaneas"] = a.get("type")
        # con esos mismos nombres hay otros elementos que no son los de la VM: el ajuste NUMA
        # y los modulos de memoria (<memory mode=...>, <memory model=...>, sin unidad) y cada
        # vCPU que se puede anadir en caliente (<vcpu id=...>)
        elif elemento == "memory":
            if "unit" in a:
                vm["memoria"] = _memoria(linea, que)
        elif elemento == "currentMemory":
            vm["memoria_actual"] = _memoria(linea, que)
        elif elemento == "vcpu":
            if "id" not in a:
                vm["vcpus"] = _entero(_texto_de(linea) or "", "el numero de vCPU")
        elif elemento == "type":
            vm["maquina"] = a.get("machine")
        elif elemento == "loader":
            vm["firmware"] = "uefi"
        elif elemento == "boot":
            vm["arranque"].append(a.get("dev"))
        elif elemento == "graphics":
            # solo estos tres datos: la contrasena, si la linea la trajera, no se lee
            puerto = _entero(a["port"], "el puerto de la consola") if "port" in a else None
            vm["consola"] = {"tipo": a.get("type"), "puerto": puerto if puerto and puerto > 0 else None,
                             "escucha": a.get("listen")}
        elif elemento == "hostdev" and not cierre:
            vm["dispositivos_pasados"] += 1
        elif elemento == "tpm":
            vm["tpm"] = a.get("model")
    if vm["memoria"] is None or vm["vcpus"] is None:
        raise _no_reconocida(que, "VM %s sin memoria o sin vCPU" % uuid)
    return vm


def _vm_ilegible(uuid, lineas, error):
    """Una VM cuya definicion no se entiende: su nombre, si se ve, y el error; lo demas sin valor."""
    nombre = next((_acotado(_texto_de(linea.strip()), MAX_NOMBRE) for linea in lineas
                   if linea.strip().startswith("<qvs:name>")), None)
    vm = dict.fromkeys(("descripcion", "sistema", "arquitectura", "arranque_automatico", "instantaneas", "memoria",
                        "memoria_actual", "vcpus", "maquina", "firmware", "tpm", "arranque", "discos", "interfaces",
                        "consola", "dispositivos_pasados"))
    return dict(vm, uuid=uuid, nombre=nombre, error=error)


def vm_xml(texto):
    """La definicion de cada VM: nombre y descripcion, sistema, memoria, vCPU, firmware,
    arranque, discos, interfaces de red y consola (tipo, puerto y direccion; nunca su clave).
    Una VM con algo que no se entiende sale con su 'error' y sin datos: no tumba a las demas."""
    que = "la definicion de las VMs"
    vms = []
    for uuid, lineas in _por_vm(_de_libvirt(texto, que), que):
        try:
            vms.append(_vm(uuid, lineas, que))
        except ValueError as e:
            vms.append(_vm_ilegible(uuid, lineas, "no se entiende su definicion: %s" % e))
    return vms


# ==== direcciones (virsh domifaddr --source arp) ================================================

def vm_ip(texto):
    """Las direcciones de una VM que el NAS tiene en su tabla ARP (puede no haber ninguna)."""
    que = "las direcciones de la VM"
    lineas = _lineas(texto)
    if len(lineas) < 2 or lineas[0].split()[:1] != ["Name"] or not lineas[1].startswith("---"):
        raise _no_reconocida(que, lineas[0] if lineas else "")
    direcciones = []
    for linea in lineas[2:]:
        campos = linea.split()
        if len(campos) != 4 or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", campos[1]):
            raise _no_reconocida(que, linea)
        direcciones.append({"interfaz": campos[0], "mac": campos[1].lower(), "protocolo": campos[2],
                            "direccion": campos[3].rsplit("/", 1)[0]})
    return direcciones


# ==== uso (dos lecturas de domstats) ============================================================

def _lectura(lineas, que):
    """(segundos del reloj del NAS, {uuid: campos}) de una lectura: el reloj, lo que da domstats
    y su codigo de salida ("==rc N"). Sin dominios y sin ese 0, no es "ninguna en marcha"."""
    if not lineas or not re.fullmatch(r"[0-9]+\.[0-9]+ [0-9]+\.[0-9]+", lineas[0].strip()):
        raise _no_reconocida(que, lineas[0] if lineas else "")
    rc = re.fullmatch(r"==rc (-?[0-9]+)", lineas[-1].strip()) if len(lineas) > 1 else None
    if not rc:
        raise _no_reconocida(que, lineas[-1])
    if rc.group(1) != "0":
        raise ValueError("%s: virsh domstats fallo (codigo %s)" % (que, rc.group(1)))
    return float(lineas[0].split()[0]), dict(_dominios(lineas[1:-1], que))


def _ritmo(antes, despues, clave, segundos, divisor=1, decimales=1):
    """Lo que ha crecido un contador por segundo; None si falta o si ha retrocedido."""
    if clave not in antes or clave not in despues:
        return None
    crece = _entero(despues[clave], "un contador") - _entero(antes[clave], "un contador")
    return round(crece / segundos / divisor, decimales) if crece >= 0 else None


def vm_uso(texto):
    """Uso de las VMs en marcha entre dos lecturas: nucleos de CPU ocupados y que parte es de
    lo que la VM puede usar, memoria, y bytes y operaciones por segundo de discos y red."""
    que = "el uso de las VMs"
    antes, marca, despues = texto.partition("==5s")
    if not marca:
        raise _no_reconocida(que)
    t0, primera = _lectura(_de_libvirt(antes, que), que)
    t1, segunda = _lectura(_de_libvirt(despues, que), que)
    segundos = round(t1 - t0, 2)
    if segundos <= 0:
        raise ValueError("%s: el reloj del NAS no avanza entre las dos lecturas" % que)
    vms = []
    for uuid, d in segunda.items():
        a = primera.get(uuid)
        if a is None:
            continue                 # arrancada entre las dos lecturas: no hay con que comparar
        vcpus = _numero(d, "vcpu.current")
        nucleos = _ritmo(a, d, "cpu.time", segundos, 10 ** 9, decimales=2)
        vms.append({
            "uuid": uuid, "vcpus": vcpus, "cpu_nucleos": nucleos,
            "cpu_pct": round(min(nucleos / vcpus, 1) * 100, 1) if nucleos is not None and vcpus else None,
            "memoria": _kib(d, "balloon.current"), "memoria_residente": _kib(d, "balloon.rss"),
            "discos": [{"dispositivo": d.get("block.%d.name" % i),
                        "lectura_bytes_s": _ritmo(a, d, "block.%d.rd.bytes" % i, segundos),
                        "escritura_bytes_s": _ritmo(a, d, "block.%d.wr.bytes" % i, segundos),
                        "lecturas_s": _ritmo(a, d, "block.%d.rd.reqs" % i, segundos),
                        "escrituras_s": _ritmo(a, d, "block.%d.wr.reqs" % i, segundos)}
                       for i in _indices(d, "block") if "block.%d.rd.bytes" % i in d],
            "red": [{"interfaz": d.get("net.%d.name" % i),
                     "rx_bytes_s": _ritmo(a, d, "net.%d.rx.bytes" % i, segundos),
                     "tx_bytes_s": _ritmo(a, d, "net.%d.tx.bytes" % i, segundos)} for i in _indices(d, "net")]})
    return {"segundos": segundos, "vms": vms}


# ==== cadena de imagenes (qemu-img info --backing-chain) ========================================

def _capa(c, que):
    if not isinstance(c, dict) or not isinstance(c.get("filename"), str):
        raise _no_reconocida(que, repr(c))
    return {"fichero": _acotado(c["filename"], MAX_RUTA), "formato": c.get("format"),
            "virtual": c.get("virtual-size"), "ocupa": c.get("actual-size"),
            "base": _acotado(c.get("full-backing-filename") or c.get("backing-filename"), MAX_RUTA)}


CADENA_CORTADA = "!! cadena cortada"


def _objetos_json(cuerpo, que):
    """Los objetos JSON seguidos de un texto (qemu-img info da uno por capa)."""
    objetos, decodificador, i = [], json.JSONDecoder(), 0
    while i < len(cuerpo):
        if cuerpo[i].isspace():
            i += 1
            continue
        try:
            objeto, i = decodificador.raw_decode(cuerpo, i)
        except ValueError:
            raise _no_reconocida(que, cuerpo[i:])
        objetos.append(objeto)
    return objetos


def vm_imagenes(texto):
    """Por VM, la cadena de imagenes de cada disco, de la capa en uso a la base: formato,
    tamano virtual y lo que ocupa cada una. Un disco cuya imagen no se pudo leer queda con
    'cadena' sin valor. 'base_sin_leer' es la base de la ultima capa leida cuando la cadena
    sigue y no se ha leido (no es un fichero local, no se pudo abrir o la cadena se corto)."""
    que = "las imagenes de las VMs"
    vms = []
    for uuid, lineas in _por_vm(_de_libvirt(texto, que), que):
        discos, crudo = [], None
        for linea in lineas + ["-- "]:              # el centinela cierra el ultimo disco
            if linea.startswith("-- "):
                if crudo is not None:
                    capas = [_capa(c, que) for c in _objetos_json("\n".join(crudo), que)]
                    if capas:
                        discos[-1].update(cadena=capas, base_sin_leer=capas[-1]["base"])
                if linea != "-- ":
                    discos.append({"fichero": _acotado(linea[3:].strip(), MAX_RUTA), "cadena": None,
                                   "base_sin_leer": None, "cortada": False})
                    crudo = []
            elif crudo is None:
                raise _no_reconocida(que, linea)
            elif linea.strip() == CADENA_CORTADA:
                discos[-1]["cortada"] = True
            else:
                crudo.append(linea)
        vms.append({"uuid": uuid, "discos": discos})
    return vms


# ==== instantaneas ==============================================================================

def vm_snap_vs(texto):
    """Las instantaneas de Virtualization Station de cada VM: un fichero <momento>.xml por
    instantanea y, si se tomo con la VM en marcha, otro .state con su memoria. Una VM cuya
    carpeta de metadatos no se encontro queda con 'instantaneas' sin valor: no se sabe."""
    que = "las instantaneas de VS"
    vms = []
    for uuid, lineas in _por_vm(_de_libvirt(texto, que), que):
        momentos, sin_carpeta = {}, False
        for linea in lineas:
            sin_carpeta = sin_carpeta or linea.startswith(SIN_LEER)
            m = FICHERO_SNAP.fullmatch(linea.strip())
            if m:
                momentos.setdefault(int(m.group(1)), set()).add(m.group(2))
        vms.append({"uuid": uuid, "instantaneas": None if sin_carpeta else [
            {"id": momento, "creada": fecha_utc(momento), "con_memoria": "state" in clases}
            for momento, clases in sorted(momentos.items()) if "xml" in clases]})
    return vms


def vm_snap_libvirt(texto):
    """Las instantaneas que conoce libvirt (VS usa las suyas: lo normal es que no haya)."""
    que = "las instantaneas de libvirt"
    vms = []
    for uuid, lineas in _por_vm(_de_libvirt(texto, que), que):
        if len(lineas) < 2 or lineas[0].split()[:1] != ["Name"] or not lineas[1].startswith("---"):
            raise _no_reconocida(que, lineas[0] if lineas else "VM %s" % uuid)
        instantaneas = []
        for linea in lineas[2:]:
            m = re.fullmatch(r"\s*(\S+)\s+([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8} [+-][0-9]{4})\s+(\S+)\s*(\S*)\s*", linea)
            if not m:
                raise _no_reconocida(que, linea)
            instantaneas.append({"nombre": _acotado(m.group(1), MAX_NOMBRE), "creada": m.group(2),
                                 "estado": m.group(3), "padre": m.group(4) or None})
        vms.append({"uuid": uuid, "instantaneas": instantaneas})
    return vms


# ================================================================================================
# contenedores (Container Station)
# ================================================================================================

MAX_LINEA = 400                     # caracteres de cada linea de registro que se devuelven
MARCA_RC = re.compile(r"==rc (-?[0-9]+)")       # ultima linea de la orden del registro
# lo que escribe el propio cliente de docker cuando no puede atender la consulta
ERROR_DOCKER = re.compile(r"^(Cannot connect to the Docker daemon|Error response from daemon|Error: |"
                          r"permission denied while trying to connect|error during connect)", re.I)
CUENTAS_INFO = ("contenedores", "en_marcha", "en_pausa", "parados", "imagenes", "cpus", "memoria")
SALUD = re.compile(r"\((healthy|unhealthy|health: starting)\)")
SALIDA = re.compile(r"^Exited \((-?[0-9]+)\)")
PUERTO = re.compile(r"^(?:(.*):([0-9]+(?:-[0-9]+)?)->)?([0-9]+(?:-[0-9]+)?)/([a-z]+)$")
SIN_FECHA = "0001-01-01T00:00:00Z"
# docker da la memoria en multiplos de 1024 (KiB...) y la red y el disco en multiplos de 1000 (kB...)
UNIDADES = {"B": 1, "kB": 10 ** 3, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9, "TB": 10 ** 12, "PB": 10 ** 15,
            "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4, "PiB": 1024 ** 5}
TAMANO = re.compile(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]+)")
SIN_CIFRA = "--"
CARPETAS_LXD = {"/var/lib/lxd/containers": "contenedores", "/var/lib/lxd/virtual-machines": "maquinas"}


def _de_docker(texto, que):
    """Las lineas de una salida de docker; si lo que hay es un error del cliente, ValueError."""
    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    for linea in lineas[:1]:
        if ERROR_DOCKER.match(linea.strip()):
            raise ValueError("%s: docker no pudo atender la consulta: %s" % (que, _acotado(linea.strip(), 160)))
    return lineas


def _columnas(linea, cuantas, que):
    campos = linea.split("\t")
    if len(campos) != cuantas:
        raise _no_reconocida(que, linea)
    return [c.strip() for c in campos]


def ct_info(texto):
    """Version del motor Docker de Container Station y cuantos contenedores e imagenes hay."""
    que = "el resumen de docker"
    campos = {}
    for linea in _de_docker(texto, que):
        clave, sep, valor = linea.partition("=")
        if not sep:
            raise _no_reconocida(que, linea)
        campos[clave.strip()] = valor.strip()
    if not campos.get("version") or any(c not in campos for c in CUENTAS_INFO):
        raise _no_reconocida(que)
    info = {"version": _acotado(campos["version"], MAX_NOMBRE), "driver": campos.get("driver") or None,
            "raiz": _acotado(campos.get("raiz") or None, MAX_RUTA)}
    info.update({c: _entero(campos[c], c) for c in CUENTAS_INFO})
    return info


def _puertos(texto, que):
    puertos = []
    for trozo in [t.strip() for t in texto.split(",") if t.strip()]:
        m = PUERTO.fullmatch(trozo)
        if not m:
            raise _no_reconocida(que, trozo)
        anfitrion = m.group(1)
        if anfitrion is not None:
            anfitrion = anfitrion.strip("[]") or None
        puertos.append({"anfitrion": anfitrion, "puerto": m.group(2), "interno": m.group(3), "protocolo": m.group(4)})
    return puertos


def ct_lista(texto):
    """docker ps -a: cada contenedor con su imagen, estado, salud, puertos, redes y proyecto."""
    que = "la lista de contenedores"
    contenedores = []
    for linea in _de_docker(texto, que):
        nombre, imagen, estado, detalle, puertos, redes, creado, proyecto = _columnas(linea, 8, que)
        salud, salida = SALUD.search(detalle), SALIDA.match(detalle)
        contenedores.append({
            "nombre": _acotado(nombre, MAX_NOMBRE), "imagen": _acotado(imagen, MAX_NOMBRE), "estado": estado,
            "detalle": _acotado(detalle, MAX_NOMBRE),
            "salud": salud.group(1).replace("health: ", "") if salud else None,
            "salida": int(salida.group(1)) if salida else None, "puertos": _puertos(puertos, que),
            "redes": [_acotado(r, MAX_NOMBRE) for r in redes.split(",") if r],
            "creado": creado or None, "proyecto": _acotado(proyecto, MAX_NOMBRE) if proyecto else None})
    return contenedores


def _json(texto, que):
    try:
        return json.loads(texto)
    except ValueError:
        raise _no_reconocida(que, texto)


def ct_compose(texto):
    """docker compose ls: las aplicaciones (proyectos), su estado y sus ficheros de definicion."""
    que = "las aplicaciones compose"
    lineas = _de_docker(texto, que)
    proyectos = _json("\n".join(lineas), que) if lineas else None
    if not isinstance(proyectos, list):
        raise _no_reconocida(que, "\n".join(lineas))
    resultado = []
    for x in proyectos:
        if not isinstance(x, dict) or not isinstance(x.get("Name"), str):
            raise _no_reconocida(que, repr(x))
        resultado.append({"proyecto": _acotado(x["Name"], MAX_NOMBRE), "estado": _acotado(x.get("Status"), MAX_NOMBRE),
                          "ficheros": [_acotado(f, MAX_RUTA) for f in str(x.get("ConfigFiles") or "").split(",") if f]})
    return resultado


def _red_de_contenedor(trozo, que):
    red, sep, resto = trozo.partition("=")
    partes = resto.split(" ")
    if not sep or not red or len(partes) != 3:
        raise _no_reconocida(que, trozo)
    direccion, _, prefijo = partes[0].partition("/")
    return {"red": _acotado(red, MAX_NOMBRE), "direccion": direccion or None,
            "prefijo": _entero(prefijo, "el prefijo") if direccion else None,
            "puerta": partes[1] or None, "mac": partes[2] or None}


def ct_detalle(texto):
    """docker inspect de un contenedor, solo con los campos que pide la orden: estado, salud,
    reinicios, limites, redes, puertos, montajes y proyecto compose. Lo que no este en esa
    lista no se devuelve aunque la salida lo trajera."""
    que = "el detalle del contenedor"
    crudo = {}
    for linea in _de_docker(texto, que):
        clave, sep, valor = linea.partition("=")
        if not sep:
            raise _no_reconocida(que, linea)
        crudo[clave] = valor
    falta = [c for c in ("nombre", "imagen", "estado", "salida", "redes", "puertos", "montajes") if c not in crudo]
    if falta:
        raise _no_reconocida(que, "falta %s" % ", ".join(falta))
    c = {clave: _json(valor, que) for clave, valor in crudo.items() if clave != "redes"}

    def texto_de(clave, maximo=MAX_NOMBRE):
        return _acotado(c.get(clave), maximo) if c.get(clave) not in (None, "") else None

    def fecha(clave):
        return texto_de(clave) if c.get(clave) != SIN_FECHA else None

    if not isinstance(c["salida"], int) or not isinstance(c["montajes"], list) or not isinstance(c["puertos"], dict):
        raise _no_reconocida(que)
    puertos = []
    for interno, publicados in c["puertos"].items():
        for x in publicados or [{}]:
            puertos.append({"interno": interno, "anfitrion": x.get("HostIp") or None, "puerto": x.get("HostPort") or None})
    return {
        "nombre": _acotado(str(c["nombre"]).lstrip("/"), MAX_NOMBRE), "imagen": texto_de("imagen"),
        "creado": fecha("creado"), "estado": texto_de("estado"), "salida": c["salida"],
        "sin_memoria": c.get("sin_memoria"), "error": texto_de("error", MAX_DESCRIPCION),
        "inicio": fecha("inicio"), "fin": fecha("fin"), "reinicios": c.get("reinicios"),
        "salud": texto_de("salud"), "reinicio": texto_de("reinicio"),
        "memoria_limite": c.get("memoria") or None,
        "cpus_limite": round(c["nanocpus"] / 10 ** 9, 2) if c.get("nanocpus") else None,
        "privilegiado": c.get("privilegiado"), "modo_red": texto_de("modo_red"),
        "redes": [_red_de_contenedor(t, que) for t in crudo["redes"].split(";") if t.strip()],
        "puertos": puertos,
        "montajes": [{"tipo": m.get("Type"), "volumen": _acotado(m.get("Name"), MAX_NOMBRE),
                      "destino": _acotado(m.get("Destination"), MAX_RUTA), "escritura": m.get("RW"),
                      "origen": _acotado(m.get("Source"), MAX_RUTA)} for m in c["montajes"]],
        "proyecto": texto_de("proyecto"), "servicio": texto_de("servicio"), "compose": texto_de("compose", MAX_RUTA)}


def _bytes(texto, que):
    if texto == SIN_CIFRA:
        return None
    m = TAMANO.fullmatch(texto)
    if not m or m.group(2) not in UNIDADES:
        raise _no_reconocida(que, texto)
    return round(float(m.group(1)) * UNIDADES[m.group(2)])


def _par(texto, que):
    partes = [x.strip() for x in texto.split(" / ")]
    if len(partes) != 2:
        raise _no_reconocida(que, texto)
    return _bytes(partes[0], que), _bytes(partes[1], que)


def _pct(texto, que):
    if texto == SIN_CIFRA:
        return None
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?%", texto):
        raise _no_reconocida(que, texto)
    return float(texto[:-1])


def ct_stats(texto):
    """docker stats: de cada contenedor en marcha, CPU, memoria y su limite, lo recibido y
    enviado por red, lo leido y escrito en disco y el numero de procesos. Una muestra."""
    que = "el uso de los contenedores"
    uso = []
    for linea in _de_docker(texto, que):
        nombre, cpu, memoria, mem_pct, red, disco, procesos = _columnas(linea, 7, que)
        usada, limite = _par(memoria, que)
        recibido, enviado = _par(red, que)
        leido, escrito = _par(disco, que)
        fila = {"nombre": _acotado(nombre, MAX_NOMBRE), "cpu_pct": _pct(cpu, que), "memoria": usada,
                "memoria_limite": limite, "memoria_pct": _pct(mem_pct, que), "red_recibido": recibido,
                "red_enviado": enviado, "disco_leido": leido, "disco_escrito": escrito,
                "procesos": None if procesos == SIN_CIFRA else _entero(procesos, "los procesos")}
        if limite == 0:
            # "0B / 0B": un contenedor que aun arranca o ya se ha parado; no se midio, y sus
            # ceros no son cifras
            fila = dict(dict.fromkeys(fila), nombre=fila["nombre"])
        uso.append(fila)
    return uso


def ct_logs(texto):
    """Las lineas del registro de un contenedor, sin caracteres de control y cortadas. Son
    texto que escribe el programa del contenedor: datos, no instrucciones.

    El registro llega mezclado con lo que diga el propio docker, asi que la orden termina con
    el codigo de salida de docker ("==rc N"). Con 0, todo lo anterior lo ha escrito el
    contenedor, empiece como empiece; con otro valor es un fallo de docker; sin esa linea no
    se sabe si docker respondio."""
    que = "el registro del contenedor"
    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    marca = MARCA_RC.fullmatch(lineas[-1].strip()) if lineas else None
    if not marca:
        raise _no_reconocida(que, lineas[-1] if lineas else "")
    cuerpo = lineas[:-1]
    if marca.group(1) != "0":
        raise ValueError("%s: docker no pudo atender la consulta: %s" % (
            que, _acotado(cuerpo[-1].strip(), 160) if cuerpo else "termino con codigo %s" % marca.group(1)))
    return [_acotado(linea, MAX_LINEA) for linea in cuerpo]


def ct_redes(texto):
    """Las redes de Docker: driver, ambito, subredes y contenedores conectados con su IP."""
    que = "las redes de docker"
    redes = []
    for linea in _de_docker(texto, que):
        campos = linea.split("\t")
        if len(campos) != 6:
            raise _no_reconocida(que, linea)
        nombre, driver, ambito, interna, ipam, conectados = [c.strip() for c in campos]
        subredes = _json(ipam, que) or []
        if not isinstance(subredes, list):
            raise _no_reconocida(que, ipam)
        contenedores = []
        for trozo in conectados.split():
            contenedor, sep, direccion = trozo.partition("=")
            if not sep or not contenedor:
                raise _no_reconocida(que, trozo)
            contenedores.append({"nombre": _acotado(contenedor, MAX_NOMBRE), "direccion": direccion.split("/")[0] or None})
        redes.append({"red": _acotado(nombre, MAX_NOMBRE), "driver": driver, "ambito": ambito,
                      "interna": interna == "true",
                      "subredes": [{"subred": s.get("Subnet"), "puerta": s.get("Gateway")} for s in subredes],
                      "contenedores": contenedores})
    if not redes:
        raise _no_reconocida(que)              # docker tiene siempre sus tres redes de fabrica
    return redes


def ct_internos(texto):
    """Los contenedores del docker interno de Container Station (servicios del propio paquete)."""
    que = "los contenedores internos"
    return [dict(zip(("nombre", "imagen", "estado"), [_acotado(c, MAX_NOMBRE) for c in _columnas(linea, 3, que)]))
            for linea in _de_docker(texto, que)]


def ct_lxd(texto):
    """Las instancias de LXD, por los nombres de sus carpetas (el cliente lxc no se ejecuta)."""
    que = "las carpetas de LXD"
    resultado, actual = {}, None
    for linea in _lineas(texto):
        if linea.startswith("== "):
            if linea[3:] not in CARPETAS_LXD:
                raise _no_reconocida(que, linea)
            actual = resultado.setdefault(CARPETAS_LXD[linea[3:]], [])
        elif actual is None:
            raise _no_reconocida(que, linea)
        else:
            actual.append(_acotado(linea.strip(), MAX_NOMBRE))
    if set(resultado) != set(CARPETAS_LXD.values()):
        raise _no_reconocida(que)
    return resultado
