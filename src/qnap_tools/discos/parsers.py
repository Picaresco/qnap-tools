# -*- coding: utf-8 -*-
"""Parsers de la pata de discos: texto de una orden -> estructura.

Funciones puras, una por orden de discos/comandos.py. Las claves van en castellano sin
acentos. Una salida que no se reconoce lanza ValueError: nunca se devuelven datos inventados
ni una lista vacia por no haber entendido el texto. Solo devuelven vacio las ordenes en las
que "no hay nada" es una respuesta valida (sin SSD, sin avisos configurados).

Un disco se identifica por cabina y bahia (dos numeros); la lista y el reparto de
qcli_storage usan otros nombres (NAS_HOST, P2-1) y se cruzan con el resto por dispositivo.
"""
import json
import re
from datetime import datetime, timezone

SIN_DATO = "--"
# codigo "type" de los ficheros de cabina, visto en los tres NAS de pruebas
BUS = {"0": "sata", "2": "usb", "4": "nvme"}
CLASE_NVME = "4"                    # segundo campo de la cabecera de un fichero SMART
FICHERO_CABINA = re.compile(r"^== /etc/enclosure_([0-9]+)(_del)?\.conf$")
SECCION_DISCO = re.compile(r"^\[PhysicalDisk_([0-9]+)\]$")
FICHERO_SMART = re.compile(r"^== \S*smart_([0-9]+)_([0-9]+)\.info$")
FICHERO_VIDA = re.compile(r"^== \S*disk_([0-9]+)_([0-9]+)\.info$")
SECCION_AVISO = re.compile(r"^\[S\.M\.A\.R\.T\. ID #([0-9]+)\]$")
TEMPERATURA = re.compile(r"^(--|[0-9]+) C/(--|[0-9]+) F$")
SIN_PRIVILEGIOS = ("0 C/32 F", SIN_DATO)     # lo que responde getsysinfo sin ser root
CAMPOS_SALUD = ("modelo", "temperatura", "smart", "estado")
CAMPOS_CABECERA_SMART = 9           # hasta la temperatura, que es el noveno
SECTOR = 512                        # unidad de los contadores de /proc/diskstats
MEGA = 1024 * 1024
CONTADORES = 11                     # los de siempre; los nucleos nuevos anaden mas detras


# --- utilidades -----------------------------------------------------------------------------

def _no_reconocida(que, linea=""):
    return ValueError("salida de %s no reconocida%s" % (que, (": %r" % linea[:80]) if linea else ""))


def _lineas(texto):
    return [linea.rstrip() for linea in texto.splitlines() if linea.strip()]


def _entero(valor, que):
    v = valor.strip()
    if not re.fullmatch(r"-?[0-9]+", v):
        raise ValueError("%s no es un numero: %r" % (que, valor[:40]))
    return int(v)


def _texto(valor):
    v = (valor or "").strip()
    return v if v and v != SIN_DATO else None


def _clave_valor(linea, que):
    clave, sep, valor = linea.partition("=")
    if not sep:
        raise _no_reconocida(que, linea)
    return clave.strip(), valor.strip()


def _tabla(texto, que):
    """Tabla de columnas alineadas de qcli_storage -> [{cabecera: valor}], cortando cada fila
    por donde empieza cada titulo (los valores llevan espacios: 'RAID 1', '465.76 GB')."""
    lineas = _lineas(texto)
    if not lineas or not lineas[0].startswith("Enclosure") or "Sys_Name" not in lineas[0]:
        raise _no_reconocida(que, lineas[0] if lineas else "")
    titulos = [(m.group(0), m.start()) for m in re.finditer(r"\S+", lineas[0])]
    filas = []
    for linea in lineas[1:]:
        fila = {}
        for i, (titulo, inicio) in enumerate(titulos):
            fin = titulos[i + 1][1] if i + 1 < len(titulos) else None
            fila[titulo] = linea[inicio:fin].strip()
        # una fila descolocada (un valor mas ancho que su columna) no se adivina
        if not fila["Sys_Name"].startswith("/dev/") or " " in fila["Enclosure"] or not fila["Port"]:
            raise _no_reconocida(que, linea)
        fila["Sys_Name"] = fila["Sys_Name"].split("(")[0]
        filas.append(fila)
    if not filas:
        raise _no_reconocida(que, lineas[0])
    return filas


# --- discos -----------------------------------------------------------------------------------

def discos_lista(texto):
    """qcli_storage -d: un disco por fila, con el nombre de puerto que ve el usuario."""
    discos = []
    for fila in _tabla(texto, "la lista de discos"):
        tipo, _, uso = fila.get("Type", "").partition(":")
        discos.append({
            "cabina": fila["Enclosure"], "puerto": fila["Port"], "dispositivo": fila["Sys_Name"],
            "tipo": _texto(tipo), "uso": _texto(uso), "tamano": _texto(fila.get("Size")),
            "alias": _texto(fila.get("Alias")), "modelo": _texto(fila.get("Model"))})
    return discos


def discos_reparto(texto):
    """qcli_storage -p: a que grupo (vdev en QuTS hero, md en QTS) y pool pertenece cada disco.
    Los nombres de carpeta y de volumen de la ultima columna no se devuelven."""
    reparto = []
    for fila in _tabla(texto, "el reparto de discos"):
        if "RAID_Type" not in fila or "Pool" not in fila or not ("VDEV" in fila or "RAID" in fila):
            raise _no_reconocida("el reparto de discos", texto.splitlines()[0])
        pool = _texto(fila["Pool"])
        reparto.append({
            "cabina": fila["Enclosure"], "puerto": fila["Port"], "dispositivo": fila["Sys_Name"],
            "uso": _texto(fila.get("Type")), "grupo": _texto(fila.get("VDEV", fila.get("RAID"))),
            "raid": _texto(fila["RAID_Type"].split(",")[0]),
            "pool": _entero(pool, "el pool") if pool is not None else None})
    return reparto


def discos_detalle(texto):
    """Campos de /etc/enclosure_<cabina>.conf: un disco por seccion [PhysicalDisk_<bahia>].
    Los ficheros enclosure_<n>_del.conf guardan discos que ya no estan y no cuentan."""
    que = "el detalle de los discos"
    discos, crudo, cabina = [], None, None
    vale = False                     # dentro de un fichero que cuenta
    for linea in _lineas(texto):
        if linea.startswith("== "):
            m = FICHERO_CABINA.match(linea)
            if not m:
                raise _no_reconocida(que, linea)
            cabina, vale, crudo = int(m.group(1)), not m.group(2), None
            continue
        if cabina is None:
            raise _no_reconocida(que, linea)
        m = SECCION_DISCO.match(linea)
        if m:
            crudo = {"cabina": cabina, "seccion": m.group(1)}
            if vale:
                discos.append(crudo)
            continue
        if crudo is None:
            raise _no_reconocida(que, linea)
        clave, valor = _clave_valor(linea, que)
        crudo[clave] = valor
    if not discos:
        raise _no_reconocida(que)
    return [_disco(c) for c in discos]


def _disco(c):
    def numero(clave):
        return _entero(c[clave], clave) if c.get(clave) else None
    sectores, sector = numero("capacity"), numero("sector_size")
    return {
        "cabina": c["cabina"], "bahia": _entero(c.get("port_id") or c["seccion"], "port_id"),
        "dispositivo": _texto(c.get("pd_sys_name")), "bus": BUS.get(c.get("type", "")),
        "fabricante": _texto(c.get("vendor")), "modelo": _texto(c.get("model")),
        "serie": _texto(c.get("serial_no")), "firmware": _texto(c.get("revision")),
        "bytes": sectores * sector if sectores is not None and sector is not None else None,
        "rpm": numero("rotation_speed") or None,       # 0 = no gira o no lo dice
        "estado": numero("status")}


def discos_salud(texto):
    """getsysinfo por bahia de la cabina principal: temperatura y veredicto SMART del NAS.
    Solo las bahias ocupadas. Sin privilegios getsysinfo responde 0 C y -- en todas: eso es un
    error, nunca cero grados."""
    que = "la salud de los discos"
    bahias, actual = [], None
    for linea in _lineas(texto):
        if linea.startswith("== "):
            actual = {"bahia": _entero(linea[3:], "la bahia")}
            bahias.append(actual)
            continue
        if actual is None:
            raise _no_reconocida(que, linea)
        clave, valor = _clave_valor(linea, que)
        actual[clave] = valor
    if not bahias:
        raise _no_reconocida(que)
    ocupadas = []
    for b in bahias:
        if any(campo not in b for campo in CAMPOS_SALUD):
            raise _no_reconocida(que, "bahia %d" % b["bahia"])
        m = TEMPERATURA.match(b["temperatura"])
        if not m:
            raise _no_reconocida(que, b["temperatura"])
        if _texto(b["modelo"]) is None:
            continue                                   # bahia vacia
        sin_dato = (b["temperatura"], b["smart"]) == SIN_PRIVILEGIOS
        grados = int(m.group(1)) if m.group(1) != SIN_DATO else 0
        ocupadas.append({
            "bahia": b["bahia"], "modelo": b["modelo"], "temperatura": grados if grados > 0 else None,
            "smart": _texto(b["smart"]), "estado": _entero(b["estado"], "el estado"),
            "_sin_dato": sin_dato})
    if ocupadas and all(o["_sin_dato"] for o in ocupadas):
        raise ValueError("getsysinfo no ha dado temperatura ni estado SMART de ningun disco "
                         "(responde asi cuando se lanza sin privilegios de root)")
    for o in ocupadas:
        del o["_sin_dato"]
    return ocupadas


# --- SMART ------------------------------------------------------------------------------------

def _smart(lineas, que):
    """Un fichero smart_<cabina>_<bahia>.info: una cabecera y una linea por atributo
    (id,nombre,valor,peor,umbral,crudo,...). En un NVMe los atributos son los campos de su
    registro de salud y solo llevan valor crudo."""
    if not lineas:
        raise _no_reconocida(que)
    cabecera = lineas[0].split(",")
    if len(cabecera) < CAMPOS_CABECERA_SMART:
        raise _no_reconocida(que, lineas[0])
    nvme = cabecera[1].strip() == CLASE_NVME
    grados = _entero(cabecera[CAMPOS_CABECERA_SMART - 1], "la temperatura")
    atributos = []
    for linea in lineas[1:]:
        ident, _, resto = linea.partition(",")
        partes = resto.rsplit(",", 5)          # el nombre puede llevar comas
        if len(partes) != 6:
            raise _no_reconocida(que, linea)
        nombre, valor, peor, umbral, crudo, _ = partes
        valor, peor, umbral = (_entero(x, "un atributo SMART") for x in (valor, peor, umbral))
        crudo = crudo.strip()
        atributos.append({
            "id": _entero(ident, "el identificador de un atributo SMART"), "nombre": nombre.strip(),
            "valor": None if nvme else valor, "peor": None if nvme else peor,
            "umbral": None if nvme else umbral,
            "crudo": int(crudo) if re.fullmatch(r"-?[0-9]+", crudo) else crudo,
            # el criterio del propio SMART: el valor normalizado ha caido hasta su umbral
            "bajo_umbral": not nvme and umbral > 0 and valor <= umbral})
    return {"clase": "nvme" if nvme else "ata", "temperatura": grados if grados > 0 else None,
            "atributos": atributos}


def smart_atributos(texto):
    return _smart(_lineas(texto), "los atributos SMART")


def smart_todos(texto):
    que = "los ficheros SMART"
    bloques = []
    for linea in _lineas(texto):
        if linea.startswith("== "):
            m = FICHERO_SMART.match(linea)
            if not m:
                raise _no_reconocida(que, linea)
            bloques.append((int(m.group(1)), int(m.group(2)), []))
        elif not bloques:
            raise _no_reconocida(que, linea)
        else:
            bloques[-1][2].append(linea)
    if not bloques:
        raise _no_reconocida(que)
    return [dict(_smart(lineas, "%s (cabina %d, bahia %d)" % (que, cabina, bahia)),
                 cabina=cabina, bahia=bahia) for cabina, bahia, lineas in bloques]


def smart_umbrales(texto):
    """Avisos por valor crudo que el usuario ha configurado en el NAS (/tmp/smart_warning.conf)."""
    que = "los avisos SMART"
    politica, avisos, actual = None, [], None
    for linea in _lineas(texto):
        m = SECCION_AVISO.match(linea)
        if m:
            actual = {"id": int(m.group(1))}
            avisos.append(actual)
            continue
        if linea.startswith("["):
            raise _no_reconocida(que, linea)
        clave, valor = _clave_valor(linea, que)
        if clave == "policy" and actual is None:
            politica = _entero(valor, "la politica")
        elif clave in ("enable", "value") and actual is not None:
            actual[clave] = _entero(valor, clave)
        else:
            raise _no_reconocida(que, linea)
    for a in avisos:
        if a.get("enable") not in (0, 1) or "value" not in a:
            raise _no_reconocida(que, "ID #%d" % a["id"])
    return {"politica": politica,
            "avisos": [{"id": a["id"], "activo": a["enable"] == 1, "limite": a["value"]} for a in avisos]}


def ssd_vida(texto):
    """Desgaste de cada SSD segun el NAS (SSD_LIFE_USED, en %). Sin SSD, lista vacia."""
    que = "la vida de los SSD"
    vidas = []
    for linea in _lineas(texto):
        if linea.startswith("== "):
            m = FICHERO_VIDA.match(linea)
            if not m:
                raise _no_reconocida(que, linea)
            vidas.append({"cabina": int(m.group(1)), "bahia": int(m.group(2)), "usado_pct": None})
            continue
        clave, valor = _clave_valor(linea, que)
        if clave != "SSD_LIFE_USED" or not vidas:
            raise _no_reconocida(que, linea)
        vidas[-1]["usado_pct"] = _entero(valor, "el desgaste")
    return vidas


# --- rendimiento ------------------------------------------------------------------------------

def _lectura(lineas, que):
    """Una lectura: la linea de /proc/uptime y las de /proc/diskstats -> (segundos, {disco: contadores})."""
    if not lineas or not re.fullmatch(r"[0-9]+\.[0-9]+ [0-9]+\.[0-9]+", lineas[0].strip()):
        raise _no_reconocida(que, lineas[0] if lineas else "")
    discos = {}
    for linea in lineas[1:]:
        campos = linea.split()
        if len(campos) < 3 + CONTADORES:
            raise _no_reconocida(que, linea)
        discos[campos[2]] = [_entero(c, "un contador") for c in campos[3:3 + CONTADORES]]
    if not discos:
        raise _no_reconocida(que)
    return float(lineas[0].split()[0]), discos


def diskstats(texto):
    """Dos lecturas de /proc/diskstats separadas por '==5s' -> actividad de cada disco entre
    las dos: operaciones por segundo, MB/s (de 1024 x 1024 bytes), espera media por operacion
    y porcentaje del tiempo ocupado. Si un contador retrocede, ese disco queda sin cifras."""
    que = "el rendimiento de los discos"
    lineas = _lineas(texto)
    marcas = [i for i, linea in enumerate(lineas) if linea.startswith("==")]
    if len(marcas) != 1:
        raise _no_reconocida(que)
    t0, antes = _lectura(lineas[:marcas[0]], que)
    t1, despues = _lectura(lineas[marcas[0] + 1:], que)
    segundos = t1 - t0
    if segundos <= 0:
        raise ValueError("el intervalo entre las dos lecturas no es valido: %.2f s" % segundos)
    discos = []
    for nombre, a in antes.items():
        if nombre not in despues:
            continue
        d = [fin - ini for ini, fin in zip(a, despues[nombre])]
        lecturas, _, sect_leidos, ms_leyendo, escrituras, _, sect_escritos, ms_escribiendo, _, ms_ocupado, _ = d
        # el noveno (operaciones en curso) es un valor instantaneo, no un contador
        if min(lecturas, sect_leidos, ms_leyendo, escrituras, sect_escritos, ms_escribiendo, ms_ocupado) < 0:
            discos.append(dict.fromkeys(("dispositivo", "lecturas_s", "escrituras_s", "leido_mb_s",
                                         "escrito_mb_s", "espera_ms", "ocupacion_pct"), None)
                          | {"dispositivo": nombre})
            continue
        operaciones = lecturas + escrituras
        discos.append({
            "dispositivo": nombre,
            "lecturas_s": round(lecturas / segundos, 1), "escrituras_s": round(escrituras / segundos, 1),
            "leido_mb_s": round(sect_leidos * SECTOR / segundos / MEGA, 2),
            "escrito_mb_s": round(sect_escritos * SECTOR / segundos / MEGA, 2),
            "espera_ms": round((ms_leyendo + ms_escribiendo) / operaciones, 2) if operaciones else None,
            "ocupacion_pct": min(100.0, round(ms_ocupado / (segundos * 1000) * 100, 1))})
    return {"segundos": round(segundos, 2), "discos": discos}


# ==== QuTS hero ===============================================================================

MAX_FICHEROS = 20                   # ficheros danados que se listan de cada pool
MAX_RUTA = 200
MAX_TEXTO = 64                      # texto que escribe un tercero (un alias)
MAX_NOMBRE = 255
CLAVE_ESTADO = re.compile(r"^ {0,6}([a-z]+): ?(.*)$")      # "  pool: zpool1", "status: ..."
MIEMBRO_ZFS = re.compile(r"enc_([0-9]+)/disk_0x([0-9a-fA-F]+)_")
CUENTA = re.compile(r"^([0-9]+(?:\.[0-9]+)?)([KMGT]?)$")
MILES = {"": 1, "K": 10 ** 3, "M": 10 ** 6, "G": 10 ** 9, "T": 10 ** 12}
SECCION_PROG = re.compile(r"^\[(Global|Retention|Schedule)([0-9]*)\]$")
LINEA_JSON = re.compile(r'^( *)"([^"]+)":(.*)$')
LISTAS_ISCSI = {"target": "destinos", "lun": "lun", "initiator": "iniciadores"}
GIB = 2 ** 30                       # la capacidad de un LUN de QuTS hero va en GiB
SIN_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _veces(valor, que):
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)x", valor.strip())
    if not m:
        raise ValueError("%s no es una proporcion: %r" % (que, valor[:40]))
    return float(m.group(1))


def _tamano(valor, que):
    """Tamano en bytes de zfs/zpool -p; '-' y 'none' son 'no tiene'."""
    v = valor.strip()
    return None if v in ("-", "none") else _entero(v, que)


def _valor(valor):
    v = valor.strip()
    if not v:
        return None
    return int(v) if re.fullmatch(r"-?[0-9]+", v) else v


def _acotado(valor, maximo):
    return SIN_CONTROL.sub(" ", str(valor))[:maximo] if valor is not None else None


def _tabulado(texto, campos, que):
    filas = []
    for linea in _lineas(texto):
        fila = linea.split("\t")
        if len(fila) != campos:
            raise _no_reconocida(que, linea)
        filas.append(fila)
    return filas


def pools(texto):
    """zpool list -H -p: tamano, ocupado y libre en bytes, y la salud de cada pool."""
    que = "la lista de pools"
    filas = _tabulado(texto, 7, que)
    if not filas:
        raise _no_reconocida(que)
    return [{"pool": f[0], "bytes": _entero(f[1], "el tamano"), "usado": _entero(f[2], "lo ocupado"),
             "libre": _entero(f[3], "lo libre"), "ocupacion_pct": _entero(f[4].rstrip("%"), "la ocupacion"),
             "dedup": _veces(f[5], "la deduplicacion"), "salud": f[6].strip()} for f in filas]


def _cuenta(valor):
    m = CUENTA.match(valor)
    if not m:
        raise ValueError("contador de errores no reconocido: %r" % valor[:40])
    return int(float(m.group(1)) * MILES[m.group(2)])


def _tarea(texto):
    """La linea 'scan:' de zpool status: verificacion (scrub) o reconstruccion (resilver)."""
    if not texto or texto.startswith("none requested"):
        return None
    progreso = re.search(r"([0-9]+(?:\.[0-9]+)?)% done", texto)
    errores = re.search(r"with ([0-9]+) errors", texto)
    return {"tipo": "resilver" if "resilver" in texto else "scrub" if "scrub" in texto else None,
            "en_curso": "in progress" in texto,
            "progreso_pct": float(progreso.group(1)) if progreso else None,
            "errores": int(errores.group(1)) if errores else None, "texto": texto}


def _dispositivos(pool, lineas, que):
    """La tabla 'config:' de un pool -> lista plana con el nivel de cada dispositivo en el arbol.
    El papel es datos, o el de la seccion en la que esta (logs, cache, spares)."""
    if not lineas or lineas[0].split()[:2] != ["NAME", "STATE"]:
        raise _no_reconocida(que, lineas[0] if lineas else "pool %s sin tabla de dispositivos" % pool)
    dispositivos, papel, grupo = [], "datos", None
    for linea in lineas[1:]:
        cuerpo = linea[1:] if linea.startswith("\t") else linea
        nivel = (len(cuerpo) - len(cuerpo.lstrip(" "))) // 2
        campos = cuerpo.split()
        if nivel == 0:
            if campos[0] != pool:
                if len(campos) != 1:
                    raise _no_reconocida(que, linea)
                papel = campos[0]
            continue
        if len(campos) < 2:
            raise _no_reconocida(que, linea)
        if nivel == 1:
            grupo = campos[0]
        if papel == "spares":         # un repuesto solo tiene estado (AVAIL, INUSE ...)
            cuentas, nota = (None, None, None), " ".join(campos[2:]) or None
        elif len(campos) < 5:
            raise _no_reconocida(que, linea)
        else:
            cuentas, nota = [_cuenta(c) for c in campos[2:5]], " ".join(campos[5:]) or None
        dispositivos.append({
            "nombre": campos[0], "nivel": nivel, "papel": papel, "grupo": grupo, "es_disco": True,
            "cabina": None, "bahia": None, "estado": campos[1], "lectura": cuentas[0],
            "escritura": cuentas[1], "suma": cuentas[2], "nota": nota})
    if not dispositivos:
        raise _no_reconocida(que, "pool %s sin dispositivos" % pool)
    for i, d in enumerate(dispositivos):
        d["es_disco"] = i + 1 == len(dispositivos) or dispositivos[i + 1]["nivel"] <= d["nivel"]
        # un disco que falta sale con su identificador y, en la nota, la ruta que tenia
        m = (MIEMBRO_ZFS.search(d["nombre"]) or MIEMBRO_ZFS.search(d["nota"] or "")) if d["es_disco"] else None
        if m:
            # el numero de disco lleva la cabina en la parte alta: 0x170001 = cabina 23, bahia 1
            d["cabina"], d["bahia"] = int(m.group(1)), int(m.group(2), 16) & 0xFFFF
    return dispositivos


def pools_estado(texto):
    """zpool status -v: por pool, estado, aviso, la verificacion o reconstruccion (tarea), el
    arbol de dispositivos con sus contadores de error y los ficheros danados."""
    que = "el estado de los pools"
    crudos, actual, clave = [], None, None
    for linea in texto.splitlines():
        if not linea.strip():
            continue
        m = CLAVE_ESTADO.match(linea)
        if m:
            clave, valor = m.group(1), m.group(2).strip()
            if clave == "pool":
                actual = {"pool": valor, "campos": {}, "config": [], "ficheros": []}
                crudos.append(actual)
            elif actual is None:
                raise _no_reconocida(que, linea)
            else:
                actual["campos"][clave] = valor
        elif actual is None or clave is None:
            raise _no_reconocida(que, linea)
        elif clave == "config":
            actual["config"].append(linea)
        elif clave == "errors":
            actual["ficheros"].append(linea.strip())
        else:                          # continuacion de un texto de varias lineas
            actual["campos"][clave] = (actual["campos"][clave] + " " + linea.strip()).strip()
    if not crudos:
        raise _no_reconocida(que)
    resultado = []
    for c in crudos:
        campos = c["campos"]
        if not campos.get("state"):
            raise _no_reconocida(que, "pool %s sin estado" % c["pool"])
        errores = campos.get("errors") or None
        resultado.append({
            "pool": c["pool"], "estado": campos["state"], "aviso": campos.get("status") or None,
            "accion": campos.get("action") or None, "tarea": _tarea(campos.get("scan")),
            "dispositivos": _dispositivos(c["pool"], c["config"], que),
            "errores_de_datos": {
                "hay": errores is not None and not errores.startswith("No known data errors"),
                "texto": errores, "ficheros": [_acotado(f, MAX_RUTA) for f in c["ficheros"][:MAX_FICHEROS]],
                "total": len(c["ficheros"])}})
    return resultado


def datasets(texto):
    """zfs list -H -p de sistemas de ficheros y volumenes, con sus propiedades."""
    que = "la lista de datasets"
    filas = _tabulado(texto, 13, que)
    if not filas:
        raise _no_reconocida(que)
    resultado = []
    for f in filas:
        clave = f[12].strip()
        resultado.append({
            "nombre": f[0], "pool": f[0].split("/")[0], "tipo": f[1].strip(),
            "usado": _entero(f[2], "lo usado"), "disponible": _entero(f[3], "lo disponible"),
            "referido": _entero(f[4], "lo referido"),
            "cuota": _tamano(f[5], "la cuota") or None, "cuota_ref": _tamano(f[6], "la cuota") or None,
            "compresion_ratio": _veces(f[7], "la compresion"),
            "montaje": None if f[8].strip() in ("-", "none", "legacy") else f[8].strip(),
            "compresion": f[9].strip(), "dedup": f[10].strip(),
            "cifrado": f[11].strip() not in ("off", "-"), "clave": None if clave in ("none", "-") else clave})
    return resultado


def zfs_retenido(texto):
    """zfs list -H -p -o name,usedbysnapshots: los bytes que retienen las instantaneas de cada dataset."""
    que = "lo retenido por las instantaneas"
    filas = _tabulado(texto, 2, que)
    if not filas:
        raise _no_reconocida(que)
    return {f[0]: _entero(f[1], "lo retenido") for f in filas}


def zfs_snapshots(texto):
    """zfs list -H -p -t snapshot: las instantaneas, de la mas antigua a la mas reciente."""
    que = "la lista de instantaneas"
    instantaneas = []
    for f in _tabulado(texto, 4, que):
        dataset, arroba, nombre = f[0].partition("@")
        if not arroba or not dataset or not nombre:
            raise _no_reconocida(que, f[0])
        creada = _entero(f[3], "la fecha")
        instantaneas.append({
            "nombre": f[0], "dataset": dataset, "instantanea": nombre, "usado": _entero(f[1], "lo usado"),
            "referido": _entero(f[2], "lo referido"), "creada_epoch": creada, "creada": _fecha(creada)})
    return instantaneas


def _fecha(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshots_prog(texto):
    """Programacion y retencion de instantaneas por volumen (zsnapshotSchedule.conf). Los campos
    van con el nombre y el valor que les da el NAS; "volumen" es su source_lv_id."""
    que = "la programacion de instantaneas"
    resultado = {"global": {}, "retenciones": [], "programaciones": []}
    actual = None
    for linea in _lineas(texto):
        if linea.startswith("["):
            m = SECCION_PROG.match(linea)
            actual = {}
            if not m:
                continue               # una seccion que no se conoce: se ignora con sus campos
            if m.group(1) == "Global":
                actual = resultado["global"]
            else:
                actual["volumen"] = int(m.group(2)) if m.group(2) else None
                resultado["retenciones" if m.group(1) == "Retention" else "programaciones"].append(actual)
            continue
        if actual is None:
            raise _no_reconocida(que, linea)
        clave, valor = _clave_valor(linea, que)
        if clave == "source_lv_id":
            actual["volumen"] = _valor(valor)
        else:
            actual[clave] = _valor(valor)
    return resultado


def _arbol_iscsi(lineas, que):
    """Lineas '"clave":valor' con la sangria del fichero (2 espacios por nivel) -> diccionario
    anidado. La orden solo saca las claves elegidas: una linea cuyo padre no salio se descarta,
    con lo que cuelga de ella, si esta dentro de una entrada numerada; si no, es un error."""
    raiz = {}
    pila = [(0, raiz)]                              # (sangria de la clave, su diccionario)
    for linea in lineas:
        m = LINEA_JSON.match(linea)
        if not m or len(m.group(1)) < 2 or len(m.group(1)) % 2:
            raise _no_reconocida(que, linea)
        sangria, clave, crudo = len(m.group(1)), m.group(2), m.group(3).strip().rstrip(",")
        while pila[-1][0] >= sangria:
            pila.pop()
        nivel, padre = pila[-1]
        if padre is None or nivel != sangria - 2:    # su padre no salio en la orden
            if padre is not None and nivel < 4:
                raise _no_reconocida(que, linea)
            if crudo == "{":
                pila.append((sangria, None))
        elif crudo == "{":
            padre[clave] = {}
            pila.append((sangria, padre[clave]))
        else:
            padre[clave] = {} if crudo == "{}" else _json(crudo, que)
    return raiz


def _entrada_iscsi(seccion, numero, campos, que):
    if not numero.isdigit() or not isinstance(campos, dict):
        raise _no_reconocida(que, numero)

    def texto(clave, maximo):
        valor = campos.get(clave)
        return None if valor is None else _acotado(str(valor), maximo)

    def entero(clave):
        valor = campos.get(clave)
        return None if valor is None else _entero(str(valor), clave)

    entrada = {"id": int(numero), "nombre": texto("name", MAX_NOMBRE), "alias": texto("alias", MAX_TEXTO)}
    if seccion == "target":
        habilitado, lun = entero("target_enable"), campos.get("target_lun") or {}
        portales = campos.get("interfaces")
        entrada.update({
            "activo": None if habilitado is None else habilitado == 1, "estado": entero("status"),
            "portales": [_acotado(x, MAX_NOMBRE) for x in str(portales or "").split(",") if x],
            "lun": [_acotado(str(x.get("name")), MAX_NOMBRE) for x in lun.values() if isinstance(x, dict)],
            "acl_iniciador": _entero(str(campos["acl_group"]["initiator_id"]), "initiator_id")
            if isinstance(campos.get("acl_group"), dict) and "initiator_id" in campos["acl_group"] else None})
    elif seccion == "lun":
        capacidad, fino = entero("capacity"), campos.get("thin")
        entrada.update({
            "capacidad": None if capacidad is None else capacidad * GIB,
            "fino": fino if isinstance(fino, bool) else None, "estado": entero("status"),
            "dataset": texto("blkdev_name", MAX_NOMBRE)})
    return entrada


def zfs_iscsi(texto):
    """Las claves elegidas de los dos JSON de iSCSI de QuTS hero, tal como las da la orden: una
    por linea, con la sangria del fichero (2 espacios por nivel). Validado con un destino y un
    LUN reales."""
    que = "la configuracion de iSCSI"
    resultado = {"servicio": None, "destinos": [], "lun": [], "iniciadores": []}
    ficheros = []
    for linea in _lineas(texto):
        if linea.startswith("== "):
            ficheros.append([])
        elif not ficheros:
            raise _no_reconocida(que, linea)
        else:
            ficheros[-1].append(linea)
    for lineas in ficheros:
        arbol = _arbol_iscsi(lineas, que)
        if not arbol:
            raise _no_reconocida(que, "fichero sin ninguna clave reconocida")
        for seccion, contenido in arbol.items():
            if seccion == "portal" and isinstance(contenido, dict):
                activo, puerto = contenido.get("service_enable"), contenido.get("service_port")
                prefijo = contenido.get("iqn_prefix")
                resultado["servicio"] = {
                    "activo": None if activo is None else bool(activo),
                    "puerto": None if puerto is None else _entero(str(puerto), "el puerto"),
                    "prefijo_iqn": None if prefijo is None else _acotado(str(prefijo), MAX_NOMBRE)}
            elif seccion in LISTAS_ISCSI and isinstance(contenido, dict):
                resultado[LISTAS_ISCSI[seccion]].extend(
                    _entrada_iscsi(seccion, numero, campos, que) for numero, campos in contenido.items())
            else:
                raise _no_reconocida(que, seccion)
    return resultado


def _json(crudo, que):
    try:
        return json.loads(crudo)
    except ValueError:
        raise _no_reconocida(que, crudo) from None


# ==== QTS =====================================================================================

KIB = 1024                          # /proc/mdstat cuenta en bloques de 1 KiB
POR_VOLUMEN = 10000                 # identificador de instantanea = volumen * 10000 + orden
CABECERA_MD = re.compile(r"^(md[0-9]+) : (active|inactive)\b(.*)$")
MIEMBRO_MD = re.compile(r"^(\S+?)\[([0-9]+)\]((?:\([A-Z]\))*)$")
BLOQUES_MD = re.compile(r"^\s+([0-9]+) blocks\b")
MAPA_MD = re.compile(r"\[([0-9]+)/([0-9]+)\] \[([U_]+)\]")
TAREA_MD = re.compile(r"\b(recovery|resync|check|reshape)\s*=\s*([0-9]+(?:\.[0-9]+)?)%")
ESPERA_MD = re.compile(r"\b(recovery|resync|check|reshape)\s*=\s*(DELAYED|PENDING)\b")
PARTICION = re.compile(r"^(nvme[0-9]+n[0-9]+)p[0-9]+$|^([a-z]+)[0-9]+$")
GRUPO_SYS = re.compile(r"^== /sys/block/(md[0-9]+)/md$")
CAMPOS_MD_SYS = ("nivel", "estado", "accion", "degradado", "discrepancias")
LINEA_DM = re.compile(r"^(\S+): ([0-9]+) ([0-9]+) (\S+)\s*(.*)$")
TIPOS_DM = ("thin-pool", "cache", "cache_client", "crypt")
SI = ("yes", "true", "1")
NO = ("no", "false", "0")


def _si_no(valor, que):
    if valor is None or not valor.strip():
        return None
    v = valor.strip().lower()
    if v in SI:
        return True
    if v in NO:
        return False
    raise ValueError("%s no es un si/no: %r" % (que, valor[:40]))


def _numero(campos, clave, que=None):
    """El campo como numero, o None si no esta o esta vacio."""
    valor = campos.get(clave)
    return _entero(valor, que or clave) if valor is not None and valor.strip() else None


def _ini(texto, que):
    """Lineas '[Seccion]' y 'clave = valor' (con o sin espacios) -> [(seccion, {clave: valor})]."""
    secciones = []
    for linea in _lineas(texto):
        if linea.startswith("["):
            if not linea.endswith("]"):
                raise _no_reconocida(que, linea)
            secciones.append((linea[1:-1], {}))
            continue
        if not secciones:
            raise _no_reconocida(que, linea)
        clave, valor = _clave_valor(linea, que)
        secciones[-1][1][clave] = valor
    return secciones


def _bahia_hex(valor, que):
    """Numero de disco de QNAP en hexadecimal: la cabina en la parte alta (1000a = cabina 1, bahia 10)."""
    v = valor.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{1,8}", v):
        raise ValueError("%s: numero de disco no reconocido: %r" % (que, valor[:40]))
    return {"cabina": int(v, 16) >> 16, "bahia": int(v, 16) & 0xFFFF}


def _disco_de(particion):
    m = PARTICION.match(particion)
    return (m.group(1) or m.group(2)) if m else particion


def mdstat(texto):
    """/proc/mdstat: por grupo, nivel, miembros (con los de repuesto y los fallados), discos
    esperados y presentes con su mapa ([UU_]) y la reconstruccion o verificacion en curso."""
    que = "mdstat"
    lineas = texto.splitlines()
    if not any(linea.startswith("Personalities") for linea in lineas):
        raise _no_reconocida(que, lineas[0] if lineas else "")
    grupos, actual = [], None
    for linea in lineas:
        m = CABECERA_MD.match(linea)
        if m:
            if actual is not None and actual["bytes"] is None:
                raise _no_reconocida(que, actual["grupo"])
            palabras = [x for x in m.group(3).split() if not x.startswith("(")]
            nivel = palabras.pop(0) if palabras and "[" not in palabras[0] else None
            miembros = []
            for palabra in palabras:
                mm = MIEMBRO_MD.match(palabra)
                if not mm:
                    raise _no_reconocida(que, linea)
                miembros.append({"dispositivo": mm.group(1), "disco": _disco_de(mm.group(1)),
                                 "posicion": int(mm.group(2)), "repuesto": "(S)" in mm.group(3),
                                 "fallado": "(F)" in mm.group(3)})
            actual = {"grupo": m.group(1), "activo": m.group(2) == "active", "nivel": nivel, "bytes": None,
                      "miembros": miembros, "esperados": None, "presentes": None, "mapa": None,
                      "degradado": None, "tarea": None}
            grupos.append(actual)
            continue
        if actual is None or not linea.strip() or not linea[:1].isspace():
            continue
        if actual["bytes"] is None:
            m = BLOQUES_MD.match(linea)
            if not m:
                raise _no_reconocida(que, linea)
            actual["bytes"] = int(m.group(1)) * KIB
            mapa = MAPA_MD.search(linea)
            if mapa:
                actual["esperados"], actual["presentes"] = int(mapa.group(1)), int(mapa.group(2))
                actual["mapa"] = mapa.group(3)
                actual["degradado"] = actual["presentes"] < actual["esperados"]
            continue
        tarea, espera = TAREA_MD.search(linea), ESPERA_MD.search(linea)
        if tarea:
            resta = re.search(r"finish=([0-9.]+)min", linea)
            velocidad = re.search(r"speed=([0-9]+)K/sec", linea)
            actual["tarea"] = {"tipo": tarea.group(1), "progreso_pct": float(tarea.group(2)),
                               "restante_min": float(resta.group(1)) if resta else None,
                               "velocidad_kb_s": int(velocidad.group(1)) if velocidad else None,
                               "en_espera": False}
        elif espera:
            actual["tarea"] = {"tipo": espera.group(1), "progreso_pct": None, "restante_min": None,
                               "velocidad_kb_s": None, "en_espera": True}
    if actual is not None and actual["bytes"] is None:
        raise _no_reconocida(que, actual["grupo"])
    return grupos


def md_sys(texto):
    """Estado de cada grupo md segun el kernel: accion en curso, discos que le faltan y
    discrepancias de la ultima verificacion. Un valor que el grupo no tiene queda en None."""
    que = "el estado de los grupos md"
    grupos, actual = [], None
    for linea in _lineas(texto):
        if linea.startswith("== "):
            m = GRUPO_SYS.match(linea)
            if not m:
                raise _no_reconocida(que, linea)
            actual = {"grupo": m.group(1)}
            grupos.append(actual)
            continue
        if actual is None:
            raise _no_reconocida(que, linea)
        clave, valor = _clave_valor(linea, que)
        actual[clave] = valor
    if not grupos:
        raise _no_reconocida(que)
    resultado = []
    for g in grupos:
        if any(campo not in g for campo in CAMPOS_MD_SYS):
            raise _no_reconocida(que, g["grupo"])
        resultado.append({"grupo": g["grupo"], "nivel": _texto(g["nivel"]), "estado": _texto(g["estado"]),
                          "accion": _texto(g["accion"]), "degradado": _numero(g, "degradado"),
                          "discrepancias": _numero(g, "discrepancias")})
    return resultado


def raid_conf(texto):
    """Los grupos RAID que QTS gestiona (raid.conf) con sus miembros por cabina y bahia. Los md
    que no salen aqui son del sistema (arranque, intercambio)."""
    que = "raid.conf"
    resultado = {"grupos": [], "repuestos_globales": []}
    for seccion, campos in _ini(texto, que):
        if seccion == "Global":
            resultado["repuestos_globales"] = [_bahia_hex(v, que) for c, v in campos.items()
                                               if c.startswith("globalSpare")]
        m = re.fullmatch(r"RAID_([0-9]+)", seccion)
        if not m:
            continue
        dispositivo = _texto(campos.get("deviceName"))
        resultado["grupos"].append({
            "id": _numero(campos, "id") if "id" in campos else int(m.group(1)), "dispositivo": dispositivo,
            "grupo": dispositivo.rsplit("/", 1)[-1] if dispositivo else None,
            "nivel": _texto(campos.get("raidLevel")),
            "miembros": [_bahia_hex(v, que) for c, v in campos.items() if c.startswith("data_")],
            "repuestos": [_bahia_hex(v, que) for c, v in campos.items() if c.startswith("spare_")]})
    return resultado


def volumenes_conf(texto):
    """Los volumenes de QTS (volume.conf): grupo RAID, cifrado, cache SSD y estado. Los tamanos
    no estan aqui: salen de qlvm.conf y de la ocupacion de cada punto de montaje."""
    que = "volume.conf"
    volumenes = []
    for seccion, c in _ini(texto, que):
        m = re.fullmatch(r"VOL_([0-9]+)", seccion)
        if not m:
            raise _no_reconocida(que, seccion)
        grupo = _numero(c, "raidId")
        interno = _numero(c, "internal")
        volumenes.append({
            "id": _numero(c, "volId") if "volId" in c else int(m.group(1)),
            "nombre": _acotado(_texto(c.get("volName")), MAX_NOMBRE),
            "grupo_id": grupo if grupo is not None and grupo >= 0 else None,
            "grupo": _texto(c.get("raidName")), "cifrado": _si_no(c.get("encryption"), "encryption"),
            "cache_ssd": _si_no(c.get("ssdCache"), "ssdCache"), "sucio": _si_no(c.get("unclean"), "unclean"),
            "dispositivo": _texto(c.get("mappingName")), "solo_lectura": _si_no(c.get("readOnly"), "readOnly"),
            "estado": _numero(c, "status"), "tipo": _numero(c, "volType"),
            "interno": None if interno is None else interno == 1})
    return volumenes


def lvm_conf(texto):
    """Pools de almacenamiento, pools ligeros y volumenes logicos de QTS (qlvm.conf). Los
    tamanos vienen en sectores de 512 bytes y se devuelven en bytes."""
    que = "qlvm.conf"
    resultado = {"pools": [], "pools_ligeros": [], "volumenes": [], "miembros": []}

    def bytes_de(c, clave):
        sectores = _numero(c, clave)
        return sectores * SECTOR if sectores is not None else None

    for seccion, c in _ini(texto, que):
        clase = seccion.split("_")[0]
        if clase == "POOL":
            ligero = _numero(c, "tpId")
            resultado["pools"].append({
                "id": _numero(c, "poolId"), "nombre": _texto(c.get("poolName")),
                "pool_ligero": ligero if ligero is not None and ligero >= 0 else None,
                "umbral_pct": _numero(c, "threshold") or None,
                "sobre_umbral": _si_no(c.get("overThreshold"), "overThreshold"),
                "reserva_instantaneas_pct": _numero(c, "snapshot_reserved")})
        elif clase == "TP":
            resultado["pools_ligeros"].append({
                "id": _numero(c, "tpId"), "dispositivo": _texto(c.get("tpName")),
                "bytes": bytes_de(c, "tpSize"), "metadatos_bytes": bytes_de(c, "metaSize")})
        elif clase == "LV":
            resultado["volumenes"].append({
                "id": _numero(c, "lvId"), "pool": _numero(c, "poolId"), "dispositivo": _texto(c.get("lvName")),
                "bytes": bytes_de(c, "lvSize"), "umbral_pct": _numero(c, "threshold") or None,
                "sobre_umbral": _si_no(c.get("overThreshold"), "overThreshold"),
                "nombre": _acotado(_texto(c.get("volName")), MAX_NOMBRE)})
        elif clase == "MEMBER":
            resultado["miembros"].append({"id": _numero(c, "memberId"), "dispositivo": _texto(c.get("memberName"))})
    return resultado


def _pct(fraccion, que):
    m = re.fullmatch(r"([0-9]+)/([0-9]+)", fraccion)
    if not m:
        raise _no_reconocida(que, fraccion)
    return round(int(m.group(1)) / int(m.group(2)) * 100, 1) if int(m.group(2)) else None


def dm_estado(texto):
    """dmsetup status: ocupacion de datos y metadatos de cada pool ligero, ocupacion de la cache
    SSD y volumenes cifrados abiertos. El resto de dispositivos (lineales, etc.) no se devuelve."""
    que = "el estado del device-mapper"
    lineas = _lineas(texto)
    if not lineas:
        raise _no_reconocida(que)
    resultado = []
    for linea in lineas:
        m = LINEA_DM.match(linea)
        if not m:
            raise _no_reconocida(que, linea)
        nombre, tipo, resto = m.group(1), m.group(4), m.group(5).split()
        if tipo not in TIPOS_DM:
            continue
        pool = re.match(r"vg([0-9]+)-", nombre)
        d = {"nombre": nombre, "tipo": tipo, "pool": int(pool.group(1)) if pool else None,
             "bytes": int(m.group(3)) * SECTOR}
        if tipo == "thin-pool":
            fallo = resto[:1] == ["Fail"]
            if not fallo and len(resto) < 5:
                raise _no_reconocida(que, linea)
            d.update({"datos_pct": None if fallo else _pct(resto[2], que),
                      "metadatos_pct": None if fallo else _pct(resto[1], que),
                      "modo": None if fallo else resto[4], "fallo": fallo})
        elif tipo == "cache":
            if len(resto) < 4:
                raise _no_reconocida(que, linea)
            d.update({"usado_pct": _pct(resto[3], que), "metadatos_pct": _pct(resto[1], que)})
        elif tipo == "cache_client":
            m2 = re.fullmatch(r"([0-9]+)/([0-9]+)", resto[0]) if resto else None
            if not m2:
                raise _no_reconocida(que, linea)
            del d["bytes"]
            d.update({"bloques_usados": int(m2.group(1)), "bloques": int(m2.group(2))})
        resultado.append(d)
    return resultado


def lvm_snapshots(texto):
    """Las instantaneas de QTS (snapshot.conf), de la mas antigua a la mas reciente. El volumen
    sale del identificador (volumen * 10000 + orden) y el tamano es el del volumen."""
    que = "snapshot.conf"
    total, instantaneas = None, []
    for seccion, c in _ini(texto, que):
        if seccion == "Global":
            total = _numero(c, "Count")
        if not re.fullmatch(r"Snapshot[0-9]+", seccion):
            continue
        ident = _numero(c, "snapshotId")
        if ident is None:
            raise _no_reconocida(que, seccion)
        sectores, creada = _numero(c, "size"), _numero(c, "time")
        vital, replicada = _numero(c, "vital"), _numero(c, "replicated")
        instantaneas.append({
            "id": ident, "volumen": ident // POR_VOLUMEN,
            "nombre": _acotado(_texto(c.get("name")), MAX_NOMBRE),
            "bytes": sectores * SECTOR if sectores is not None else None, "creada_epoch": creada,
            "creada": _fecha(creada) if creada is not None else None,
            "caduca_min": _numero(c, "expiremin") or None,
            "vital": None if vital is None else vital == 1,
            "replicada": None if replicada is None else replicada == 1})
    instantaneas.sort(key=lambda s: s["creada_epoch"] or 0)
    return {"total": total, "instantaneas": instantaneas}


def lvm_iscsi(texto):
    """iscsi_trgt.conf de QTS: servicio, iniciadores y, si los hay, destinos y LUN. Una seccion
    con datos cuyo nombre no se conoce va en 'sin_reconocer': no es lo mismo que no tener nada."""
    que = "iscsi_trgt.conf"
    resultado = {"servicio": None, "destinos": [], "lun": [], "iniciadores": []}
    for seccion, c in _ini(texto, que):
        if seccion == "iSCSIPortal":
            resultado["servicio"] = {
                "activo": _si_no(c.get("bServiceEnable"), "bServiceEnable"), "puerto": _numero(c, "servicePort"),
                "prefijo_iqn": _acotado(_texto(c.get("targetIQNPrefix")), MAX_NOMBRE)}
            continue
        m = re.fullmatch(r"(init|target|LUN)([0-9]+)Info", seccion)
        if not m:
            if c:
                resultado.setdefault("sin_reconocer", []).append(_acotado(seccion, MAX_TEXTO))
            continue
        ident = int(m.group(2))
        if m.group(1) == "init":
            resultado["iniciadores"].append({
                "id": ident, "nombre": _acotado(_texto(c.get("initiatorIQN")), MAX_NOMBRE),
                "alias": _acotado(_texto(c.get("initiatorAlias")), MAX_TEXTO)})
        elif m.group(1) == "target":
            resultado["destinos"].append({
                "id": ident, "nombre": _acotado(_texto(c.get("targetName")), MAX_NOMBRE),
                "iqn": _acotado(_texto(c.get("targetIQN")), MAX_NOMBRE),
                "alias": _acotado(_texto(c.get("targetAlias")), MAX_TEXTO),
                "activo": _si_no(c.get("bTargetEnable"), "bTargetEnable"),
                "estado": _valor(c.get("targetStatus", ""))})
        else:
            resultado["lun"].append({
                "id": ident, "nombre": _acotado(_texto(c.get("LUNName")), MAX_NOMBRE),
                "capacidad": _valor(c.get("LUNCapacity", "")), "estado": _valor(c.get("LUNStatus", "")),
                "activo": _si_no(c.get("bLUNEnable"), "bLUNEnable")})
    return resultado


# ==== carpetas compartidas y ocupacion (los dos sistemas) =====================================

MAX_COMENTARIO = 120
LISTAS_SMB = {"valid users": "usuarios_validos", "invalid users": "denegados", "read list": "solo_lectura",
              "write list": "escritura"}
NOMBRE_EN_LISTA = re.compile(r'(@?)"([^"]*)"|([^,\s][^,]*)')
EXPORTACION = re.compile(r'^(?:"([^"]+)"|(\S+))\s+(\S.*)$')
CLIENTE_NFS = re.compile(r"([^\s()]+)\(([^()]*)\)")


def ocupacion(texto):
    """df -P -k de los montajes de volumen: tamano, usado y libre en bytes de cada sistema de
    ficheros montado bajo /share, una vez cada uno; los tmpfs no cuentan."""
    que = "la ocupacion"
    lineas = _lineas(texto)
    if not lineas or not lineas[0].startswith("Filesystem"):
        raise _no_reconocida(que, lineas[0] if lineas else "")
    resultado, vistos = [], set()
    for linea in lineas[1:]:
        c = linea.split(None, 5)
        if len(c) != 6:
            raise _no_reconocida(que, linea)
        if not c[5].startswith("/share/") or c[0] == "tmpfs" or c[5] in vistos:
            continue
        vistos.add(c[5])
        resultado.append({
            "dispositivo": c[0], "bytes": _entero(c[1], "el tamano") * KIB, "usado": _entero(c[2], "lo usado") * KIB,
            "libre": _entero(c[3], "lo libre") * KIB, "ocupacion_pct": _entero(c[4].rstrip("%"), "la ocupacion"),
            "montaje": c[5]})
    return resultado


def _volumen_de(ruta):
    """/share/ZFS2_DATA/Public -> ZFS2_DATA; ZFS2_DATA/Public -> ZFS2_DATA. Una ruta con una
    variable de Samba (%H, la carpeta personal de quien entra) no esta en un volumen."""
    if "%" in (ruta or ""):
        return None
    partes = [x for x in (ruta or "").split("/") if x]
    if partes[:1] == ["share"]:
        partes = partes[1:]
    return partes[0] if partes else None


def _lista_smb(valor):
    """'"root",@"everyone",ana' -> usuarios y grupos (los grupos llevan @)."""
    lista = {"usuarios": [], "grupos": []}
    for m in NOMBRE_EN_LISTA.finditer(valor):
        if m.group(3) is not None:
            nombre = m.group(3).strip()
            grupo, nombre = nombre.startswith("@"), nombre.lstrip("@").strip()
        else:
            grupo, nombre = bool(m.group(1)), m.group(2)
        if nombre:
            lista["grupos" if grupo else "usuarios"].append(_acotado(nombre, MAX_NOMBRE))
    return lista


def carpetas_smb(texto):
    """Las carpetas compartidas segun smb.conf: ruta, comentario y quien entra. Las listas son
    las de Samba: validos, denegados, solo lectura y escritura; los grupos se dan aparte."""
    que = "smb.conf"
    secciones = [(s, {k.strip().lower(): v for k, v in c.items()}) for s, c in _ini(texto, que)]
    if not secciones:
        raise _no_reconocida(que)
    carpetas = []
    for nombre, c in secciones:
        if nombre == "global":
            continue
        ruta = _texto(c.get("path"))
        carpeta = {
            "nombre": _acotado(nombre, MAX_NOMBRE), "ruta": ruta, "volumen": _volumen_de(ruta),
            "comentario": _acotado(_texto(c.get("comment")), MAX_COMENTARIO),
            "visible": _si_no(c.get("browsable", c.get("browseable")), "browsable"),
            "papelera": _si_no(c.get("recycle bin"), "recycle bin"), "invitados": _si_no(c.get("guest ok"), "guest ok")}
        for campo, clave in LISTAS_SMB.items():
            carpeta[clave] = _lista_smb(c.get(campo, ""))
        carpetas.append(carpeta)
    return carpetas


def carpetas_uso(texto):
    """El uso de cada carpeta que el propio NAS calcula de vez en cuando (volumeStatus.conf),
    con la fecha del dato. Una carpeta sin dato no se lista."""
    uso = []
    for carpeta, c in _ini(texto, "volumeStatus.conf"):
        usado = _numero(c, "Used Size")
        if usado is None:
            continue
        epoch = _numero(c, "Latest Update Time")
        uso.append({"carpeta": _acotado(carpeta, MAX_NOMBRE), "usado": usado,
                    "directorios": _numero(c, "Directory Count"), "ficheros": _numero(c, "File Count"),
                    "actualizado_epoch": epoch, "actualizado": _fecha(epoch) if epoch is not None else None})
    return uso


def carpetas_nfs(texto):
    """/etc/exports: carpetas exportadas por NFS con sus clientes y opciones (sin el fsid)."""
    que = "/etc/exports"
    exportadas = {}
    for linea in _lineas(texto):
        if linea.lstrip().startswith("#"):
            continue
        m = EXPORTACION.match(linea)
        clientes = CLIENTE_NFS.findall(m.group(3)) if m else []
        if not clientes or CLIENTE_NFS.sub("", m.group(3)).strip():
            raise _no_reconocida(que, linea)
        ruta = m.group(1) or m.group(2)
        entrada = exportadas.setdefault(ruta, {"ruta": ruta, "carpeta": ruta.rstrip("/").rsplit("/", 1)[-1],
                                               "clientes": []})
        for cliente, opciones in clientes:
            opciones = [o.strip() for o in opciones.split(",") if o.strip() and not o.strip().startswith("fsid=")]
            entrada["clientes"].append({"cliente": cliente, "escritura": "rw" in opciones, "opciones": opciones})
    return list(exportadas.values())


def carpetas_enlaces(texto):
    """ls -l /share/: cada carpeta compartida es un enlace a su sitio dentro de un volumen."""
    que = "la lista de /share"
    lineas = _lineas(texto)
    if not lineas:
        raise _no_reconocida(que)
    enlaces = []
    for linea in lineas:
        if linea.startswith("total "):
            continue
        campos = linea.split(None, 8)
        if len(campos) != 9 or not re.fullmatch(r"[bcdlps-][rwxsStT-]{9}[.+@]?", campos[0]):
            raise _no_reconocida(que, linea)
        if not campos[0].startswith("l"):
            continue
        carpeta, flecha, destino = campos[8].partition(" -> ")
        if not flecha:
            raise _no_reconocida(que, linea)
        enlaces.append({"carpeta": _acotado(carpeta, MAX_NOMBRE), "destino": destino,
                        "volumen": _volumen_de(destino)})
    return enlaces
