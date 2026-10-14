# -*- coding: utf-8 -*-
"""Herramientas de flota contra el NAS de laboratorio. Solo con QNAP_TOOLS_PRUEBA_REAL=1.

Se da de alta con instalar_clave=False: asi la prueba no escribe nada en el NAS.
"""
import real
from qnap_tools import servidor
from qnap_tools.flota import servidor as flota_srv

pytestmark = real.solo_real


def test_alta_sin_clave_comprobar_y_baja(tmp_path):
    env = real.leer_env()
    entorno = {"QNAP_TOOLS_USER": env["QNAP_USER"], "QNAP_TOOLS_PASSWORD": env["QNAP_PASSWORD"],
               "QNAP_TOOLS_DATA": str(tmp_path)}
    h = flota_srv.Herramientas(servidor.Contexto(entorno))
    nas = real.nas_de_laboratorio()

    alta = h.nas_alta("lab", nas.host, nas.port, instalar_clave=False)
    assert alta["ok"] is True, alta
    assert alta["acceso"] == "contrasena" and alta["sudo_root"] is True
    assert alta["huella_host"].startswith("ssh-") or alta["huella_host"].startswith("ecdsa-")
    assert "SHA256:" in alta["huella_host"]
    assert alta["perfil"]["sistema"] == "hero" and alta["avisos"] == []
    assert not (tmp_path / "id_ed25519").exists()

    lista = h.nas_lista()
    assert [n["nombre"] for n in lista["nas"]] == ["lab"] and lista["nas"][0]["auth"] == "contrasena"

    comprobado = h.nas_comprobar("lab")
    assert comprobado[0]["ok"] is True, comprobado
    assert comprobado[0]["datos"]["acceso"] == "contrasena"
    assert comprobado[0]["datos"]["sudo_root"] is True

    repetida = h.nas_alta("lab", nas.host, nas.port, instalar_clave=False)
    assert repetida["ok"] is False and "ya existe" in repetida["error"]

    assert h.nas_baja("lab")["ok"] is True
    assert h.nas_lista()["nas"] == []
    assert (tmp_path / "known_hosts").read_text(encoding="utf-8").strip() == ""
    h.ctx.flota.cerrar()
