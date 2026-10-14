# -*- coding: utf-8 -*-
"""Las 9 herramientas de qnap-redes sobre NAS simulados que responden con salidas reales."""
import asyncio
import re
from pathlib import Path

import paramiko

import falsos
from qnap_tools import inventario as inv
from qnap_tools import servidor
from qnap_tools.comandos import Comando
from qnap_tools.inventario import Nas
from qnap_tools.redes import comandos as rc
from qnap_tools.redes import servidor as redes_srv
from qnap_tools.transporte import Conexion

DATOS = Path(__file__).parent / "datos" / "redes"
# los valores con los que se capturaron las ordenes con parametro
PARAMETROS = {
    "ETHTOOL": {"iface": "eth0"}, "ETHTOOL_DRIVER": {"iface": "eth0"}, "ETHTOOL_STATS": {"iface": "eth0"},
    "PUENTES_MAC": {"iface": "qvs2"}, "PING": {"destino": "192.0.2.36"},
    "TRACEROUTE": {"destino": "192.0.2.38"}, "NSLOOKUP": {"destino": "www.qnap.com"}}
ENTORNO = {"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto"}


def dato(nombre):
    return (DATOS / (nombre + ".txt")).read_text(encoding="utf-8")


def nas_hero(**extra):
    """Un QuTS hero simulado: a cada orden de redes responde con su salida real."""
    respuestas = {}
    for nombre, comando in vars(rc).items():
        if isinstance(comando, Comando):
            respuestas[comando.render(PARAMETROS.get(nombre))] = dato(comando.id + "_hero")
    return falsos.Mundo(respuestas, **extra)


def montar(tmp_path, mundos, entorno=None):
    """Herramientas de redes sobre NAS simulados: un Mundo por nombre de NAS."""
    entorno = dict(ENTORNO if entorno is None else entorno, QNAP_TOOLS_DATA=str(tmp_path))

    def fabrica(nas, cfg):
        return Conexion(nas, cfg, fabrica=mundos[nas.nombre].cliente)
    ctx = servidor.Contexto(entorno, fabrica_conexion=fabrica)
    nas = {n: Nas(n, "192.0.2.%d" % (i + 10)) for i, n in enumerate(sorted(mundos))}
    inv.guardar(Path(tmp_path) / "inventario.toml", nas)
    return redes_srv.Herramientas(ctx)


def uno_solo(tmp_path, mundo=None):
    mundo = mundo or nas_hero()
    return montar(tmp_path, {"casa": mundo}), mundo


def por(lista, clave, valor):
    (uno,) = [x for x in lista if x[clave] == valor]
    return uno


def con_sudo(mundo):
    """{orden: si fue con sudo} de lo que ha recibido el NAS simulado."""
    return dict(mundo.ordenes)


# --- red_resumen -----------------------------------------------------------------------------

def test_resumen_de_todos_da_una_entrada_por_nas(tmp_path):
    h = montar(tmp_path, {"casa": nas_hero(), "oficina": nas_hero()})
    r = h.red_resumen("todos")
    assert [(e["nas"], e["ok"]) for e in r] == [("casa", True), ("oficina", True)]
    assert por(r[1]["datos"]["interfaces"]["filas"], "interfaz", "eth0")["ipv4"] == ["192.0.2.16/24"]


def test_resumen_da_las_interfaces_activas_la_puerta_de_enlace_y_el_dns(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_resumen("casa")
    d = r["datos"]
    # con direccion y sin estar caidas: las demas (puentes de contenedores sin uso, lo) no salen
    assert [i["interfaz"] for i in d["interfaces"]["filas"]] == ["eth0", "qvs2"]
    assert d["interfaces"]["filas"][0] == {
        "interfaz": "eth0", "tipo": "fisica", "estado": "up", "ipv4": ["192.0.2.16/24"],
        "ipv6": ["fe80::200:5eff:fe00:5301/64"], "mac": "00:11:22:33:44:02", "velocidad_mbps": 1000,
        "mtu": 1500}
    assert d["interfaces"]["filas"][1]["tipo"] == "puente"
    assert d["total_interfaces"] == 18
    assert d["puerta_enlace"] == [{"via": "192.0.2.36", "interfaz": "eth0", "metrica": 100}]
    assert d["dns"]["servidores"] == ["127.0.1.1"]
    assert d["dns"]["superiores"][0] == {"servidor": "192.0.2.20", "interfaz": "eth0"}


def test_resumen_incluye_un_puerto_fisico_con_enlace_aunque_no_tenga_direccion(tmp_path):
    # como en un QTS, donde la direccion la tiene el puente y no el puerto
    mundo = nas_hero()
    mundo.respuestas["ip -br addr"] = dato("direcciones_hero").replace(
        "192.0.2.16/24 fe80::200:5eff:fe00:5301/64", "")
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_resumen("casa")
    eth0 = por(r["datos"]["interfaces"]["filas"], "interfaz", "eth0")
    assert eth0["ipv4"] == [] and eth0["velocidad_mbps"] == 1000


# --- red_interfaces ---------------------------------------------------------------------------

def test_interfaces_da_estado_contadores_y_caudal_de_todas(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_interfaces("casa")
    d = r["datos"]
    assert d["interfaces"]["total"] == 18 and d["interfaces"]["truncado"] is False
    assert por(d["interfaces"]["filas"], "interfaz", "eth0") == {
        "interfaz": "eth0", "tipo": "fisica", "estado": "up", "mac": "00:11:22:33:44:02",
        "velocidad_mbps": 1000, "duplex": "full", "mtu": 1500, "portadora": True,
        "rx_bytes": 28969007, "rx_paquetes": 175819, "rx_errores": 0, "rx_descartes": 0,
        "tx_bytes": 493657642, "tx_paquetes": 401912, "tx_errores": 0, "tx_descartes": 0,
        "colisiones": 0, "rx_bps": 184, "tx_bps": 10920}
    assert por(d["interfaces"]["filas"], "interfaz", "bond0")["tipo"] == "agregacion"
    assert por(d["interfaces"]["filas"], "interfaz", "vnet0")["tipo"] == "virtual"


def test_interfaces_marca_agregaciones_y_vlan_como_no_probadas(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_interfaces("casa")
    d = r["datos"]
    assert d["agregaciones"]["no_probado"] is True
    assert [b["interfaz"] for b in d["agregaciones"]["filas"]] == ["bond0", "bond1", "bond2", "bond3"]
    assert d["vlan"] == {"no_probado": True, "filas": []}


def test_interfaces_sin_sudo_da_el_error_en_el_bloque_de_vlan_y_no_pierde_lo_demas(tmp_path):
    mundo = nas_hero()
    mundo.respuestas[rc.VLAN.plantilla] = (1, "", "cat: /proc/net/vlan/config: Permission denied\n")
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_interfaces("casa")
    assert r["ok"] is True and r["datos"]["interfaces"]["total"] == 18
    assert r["datos"]["vlan"]["no_probado"] is True and "Permission denied" in r["datos"]["vlan"]["error"]
    assert "filas" not in r["datos"]["vlan"]


def test_interfaces_si_sudo_no_acepta_la_contrasena_solo_falla_el_bloque_que_lo_necesita(tmp_path):
    mundo = nas_hero()
    mundo.respuestas[rc.VLAN.plantilla] = (1, "", "Sorry, try again.\nsudo: 1 incorrect password attempt\n")
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_interfaces("casa")
    assert r["ok"] is True and r["datos"]["interfaces"]["total"] == 18
    assert "sudo" in r["datos"]["vlan"]["error"] and r["datos"]["vlan"]["no_probado"] is True


def test_interfaces_de_una_sola_da_enlace_controlador_y_errores(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_interfaces("casa", interfaz="eth0")
    d = r["datos"]
    assert d["interfaz"]["interfaz"] == "eth0" and d["interfaz"]["rx_bps"] == 184
    assert d["interfaz"]["marcas"] == ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"]
    assert d["interfaz"]["par"] is None
    assert d["enlace"]["velocidad_mbps"] == 1000 and d["enlace"]["velocidad_maxima_mbps"] == 2500
    assert d["controlador"] == {"driver": "r8125", "version": "9.013.02-NAPI-RSS", "firmware": None,
                                "bus": "0000:0c:00.0"}
    assert d["errores"] == {"disponible": True, "contadores": 39, "errores": {"rx_mac_missed": 817}}
    assert con_sudo(mundo)["ethtool eth0"] is False


def test_interfaces_rechaza_un_nombre_con_una_orden_dentro_sin_tocar_el_nas(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_interfaces("casa", interfaz="eth0; reboot")
    assert r["ok"] is False and "interfaz" in r["error"] and "datos" not in r
    assert mundo.ordenes == [] and mundo.conexiones == 0


def test_interfaces_avisa_de_una_interfaz_que_no_existe_sin_lanzar_ethtool(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_interfaces("casa", interfaz="eth9")
    assert r["ok"] is False and "eth9" in r["error"] and "eth0" in r["error"]
    assert not [o for o, _ in mundo.ordenes if o.startswith("ethtool")]


def test_interfaces_de_una_virtual_no_falla_por_no_tener_controlador(tmp_path):
    mundo = nas_hero()
    mundo.respuestas.update({
        "ethtool qvs2": "Settings for qvs2:\n\tLink detected: yes\n",
        "ethtool -i qvs2": (71, "", "Cannot get driver information: Operation not supported\n"),
        "ethtool -S qvs2": (94, "", "no stats available\n")})
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_interfaces("casa", interfaz="qvs2")
    assert r["ok"] is True
    d = r["datos"]
    assert d["enlace"]["enlace"] is True and d["enlace"]["velocidad_mbps"] is None
    assert "Operation not supported" in d["controlador"]["error"]
    assert d["errores"] == {"disponible": False, "contadores": 0, "errores": {}}


# --- red_conmutadores ---------------------------------------------------------------------------

def test_conmutadores_da_cada_puente_con_sus_puertos_y_direcciones(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_conmutadores("casa")
    puentes = r["datos"]["puentes"]
    assert puentes["total"] == 6
    assert por(puentes["filas"], "puente", "qvs2") == {
        "puente": "qvs2", "id": "8000.00112233440d", "stp": True, "interfaces": ["vnet0", "vnet1"],
        "estado": "UP", "ipv4": ["192.0.2.19/24"],
        "mac_aprendidas": {"total": 2, "truncado": False, "filas": [
            {"puerto": 1, "mac": "00:11:22:33:44:10", "antiguedad_s": 0.49},
            {"puerto": 2, "mac": "00:11:22:33:44:11", "antiguedad_s": 0.24}]},
        "mac_locales": 2}


def test_conmutadores_no_pide_las_mac_de_un_puente_sin_puertos(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_conmutadores("casa")
    docker0 = por(r["datos"]["puentes"]["filas"], "puente", "docker0")
    assert docker0["interfaces"] == [] and docker0["mac_aprendidas"] is None and docker0["mac_locales"] is None
    assert [o for o, _ in mundo.ordenes if o.startswith("brctl showmacs")] == ["brctl showmacs qvs2"]


def test_conmutadores_con_un_puente_de_nombre_no_admitido_lo_dice_en_ese_puente(tmp_path):
    mundo = nas_hero()
    mundo.respuestas["brctl show"] = dato("puentes_hero") + "br+raro\t\t8000.001122334455\tno\t\tveth1\n"
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_conmutadores("casa")
    assert r["ok"] is True
    filas = r["datos"]["puentes"]["filas"]
    assert "error" in por(filas, "puente", "br+raro")["mac_aprendidas"]
    assert por(filas, "puente", "qvs2")["mac_aprendidas"]["total"] == 2


def test_conmutadores_si_falla_la_consulta_de_un_puente_lo_dice_en_ese_puente(tmp_path):
    # un puente de contenedores puede desaparecer entre una consulta y la siguiente
    mundo = nas_hero()
    mundo.respuestas["brctl showmacs qvs2"] = (1, "", "read of forward table failed: No such device\n")
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_conmutadores("casa")
    assert r["ok"] is True
    qvs2 = por(r["datos"]["puentes"]["filas"], "puente", "qvs2")
    assert "No such device" in qvs2["mac_aprendidas"]["error"] and qvs2["mac_locales"] is None


# --- red_rutas ------------------------------------------------------------------------------------

def test_rutas_da_rutas_reglas_vecinos_y_estaticas(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_rutas("casa")
    d = r["datos"]
    assert d["rutas"]["total"] == 9 and d["rutas"]["filas"][0]["via"] == "192.0.2.36"
    assert d["reglas"]["total"] == 26 and d["reglas"]["filas"][0]["tabla"] == "local"
    assert d["vecinos"]["total"] == 10
    assert d["estaticas"] == {"no_probado": True, "filas": []}


def test_una_orden_que_no_devuelve_nada_es_un_error_y_no_datos_vacios(tmp_path):
    mundo = nas_hero()
    mundo.respuestas["ip route"] = ""
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_rutas("casa")
    assert r["ok"] is False and "datos" not in r
    assert "rutas" in r["error"] and "no devolvio nada" in r["error"]


def test_una_salida_que_no_se_reconoce_es_un_error_que_nombra_la_consulta(tmp_path):
    mundo = nas_hero()
    mundo.respuestas["brctl show"] = "algo que no es la tabla de puentes\n"
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_conmutadores("casa")
    assert r["ok"] is False and "datos" not in r
    assert "casa" in r["error"] and "puentes" in r["error"] and "no reconocida" in r["error"]


# --- red_servicios ---------------------------------------------------------------------------------

def test_servicios_pide_los_puertos_con_sudo_y_la_configuracion_sin_el(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_servicios("casa")
    assert r["ok"] is True
    sudo = con_sudo(mundo)
    assert sudo["netstat -tlnp"] is True and sudo["netstat -ulnp"] is True
    assert sudo[rc.SERVICIOS.plantilla] is False


def test_servicios_con_la_configuracion_ilegible_es_un_error(tmp_path):
    mundo = nas_hero()
    mundo.respuestas[rc.SERVICIOS.plantilla] = re.sub(r" = .*", " =", dato("servicios_hero"))
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_servicios("casa")
    assert r["ok"] is False and "servicios" in r["error"] and "datos" not in r


def test_servicios_da_la_configuracion_y_los_puertos_agrupados(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_servicios("casa")
    d = r["datos"]
    assert d["configurados"]["ssh"] == {"activo": True, "puerto": 22}
    escucha = d["en_escucha"]["filas"]
    assert [e for e in escucha if e["puerto"] == 22] == [
        {"protocolo": "tcp", "puerto": 22, "proceso": "sshd", "pids": [16436],
         "direcciones": ["0.0.0.0", "::"], "alcance": "todas"}]
    assert por(escucha, "puerto", 3311) == {
        "protocolo": "tcp", "puerto": 3311, "proceso": "mariadbd", "pids": [18446],
        "direcciones": ["127.0.0.1"], "alcance": "local"}
    # cuatro procesos dhcpd (uno por red) en el mismo puerto: una sola fila
    assert por([e for e in escucha if e["protocolo"] == "udp"], "puerto", 67)["pids"] == [
        13447, 13449, 13451, 13453]
    tftp = por([e for e in escucha if e["protocolo"] == "udp"], "puerto", 69)
    assert tftp["alcance"] == "concretas" and len(tftp["direcciones"]) == 7
    assert d["en_escucha"]["total"] == len(escucha) < 149      # 149 lineas de netstat


# --- red_dhcp_dns ----------------------------------------------------------------------------------

def test_dhcp_dns(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_dhcp_dns("casa")
    d = r["datos"]
    assert d["dns"]["servidores"] == ["127.0.1.1"]
    assert [a["interfaz"] for a in d["dhcp_servidor"]] == ["docker0", "lxcbr0", "lxdbr0", "qvs2"]
    assert d["dhcp_concesiones"]["total"] == 1 and d["dhcp_concesiones"]["filas"][0]["ip"] == "192.0.2.1"
    assert d["dhcp_concesiones"]["truncado"] is False and "ficheros_recortados" not in d["dhcp_concesiones"]


def test_dhcp_dns_avisa_si_las_concesiones_llegan_recortadas(tmp_path):
    mundo = nas_hero()
    mundo.respuestas[rc.DHCP_LEASES.plantilla] = dato("dhcp_leases_hero").replace(
        "==lineas 11", "==lineas %d" % (rc.LINEAS_LEASES + 50))
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_dhcp_dns("casa")
    concesiones = r["datos"]["dhcp_concesiones"]
    assert concesiones["truncado"] is True and concesiones["ficheros_recortados"] == ["qvs2"]


def test_dhcp_dns_de_un_nas_que_no_sirve_dhcp(tmp_path):
    mundo = nas_hero()
    mundo.respuestas[rc.DHCP_SERVIDOR.plantilla] = ""
    mundo.respuestas[rc.DHCP_LEASES.plantilla] = ""
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_dhcp_dns("casa")
    assert r["ok"] is True
    assert r["datos"]["dhcp_servidor"] is None and r["datos"]["dhcp_concesiones"] is None
    assert r["datos"]["dns"]["servidores"] == ["127.0.1.1"]


# --- red_cortafuegos ---------------------------------------------------------------------------------

def test_cortafuegos_resume_iptables_y_el_bloqueo_por_ip(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_cortafuegos("casa")
    d = r["datos"]
    assert [(t["tabla"], t["reglas"], len(t["cadenas"])) for t in d["iptables"]] == [
        ("filter", 48, 12), ("nat", 18, 8), ("mangle", 8, 10)]
    assert d["bloqueo_ip"]["activo"] is True and d["bloqueo_ip"]["servicios"]["ssh"] is False
    assert con_sudo(mundo)["iptables-save"] is True


def test_cortafuegos_si_no_se_puede_leer_el_bloqueo_por_ip_lo_dice_en_su_bloque(tmp_path):
    mundo = nas_hero()
    mundo.respuestas[rc.BLOQUEO_IP.plantilla] = re.sub(r" = .*", " =", dato("bloqueo_ip_hero"))
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_cortafuegos("casa")
    assert r["ok"] is True and len(r["datos"]["iptables"]) == 3
    assert "error" in r["datos"]["bloqueo_ip"] and "activo" not in r["datos"]["bloqueo_ip"]


def test_cortafuegos_marca_qufirewall_como_no_probado(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_cortafuegos("casa")
    assert r["datos"]["qufirewall"] == {"no_probado": True, "activo": None}


# --- red_acceso_remoto ---------------------------------------------------------------------------------

def test_acceso_remoto_da_ddns_upnp_y_presencia_de_vpn(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_acceso_remoto("casa")
    d = r["datos"]
    assert d["ddns"] == {
        "myqnapcloud": {"activo": True, "nombre": "nas-ejemplo", "dominio": "myqnapcloud.com"},
        "proveedores_activos": [{"proveedor": "myQNAPcloud", "nombre": "nas-ejemplo.myqnapcloud.com"}],
        "proveedores_disponibles": 15}
    assert d["upnp"] == {"activo": False}
    assert d["vpn"] == {"qvpn_activo": None, "tuneles": []}
    assert not any(sudo for _, sudo in mundo.ordenes)


def test_acceso_remoto_saca_los_tuneles_de_las_interfaces_del_nas(tmp_path):
    # escrito a mano: ningun NAS de pruebas tenia tuneles. Un tapN es de una maquina virtual.
    mundo = nas_hero()
    mundo.respuestas["ip -br link"] = dato("enlaces_hero") + (
        "tun0             UNKNOWN        <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> \n"
        "wg0              UNKNOWN        <POINTOPOINT,NOARP,UP,LOWER_UP> \n"
        "tap0             UNKNOWN        00:11:22:33:44:99 <BROADCAST,MULTICAST,UP,LOWER_UP> \n")
    mundo.respuestas[rc.VPN_PRESENCIA.plantilla] = "activo=TRUE\n"
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_acceso_remoto("casa")
    assert r["datos"]["vpn"] == {"qvpn_activo": True, "tuneles": [
        {"interfaz": "tun0", "estado": "UNKNOWN"}, {"interfaz": "wg0", "estado": "UNKNOWN"}]}


def test_las_instrucciones_avisan_de_que_el_texto_del_nas_no_son_ordenes():
    assert "no son instrucciones" in redes_srv.INSTRUCCIONES


# --- red_diagnostico -------------------------------------------------------------------------------------

def test_diagnostico_ping_va_con_sudo(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_diagnostico("casa", "192.0.2.36")
    assert r["ok"] is True
    assert r["datos"] == {"prueba": "ping", "destino": "192.0.2.36", "enviados": 3, "recibidos": 3,
                          "perdida_pct": 0, "min_ms": 0.504, "media_ms": 0.572, "max_ms": 0.672}
    assert mundo.ordenes == [("ping -c 3 -W 2 192.0.2.36", True)]


def test_diagnostico_traceroute(tmp_path):
    h, _ = uno_solo(tmp_path)
    (r,) = h.red_diagnostico("casa", "192.0.2.38", prueba="traceroute")
    assert r["datos"]["prueba"] == "traceroute" and r["datos"]["alcanzado"] is True
    assert len(r["datos"]["saltos"]) == 8


def test_diagnostico_dns_no_necesita_sudo(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_diagnostico("casa", "www.qnap.com", prueba="dns")
    assert r["datos"]["resuelto"] is True and len(r["datos"]["direcciones"]) == 4
    assert mundo.ordenes == [("nslookup www.qnap.com", False)]


def test_diagnostico_rechaza_una_prueba_desconocida_sin_tocar_el_nas(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_diagnostico("casa", "192.0.2.36", prueba="otra")
    assert r["ok"] is False and "ping" in r["error"] and "traceroute" in r["error"]
    assert mundo.ordenes == [] and mundo.conexiones == 0


def test_diagnostico_rechaza_un_destino_con_una_orden_dentro_sin_tocar_el_nas(tmp_path):
    h, mundo = uno_solo(tmp_path)
    for destino in ("192.0.2.36; reboot", "$(reboot)", "-f", "192.0.2.36 -s 65000", ""):
        (r,) = h.red_diagnostico("casa", destino)
        assert r["ok"] is False and "destino" in r["error"], destino
    assert mundo.ordenes == [] and mundo.conexiones == 0


def test_diagnostico_a_un_nombre_que_no_resuelve_da_el_motivo(tmp_path):
    mundo = nas_hero()
    mundo.respuestas["ping -c 3 -W 2 no-existe.test"] = (1, "", "ping: bad address 'no-existe.test'\n")
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_diagnostico("casa", "no-existe.test")
    assert r["ok"] is False and "bad address" in r["error"]


# --- lo comun a todas --------------------------------------------------------------------------------------

def test_un_nas_que_falla_no_tapa_a_los_demas(tmp_path):
    caido = nas_hero(error_conexion=paramiko.SSHException("Connection refused"))
    h = montar(tmp_path, {"casa": nas_hero(), "oficina": caido})
    r = h.red_rutas("todos")
    assert [(e["nas"], e["ok"]) for e in r] == [("casa", True), ("oficina", False)]
    assert "datos" not in r[1] and r[1]["error"]


def test_un_nas_que_no_esta_en_el_inventario_dice_cuales_hay(tmp_path):
    h, mundo = uno_solo(tmp_path)
    (r,) = h.red_resumen("otro")
    assert r["ok"] is False and "casa" in r["error"]
    assert mundo.conexiones == 0


def test_sin_credencial_la_herramienta_lo_dice(tmp_path):
    h = montar(tmp_path, {"casa": nas_hero()}, entorno={"QNAP_TOOLS_USER": "usuario"})
    (r,) = h.red_resumen("casa")
    assert r["ok"] is False and "contrasena" in r["error"].lower()


def test_la_contrasena_no_sale_en_un_error(tmp_path):
    mundo = nas_hero()
    mundo.respuestas["ip route"] = (1, "", "fallo raro con secreto dentro\n")
    h, _ = uno_solo(tmp_path, mundo)
    (r,) = h.red_rutas("casa")
    assert r["ok"] is False and "secreto" not in r["error"] and "***" in r["error"]


def test_todas_las_herramientas_funcionan_sobre_el_nas_simulado(tmp_path):
    h, mundo = uno_solo(tmp_path)
    llamadas = {
        "red_resumen": (), "red_interfaces": (), "red_conmutadores": (), "red_rutas": (),
        "red_servicios": (), "red_dhcp_dns": (), "red_cortafuegos": (), "red_acceso_remoto": (),
        "red_diagnostico": ("192.0.2.36",)}
    assert sorted(llamadas) == sorted(redes_srv.HERRAMIENTAS)
    for nombre, extra in llamadas.items():
        (r,) = getattr(h, nombre)("casa", *extra)
        assert r["ok"] is True, (nombre, r)
    assert mundo.conexiones == 1          # todas por la misma conexion


def test_el_servidor_solo_lanza_ordenes_definidas_como_comando(tmp_path):
    h, mundo = uno_solo(tmp_path)
    for nombre in redes_srv.HERRAMIENTAS:
        getattr(h, nombre)("casa", *(("192.0.2.36",) if nombre == "red_diagnostico" else ()))
    h.red_interfaces("casa", interfaz="eth0")
    definidas = {c.render(PARAMETROS.get(n)): c.sudo for n, c in vars(rc).items() if isinstance(c, Comando)}
    for orden, sudo in mundo.ordenes:
        assert orden in definidas and definidas[orden] is sudo, orden


def test_no_hay_ningun_comando_definido_que_no_use_alguna_herramienta(tmp_path):
    h, mundo = uno_solo(tmp_path)
    for nombre in redes_srv.HERRAMIENTAS:
        if nombre != "red_diagnostico":
            getattr(h, nombre)("casa")
    h.red_interfaces("casa", interfaz="eth0")
    for prueba, destino in (("ping", "192.0.2.36"), ("traceroute", "192.0.2.38"), ("dns", "www.qnap.com")):
        h.red_diagnostico("casa", destino, prueba=prueba)
    lanzadas = {orden for orden, _ in mundo.ordenes}
    sin_uso = [n for n, c in vars(rc).items()
               if isinstance(c, Comando) and c.render(PARAMETROS.get(n)) not in lanzadas]
    assert sin_uso == []


def test_el_servidor_registra_las_nueve_herramientas_con_descripcion(tmp_path):
    mcp = redes_srv.construir(dict(ENTORNO, QNAP_TOOLS_DATA=str(tmp_path)))
    herramientas = asyncio.run(mcp.list_tools())
    assert sorted(t.name for t in herramientas) == [
        "red_acceso_remoto", "red_conmutadores", "red_cortafuegos", "red_dhcp_dns", "red_diagnostico",
        "red_interfaces", "red_resumen", "red_rutas", "red_servicios"]
    assert all(t.description and len(t.description) > 40 for t in herramientas)
    assert all("nas" in t.inputSchema["required"] for t in herramientas)
    (diag,) = [t for t in herramientas if t.name == "red_diagnostico"]
    assert set(diag.inputSchema["properties"]) == {"nas", "destino", "prueba"}
    assert diag.inputSchema["required"] == ["nas", "destino"]


def test_el_servidor_arranca_aunque_falte_la_credencial():
    assert len(asyncio.run(redes_srv.construir({}).list_tools())) == 9
