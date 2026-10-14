# -*- coding: utf-8 -*-
"""Genera datos de prueba de discos de QTS a partir de salidas ya guardadas.

No se conecta a ningun NAS: lee pruebas/resultados/<nas>/ (salidas de la exploracion, no
versionadas), las pasa al formato de las ordenes del producto, las anonimiza y escribe
tests/datos/discos/<id>_<sufijo>.txt.

Uso: python deriva_discos_qts.py <nas> <sufijo> [--palabra REAL=EJEMPLO ...]
"""
import os
import re
import sys

import anonimiza
import captura
import ro
from qnap_tools.discos import comandos as dc

CABECERA = 2      # "$ orden" y "[rc=N]" que antepone el arnes ro.py
CAMPOS = re.compile(r"^\[PhysicalDisk|^(%s) =" % "|".join(dc.CAMPOS_DISCO))
UMBRALES = re.compile(r"^\[|^(policy|enable|value) =")
SALUD = re.compile(r"^(--|[0-9]+ C/[0-9]+ F|-- C/-- F)(--|[A-Za-z]+)(-?[0-9]+)$")
CAMPOS_MD = ("nivel", "estado", "accion", "degradado", "discrepancias")


def _tal_cual(texto, origen):
    return texto


def _detalle(texto, origen):
    # la exploracion pedia tambien las velocidades de enlace; el producto no
    return "".join(l for l in texto.splitlines(True) if l.startswith("== ") or CAMPOS.search(l))


def _umbrales(texto, origen):
    return "".join(l for l in texto.splitlines(True) if UMBRALES.search(l))


def _salud(texto, origen):
    """La exploracion lanzaba los cuatro getsysinfo seguidos y salian pegados en una linea;
    el producto pone cada valor en la suya. El modelo se separa con el que da la cabina."""
    modelos, bahia = {}, None
    en_principal = False
    for linea in leer(origen, "discos/discos_detalle.txt").splitlines():
        if linea.startswith("== "):
            en_principal = linea.strip() == "== /etc/enclosure_0.conf"
        elif linea.startswith("port_id = "):
            bahia = int(linea.split("=")[1])
        elif linea.startswith("model = ") and en_principal:
            modelos[bahia] = linea.split("=", 1)[1].strip()
    salida, n = [], None
    for linea in texto.splitlines():
        if linea.startswith("== "):
            n = int(linea[3:])
            continue
        if n > max(modelos):
            continue                  # el producto pregunta solo por las bahias que hay
        modelo = modelos.get(n, "--")
        if not linea.startswith(modelo):
            raise SystemExit("bahia %d: no empieza por su modelo: %r" % (n, linea))
        m = SALUD.match(linea[len(modelo):])
        if not m:
            raise SystemExit("bahia %d: no reconocida: %r" % (n, linea))
        salida += ["== %d" % n, "modelo=" + modelo, "temperatura=" + m.group(1),
                   "smart=" + m.group(2), "estado=" + m.group(3)]
    return "\n".join(salida) + "\n"


def _md_sys(texto, origen):
    """La exploracion ponia los cinco valores de cada grupo en una linea; el producto, uno por
    linea con su nombre."""
    salida = []
    for linea in texto.splitlines():
        if linea.startswith("== "):
            salida.append(linea)
            continue
        valores = linea.split()
        if len(valores) != len(CAMPOS_MD):
            raise SystemExit("grupo md con valores de menos: %r" % linea)
        salida += ["%s=%s" % par for par in zip(CAMPOS_MD, valores)]
    return "\n".join(salida) + "\n"


def _como(comando):
    """Filtra la salida guardada con el mismo patron que usa grep en la orden del producto
    (con -o, solo la parte que casa)."""
    m = re.search(r"grep (-o )?-E '([^']*)'", comando.plantilla)
    solo_lo_que_casa, patron = bool(m.group(1)), re.compile(m.group(2).replace("[[:space:]]", r"\s"))

    def filtra(texto, origen):
        salida = []
        for linea in texto.splitlines():
            casa = patron.search(linea)
            if casa:
                salida.append(casa.group(0) if solo_lo_que_casa else linea)
        return "\n".join(salida) + "\n"
    return filtra


def _exports(texto, origen):
    # la exploracion guardo /etc/exports seguido de otro fichero: el producto solo lee el primero
    return texto.split("[Global]")[0]


# fichero de resultados -> (id de la orden del producto, adaptacion al formato del producto,
# sufijos para los que vale; None = todos)
ORIGENES = (
    ("discos/discos_lista.txt", "discos_lista", _tal_cual, None),
    ("discos/discos_reparto.txt", "discos_reparto", _tal_cual, None),
    ("discos/discos_detalle.txt", "discos_detalle", _detalle, None),
    ("discos/discos_temp.sudo.txt", "discos_salud", _salud, None),
    ("discos/smart_atributos.sudo.txt", "smart_todos", _tal_cual, None),
    ("discos/smart_umbrales.txt", "smart_umbrales", _umbrales, ("qts",)),
    ("discos/ssd_vida.txt", "ssd_vida", _tal_cual, None),
    ("discos/md_estado.txt", "mdstat", _tal_cual, None),
    ("discos/md_sync.txt", "md_sys", _md_sys, None),
    ("discos_qts/raid_conf.txt", "raid_conf", _como(dc.RAID_CONF), None),
    ("discos/volumenes_conf.txt", "volumenes_conf", _como(dc.VOLUMENES_CONF), None),
    # la exploracion corto este fichero a 200 lineas: solo vale donde cabia entero
    ("discos_qts/lvm_pools.txt", "lvm_conf", _como(dc.LVM_CONF), ("qts",)),
    # solo las lineas de pools ligeros y cache, y cortadas a 300 caracteres; el producto las trae todas
    ("discos_qts/thin_uso.sudo.txt", "dm_estado", _tal_cual, None),
    ("discos_qts/snapshots_prog.txt", "lvm_snapshots_prog", _como(dc.SNAPSHOTS_PROG_QTS), None),
    ("discos_qts/iscsi.txt", "lvm_iscsi", _como(dc.ISCSI_QTS), ("qts",)),
    ("discos/carpetas_smb.txt", "carpetas_smb", _como(dc.CARPETAS_SMB), ("qts",)),
    ("discos/carpetas_uso.txt", "carpetas_uso", _como(dc.CARPETAS_USO), ("qts",)),
    ("discos/carpetas_nfs.txt", "carpetas_nfs", _exports, ("qts",)),
    # la exploracion corto la lista a 80 lineas
    ("discos/carpetas_enlaces.txt", "carpetas_enlaces", _tal_cual, ("qts",)),
)


def leer(origen, fichero):
    with open(os.path.join(origen, fichero), encoding="utf-8") as f:
        return "".join(l for l in f.read().splitlines(True)[CABECERA:] if not l.startswith("[stderr]"))


def nombres_de(origen):
    """Nombres de volumen que hay que ocultar: los del reparto y los de volume.conf y qlvm.conf."""
    nombres = captura.nombres_del_reparto(leer(origen, "discos/discos_reparto.txt"), "volumen")
    for fichero in ("discos/volumenes_conf.txt", "discos_qts/lvm_pools.txt"):
        for nombre in re.findall(r"(?m)^volName *= *(\S.*?) *$", leer(origen, fichero)):
            nombres.setdefault(nombre, "volumen%d" % (len(nombres) + 1))
    return captura.nombres_de_carpetas(nombres, leer(origen, "discos/carpetas_smb.txt"),
                                       leer(origen, "discos/carpetas_uso.txt"),
                                       leer(origen, "discos/carpetas_enlaces.txt"))


def main():
    args = sys.argv[1:]
    palabras = anonimiza._palabras(args)
    nas, sufijo = args
    origen = os.path.join(ro.AQUI, "resultados", nas)
    destino = os.path.join(ro.RAIZ, "tests", "datos", "discos")
    nombres = nombres_de(origen)
    anon = anonimiza.Anonimizador(palabras, nombres)
    dudas_en_total = 0
    for fichero, ident, adapta, sufijos in ORIGENES:
        if sufijos is not None and sufijo not in sufijos:
            continue
        texto = anon.aplicar(adapta(leer(origen, fichero), origen))
        with open(os.path.join(destino, "%s_%s.txt" % (ident, sufijo)), "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
        dudas = anonimiza.revisar(texto, list(palabras), list(nombres))
        dudas_en_total += len(dudas)
        print("%-34s -> %-30s %4d lineas%s" % (
            fichero, "%s_%s.txt" % (ident, sufijo), texto.count("\n"),
            ("  DUDAS: %s" % dudas[:6]) if dudas else ""))
    print("nombres ocultados: %d | dudas en total: %d" % (len(nombres), dudas_en_total))


if __name__ == "__main__":
    main()
