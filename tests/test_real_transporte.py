# -*- coding: utf-8 -*-
"""Transporte contra el NAS de laboratorio. Solo con QNAP_TOOLS_PRUEBA_REAL=1."""
import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

import real
from qnap_tools import transporte
from qnap_tools.transporte import Conexion

pytestmark = real.solo_real


def otra_clave_publica(tipo):
    """Una clave publica distinta, del mismo tipo que la que presenta el NAS."""
    if tipo == "ssh-ed25519":
        privada = ed25519.Ed25519PrivateKey.generate()
    elif tipo.startswith("ecdsa-sha2-nistp256"):
        privada = ec.generate_private_key(ec.SECP256R1())
    elif tipo.startswith("ecdsa-sha2-nistp384"):
        privada = ec.generate_private_key(ec.SECP384R1())
    elif tipo.startswith("ecdsa-sha2-nistp521"):
        privada = ec.generate_private_key(ec.SECP521R1())
    else:
        privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return privada.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode("ascii")


def test_alta_fija_el_host_y_sudo_da_root(tmp_path):
    nas, cfg = real.nas_de_laboratorio(), real.cfg_de_laboratorio(tmp_path)
    con = Conexion(nas, cfg)
    assert con.conectar(fijar_host=True) == "contrasena"       # carpeta nueva: aun no hay clave
    assert len(paramiko.HostKeys(str(cfg.known_hosts))) == 1
    sin = con.ejecutar("id")
    con_sudo = con.ejecutar("id", sudo=True)
    con.cerrar()
    assert sin.rc == 0 and "uid=0(" not in sin.salida and "administrators" in sin.salida
    assert con_sudo.rc == 0 and con_sudo.salida.startswith("uid=0(")
    assert "lecture" not in con_sudo.error


def test_host_fijado_se_verifica_y_sin_fijar_se_rechaza(tmp_path):
    nas = real.nas_de_laboratorio()
    cfg = real.cfg_de_laboratorio(tmp_path / "a")
    con = Conexion(nas, cfg)
    con.conectar(fijar_host=True)
    con.cerrar()
    # ya fijado: conecta sin fijar
    con = Conexion(nas, cfg)
    con.conectar()
    assert con.ejecutar("echo hola").salida == "hola\n"
    con.cerrar()
    # otro ordenador (carpeta de datos vacia): no esta fijado
    with pytest.raises(transporte.HostSinFijar):
        Conexion(nas, real.cfg_de_laboratorio(tmp_path / "b")).conectar()


def test_clave_de_host_cambiada_se_rechaza(tmp_path):
    nas, cfg = real.nas_de_laboratorio(), real.cfg_de_laboratorio(tmp_path)
    con = Conexion(nas, cfg)
    con.conectar(fijar_host=True)
    con.cerrar()
    lineas = cfg.known_hosts.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    entrada, tipo, _ = lineas[0].split(" ", 2)
    cfg.known_hosts.write_text("%s %s\n" % (entrada, otra_clave_publica(tipo)), encoding="utf-8")
    with pytest.raises(transporte.HostCambiado):
        Conexion(nas, cfg).conectar()
    # ni siquiera en un alta se acepta en silencio una clave distinta de la fijada
    with pytest.raises(transporte.HostCambiado):
        Conexion(nas, cfg).conectar(fijar_host=True)


def test_tiempo_agotado_y_la_conexion_sigue_sirviendo(tmp_path):
    nas, cfg = real.nas_de_laboratorio(), real.cfg_de_laboratorio(tmp_path)
    con = Conexion(nas, cfg)
    con.conectar(fijar_host=True)
    r = con.ejecutar("echo antes; sleep 6; echo despues", timeout=1)
    assert r.agotado is True and r.salida == "antes\n"
    assert con.ejecutar("echo sigo").salida == "sigo\n"
    con.cerrar()


def test_contrasena_erronea_es_autenticacion_fallida(tmp_path):
    nas = real.nas_de_laboratorio()
    bueno = real.cfg_de_laboratorio(tmp_path)
    Conexion(nas, bueno).conectar(fijar_host=True)
    from qnap_tools import config
    malo = config.cargar({"QNAP_TOOLS_USER": bueno.usuario, "QNAP_TOOLS_PASSWORD": "no-es-esta-0000",
                          "QNAP_TOOLS_DATA": str(tmp_path)})
    with pytest.raises(transporte.AutenticacionFallida) as e:
        Conexion(nas, malo).conectar()
    assert "no-es-esta-0000" not in str(e.value)
