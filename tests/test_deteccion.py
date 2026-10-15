# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

import falsos
from qnap_tools import config, deteccion
from qnap_tools.inventario import Nas
from qnap_tools.transporte import Conexion

DATOS = Path(__file__).parent / "datos"
NAS = Nas("casa", "192.0.2.10")


def conexion(tmp_path, salida):
    """Conexion abierta contra un NAS simulado que responde `salida` a la orden de deteccion."""
    mundo = falsos.Mundo({deteccion.DETECCION.plantilla: salida})
    cfg = config.cargar({"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto",
                         "QNAP_TOOLS_DATA": str(tmp_path)})
    con = Conexion(NAS, cfg, fabrica=mundo.cliente)
    con.conectar()
    return con, mundo


def leer(nombre):
    return (DATOS / nombre).read_text(encoding="utf-8")


def test_quts_hero_con_sus_paquetes(tmp_path):
    con, _ = conexion(tmp_path, leer("deteccion_hero.txt"))
    assert deteccion.detectar(con) == deteccion.Perfil(
        sistema="hero", modelo="TS-X85", firmware="6.0.2", build="20260819", nombre="NAS-EJEMPLO",
        paquetes={"QKVM": "/share/ZFS600_DATA/.qpkg/QKVM",
                  "container-station": "/share/ZFS600_DATA/.qpkg/container-station"})


def test_qts_con_paquete_desactivado_y_otro_sin_instalar(tmp_path):
    con, _ = conexion(tmp_path, leer("deteccion_qts.txt"))
    perfil = deteccion.detectar(con)
    assert perfil.sistema == "qts" and perfil.firmware == "5.2.10"
    assert perfil.paquetes == {}
    assert perfil.avisos == ()


def test_es_una_sola_orden_y_sin_sudo(tmp_path):
    con, mundo = conexion(tmp_path, leer("deteccion_hero.txt"))
    deteccion.detectar(con)
    assert mundo.ordenes == [(deteccion.DETECCION.plantilla, False)]


def test_la_version_se_lee_de_default_config_y_no_de_etc_config():
    # /etc/config/uLinux.conf puede llevar una version obsoleta (visto en un QuTS hero real)
    p = deteccion.DETECCION.plantilla
    assert "/etc/default_config/uLinux.conf" in p
    assert "/etc/config/uLinux.conf" not in p


@pytest.mark.parametrize("salida", [
    "",
    "\n\n",
    "sistema=hero\nmodelo=TS-X85\n",                       # falta firmware
    "sistema=\nfirmware=5.2.10\n",                          # falta sistema
    "sistema=windows\nfirmware=5.2.10\n",                   # sistema desconocido
    "sh: getcfg: command not found\n",
])
def test_salida_insuficiente_es_deteccion_fallida(tmp_path, salida):
    con, _ = conexion(tmp_path, (0, salida, ""))
    with pytest.raises(deteccion.DeteccionFallida) as e:
        deteccion.detectar(con)
    assert "casa" in str(e.value)


def test_un_codigo_de_salida_distinto_de_cero_es_deteccion_fallida(tmp_path):
    con, _ = conexion(tmp_path, (1, leer("deteccion_hero.txt"), ""))
    with pytest.raises(deteccion.DeteccionFallida) as e:
        deteccion.detectar(con)
    assert "casa" in str(e.value) and "codigo 1" in str(e.value)


def test_tiempo_agotado_es_deteccion_fallida(tmp_path, monkeypatch):
    con, _ = conexion(tmp_path, falsos.CUELGA)
    monkeypatch.setattr(deteccion, "DETECCION", deteccion.DETECCION.__class__(
        "deteccion", deteccion.DETECCION.plantilla, timeout=1))
    with pytest.raises(deteccion.DeteccionFallida) as e:
        deteccion.detectar(con)
    assert "tiempo" in str(e.value)


def test_lineas_de_ruido_se_ignoran(tmp_path):
    con, _ = conexion(tmp_path, "Bienvenido al NAS\n\n" + leer("deteccion_hero.txt") + "otra cosa\n")
    assert deteccion.detectar(con).sistema == "hero"


def test_enable_en_minusculas_tambien_vale(tmp_path):
    salida = leer("deteccion_hero.txt").replace("enable=TRUE", "enable=true")
    con, _ = conexion(tmp_path, salida)
    assert set(deteccion.detectar(con).paquetes) == {"QKVM", "container-station"}


def test_ruta_de_paquete_sospechosa_no_se_usa_y_se_avisa(tmp_path):
    salida = leer("deteccion_hero.txt").replace(
        "paquete.QKVM.ruta=/share/ZFS600_DATA/.qpkg/QKVM", "paquete.QKVM.ruta=/share/x; reboot")
    con, _ = conexion(tmp_path, salida)
    perfil = deteccion.detectar(con)
    assert "QKVM" not in perfil.paquetes
    assert "container-station" in perfil.paquetes
    assert len(perfil.avisos) == 1 and "QKVM" in perfil.avisos[0]
