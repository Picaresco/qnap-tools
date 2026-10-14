# -*- coding: utf-8 -*-
"""Genera los datos de prueba de redes de QTS a partir de salidas ya guardadas.

No se conecta a ningun NAS: lee pruebas/resultados/<nas>/redes/ (salidas de la exploracion,
no versionadas), las anonimiza y escribe tests/datos/redes/<id>_qts.txt. Solo se toman las
ordenes cuyo formato difiere del de QuTS hero o que alli no daban datos.

Uso: python deriva_redes_qts.py <nas> [--palabra REAL=EJEMPLO ...]
"""
import os
import re
import sys

import anonimiza
import ro

# fichero de resultados -> id del comando del producto (redes/comandos.py)
ORIGENES = (
    ("if_enlaces.txt", "enlaces"),            # interfaces veth con sufijo @ifN
    ("if_direcciones.txt", "direcciones"),
    ("puentes.txt", "puentes"),               # puentes con varias interfaces (lineas de continuacion)
    ("rutas.txt", "rutas"),                   # iproute2 antiguo: dos espacios entre campos
    ("bonding.txt", "bonding"),               # un bond en modo 802.3ad
    ("vlan.sudo.txt", "vlan"),
    ("diag_dns.txt", "nslookup"),
    ("diag_ping_gw.sudo.txt", "ping"),
)
CABECERA = 2      # "$ orden" y "[rc=N]" que antepone el arnes ro.py


def main():
    args = sys.argv[1:]
    palabras = anonimiza._palabras(args)
    (nas,) = args
    origen = os.path.join(ro.AQUI, "resultados", nas, "redes")
    destino = os.path.join(ro.RAIZ, "tests", "datos", "redes")
    anon = anonimiza.Anonimizador(palabras)
    dudas_en_total = 0
    for fichero, ident in ORIGENES:
        with open(os.path.join(origen, fichero), encoding="utf-8") as f:
            texto = "".join(f.read().splitlines(True)[CABECERA:])
        # la exploracion imprimia la ruta entera del bond; el producto, solo su nombre
        texto = re.sub(r"^== /proc/net/bonding/", "== ", texto, flags=re.M)
        texto = anon.aplicar(texto)
        with open(os.path.join(destino, "%s_qts.txt" % ident), "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
        dudas = anonimiza.revisar(texto, list(palabras))
        dudas_en_total += len(dudas)
        print("%-24s -> %-22s %4d lineas%s" % (
            fichero, ident + "_qts.txt", texto.count("\n"), ("  DUDAS: %s" % dudas[:6]) if dudas else ""))
    print("dudas en total: %d" % dudas_en_total)


if __name__ == "__main__":
    main()
