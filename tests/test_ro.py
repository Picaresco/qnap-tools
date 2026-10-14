# -*- coding: utf-8 -*-
"""El arnes del laboratorio: como entra en cada NAS."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pruebas"))
import ro  # noqa: E402

ENV = {"QNAP_USER": "usuario", "QNAP_PASSWORD": "secreto", "QNAP_HOST": "192.0.2.10",
       "NAS3_HOST": "192.0.2.11", "NAS3_PORT": "223"}


def clientes(monkeypatch, tmp_path):
    """Sustituye paramiko.SSHClient por un doble que apunta cada intento de conexion."""
    intentos = []

    class Cliente:
        def load_host_keys(self, ruta):
            pass

        def set_missing_host_key_policy(self, politica):
            pass

        def connect(self, **argumentos):
            intentos.append(argumentos)

    clave = tmp_path / "id_ed25519"
    clave.write_text("clave de pega", encoding="utf-8")
    monkeypatch.setattr(ro.paramiko, "SSHClient", Cliente)
    monkeypatch.setattr(ro, "CLAVE", str(clave))
    monkeypatch.setattr(ro, "HOSTS", str(tmp_path / "known_hosts"))
    return intentos


def test_donde_la_clave_de_pruebas_esta_instalada_se_entra_con_ella(monkeypatch, tmp_path):
    intentos = clientes(monkeypatch, tmp_path)
    _, via = ro.conectar(ENV, "nas1")
    assert via == "clave" and len(intentos) == 1 and "key_filename" in intentos[0]


def test_donde_no_esta_instalada_no_se_ofrece_y_se_entra_por_contrasena(monkeypatch, tmp_path):
    # ofrecer una clave que el NAS no tiene deja un intento fallido en cada conexion, y varios
    # seguidos hacen que el NAS corte durante un rato las conexiones nuevas de este equipo
    intentos = clientes(monkeypatch, tmp_path)
    _, via = ro.conectar(ENV, "nas3")
    assert via == "contrasena" and len(intentos) == 1
    assert "key_filename" not in intentos[0] and intentos[0]["password"] == "secreto"
    assert intentos[0]["port"] == 223 and "nas3" in ro.SIN_CLAVE
