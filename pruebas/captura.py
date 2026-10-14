# -*- coding: utf-8 -*-
"""Captura la salida real de las ordenes de una pata del producto y la guarda anonimizada.

Uso: python captura.py <pata> <nas> <sufijo> [--simular] [--solo ID,ID] [--palabra REAL=EJEMPLO ...]
  pata: redes, discos...   nas: uno de los del .env (ver ro.py)
  sufijo: "hero" o "qts" (va en el nombre de los ficheros)
  --simular: no escribe; dice que ficheros escribiria y si ya existen
  --solo: captura solo las ordenes con esos identificadores

Lanza cada Comando de qnap_tools.<pata>.comandos valido para el sistema de ese NAS por el
transporte del producto (clave y known_hosts del laboratorio, pruebas/claves/), tras pasarlo
por la guardia de solo lectura, y escribe tests/datos/<pata>/<id>_<sufijo>.txt. Las ordenes
con parametros toman valores reales del propio NAS (una funcion por pata). Solo lectura.
"""
import importlib
import os
import re
import sys

import anonimiza
import guardia
import ro
from qnap_tools import config
from qnap_tools.comandos import Comando
from qnap_tools.deteccion import detectar
from qnap_tools.ejecutor import ErrorComando, lanzar_en
from qnap_tools.inventario import Nas
from qnap_tools.transporte import Conexion


def ordenes(pata, sistema):
    """[(NOMBRE, Comando)] de una pata que valen para este sistema, en orden alfabetico."""
    modulo = importlib.import_module("qnap_tools.%s.comandos" % pata)
    return [(nombre, c) for nombre, c in sorted(vars(modulo).items())
            if isinstance(c, Comando) and c.sistema in ("ambos", sistema)]


# --- valores de los parametros, por pata ------------------------------------------------
# Cada funcion recibe leer(NOMBRE) -> salida de esa orden sin parametros, y devuelve
# {NOMBRE: valores} para las ordenes que los llevan; None = este NAS no tiene con que probarla.

def _valores_redes(leer, sistema):
    iface = re.search(r"^(eth[0-9]+)\s+UP", leer("ENLACES"), re.M).group(1)
    puente = re.search(r"^(qvs[0-9]+|br[0-9]+)\s", leer("PUENTES"), re.M)
    pasarela = re.search(r"^default via (\S+)", leer("RUTAS"), re.M).group(1)
    return {"ETHTOOL": {"iface": iface}, "ETHTOOL_DRIVER": {"iface": iface},
            "ETHTOOL_STATS": {"iface": iface},
            "PUENTES_MAC": {"iface": puente.group(1)} if puente else None,
            "PING": {"destino": pasarela}, "TRACEROUTE": {"destino": "8.8.8.8"},
            "NSLOOKUP": {"destino": "www.qnap.com"}}


def _valores_discos(leer, sistema):
    # el primer disco de la cabina principal: /etc/enclosure_0.conf, port_id = N
    detalle = leer("DISCOS_DETALLE")
    m = re.search(r"^== /etc/enclosure_([0-9]+)[.]conf\s+\[PhysicalDisk_[0-9]+\]\s+port_id = ([0-9]+)",
                  detalle, re.M)
    return {"SMART_ATRIBUTOS": {"cabina": m.group(1), "bahia": m.group(2)} if m else None}


def _si_existe(leer):
    """leer() que devuelve vacio para una orden que la pata aun no define."""
    def lee(nombre):
        try:
            return leer(nombre)
        except KeyError:
            return ""
    return lee


def _valores_virtualizacion(leer, sistema):
    leer = _si_existe(leer)
    # una VM y un contenedor cualesquiera del NAS; None si no tiene
    vm = re.search(r"(?m)^== ([0-9a-f-]{36})$", leer("VM_XML"))
    contenedor = re.search(r"(?m)^([A-Za-z0-9][A-Za-z0-9_.-]*)\t", leer("CT_LISTA"))
    uuid = {"uuid": vm.group(1)} if vm else None
    nombre = {"contenedor": contenedor.group(1)} if contenedor else None
    return {"VM_IP": uuid, "CT_DETALLE": nombre,
            "CT_LOGS": dict(nombre, lineas="5") if nombre else None}


def _valores_logs(leer, sistema):
    # todo el registro (fechas extremas), y para la busqueda por texto una palabra del evento mas
    # reciente: asi encuentra al menos ese
    ultimo = leer("EVT_RECUENTO").split("==ultimo", 1)[-1]
    palabra = re.search(r"(?m)^ *[0-9]+,(?:[^,\n]*,){6}[^A-Za-z\n]*([A-Za-z]{4,})", ultimo)
    todo = {"desde": "2000-01-01", "hasta": "2099-12-31", "limite": "20"}
    return {"EVT_LISTA": dict(todo, gravedad="0"),
            "EVT_PALABRA": dict(todo, gravedad="0", texto=palabra.group(1)) if palabra else None,
            "CONN_LISTA": {"tipo": "0", "limite": "20"}, "NOTICE_LISTA": {"limite": "20"},
            "KMSG_LINEAS": {"nivel": "3", "lineas": "20"}, "DMESG": {"lineas": "20"}}


VALORES = {"redes": _valores_redes, "discos": _valores_discos, "virtualizacion": _valores_virtualizacion,
           "logs": _valores_logs}

# --- nombres propios que hay que ocultar, por pata -----------------------------------------
# Cada funcion recibe leer(NOMBRE) y devuelve {real: ejemplo} con los nombres de carpeta, de
# usuario, etc. que aparecen en las salidas de ese NAS.
def nombres_del_reparto(reparto, ejemplo="carpeta"):
    """Los nombres de carpeta o de volumen de la ultima columna de 'qcli_storage -p'."""
    lineas = reparto.splitlines()
    columna = max(lineas[0].find("SharedFolderName"), lineas[0].find("VolName"))
    nombres = {}
    for linea in lineas[1:]:
        for nombre in linea[columna:].split(","):
            nombre = nombre.strip()
            # "--" es la marca de "ninguno" (discos de cache o de repuesto), no un nombre
            if re.search(r"[A-Za-z0-9]", nombre) and nombre not in nombres:
                nombres[nombre] = "%s%d" % (ejemplo, len(nombres) + 1)
    return nombres


# cuentas y grupos que trae cualquier QNAP de fabrica: no dicen nada de nadie
DE_FABRICA = ("admin", "administrators", "everyone", "guest", "root")


def nombres_de_carpetas(nombres, smb, uso="", enlaces=""):
    """Anade a 'nombres' las carpetas (secciones de smb.conf y de volumeStatus.conf, y enlaces
    de /share) y los usuarios y grupos de las listas de acceso de smb.conf."""
    carpetas = re.findall(r"(?m)^\[([^\]\n]+)\]", smb + "\n" + uso)
    carpetas += re.findall(r"(?m)^l\S+ +\S+ +\S+ +\S+ +\S+ +\S+ +\S+ +\S+ (.+) -> ", enlaces)
    for carpeta in carpetas:
        # una carpeta montada de otro equipo se llama "Nombre (usuario@equipo)"
        remota = re.fullmatch(r"(.+?) \(([^@()]+)@[^()]*\)", carpeta)
        if remota:
            carpeta = remota.group(1)
            if remota.group(2).lower() not in DE_FABRICA:
                nombres.setdefault(remota.group(2), "usuario%d" % (len(nombres) + 1))
        if carpeta != "global":
            nombres.setdefault(carpeta, "carpeta%d" % (len(nombres) + 1))
    for linea in re.findall(r"(?m)^\s*(?:valid users|invalid users|read list|write list)\s*=(.*)$", smb):
        for grupo, nombre in re.findall(r'(@?)"([^"]+)"', linea):
            if nombre.lower() not in DE_FABRICA:
                nombres.setdefault(nombre, "%s%d" % ("grupo" if grupo else "usuario", len(nombres) + 1))
    return nombres


def _nombres_discos(leer, sistema):
    nombres = nombres_del_reparto(leer("DISCOS_REPARTO"), "carpeta" if sistema == "hero" else "volumen")
    if sistema == "hero":
        # la carpeta de cada dataset sale en su punto de montaje: /share/ZFS2_DATA/<carpeta>/...
        for nombre in re.findall(r"/share/[A-Za-z0-9]+_DATA/([^/\s]+)", leer("DATASETS")):
            nombres.setdefault(nombre, "carpeta%d" % (len(nombres) + 1))
    else:
        # el nombre que el usuario dio a cada volumen: volume.conf y qlvm.conf
        for orden in ("VOLUMENES_CONF", "LVM_CONF"):
            for nombre in re.findall(r"(?m)^volName *= *(\S.*?) *$", leer(orden)):
                nombres.setdefault(nombre, "volumen%d" % (len(nombres) + 1))
    return nombres_de_carpetas(nombres, leer("CARPETAS_SMB"), leer("CARPETAS_USO"), leer("CARPETAS_ENLACES"))


# redes que crea Docker por su cuenta y nombres de los paquetes de QNAP: no se ocultan
REDES_DE_FABRICA = ("bridge", "host", "none")


def _nombres_virtualizacion(leer, sistema):
    """Nombres de VM (del XML), y de contenedor, imagen, red y proyecto (de la lista de
    contenedores y de la de redes). Las carpetas y ficheros los cambia la regla de rutas."""
    nombres, leer = {}, _si_existe(leer)

    def anadir(nombre, ejemplo):
        if nombre and nombre not in nombres:
            nombres[nombre] = "%s%d" % (ejemplo, sum(1 for v in nombres.values() if v.startswith(ejemplo)) + 1)

    for nombre in re.findall(r"<qvs:name>([^<\n]+)</qvs:name>", leer("VM_XML")):
        anadir(nombre, "vm")
    for linea in leer("CT_LISTA").splitlines():
        campos = linea.split("\t")
        if len(campos) < 8:
            continue
        anadir(campos[0], "contenedor")
        anadir(re.sub(r"[:@][^/]*$", "", campos[1]), "imagen")
        for red in campos[5].split(","):
            if red not in REDES_DE_FABRICA:
                anadir(red, "red")
        anadir(campos[7], "proyecto")
    for linea in leer("CT_LXD").splitlines():
        if linea.strip() and not linea.startswith("== "):
            anadir(linea.strip(), "lxd")
    for linea in leer("CT_REDES").splitlines():
        red = linea.split("\t")[0]
        if "\t" in linea and red not in REDES_DE_FABRICA:
            anadir(red, "red")
    return nombres


def _nombres_logs(leer, sistema):
    """Los registros nombran carpetas, volumenes, usuarios, VM y contenedores: los mismos nombres
    que se ocultan en esas patas, leidos con sus ordenes ("pata.ORDEN")."""
    nombres = _nombres_discos(lambda n: leer("discos." + n), sistema)
    for real, ejemplo in _nombres_virtualizacion(lambda n: leer("virtualizacion." + n), sistema).items():
        nombres.setdefault(real, ejemplo)
    return nombres


NOMBRES = {"discos": _nombres_discos, "virtualizacion": _nombres_virtualizacion, "logs": _nombres_logs}
# patas cuyas salidas llevan rutas de carpetas y ficheros del usuario bajo /share
CON_RUTAS = ("virtualizacion",)
# patas cuyas salidas son registros: texto entre comillas, y usuario y equipo de cada fila
CON_COMILLAS = ("logs",)


def valores_reales(pata, leer, sistema):
    return VALORES[pata](leer, sistema) if pata in VALORES else {}


def nombres_a_ocultar(pata, leer, sistema):
    return NOMBRES[pata](leer, sistema) if pata in NOMBRES else {}


def main():
    args = sys.argv[1:]
    palabras = anonimiza._palabras(args)
    simular = "--simular" in args
    if simular:
        args.remove("--simular")
    solo = None
    if "--solo" in args:
        i = args.index("--solo")
        solo = set(args[i + 1].split(","))
        del args[i:i + 2]
    pata, nas_nombre, sufijo = args
    env = ro.leer_env()
    host, puerto = ro.NAS[nas_nombre]
    cfg = config.cargar({"QNAP_TOOLS_USER": env["QNAP_USER"], "QNAP_TOOLS_PASSWORD": env["QNAP_PASSWORD"],
                         "QNAP_TOOLS_DATA": os.path.join(ro.AQUI, "claves")})
    # donde la clave de pruebas no esta instalada no se ofrece (ver ro.SIN_CLAVE)
    con = Conexion(Nas("lab", env[host], int(env.get(puerto, "22")),
                       auth="contrasena" if nas_nombre in ro.SIN_CLAVE else "auto"), cfg)
    print("conectado por %s" % con.conectar())
    sistema = detectar(con).sistema
    lista = ordenes(pata, sistema)
    porNombre = dict(lista)
    print("sistema %s: %d ordenes de %s" % (sistema, len(lista), pata))
    destino = os.path.join(ro.RAIZ, "tests", "datos", pata)

    def captura(comando, valores=None):
        guardia.comprobar(comando.render(valores))
        return lanzar_en(con, comando, valores)

    leidas = {}

    def leer(nombre):
        """Salida de una orden sin parametros, una sola vez; "pata.ORDEN" es de otra pata."""
        if nombre not in leidas:
            otra, _, orden = nombre.rpartition(".")
            leidas[nombre] = captura((dict(ordenes(otra, sistema)) if otra else porNombre)[orden])
        return leidas[nombre]

    valores = valores_reales(pata, leer, sistema)
    nombres = nombres_a_ocultar(pata, leer, sistema)
    anon = anonimiza.Anonimizador(palabras, nombres, rutas=pata in CON_RUTAS, comillas=pata in CON_COMILLAS)
    if not simular:
        os.makedirs(destino, exist_ok=True)
    dudas_en_total = 0
    for nombre, comando in lista:
        if solo is not None and comando.id not in solo:
            continue
        ruta = os.path.join(destino, "%s_%s.txt" % (comando.id, sufijo))
        if nombre in valores and valores[nombre] is None:
            print("%-20s sin parametro disponible en este NAS: no se captura" % nombre)
            continue
        if comando.params and nombre not in valores:
            print("%-20s FALTA el valor de sus parametros en captura.py: no se captura" % nombre)
            continue
        if simular:
            print("%-20s %s %s" % (nombre, os.path.relpath(ruta, ro.RAIZ),
                                   "(existe)" if os.path.exists(ruta) else "(NUEVO)"))
            continue
        try:
            salida = leer(nombre) if not comando.params else captura(comando, valores.get(nombre))
        except ErrorComando as e:
            print("%-20s ERROR: %s" % (nombre, anon.aplicar(str(e))))
            continue
        texto = anon.aplicar(salida)
        with open(ruta, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
        dudas = anonimiza.revisar(texto, list(palabras), list(nombres), rutas=pata in CON_RUTAS,
                                  comillas=pata in CON_COMILLAS)
        dudas_en_total += len(dudas)
        print("%-20s %6d bytes %4d lineas%s" % (
            nombre, len(texto), texto.count("\n"), ("  DUDAS: %s" % dudas[:6]) if dudas else ""))
    con.cerrar()
    if not simular:
        print("nombres ocultados: %d | dudas en total: %d" % (len(nombres), dudas_en_total))


if __name__ == "__main__":
    main()
