# -*- coding: utf-8 -*-
"""Valores de los parametros y nombres a ocultar con los que pruebas/captura.py captura la pata
de registros (sin conectar a ningun NAS)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pruebas"))
import captura  # noqa: E402

from qnap_tools.logs import comandos as lc  # noqa: E402

RECUENTO = (
    "==gravedad 1 120\n==gravedad 2 8\n==gravedad 3 1\n==primero\n"
    "event_id,event_type,event_date,event_time,event_user,event_ip,event_comp,event_desc,\n"
    "1,  0,2026-01-02,10:00:00,System,127.0.0.1,localhost,[App Center] Se instalo algo.,\n"
    "Done. Return value is 0\n==ultimo\n"
    "event_id,event_type,event_date,event_time,event_user,event_ip,event_comp,event_desc,\n"
    "129,  0,2026-10-14,03:00:00,System,127.0.0.1,localhost,[Antivirus] Se actualizaron las firmas.,\n"
    "Done. Return value is 0\n")


def test_las_ordenes_de_registros_con_parametros_reciben_valores_que_pasan_la_validacion():
    valores = captura.valores_reales("logs", {"EVT_RECUENTO": RECUENTO}.__getitem__, "hero")
    for nombre, comando in captura.ordenes("logs", "hero"):
        if comando.params:
            assert nombre in valores, nombre
            comando.render(valores[nombre])
    # la busqueda por texto prueba con una palabra del evento mas reciente: asi encuentra algo
    assert valores["EVT_PALABRA"]["texto"] == "Antivirus"
    assert valores["EVT_LISTA"]["gravedad"] == "0" and valores["CONN_LISTA"]["tipo"] == "0"


def test_los_registros_se_anonimizan_con_comillas_y_sin_rutas():
    assert "logs" in captura.CON_COMILLAS and "logs" not in captura.CON_RUTAS


def test_los_nombres_a_ocultar_de_los_registros_son_los_de_carpetas_y_maquinas_virtuales():
    # los registros nombran carpetas, volumenes, VM y contenedores: se leen con las ordenes de
    # esas patas ("pata.ORDEN")
    salidas = {
        "discos.DISCOS_REPARTO": "Disk  SharedFolderName\n1     Fotos,Copias\n",
        "discos.DATASETS": "",
        "discos.CARPETAS_SMB": '[Fotos]\nvalid users = "pepe"\n[Copias]\n',
        "discos.CARPETAS_USO": "", "discos.CARPETAS_ENLACES": "",
        "virtualizacion.VM_XML": "<qvs:name>Servidor web</qvs:name>\n",
        "virtualizacion.CT_LISTA": "", "virtualizacion.CT_LXD": "", "virtualizacion.CT_REDES": "",
    }
    pedidas = []

    def leer(nombre):
        pedidas.append(nombre)
        return salidas[nombre]

    nombres = captura.nombres_a_ocultar("logs", leer, "hero")
    assert {"Fotos", "Copias", "pepe", "Servidor web"} <= set(nombres)
    assert len(set(nombres.values())) == len(nombres)
    assert all("." in p for p in pedidas)
    assert lc.EVT_LISTA  # la pata existe
