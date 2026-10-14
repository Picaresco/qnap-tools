# -*- coding: utf-8 -*-
"""Parsers de la pata de registros y del estado del sistema: texto de una orden -> estructura.

Funciones puras, una por orden de logs/comandos.py. Las claves van en castellano sin acentos.
Una salida que no se reconoce lanza ValueError: nunca se devuelven datos inventados ni una lista
vacia por no haber entendido el texto.

Las tres utilidades de registro (log_tool, conn_log_tool, notice_log_tool) imprimen unas lineas
de consulta, una cabecera con los nombres de columna, una fila por linea separada por comas (y
acabada en coma) y una linea final "Done. Return value is 0". Sin resultados no imprimen ni la
cabecera: la linea final es lo que distingue "no hay" de "no respondio". Las columnas se toman
de la cabecera. La descripcion es texto libre y puede llevar comas (y saltos de linea: una linea
que no empieza por un numero sigue a la anterior), como el agente del navegador, que va al final.
"""
import re
from datetime import datetime, timezone

from .comandos import MOTORES_DE_REGISTRO

MAX_TEXTO = 500                       # descripcion o recurso: texto que escribe un tercero
MAX_NOMBRE = 255                      # usuario, equipo, aplicacion
SIN_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
VACIO = ("", "---", "(null)")
FIN = re.compile(r"Done\. Return value is (-?[0-9]+)")
CONSULTA = re.compile(r"Query database|\t")
FILA = re.compile(r" *[0-9]+,")
CIFRA = re.compile(r" *[0-9]+ *")
CUENTA = re.compile(r"==gravedad ([0-9]) ([0-9]+)")
RESUMEN = re.compile(r" *([0-9]+) +([0-9]+), *([0-9]+)")
RESUMEN_FIN = re.compile(r" *1 Done\. Return value is (-?[0-9]+)")

# Gravedad de un evento (event_type) y tipo de un acceso (conn_type)
GRAVEDADES = {0: "informacion", 1: "aviso", 2: "error"}
# Gravedad de un aviso (severity): solo las que se han visto en un NAS con su significado
GRAVEDADES_AVISO = {3: "error", 4: "aviso", 6: "informacion"}
# Servicio y accion de un acceso (conn_serv, conn_action; en los avisos, server y action)
SERVICIOS = {1: "SAMBA", 2: "FTP", 3: "HTTP", 4: "NFS", 5: "AFP", 6: "TELNET", 7: "SSH", 8: "iSCSI",
             9: "RADIUS", 10: "VPN", 11: "HTTPS"}
ACCIONES = {1: "borrar", 2: "leer", 3: "escribir", 4: "abrir", 5: "crear carpeta", 6: "montar NFS",
            7: "montar NFS fallido", 8: "renombrar", 9: "inicio de sesion fallido", 10: "inicio de sesion",
            11: "cierre de sesion", 12: "desmontar NFS", 13: "copiar", 14: "mover", 15: "anadir"}
# De donde viene un aviso (facility)
ORIGENES = {1: "SMART", 8: "registro de eventos", 9: "registro de accesos", 12: "almacenamiento",
            13: "aplicaciones", 17: "sistema", 20: "noticias", 99: "tareas"}

# Donde acaba el texto libre se sabe por las columnas que lo siguen: tienen que cuadrar todas.
EPOCH = re.compile(r" *[0-9]{9,11} *")
CON_SIGNO = re.compile(r" *-?[0-9]+ *")
MARGEN_HORA = 26 * 3600      # la fecha de la fila es la hora local del NAS: menos de un dia de diferencia


def _evento_cuadra(v):
    """El codigo es un numero (o no hay: "---") y la hora en segundos es la de la fecha de la fila
    (el cliente no sirve: en un NAS real puede ser el nombre de una aplicacion)."""
    codigo = v["event_msgid"]
    if not ((CIFRA.fullmatch(codigo) or codigo.strip() in VACIO) and EPOCH.fullmatch(v["event_timet"])):
        return False
    try:
        local = datetime.strptime("%s %s" % (v["event_date"].strip(), v["event_time"].strip()), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return abs(local.replace(tzinfo=timezone.utc).timestamp() - int(v["event_timet"])) <= MARGEN_HORA


def _acceso_cuadra(v):
    """Servicio, accion y resultado son numeros. Un recurso que imite esas columnas deja la fila
    con dos cortes posibles, y eso es un error."""
    return bool(CIFRA.fullmatch(v["conn_serv"]) and CIFRA.fullmatch(v["conn_action"])
                and CON_SIGNO.fullmatch(v.get("conn_action_result", "0")))


def _aviso_cuadra(v):
    return bool(CIFRA.fullmatch(v["varNum"]))


# Cada registro: como empieza su cabecera, su columna de texto libre, la ultima columna si
# tambien es texto libre, las columnas que tiene que tener la cabecera y como se sabe que una
# forma de partir la fila es la buena.
EVENTOS = ("event_id,", "event_desc", "event_client_agent", ("event_msgid", "event_timet"), _evento_cuadra)
ACCESOS = ("conn_id,", "conn_res", "conn_client_agent", ("conn_serv", "conn_action"), _acceso_cuadra)
AVISOS = ("id,severity,", "desc", None, ("varNum",), _aviso_cuadra)


# --- utilidades -----------------------------------------------------------------------------

def _no_reconocida(que, linea=""):
    return ValueError("salida de %s no reconocida%s" % (que, (": %r" % linea[:80]) if linea else ""))


def _entero(valor, que):
    v = str(valor).strip()
    if not re.fullmatch(r"-?[0-9]+", v):
        raise ValueError("%s no es un numero: %r" % (que, v[:40]))
    return int(v)


def _texto(valor, maximo=MAX_NOMBRE):
    v = SIN_CONTROL.sub(" ", valor).strip()
    return None if v in VACIO else v[:maximo]


def _codigo(tabla, valor, que, con_codigo=True):
    """Nombre de un codigo conocido (con el codigo detras, si se pide); si no, el codigo."""
    n = _entero(valor, que)
    if n not in tabla:
        return str(n)
    return "%s (%d)" % (tabla[n], n) if con_codigo else tabla[n]


def _final(lineas, que):
    """Comprueba la linea final de la utilidad y devuelve las de antes."""
    m = FIN.fullmatch(lineas[-1].strip()) if lineas else None
    if not m:
        raise ValueError("%s: la utilidad no termino (falta su linea final 'Done. Return value is 0')" % que)
    if m.group(1) != "0":
        raise ValueError("%s: la utilidad termino con el valor %s" % (que, m.group(1)))
    return lineas[:-1]


def _campos(fila, nombres, registro, que):
    """{columna: valor} de una fila, con las comas del texto libre en su sitio. Si la fila se
    puede partir de mas de una manera, es un error: no se elige una."""
    _, libre, cola, _, cuadra = registro
    campos = (fila[:-1] if fila.endswith(",") else fila).split(",")
    n, extra = len(nombres), len(campos) - len(nombres)
    if extra < 0:
        raise _no_reconocida(que, fila)
    d = nombres.index(libre)
    # cuantas comas de mas son del texto libre: las demas son del agente del final
    validas = []
    for k in (range(extra + 1) if cola else (extra,)):
        partes = campos[:d] + [",".join(campos[d:d + 1 + k])] + campos[d + 1 + k:]
        partes = partes[:n - 1] + [",".join(partes[n - 1:])]
        valores = dict(zip(nombres, partes))
        if cuadra(valores):
            validas.append(valores)
    if len(validas) > 1:
        raise ValueError("%s: fila que se puede partir de %d maneras: %r" % (que, len(validas), fila[:80]))
    if not validas:
        raise _no_reconocida(que, fila)
    return validas[0]


def _tabla(texto, registro, que):
    """Filas ({columna: valor}) de la salida de una utilidad de registro."""
    lineas = _final(texto.rstrip("\n").split("\n") if texto.strip() else [], que)
    nombres, filas = None, []
    for linea in lineas:
        if nombres is None:
            if linea.startswith(registro[0]):
                nombres = (linea[:-1] if linea.endswith(",") else linea).split(",")
                for columna in (registro[1],) + tuple(registro[3]) + ((registro[2],) if registro[2] else ()):
                    if columna not in nombres:
                        raise _no_reconocida(que, linea)
                if registro[2] and nombres[-1] != registro[2]:
                    raise _no_reconocida(que, linea)
            elif not (CONSULTA.match(linea) or not linea.strip()):
                raise _no_reconocida(que, linea)
        elif FILA.match(linea):
            filas.append(linea)
        elif filas:
            filas[-1] += "\n" + linea
        else:
            raise _no_reconocida(que, linea)
    return [_campos(f, nombres, registro, que) for f in filas]


def _partes(texto, marcas, que):
    """Lo que hay antes de la primera linea '==marca' y despues de cada una, en ese orden."""
    trozos, resto = [], texto
    for marca in marcas:
        antes, sep, resto = resto.partition("==%s\n" % marca)
        if not sep:
            raise ValueError("%s: falta la parte '%s'" % (que, marca))
        trozos.append(antes)
    return trozos + [resto]


def _una(texto, registro, convertir, que):
    filas = [convertir(v) for v in _tabla(texto, registro, que)]
    if len(filas) > 1:
        raise _no_reconocida(que)
    return filas[0] if filas else None


# --- eventos ----------------------------------------------------------------------------------

def _evento(v):
    return {"id": _entero(v["event_id"], "el id de un evento"),
            "fecha": "%s %s" % (v["event_date"].strip(), v["event_time"].strip()),
            "gravedad": _codigo(GRAVEDADES, v["event_type"], "la gravedad de un evento", False),
            "usuario": _texto(v["event_user"]), "ip": _texto(v["event_ip"]), "equipo": _texto(v["event_comp"]),
            "aplicacion": _texto(v.get("event_app_name", "")), "categoria": _texto(v.get("event_category", "")),
            "descripcion": _texto(v["event_desc"], MAX_TEXTO), "cliente": _texto(v.get("event_client_app", ""))}


def evt_lista(texto):
    return [_evento(v) for v in _tabla(texto, EVENTOS, "la lista de eventos")]


def evt_recuento(texto):
    que = "el recuento de eventos"
    cabeza, primero, ultimo = _partes(texto, ("primero", "ultimo"), que)
    por_gravedad = {}
    for linea in cabeza.splitlines():
        m = CUENTA.fullmatch(linea.strip())
        if not m:
            raise _no_reconocida(que, linea)
        e, n = int(m.group(1)), int(m.group(2))
        if e - 1 not in GRAVEDADES:
            raise _no_reconocida(que, linea)
        if n == 0:
            raise ValueError("%s: la utilidad no respondio al contar la gravedad %d" % (que, e))
        por_gravedad[GRAVEDADES[e - 1]] = n - 1   # el filtro va de 1 a 3; la cuenta incluye la linea final
    if set(por_gravedad) != set(GRAVEDADES.values()):
        raise ValueError("%s: faltan gravedades" % que)
    return {"por_gravedad": por_gravedad,
            "primero": _una(primero, EVENTOS, _evento, que), "ultimo": _una(ultimo, EVENTOS, _evento, que)}


# --- accesos ----------------------------------------------------------------------------------

def _acceso(v):
    return {"id": _entero(v["conn_id"], "el id de un acceso"),
            "fecha": "%s %s" % (v["conn_date"].strip(), v["conn_time"].strip()),
            "tipo": _codigo(GRAVEDADES, v["conn_type"], "el tipo de un acceso", False),
            "usuario": _texto(v["conn_user"]), "ip": _texto(v["conn_ip"]), "equipo": _texto(v["conn_comp"]),
            "recurso": _texto(v["conn_res"], MAX_TEXTO),
            "servicio": _codigo(SERVICIOS, v["conn_serv"], "el servicio de un acceso"),
            "accion": _codigo(ACCIONES, v["conn_action"], "la accion de un acceso"),
            "aplicacion": _texto(v.get("conn_app", "")), "cliente": _texto(v.get("conn_client_app", ""))}


def conn_lista(texto):
    return [_acceso(v) for v in _tabla(texto, ACCESOS, "la lista de accesos")]


def conn_extremos(texto):
    que = "los extremos del registro de accesos"
    cabeza, primero, ultimo = _partes(texto, ("primero", "ultimo"), que)
    if cabeza.strip():
        raise _no_reconocida(que, cabeza)
    return {"primero": _una(primero, ACCESOS, _acceso, que), "ultimo": _una(ultimo, ACCESOS, _acceso, que)}


# --- avisos -----------------------------------------------------------------------------------

def fecha_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aviso(v):
    servicio = _entero(v["server"], "el servicio de un aviso")
    return {"id": _entero(v["id"], "el id de un aviso"), "fecha": fecha_utc(_entero(v["time"], "la hora de un aviso")),
            "gravedad": _codigo(GRAVEDADES_AVISO, v["severity"], "la gravedad de un aviso", False),
            "origen": _codigo(ORIGENES, v["facility"], "el origen de un aviso"),
            "servicio": _codigo(SERVICIOS, v["server"], "el servicio de un aviso") if servicio else None,
            "accion": _codigo(ACCIONES, v["action"], "la accion de un aviso") if servicio else None,
            "usuario": _texto(v["user"]), "ip": _texto(v["ip"]), "equipo": _texto(v["client"]),
            "descripcion": _texto(v["desc"], MAX_TEXTO), "aplicacion": _texto(v.get("name", "")),
            # codigo del mensaje en el NAS; "0" es que no tiene
            "codigo": None if v.get("msgCode", "").strip() in ("", "0") else _texto(v["msgCode"])}


def notice_lista(texto):
    return [_aviso(v) for v in _tabla(texto, AVISOS, "la lista de avisos")]


def notice_resumen(texto):
    que = "el resumen de avisos"
    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    m = RESUMEN_FIN.fullmatch(lineas[-1]) if lineas else None
    if not m:
        raise ValueError("%s: la utilidad no termino (falta su linea final)" % que)
    if m.group(1) != "0":
        raise ValueError("%s: la utilidad termino con el valor %s" % (que, m.group(1)))
    total, por_gravedad, por_origen = 0, {}, {}
    for linea in lineas[:-1]:
        r = RESUMEN.fullmatch(linea)
        if not r:
            raise _no_reconocida(que, linea)
        n = int(r.group(1))
        gravedad = _codigo(GRAVEDADES_AVISO, r.group(2), "la gravedad de un aviso", False)
        origen = _codigo(ORIGENES, r.group(3), "el origen de un aviso")
        total += n
        por_gravedad[gravedad] = por_gravedad.get(gravedad, 0) + n
        por_origen[origen] = por_origen.get(origen, 0) + n
    return {"total": total, "por_gravedad": por_gravedad, "por_origen": por_origen}


# --- kernel ----------------------------------------------------------------------------------

NIVELES_KERNEL = {0: "emergencia", 1: "alerta", 2: "critico", 3: "error", 4: "aviso", 5: "nota",
                  6: "informacion", 7: "depuracion"}
LINEA_KMSG = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8} [+-][0-9]{2}:[0-9]{2}) <([0-7])> ?(?:\[ *[0-9.]+\] ?)?(.*)")
LINEA_DMESG = re.compile(r"\[ *([0-9]+\.[0-9]+)\] ?(.*)")
CUENTA_LINEAS = re.compile(r"==lineas ([0-9]+)(?: \S+)?")
NIVEL_CONTADO = re.compile(r" *([0-9]+) <([0-7])>")


def nombre_de_nivel(n):
    return "%s (%d)" % (NIVELES_KERNEL[n], n)


def _con_cuenta(texto, que):
    """(cuenta, lineas que siguen) de una salida que empieza por '==lineas N'."""
    lineas = texto.splitlines()
    m = CUENTA_LINEAS.fullmatch(lineas[0].strip()) if lineas else None
    if not m:
        raise ValueError("%s: falta la cuenta de lineas (no se pudo leer)" % que)
    return int(m.group(1)), [linea for linea in lineas[1:] if linea.strip()]


def kmsg_niveles(texto):
    que = "los niveles del kernel"
    cabeza, primera, niveles = _partes(texto, ("primera", "niveles"), que)
    m = CUENTA_LINEAS.fullmatch(cabeza.strip())
    if not m:
        raise ValueError("%s: falta la cuenta de lineas (no se pudo leer el registro)" % que)
    por_nivel = {}
    for linea in niveles.splitlines():
        if linea.strip():
            n = NIVEL_CONTADO.fullmatch(linea)
            if not n:
                raise _no_reconocida(que, linea)
            por_nivel[nombre_de_nivel(int(n.group(2)))] = int(n.group(1))
    total = int(m.group(1))
    return {"lineas": total, "desde": _texto(primera, 40), "por_nivel": por_nivel,
            "sin_nivel": total - sum(por_nivel.values())}


def kmsg_lineas(texto):
    total, lineas = _con_cuenta(texto, "las lineas del kernel")
    salida = []
    for linea in lineas:
        m = LINEA_KMSG.fullmatch(linea.strip())
        if m:
            salida.append({"fecha": m.group(1), "nivel": nombre_de_nivel(int(m.group(2))), "texto": _texto(m.group(3), MAX_TEXTO)})
        else:
            salida.append({"fecha": None, "nivel": None, "texto": _texto(linea, MAX_TEXTO)})
    return {"total": total, "lineas": salida}


def dmesg(texto):
    total, lineas = _con_cuenta(texto, "la cola del kernel")
    if total == 0:
        raise ValueError("la cola del kernel: dmesg no devolvio nada")
    salida = []
    for linea in lineas:
        m = LINEA_DMESG.fullmatch(linea.strip())
        salida.append({"segundos": float(m.group(1)), "texto": _texto(m.group(2), MAX_TEXTO)} if m
                      else {"segundos": None, "texto": _texto(linea, MAX_TEXTO)})
    return {"total": total, "lineas": salida}


# --- hardware --------------------------------------------------------------------------------

GRADOS = re.compile(r"([0-9]+) C/-?[0-9]+ F")
VUELTAS = re.compile(r"([0-9]+) RPM")


def _claves(texto, que):
    """{clave: valor} de las lineas 'clave=valor' de una orden."""
    valores = {}
    for linea in texto.splitlines():
        if linea.strip():
            clave, sep, valor = linea.partition("=")
            if not sep:
                raise _no_reconocida(que, linea)
            valores[clave.strip()] = valor.strip()
    return valores


def _grados(valor, que):
    m = GRADOS.fullmatch(valor or "")
    if not m or m.group(1) == "0":
        raise ValueError("%s: getsysinfo no dio una temperatura (%r): sin privilegios de root?" % (que, valor))
    return int(m.group(1))


def sensores(texto):
    que = "los sensores"
    v = _claves(texto, que)
    if not re.fullmatch(r"[0-9]+", v.get("ventiladores", "")):
        raise ValueError("%s: getsysinfo no dijo cuantos ventiladores hay" % que)
    ventiladores = []
    for i in range(1, int(v["ventiladores"]) + 1):
        m = VUELTAS.fullmatch(v.get("ventilador%d" % i, ""))
        if not m:
            raise ValueError("%s: el ventilador %d no dio sus vueltas (%r)" % (que, i, v.get("ventilador%d" % i)))
        ventiladores.append({"ventilador": i, "rpm": int(m.group(1))})
    return {"cpu_c": _grados(v.get("cpu"), que + " (cpu)"), "sistema_c": _grados(v.get("sistema"), que + " (sistema)"),
            "ventiladores": ventiladores}


CABINA = (("cabina", "enc_id", int), ("id", "enc_sys_id", str), ("fabricante", "vendor", str), ("modelo", "model", str),
          ("estado", "status", int), ("protocolo", "protocol", int), ("bahias", "disk_no", int),
          ("ventiladores", "fan_no", int), ("sensores_temperatura", "temp_no", int))


def chasis(texto):
    que = "las cabinas"
    nombres, cabinas = None, []
    for linea in texto.splitlines():
        if not linea.strip() or re.fullmatch(r"=+", linea.strip()):
            continue
        if linea.startswith("enc_id "):
            nombres = linea.split()
            continue
        campos = linea.split("\t")
        if nombres is None or len(campos) < len(nombres):
            raise _no_reconocida(que, linea)
        valores = dict(zip(nombres, campos))
        try:
            cabinas.append({clave: (_entero(valores[col], que) if tipo is int else _texto(valores[col]))
                            for clave, col, tipo in CABINA})
        except KeyError:
            raise _no_reconocida(que, linea)
    if not cabinas:
        raise ValueError("%s: hal_app no enumero ninguna cabina" % que)
    return cabinas


def fuentes(texto):
    v = _claves(texto, "las fuentes")
    if not re.fullmatch(r"[0-9]+", v.get("fuentes", "")):
        raise ValueError("las fuentes: no se pudo leer cuantas tiene el modelo")
    redundante = v.get("redundante", "")
    return {"fuentes": int(v["fuentes"]),
            "redundantes": (int(redundante) > 0) if re.fullmatch(r"[0-9]+", redundante) else None}


def _si_no(valor):
    v = (valor or "").strip().upper()
    return True if v in ("TRUE", "1", "YES") else False if v in ("FALSE", "0", "NO") else None


def _entero_o_nada(valor, que):
    return _entero(valor, que) if (valor or "").strip() else None


def sai(texto):
    que = "el SAI"
    cabeza, upsc = _partes(texto, ("upsc",), que)
    v = _claves(cabeza, que)
    lineas = [linea.strip() for linea in upsc.splitlines() if linea.strip()]
    m = re.fullmatch(r"==rc (-?[0-9]+)", lineas[-1]) if lineas else None
    if not m or "activo" not in v:
        raise ValueError("%s: salida incompleta" % que)
    responde = m.group(1) == "0"
    salida = lineas[:-1]
    activo = _si_no(v["activo"])
    estado = ("sin configurar" if activo is None else "desactivado" if not activo
              else "responde" if responde else "no responde")
    return {"estado": estado, "modelo": _texto(v.get("modelo", "")), "red": _texto(v.get("red", "")),
            "bateria": _texto(v.get("bateria", "")),
            "apagar_en_min": _entero_o_nada(v.get("apagar_en"), "el apagado del SAI"),
            "sais": [_texto(x) for x in salida] if responde else [],
            "error": None if responde else _texto(" ".join(salida), MAX_TEXTO)}


# --- sistema ---------------------------------------------------------------------------------

KIB = 1024
MEMORIA = {"MemTotal": "total", "MemAvailable": "disponible", "SwapTotal": "intercambio", "SwapFree": "intercambio_libre"}


def carga(texto):
    que = "la carga"
    antes, _, despues = texto.partition("==hilos")
    _, encendido, carga_txt = _partes(antes, ("encendido", "carga"), que)
    hilos_txt, sep, memoria_txt = despues.partition("==memoria")
    if not sep or not encendido.split() or not carga_txt.split():
        raise ValueError("%s: salida incompleta" % que)
    memoria = {}
    for linea in memoria_txt.splitlines():
        m = re.fullmatch(r"(\w+): +([0-9]+) kB", linea.strip())
        if m and m.group(1) in MEMORIA:
            memoria[MEMORIA[m.group(1)]] = int(m.group(2)) * KIB
    if set(memoria) != set(MEMORIA.values()):
        raise ValueError("%s: no se pudo leer la memoria" % que)
    return {"encendido_s": int(float(encendido.split()[0])),
            "carga": [float(x) for x in carga_txt.split()[:3]], "hilos": _entero(hilos_txt, "los hilos de CPU"),
            "memoria": memoria}


def _fecha_qnap(valor):
    """'2026/10/13 18:37:30' -> '2026-10-13 18:37:30'; vacio -> None."""
    v = (valor or "").strip()
    if not v:
        return None
    if not re.fullmatch(r"[0-9]{4}/[0-9]{2}/[0-9]{2} [0-9:]{8}", v):
        raise ValueError("fecha no reconocida: %r" % v[:40])
    return v.replace("/", "-")


def firmware(texto):
    v = _claves(texto, "el firmware")
    if not v.get("version"):
        raise ValueError("el firmware: no se pudo leer la version instalada")
    return {"version": v["version"], "compilacion": v.get("compilacion") or None,
            "ultima_comprobacion": _fecha_qnap(v.get("comprobado")),
            "ultima_actualizacion": _fecha_qnap(v.get("actualizado")),
            "comprobacion_automatica": _si_no(v.get("comprobar"))}


def firmware_auto(texto):
    que = "la actualizacion automatica"
    v = _claves(texto, que)
    if not v.get("leido"):
        raise ValueError("%s: no se pudo leer la configuracion del sistema" % que)
    del v["leido"]
    if not any(v.values()):
        return {"configurada": False}
    n = {k: _entero_o_nada(v.get(k), que) for k in ("version", "modo", "modo_v3", "programa", "hora", "minuto",
                                                      "dia_semana", "dia")}
    hora = "%02d:%02d" % (n["hora"], n["minuto"] or 0) if n["hora"] is not None else None
    return {"configurada": True, "importantes": _si_no(v.get("importantes")),
            "recomendadas": _si_no(v.get("recomendadas")), "ultimas": _si_no(v.get("ultimas")),
            "version": n["version"], "modo": n["modo"], "modo_v3": n["modo_v3"],
            "programa": {"tipo": n["programa"], "hora": hora, "dia_semana": n["dia_semana"], "dia": n["dia"]}}


def apps(texto):
    que = "las aplicaciones"
    lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    m = re.fullmatch(r"==paquetes ([0-9]+)", lineas[0]) if lineas else None
    if not m or m.group(1) == "0":
        raise ValueError("%s: no se pudo leer la lista de paquetes" % que)
    salida = []
    for linea in lineas[1:]:
        partes = linea.split()
        if len(partes) not in (1, 3):
            raise _no_reconocida(que, linea)
        salida.append({"nombre": partes[0], "instalada": len(partes) == 3,
                       "version": partes[1] if len(partes) == 3 else None,
                       "activa": _si_no(partes[2]) if len(partes) == 3 else None})
    return {"paquetes": int(m.group(1)), "apps": salida}


def motores(texto):
    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    if not lineas or not re.match(r" *PID ", lineas[0]):
        raise ValueError("los motores de registro: ps no respondio")
    return {m: sum(1 for linea in lineas[1:] if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % m, linea))
            for m in MOTORES_DE_REGISTRO}


PSTORE = re.compile(r"pstore_(?:[a-z_]+_)?[0-9]+_([0-9]{4})([0-9]{2})([0-9]{2})([0-9]{2})([0-9]{2})(?:\.log)?")
FICHERO_STAT = re.compile(r"([0-9]+) ([0-9]+) /etc/logs/(.+)")
FORZADOS = ".force_kill_in_shutdown.log"
CIERRES = "==cierres"
VOLCADO_LEIDO = re.compile(r"==volcado (\S+) ([0-9]+) ([0-9]+)")
# la ultima linea que escribe el kernel al reiniciar o apagar de forma ordenada
FINAL_REINICIO = re.compile(r"reboot: (Restarting system|machine restart)$")
FINAL_APAGADO = re.compile(r"reboot: (Power down|System halted)$")


def _cierre(fallos, final):
    if fallos:
        return "fallo"
    if FINAL_REINICIO.search(final):
        return "reinicio"
    if FINAL_APAGADO.search(final):
        return "apagado"
    return "sin_cierre"


def volcados(texto):
    """Los volcados de pstore (la consola del arranque anterior, guardada en cada reinicio en
    caliente) con como acabo ese arranque: 'reinicio' o 'apagado' ordenados, 'fallo' (el kernel
    dejo un panic, Oops o BUG) o 'sin_cierre' (se corto sin apagado); None si no es un .log y no
    se leyo."""
    que = "los volcados"
    lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    if not lineas:
        raise ValueError("%s: no se pudo listar /etc/logs" % que)
    if CIERRES not in lineas:
        raise ValueError("%s: no se pudo leer como acaba cada volcado" % que)
    corte = lineas.index(CIERRES)
    salida, forzados = {}, None
    for linea in lineas[:corte]:
        m = FICHERO_STAT.fullmatch(linea)
        if not m:
            raise _no_reconocida(que, linea)
        nombre, bytes_ = m.group(3), int(m.group(1))
        volcado = PSTORE.fullmatch(nombre)
        if volcado:
            salida[nombre] = {"fichero": nombre, "fecha": "%s-%s-%s %s:%s" % volcado.groups(), "bytes": bytes_,
                              "cierre": None, "fallos_del_kernel": None, "matados_por_memoria": None}
        elif nombre == FORZADOS:
            forzados = {"fecha": fecha_utc(int(m.group(2))), "bytes": bytes_}
    resto = lineas[corte + 1:]
    for i, linea in enumerate(resto):
        if not linea.startswith("==volcado"):
            continue
        m = VOLCADO_LEIDO.fullmatch(linea)
        if not m or m.group(1) not in salida:
            raise _no_reconocida(que, linea)
        siguiente = resto[i + 1] if i + 1 < len(resto) else ""
        final = "" if siguiente.startswith("==volcado") else siguiente
        fallos = int(m.group(2))
        salida[m.group(1)].update(cierre=_cierre(fallos, final), fallos_del_kernel=fallos,
                                  matados_por_memoria=int(m.group(3)))
    return {"volcados": sorted(salida.values(), key=lambda x: x["fecha"], reverse=True),
            "procesos_forzados_al_apagar": forzados}


# --- alertas ---------------------------------------------------------------------------------

def alertas(texto):
    que = "las alertas"
    v = _claves(texto, que)
    if not any(v.values()):
        raise ValueError("%s: no se pudo leer la configuracion" % que)
    return {"nivel": _entero_o_nada(v.get("nivel"), que), "zumbador": _si_no(v.get("zumbador")),
            "aviso_espacio_libre": _si_no(v.get("aviso_espacio")),
            "espacio_minimo_mb": _entero_o_nada(v.get("espacio_minimo"), que)}


def syslog(texto):
    """El servidor syslog del NAS. Solo salen las claves conocidas: nunca se vuelca el fichero."""
    que = "el servidor syslog"
    if not texto.strip():
        return None
    v = {}
    for linea in texto.splitlines():
        clave, sep, valor = linea.partition("=")
        if sep:
            v[clave.strip().lower()] = valor.strip()
    if "enable" not in v:
        raise _no_reconocida(que)
    return {"activo": _si_no(v["enable"]),
            "tcp": {"activo": _si_no(v.get("tcp enable")), "puerto": _entero_o_nada(v.get("tcp port"), que)},
            "udp": {"activo": _si_no(v.get("udp enable")), "puerto": _entero_o_nada(v.get("udp port"), que)},
            "mensajes_del_kernel": _si_no(v.get("klog enable")),
            "fichero": {"carpeta": _texto(v.get("log file share", "")), "nombre": _texto(v.get("log file path", "")),
                        "tamano_mb": _entero_o_nada(v.get("log file size"), que)},
            "aviso_por_correo": _si_no(v.get("alert mail"))}
