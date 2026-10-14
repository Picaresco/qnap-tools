# -*- coding: utf-8 -*-
import paramiko

from qnap_tools import claves, config


def cfg(carpeta):
    return config.cargar({"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto",
                          "QNAP_TOOLS_DATA": str(carpeta)})


def test_crea_el_par_y_devuelve_la_linea_publica(tmp_path):
    c = cfg(tmp_path / "datos")          # la carpeta de datos aun no existe
    publica = claves.asegurar(c)
    tipo, cuerpo, comentario = publica.split(" ")
    assert tipo == "ssh-ed25519" and len(cuerpo) > 40
    assert comentario.startswith("qnap-tools@")
    assert c.clave.exists()
    assert (c.datos / "id_ed25519.pub").read_text(encoding="utf-8").strip() == publica


def test_la_clave_privada_la_lee_paramiko_y_corresponde_a_la_publica(tmp_path):
    c = cfg(tmp_path)
    publica = claves.asegurar(c)
    privada = paramiko.PKey.from_path(str(c.clave))
    assert privada.get_name() == "ssh-ed25519"
    assert privada.get_base64() == publica.split(" ")[1]


def test_una_segunda_llamada_no_regenera_la_clave(tmp_path):
    c = cfg(tmp_path)
    primera = claves.asegurar(c)
    contenido = c.clave.read_bytes()
    assert claves.asegurar(c) == primera
    assert c.clave.read_bytes() == contenido


def test_si_falta_el_pub_se_reconstruye_desde_la_privada(tmp_path):
    c = cfg(tmp_path)
    primera = claves.asegurar(c)
    (c.datos / "id_ed25519.pub").unlink()
    assert claves.asegurar(c) == primera
    assert (c.datos / "id_ed25519.pub").exists()


def test_el_comentario_solo_lleva_caracteres_seguros(tmp_path, monkeypatch):
    monkeypatch.setattr(claves.socket, "gethostname", lambda: "Mi PC; rm -rf $(x)")
    comentario = claves.asegurar(cfg(tmp_path)).split(" ", 2)[2]
    assert comentario == "qnap-tools@Mi-PC--rm--rf---x-"
