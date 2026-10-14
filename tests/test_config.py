# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from qnap_tools import config

BASE = {"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto"}


def test_sin_credenciales_nombra_las_dos_variables():
    with pytest.raises(config.ConfigError) as e:
        config.cargar({})
    assert "QNAP_TOOLS_USER" in str(e.value)
    assert "QNAP_TOOLS_PASSWORD" in str(e.value)


def test_falta_solo_la_contrasena():
    with pytest.raises(config.ConfigError) as e:
        config.cargar({"QNAP_TOOLS_USER": "usuario"})
    assert "QNAP_TOOLS_PASSWORD" in str(e.value)
    assert "QNAP_TOOLS_USER" not in str(e.value)


def test_cadena_vacia_cuenta_como_ausente():
    with pytest.raises(config.ConfigError):
        config.cargar({"QNAP_TOOLS_USER": "", "QNAP_TOOLS_PASSWORD": "secreto"})


def test_marcador_sin_sustituir_cuenta_como_ausente():
    # si el plugin no sustituye ${user_config.x}, el literal no es una credencial
    with pytest.raises(config.ConfigError) as e:
        config.cargar({"QNAP_TOOLS_USER": "${user_config.ssh_user}", "QNAP_TOOLS_PASSWORD": "secreto"})
    assert "QNAP_TOOLS_USER" in str(e.value)


def test_contrasena_que_contiene_un_marcador_dentro_se_acepta():
    cfg = config.cargar({"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "a${b}c"})
    assert cfg.contrasena == "a${b}c"


def test_la_contrasena_se_conserva_tal_cual():
    cfg = config.cargar({"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": " a b \"c\" "})
    assert cfg.contrasena == " a b \"c\" "


def test_el_usuario_se_recorta():
    cfg = config.cargar({"QNAP_TOOLS_USER": " usuario ", "QNAP_TOOLS_PASSWORD": "secreto"})
    assert cfg.usuario == "usuario"


def test_datos_propio_gana_al_del_plugin():
    cfg = config.cargar({**BASE, "QNAP_TOOLS_DATA": "/a", "CLAUDE_PLUGIN_DATA": "/b"})
    assert cfg.datos == Path("/a")


def test_datos_cae_al_del_plugin():
    cfg = config.cargar({**BASE, "CLAUDE_PLUGIN_DATA": "/b"})
    assert cfg.datos == Path("/b")


def test_datos_sin_sustituir_cae_al_del_plugin():
    cfg = config.cargar({**BASE, "QNAP_TOOLS_DATA": "${CLAUDE_PLUGIN_DATA}", "CLAUDE_PLUGIN_DATA": "/b"})
    assert cfg.datos == Path("/b")


def test_datos_por_defecto_en_la_carpeta_del_usuario():
    cfg = config.cargar(dict(BASE))
    assert cfg.datos == Path.home() / ".qnap-tools"


def test_rutas_derivadas_de_la_carpeta_de_datos():
    cfg = config.cargar({**BASE, "QNAP_TOOLS_DATA": "/a"})
    assert cfg.inventario == Path("/a") / "inventario.toml"
    assert cfg.clave == Path("/a") / "id_ed25519"
    assert cfg.known_hosts == Path("/a") / "known_hosts"


def test_la_ruta_del_inventario_es_configurable():
    cfg = config.cargar({**BASE, "QNAP_TOOLS_DATA": "/a", "QNAP_TOOLS_INVENTARIO": "/comun/inv.toml"})
    assert cfg.inventario == Path("/comun/inv.toml")
    assert cfg.clave == Path("/a") / "id_ed25519"


def test_repr_y_str_no_muestran_la_contrasena():
    cfg = config.cargar(dict(BASE))
    assert "secreto" not in repr(cfg)
    assert "secreto" not in str(cfg)
