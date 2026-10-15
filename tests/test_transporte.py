# -*- coding: utf-8 -*-
import socket

import paramiko
import pytest

import falsos
from qnap_tools import config, transporte
from qnap_tools.inventario import Nas
from qnap_tools.transporte import Conexion

NAS = Nas("casa", "192.0.2.10", 2222)


def cfg(tmp_path, con_clave=True):
    c = config.cargar({"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto",
                       "QNAP_TOOLS_DATA": str(tmp_path)})
    if con_clave:
        falsos.crear_clave(c.clave)
    return c


def conectada(tmp_path, mundo, nas=NAS):
    con = Conexion(nas, cfg(tmp_path), fabrica=mundo.cliente)
    con.conectar()
    return con


# --- autenticacion ---------------------------------------------------------------

def test_auto_entra_por_clave_si_el_nas_la_acepta(tmp_path):
    mundo = falsos.Mundo()
    con = Conexion(NAS, cfg(tmp_path), fabrica=mundo.cliente)
    assert con.conectar() == "clave"
    assert mundo.intentos == [("clave", "usuario")]


def test_auto_cae_a_contrasena_si_la_clave_se_rechaza(tmp_path):
    mundo = falsos.Mundo(acepta_clave=False)
    con = Conexion(NAS, cfg(tmp_path), fabrica=mundo.cliente)
    assert con.conectar() == "contrasena"
    assert mundo.intentos == [("clave", "usuario"), ("contrasena", "usuario")]


def test_auto_sin_fichero_de_clave_va_directo_a_contrasena(tmp_path):
    mundo = falsos.Mundo()
    con = Conexion(NAS, cfg(tmp_path, con_clave=False), fabrica=mundo.cliente)
    assert con.conectar() == "contrasena"
    assert mundo.intentos == [("contrasena", "usuario")]


def test_auto_con_clave_ilegible_va_a_contrasena(tmp_path):
    c = cfg(tmp_path, con_clave=False)
    c.clave.write_text("esto no es una clave", encoding="utf-8")
    mundo = falsos.Mundo()
    assert Conexion(NAS, c, fabrica=mundo.cliente).conectar() == "contrasena"


def test_solo_clave_y_rechazada_es_autenticacion_fallida(tmp_path):
    mundo = falsos.Mundo(acepta_clave=False)
    con = Conexion(Nas("casa", "192.0.2.10", auth="clave"), cfg(tmp_path), fabrica=mundo.cliente)
    with pytest.raises(transporte.AutenticacionFallida):
        con.conectar()
    assert mundo.intentos == [("clave", "usuario")]


def test_solo_clave_sin_fichero_lo_dice(tmp_path):
    mundo = falsos.Mundo()
    con = Conexion(Nas("casa", "192.0.2.10", auth="clave"), cfg(tmp_path, con_clave=False),
                   fabrica=mundo.cliente)
    with pytest.raises(transporte.ErrorConexion) as e:
        con.conectar()
    assert "clave" in str(e.value)
    assert mundo.intentos == []


def test_solo_contrasena_no_intenta_la_clave(tmp_path):
    mundo = falsos.Mundo()
    con = Conexion(Nas("casa", "192.0.2.10", auth="contrasena"), cfg(tmp_path), fabrica=mundo.cliente)
    assert con.conectar() == "contrasena"
    assert mundo.intentos == [("contrasena", "usuario")]


def test_usuario_propio_del_nas_gana_al_comun(tmp_path):
    mundo = falsos.Mundo()
    Conexion(Nas("casa", "192.0.2.10", user="otro"), cfg(tmp_path), fabrica=mundo.cliente).conectar()
    assert mundo.intentos == [("clave", "otro")]


def test_se_conecta_al_host_y_puerto_del_inventario_sin_agente_ni_otras_claves(tmp_path):
    mundo = falsos.Mundo()
    conectada(tmp_path, mundo)
    arg = mundo.clientes[-1].argumentos
    assert (arg["hostname"], arg["port"]) == ("192.0.2.10", 2222)
    assert arg["allow_agent"] is False and arg["look_for_keys"] is False


def test_todo_rechazado_es_autenticacion_fallida_sin_la_contrasena_en_el_mensaje(tmp_path):
    mundo = falsos.Mundo(acepta_clave=False, acepta_contrasena=False)
    con = Conexion(NAS, cfg(tmp_path), fabrica=mundo.cliente)
    with pytest.raises(transporte.AutenticacionFallida) as e:
        con.conectar()
    assert "casa" in str(e.value) and "usuario" in str(e.value)
    assert "secreto" not in str(e.value)


# --- clave de host -----------------------------------------------------------------

def test_clave_de_host_cambiada_no_cae_a_contrasena(tmp_path):
    mundo = falsos.Mundo(host_cambiado=True)
    con = Conexion(NAS, cfg(tmp_path), fabrica=mundo.cliente)
    with pytest.raises(transporte.HostCambiado) as e:
        con.conectar()
    assert "casa" in str(e.value)
    assert len(mundo.clientes) == 1          # un solo intento
    assert mundo.intentos == []              # no se llego a presentar ninguna credencial


def test_host_sin_fijar_se_rechaza_fuera_del_alta(tmp_path):
    mundo = falsos.Mundo(host_fijado=False)
    con = Conexion(NAS, cfg(tmp_path), fabrica=mundo.cliente)
    with pytest.raises(transporte.HostSinFijar) as e:
        con.conectar()
    assert "nas_alta" in str(e.value)
    assert mundo.intentos == [] and mundo.fijaciones == 0


def test_en_el_alta_se_fija_la_clave_de_host(tmp_path):
    mundo = falsos.Mundo(host_fijado=False)
    c = cfg(tmp_path)
    con = Conexion(NAS, c, fabrica=mundo.cliente)
    con.conectar(fijar_host=True)
    assert mundo.fijaciones == 1
    assert c.known_hosts.exists()
    assert mundo.clientes[-1].hosts_cargados == str(c.known_hosts)


def test_fuera_del_alta_se_carga_el_known_hosts_propio_si_existe(tmp_path):
    mundo = falsos.Mundo()
    c = cfg(tmp_path)
    c.known_hosts.write_text("", encoding="utf-8")
    Conexion(NAS, c, fabrica=mundo.cliente).conectar()
    assert mundo.clientes[-1].hosts_cargados == str(c.known_hosts)
    assert not isinstance(mundo.clientes[-1].politica, paramiko.AutoAddPolicy)


# --- errores de red -------------------------------------------------------------------

@pytest.mark.parametrize("error", [
    socket.timeout("timed out"),
    ConnectionRefusedError(10061, "refused"),
    paramiko.SSHException("Error reading SSH protocol banner"),
    EOFError(),
])
def test_fallo_de_red_es_error_de_conexion_con_el_nas_en_el_mensaje(tmp_path, error):
    mundo = falsos.Mundo(error_conexion=error)
    con = Conexion(NAS, cfg(tmp_path), fabrica=mundo.cliente)
    with pytest.raises(transporte.ErrorConexion) as e:
        con.conectar()
    assert "casa" in str(e.value) and "192.0.2.10" in str(e.value)
    assert not isinstance(e.value, transporte.AutenticacionFallida)


def test_un_error_que_cita_la_contrasena_sale_saneado(tmp_path):
    mundo = falsos.Mundo(error_conexion=paramiko.SSHException("fallo con secreto dentro"))
    con = Conexion(NAS, cfg(tmp_path), fabrica=mundo.cliente)
    with pytest.raises(transporte.ErrorConexion) as e:
        con.conectar()
    assert "secreto" not in str(e.value)


# --- ejecutar ---------------------------------------------------------------------------

def test_ejecutar_sin_conectar_es_error(tmp_path):
    con = Conexion(NAS, cfg(tmp_path), fabrica=falsos.Mundo().cliente)
    with pytest.raises(transporte.ErrorConexion):
        con.ejecutar("id")


def test_ejecutar_devuelve_codigo_salida_y_error(tmp_path):
    mundo = falsos.Mundo({"id": "uid=1002(usuario)\n", "falla": (3, "algo", "mal\n")})
    con = conectada(tmp_path, mundo)
    assert con.ejecutar("id") == transporte.Resultado(0, "uid=1002(usuario)\n", "", False)
    assert con.ejecutar("falla") == transporte.Resultado(3, "algo", "mal\n", False)


def test_sin_sudo_la_orden_va_tal_cual_y_no_se_escribe_nada_en_stdin(tmp_path):
    mundo = falsos.Mundo({"id": "x"})
    conectada(tmp_path, mundo).ejecutar("id")
    assert mundo.enviado == ["id"]
    assert mundo.stdin == [""]


def test_con_sudo_se_envuelve_y_la_contrasena_va_por_stdin(tmp_path):
    mundo = falsos.Mundo({"id": "uid=0(admin)\n"})
    r = conectada(tmp_path, mundo).ejecutar("id", sudo=True)
    assert mundo.enviado == ["sudo -S -p '' sh -c id"]
    assert mundo.stdin == ["secreto\n"]
    assert r.salida == "uid=0(admin)\n"


def test_con_sudo_una_orden_con_tuberias_viaja_entrecomillada(tmp_path):
    orden = "cat /proc/mdstat | grep -c 'md[0-9]'"
    mundo = falsos.Mundo({orden: "4\n"})
    r = conectada(tmp_path, mundo).ejecutar(orden, sudo=True)
    assert mundo.ordenes == [(orden, True)]
    assert r.salida == "4\n"


def test_la_contrasena_no_viaja_en_el_texto_de_la_orden(tmp_path):
    mundo = falsos.Mundo({"id": "x"})
    conectada(tmp_path, mundo).ejecutar("id", sudo=True)
    assert "secreto" not in mundo.enviado[0]


def test_stdin_se_cierra_siempre(tmp_path):
    canales = []
    mundo = falsos.Mundo({"id": "x"})
    con = conectada(tmp_path, mundo)
    original = falsos.CanalFalso.shutdown_write

    def espia(self):
        canales.append(self)
        original(self)
    falsos.CanalFalso.shutdown_write = espia
    try:
        con.ejecutar("id")
        con.ejecutar("id", sudo=True)
    finally:
        falsos.CanalFalso.shutdown_write = original
    assert len(canales) == 2 and all(c.stdin_cerrado for c in canales)


def test_el_sermon_de_sudo_no_llega_al_error(tmp_path):
    mundo = falsos.Mundo({"id": (0, "uid=0\n", "aviso real\n")}, sudo_con_sermon=True)
    r = conectada(tmp_path, mundo).ejecutar("id", sudo=True)
    assert "lecture" not in r.error and "responsibility" not in r.error
    assert r.error.strip() == "aviso real"


def test_sudo_que_rechaza_la_contrasena_es_autenticacion_fallida(tmp_path):
    mundo = falsos.Mundo({"id": "x"})
    con = conectada(tmp_path, mundo)
    mundo.contrasena = "otra-distinta"      # el NAS ya no acepta la que tenemos
    with pytest.raises(transporte.AutenticacionFallida) as e:
        con.ejecutar("id", sudo=True)
    assert "sudo" in str(e.value) and "secreto" not in str(e.value)


def test_tiempo_agotado_cierra_el_canal_y_devuelve_lo_leido(tmp_path):
    mundo = falsos.Mundo({"lenta": falsos.CUELGA})
    mundo.parcial = "primera linea\n"
    r = conectada(tmp_path, mundo).ejecutar("lenta", timeout=0.2)
    assert r.agotado is True
    assert r.salida == "primera linea\n"


def test_salida_grande_llega_entera(tmp_path):
    grande = "0123456789abcdef\n" * 20000        # 340 KB
    mundo = falsos.Mundo({"mucho": grande})
    r = conectada(tmp_path, mundo).ejecutar("mucho")
    assert r.salida == grande


def test_bytes_que_no_son_utf8_no_rompen(tmp_path):
    mundo = falsos.Mundo({"raro": (0, b"antes \xff\xfe despues\n", b"")})
    r = conectada(tmp_path, mundo).ejecutar("raro")
    assert "antes" in r.salida and "despues" in r.salida


def test_sesion_caida_es_error_de_conexion(tmp_path):
    mundo = falsos.Mundo({"id": "x"})
    con = conectada(tmp_path, mundo)
    mundo.caida = True
    with pytest.raises(transporte.ErrorConexion) as e:
        con.ejecutar("id")
    assert "casa" in str(e.value)


def test_cerrar_es_idempotente_y_despues_no_se_puede_ejecutar(tmp_path):
    con = conectada(tmp_path, falsos.Mundo({"id": "x"}))
    con.cerrar()
    con.cerrar()
    with pytest.raises(transporte.ErrorConexion):
        con.ejecutar("id")


def test_reconectar_cierra_la_conexion_anterior(tmp_path):
    mundo = falsos.Mundo()
    con = conectada(tmp_path, mundo)
    primero = mundo.clientes[-1]
    con.conectar()
    assert primero.cerrado is True
    assert mundo.conexiones == 2


# --- fin de la salida, latidos y avisos ----------------------------------------------------

def test_la_salida_que_llega_despues_del_codigo_de_salida_no_se_pierde(tmp_path):
    texto = "".join("linea %d\n" % i for i in range(200))
    mundo = falsos.Mundo({"larga": texto}, salida_tardia=True)
    con = conectada(tmp_path, mundo)
    r = con.ejecutar("larga")
    assert r.rc == 0 and r.salida == texto


def test_si_el_fin_de_la_salida_no_llega_no_se_espera_para_siempre(tmp_path, monkeypatch):
    # un proceso hijo que retiene la salida abierta: la orden ya termino y dio su codigo
    monkeypatch.setattr(transporte, "GRACIA_FIN", 0.05)
    mundo = falsos.Mundo({"id": "x\n"}, sin_fin_de_salida=True)
    con = conectada(tmp_path, mundo)
    r = con.ejecutar("id", timeout=30)
    assert (r.rc, r.salida, r.agotado) == (0, "x\n", False)


def test_al_conectar_se_piden_latidos_para_detectar_una_conexion_muerta(tmp_path):
    mundo = falsos.Mundo()
    conectada(tmp_path, mundo)
    assert mundo.keepalives == [transporte.LATIDO] and 10 <= transporte.LATIDO <= 60


def test_el_aviso_de_host_sin_fijar_indica_enrolar_y_alta(tmp_path):
    # en un ordenador nuevo el NAS ya esta en el inventario: lo que toca es enrolar
    mundo = falsos.Mundo(host_fijado=False)
    con = Conexion(NAS, cfg(tmp_path), fabrica=mundo.cliente)
    with pytest.raises(transporte.HostSinFijar) as e:
        con.conectar()
    assert "nas_enrolar" in str(e.value) and "nas_alta" in str(e.value)


def test_host_fijado_dice_si_la_clave_de_un_nas_esta_guardada(tmp_path):
    c = cfg(tmp_path)
    assert transporte.host_fijado(c, NAS) is False
    mundo = falsos.Mundo(host_fijado=False)
    Conexion(NAS, c, fabrica=mundo.cliente).conectar(fijar_host=True)
    assert transporte.host_fijado(c, NAS) is True
    assert transporte.host_fijado(c, Nas("otro", "192.0.2.10")) is False     # mismo equipo, otro puerto


# --- canal cerrado sin codigo de salida -------------------------------------------------------

def test_un_canal_cerrado_sin_codigo_de_salida_es_error_de_conexion(tmp_path):
    # la conexion murio (o el proceso remoto fue matado) con la orden en curso: paramiko da -1
    mundo = falsos.Mundo({"cortada": (-1, "parcial\n", "")})
    con = conectada(tmp_path, mundo)
    with pytest.raises(transporte.ErrorConexion) as e:
        con.ejecutar("cortada")
    assert "casa" in str(e.value) and "codigo de salida" in str(e.value)


def test_el_tiempo_agotado_sigue_devolviendo_resultado_y_no_error(tmp_path):
    mundo = falsos.Mundo({"lenta": falsos.CUELGA})
    r = conectada(tmp_path, mundo).ejecutar("lenta", timeout=0.2)
    assert r.agotado is True and r.rc == -1


def test_el_mensaje_de_host_cambiado_da_la_ruta_de_known_hosts(tmp_path):
    mundo = falsos.Mundo(host_cambiado=True)
    c = cfg(tmp_path)
    con = Conexion(NAS, c, fabrica=mundo.cliente)
    with pytest.raises(transporte.HostCambiado) as e:
        con.conectar()
    assert str(c.known_hosts) in str(e.value) and "nas_baja" in str(e.value)
