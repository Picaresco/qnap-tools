# -*- coding: utf-8 -*-
"""Deteccion contra el NAS de laboratorio. Solo con QNAP_TOOLS_PRUEBA_REAL=1."""
import real
from qnap_tools import deteccion
from qnap_tools.transporte import Conexion

pytestmark = real.solo_real


def test_el_nas_de_laboratorio_es_un_quts_hero_con_virtualizacion(tmp_path):
    con = Conexion(real.nas_de_laboratorio(), real.cfg_de_laboratorio(tmp_path))
    con.conectar(fijar_host=True)
    perfil = deteccion.detectar(con)
    con.cerrar()
    assert perfil.sistema == "hero"
    assert perfil.modelo and perfil.firmware and perfil.build and perfil.nombre
    assert perfil.firmware[0].isdigit()
    assert perfil.paquetes["QKVM"].startswith("/share/")
    assert perfil.avisos == ()
