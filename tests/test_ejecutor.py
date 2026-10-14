# -*- coding: utf-8 -*-
import threading
import time
from pathlib import Path

import paramiko
import pytest

import falsos
from qnap_tools import comandos, config, deteccion, ejecutor
from qnap_tools import inventario as inv
from qnap_tools import transporte
from qnap_tools.comandos import Comando
from qnap_tools.ejecutor import Flota
from qnap_tools.inventario import Nas
from qnap_tools.transporte import Conexion

DATOS = Path(__file__).parent / "datos"
HERO = (DATOS / "deteccion_hero.txt").read_text(encoding="utf-8")
QTS = (DATOS / "deteccion_qts.txt").read_text(encoding="utf-8")
DET = deteccion.DETECCION.plantilla

ENLACES = Comando("enlaces", "ip -br link")


def montar(tmp_path, mundos, nas=None):
    """Flota sobre NAS simulados: un Mundo por nombre de NAS."""
    cfg = config.cargar({"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto",
                         "QNAP_TOOLS_DATA": str(tmp_path)})
    if nas is None:
        nas = {n: Nas(n, "192.0.2.%d" % (i + 1)) for i, n in enumerate(sorted(mundos))}
    inv.guardar(cfg.inventario, nas)

    def fabrica(un_nas, la_cfg):
        return Conexion(un_nas, la_cfg, fabrica=mundos[un_nas.nombre].cliente)
    return Flota(cfg, fabrica_conexion=fabrica), nas


# --- recortar ----------------------------------------------------------------------

def test_recortar_lista_larga():
    r = ejecutor.recortar(list(range(300)), 200)
    assert r["filas"] == list(range(200)) and r["total"] == 300 and r["truncado"] is True


def test_recortar_lista_corta_y_en_el_limite():
    assert ejecutor.recortar(list(range(10))) == {"filas": list(range(10)), "total": 10, "truncado": False}
    assert ejecutor.recortar(list(range(200)), 200)["truncado"] is False


# --- por_nas -------------------------------------------------------------------------

def test_todos_devuelve_una_entrada_por_nas_en_orden_alfabetico(tmp_path):
    flota, _ = montar(tmp_path, {"zeta": falsos.Mundo(), "alfa": falsos.Mundo()})
    assert flota.por_nas("todos", lambda nas: nas.host) == [
        {"nas": "alfa", "ok": True, "datos": "192.0.2.1"},
        {"nas": "zeta", "ok": True, "datos": "192.0.2.2"},
    ]


def test_un_nas_inalcanzable_no_tapa_a_los_demas(tmp_path):
    mundos = {"alfa": falsos.Mundo(error_conexion=ConnectionRefusedError(10061, "refused")),
              "zeta": falsos.Mundo({"ip -br link": "eth0 UP\n"})}
    flota, _ = montar(tmp_path, mundos)
    r = flota.por_nas("todos", lambda nas: flota.lanzar(nas, ENLACES))
    assert r[0]["nas"] == "alfa" and r[0]["ok"] is False and "alfa" in r[0]["error"]
    assert r[1] == {"nas": "zeta", "ok": True, "datos": "eth0 UP\n"}


def test_credencial_rechazada_en_un_nas_no_tapa_a_los_demas(tmp_path):
    mundos = {"alfa": falsos.Mundo(acepta_clave=False, acepta_contrasena=False),
              "zeta": falsos.Mundo({"ip -br link": "eth0 UP\n"})}
    flota, _ = montar(tmp_path, mundos)
    r = flota.por_nas("todos", lambda nas: flota.lanzar(nas, ENLACES))
    assert r[0]["ok"] is False and "rechazo" in r[0]["error"]
    assert r[1]["ok"] is True


def test_nombre_desconocido_da_una_entrada_de_error_con_los_validos(tmp_path):
    flota, _ = montar(tmp_path, {"alfa": falsos.Mundo(), "zeta": falsos.Mundo()})
    r = flota.por_nas("nope", lambda nas: 1)
    assert len(r) == 1 and r[0]["nas"] == "nope" and r[0]["ok"] is False
    assert "alfa" in r[0]["error"] and "zeta" in r[0]["error"]


def test_inventario_vacio_lo_dice(tmp_path):
    flota, _ = montar(tmp_path, {}, nas={})
    r = flota.por_nas("todos", lambda nas: 1)
    assert len(r) == 1 and r[0]["ok"] is False and "vacio" in r[0]["error"]


def test_inventario_corrupto_da_error_y_no_excepcion(tmp_path):
    flota, _ = montar(tmp_path, {"alfa": falsos.Mundo()})
    flota.cfg.inventario.write_text("esto no es [toml", encoding="utf-8")
    r = flota.por_nas("todos", lambda nas: 1)
    assert len(r) == 1 and r[0]["ok"] is False and "inventario" in r[0]["error"]


def test_un_nas_dado_de_alta_despues_se_ve_sin_reiniciar(tmp_path):
    # el alta la hace otro proceso (qnap-flota): el inventario se relee en cada consulta
    mundos = {"alfa": falsos.Mundo(), "nuevo": falsos.Mundo()}
    flota, nas = montar(tmp_path, mundos, nas={"alfa": Nas("alfa", "192.0.2.1")})
    assert [x["nas"] for x in flota.por_nas("todos", lambda n: 1)] == ["alfa"]
    inv.guardar(flota.cfg.inventario, {**nas, "nuevo": Nas("nuevo", "192.0.2.9")})
    assert [x["nas"] for x in flota.por_nas("todos", lambda n: 1)] == ["alfa", "nuevo"]


def test_cualquier_otra_excepcion_sale_como_error_con_su_clase(tmp_path):
    flota, _ = montar(tmp_path, {"alfa": falsos.Mundo()})

    def rompe(nas):
        raise RuntimeError("algo inesperado")
    r = flota.por_nas("alfa", rompe)
    assert r == [{"nas": "alfa", "ok": False, "error": "RuntimeError: algo inesperado"}]


def test_el_texto_de_error_nunca_lleva_la_contrasena(tmp_path):
    flota, _ = montar(tmp_path, {"alfa": falsos.Mundo()})

    def rompe(nas):
        raise RuntimeError("fallo con secreto dentro")
    assert "secreto" not in flota.por_nas("alfa", rompe)[0]["error"]


def test_nas_distintos_se_consultan_en_paralelo(tmp_path):
    def lento(orden, sudo):
        time.sleep(0.4)
        return "x\n"
    mundos = {n: falsos.Mundo({"ip -br link": lento}) for n in ("a", "b", "c")}
    flota, _ = montar(tmp_path, mundos)
    inicio = time.monotonic()
    r = flota.por_nas("todos", lambda nas: flota.lanzar(nas, ENLACES))
    assert all(x["ok"] for x in r)
    assert time.monotonic() - inicio < 0.95        # en serie serian 1,2 s


# --- lanzar ---------------------------------------------------------------------------

def test_lanzar_devuelve_la_salida(tmp_path):
    mundo = falsos.Mundo({"ip -br link": "eth0 UP\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    assert flota.lanzar(nas["alfa"], ENLACES) == "eth0 UP\n"
    assert mundo.ordenes == [("ip -br link", False)]     # sin deteccion previa: vale para ambos


def test_lanzar_respeta_el_sudo_del_comando(tmp_path):
    mundo = falsos.Mundo({"iptables-save": "*filter\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    flota.lanzar(nas["alfa"], Comando("fw", "iptables-save", sudo=True))
    assert mundo.ordenes == [("iptables-save", True)]


def test_parametro_invalido_no_llega_a_conectar(tmp_path):
    mundo = falsos.Mundo()
    flota, nas = montar(tmp_path, {"alfa": mundo})
    cmd = Comando("eth", "ethtool {iface}", {"iface": "interfaz"})
    with pytest.raises(comandos.ParametroInvalido):
        flota.lanzar(nas["alfa"], cmd, {"iface": "eth0; reboot"})
    assert mundo.clientes == []


def test_comando_de_hero_en_un_qts_es_error_y_no_se_ejecuta(tmp_path):
    mundo = falsos.Mundo({DET: QTS, "zpool list": "x"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    with pytest.raises(ejecutor.ErrorComando) as e:
        flota.lanzar(nas["alfa"], Comando("pools", "zpool list", sistema="hero"))
    assert "hero" in str(e.value) and "qts" in str(e.value)
    assert mundo.ordenes == [(DET, False)]


def test_comando_de_hero_en_un_hero_se_ejecuta(tmp_path):
    mundo = falsos.Mundo({DET: HERO, "zpool list": "zpool1 ONLINE\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    assert flota.lanzar(nas["alfa"], Comando("pools", "zpool list", sistema="hero")) == "zpool1 ONLINE\n"


def test_salida_vacia_es_error_y_no_dato(tmp_path):
    flota, nas = montar(tmp_path, {"alfa": falsos.Mundo({"ip -br link": ""})})
    with pytest.raises(ejecutor.ErrorComando) as e:
        flota.lanzar(nas["alfa"], ENLACES)
    assert "alfa" in str(e.value) and "enlaces" in str(e.value)


def test_codigo_distinto_de_cero_es_error_con_el_mensaje_del_nas(tmp_path):
    mundo = falsos.Mundo({"ip -br link": (1, "", "ip: can't find device\n")})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    with pytest.raises(ejecutor.ErrorComando) as e:
        flota.lanzar(nas["alfa"], ENLACES)
    assert "can't find device" in str(e.value)


def test_validacion_desactivada_devuelve_la_salida_vacia(tmp_path):
    flota, nas = montar(tmp_path, {"alfa": falsos.Mundo({"ip rule": ""})})
    assert flota.lanzar(nas["alfa"], Comando("reglas", "ip rule", valida=None)) == ""


def test_tiempo_agotado_es_error_que_dice_el_maximo(tmp_path):
    flota, nas = montar(tmp_path, {"alfa": falsos.Mundo({"lenta": falsos.CUELGA})})
    with pytest.raises(ejecutor.ErrorComando) as e:
        flota.lanzar(nas["alfa"], Comando("lenta", "lenta", timeout=1))
    assert "1 s" in str(e.value) and "tiempo" in str(e.value)


# --- conexiones ---------------------------------------------------------------------------

def test_dos_ordenes_seguidas_usan_una_sola_conexion(tmp_path):
    mundo = falsos.Mundo({"ip -br link": "x\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    flota.lanzar(nas["alfa"], ENLACES)
    flota.lanzar(nas["alfa"], ENLACES)
    assert mundo.conexiones == 1


def test_conexion_caida_se_reabre_una_vez(tmp_path):
    mundo = falsos.Mundo({"ip -br link": "x\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    flota.lanzar(nas["alfa"], ENLACES)
    mundo.cortar()
    assert flota.lanzar(nas["alfa"], ENLACES) == "x\n"
    assert mundo.conexiones == 2


def test_caida_persistente_es_error_de_conexion(tmp_path):
    mundo = falsos.Mundo({"ip -br link": "x\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    flota.lanzar(nas["alfa"], ENLACES)
    mundo.caida = True
    with pytest.raises(transporte.ErrorConexion):
        flota.lanzar(nas["alfa"], ENLACES)
    assert mundo.conexiones == 2         # un solo reintento


def test_sudo_rechazado_no_se_reintenta(tmp_path):
    mundo = falsos.Mundo({"iptables-save": "x\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    cmd = Comando("fw", "iptables-save", sudo=True)
    flota.lanzar(nas["alfa"], cmd)
    mundo.contrasena = "otra"
    with pytest.raises(transporte.AutenticacionFallida):
        flota.lanzar(nas["alfa"], cmd)
    assert mundo.conexiones == 1 and len(mundo.ordenes) == 2


def test_host_cambiado_al_reabrir_se_propaga(tmp_path):
    mundo = falsos.Mundo({"ip -br link": "x\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    flota.lanzar(nas["alfa"], ENLACES)
    mundo.cortar()
    mundo.host_cambiado = True
    with pytest.raises(transporte.HostCambiado):
        flota.lanzar(nas["alfa"], ENLACES)


def test_si_cambia_la_entrada_del_inventario_se_reconecta_y_se_redetecta(tmp_path):
    mundo = falsos.Mundo({DET: HERO, "ip -br link": "x\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    flota.perfil(nas["alfa"])
    otro = Nas("alfa", "192.0.2.99", 2222)
    flota.lanzar(otro, ENLACES)
    assert mundo.conexiones == 2
    assert mundo.clientes[-1].argumentos["hostname"] == "192.0.2.99"
    flota.perfil(otro)
    assert [o for o, _ in mundo.ordenes].count(DET) == 2


def test_las_ordenes_a_un_mismo_nas_van_en_serie(tmp_path):
    estado = {"dentro": 0, "maximo": 0}
    candado = threading.Lock()

    def lento(orden, sudo):
        with candado:
            estado["dentro"] += 1
            estado["maximo"] = max(estado["maximo"], estado["dentro"])
        time.sleep(0.05)
        with candado:
            estado["dentro"] -= 1
        return "x\n"
    flota, nas = montar(tmp_path, {"alfa": falsos.Mundo({"ip -br link": lento})})
    hilos = [threading.Thread(target=flota.lanzar, args=(nas["alfa"], ENLACES)) for _ in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert estado["maximo"] == 1


def test_cerrar_cierra_las_conexiones_y_despues_se_puede_seguir(tmp_path):
    mundo = falsos.Mundo({"ip -br link": "x\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    flota.lanzar(nas["alfa"], ENLACES)
    flota.cerrar()
    assert mundo.clientes[0].cerrado is True
    assert flota.lanzar(nas["alfa"], ENLACES) == "x\n"
    assert mundo.conexiones == 2


# --- perfil -----------------------------------------------------------------------------------

def test_el_perfil_se_detecta_una_sola_vez(tmp_path):
    mundo = falsos.Mundo({DET: HERO})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    assert flota.perfil(nas["alfa"]).sistema == "hero"
    assert flota.perfil(nas["alfa"]).sistema == "hero"
    assert mundo.ordenes == [(DET, False)]


def test_deteccion_fallida_sale_como_error_del_nas(tmp_path):
    flota, _ = montar(tmp_path, {"alfa": falsos.Mundo({DET: (0, "nada util\n", "")})})
    r = flota.por_nas("alfa", lambda nas: flota.perfil(nas).sistema)
    assert r[0]["ok"] is False and "identificar" in r[0]["error"]


def test_host_cambiado_sale_como_error_del_nas(tmp_path):
    flota, _ = montar(tmp_path, {"alfa": falsos.Mundo(host_cambiado=True)})
    r = flota.por_nas("alfa", lambda nas: flota.lanzar(nas, ENLACES))
    assert r[0]["ok"] is False and "clave de host" in r[0]["error"]


def test_tras_un_tiempo_agotado_la_siguiente_consulta_abre_una_conexion_nueva(tmp_path):
    # no se sabe como queda una sesion con una orden a medias: no se vuelve a esperar sobre ella
    mundo = falsos.Mundo({"lenta": falsos.CUELGA, "ip -br link": "x\n"})
    flota, nas = montar(tmp_path, {"alfa": mundo})
    with pytest.raises(ejecutor.ErrorComando):
        flota.lanzar(nas["alfa"], Comando("lenta", "lenta", timeout=1))
    assert flota.lanzar(nas["alfa"], ENLACES) == "x\n"
    assert mundo.conexiones == 2
