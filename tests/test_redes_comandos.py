# -*- coding: utf-8 -*-
"""Coherencia de los comandos de la pata de redes: todos son de solo lectura."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pruebas"))
import guardia  # noqa: E402  (la guardia de solo lectura del laboratorio)

from qnap_tools.comandos import Comando  # noqa: E402
from qnap_tools.redes import comandos as rc  # noqa: E402

EJEMPLOS = {"interfaz": "eth0", "destino": "192.0.2.1"}
SECRETOS = re.compile(
    r"shadow|smbpasswd|ssh_host|\.pem|id_rsa|id_ed25519|authorized_keys|qvpn/|openvpn|"
    r"ipsec\.(conf|secrets)|wg[0-9]*\.conf|privatekey|nm\.conf")


def todos():
    return {nombre: valor for nombre, valor in vars(rc).items() if isinstance(valor, Comando)}


def test_hay_un_comando_por_cada_orden_prevista():
    assert set(todos()) >= {
        "ENLACES", "DIRECCIONES", "SYS_RED", "TRAFICO", "ETHTOOL",
        "ETHTOOL_DRIVER", "ETHTOOL_STATS", "BONDING", "VLAN", "PUENTES", "PUENTES_MAC", "RUTAS",
        "REGLAS", "VECINOS", "RUTAS_ESTATICAS", "DNS", "DHCP_SERVIDOR", "DHCP_LEASES",
        "ESCUCHA_TCP", "ESCUCHA_UDP", "SERVICIOS", "IPTABLES", "BLOQUEO_IP", "DDNS", "UPNP",
        "VPN_PRESENCIA", "PING", "TRACEROUTE", "NSLOOKUP"}


def test_los_identificadores_son_unicos():
    ids = [c.id for c in todos().values()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_cada_comando_pasa_la_guardia_de_solo_lectura_del_laboratorio(nombre):
    comando = todos()[nombre]
    texto = comando.render({p: EJEMPLOS[tipo] for p, tipo in comando.params.items()})
    guardia.comprobar(texto)          # lanza guardia.Bloqueado si algo no esta permitido


def test_la_guardia_del_laboratorio_sigue_bloqueando_escrituras():
    # si esto dejara de fallar, la prueba anterior no demostraria nada
    for texto in ("rm -rf /tmp/x", "ip link set eth0 down", "echo x ${f##*/}; reboot"):
        with pytest.raises(guardia.Bloqueado):
            guardia.comprobar(texto)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ningun_comando_toca_rutas_con_secretos(nombre):
    assert not SECRETOS.search(todos()[nombre].plantilla)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ulinux_conf_solo_se_lee_campo_a_campo_con_getcfg(nombre):
    plantilla = todos()[nombre].plantilla
    resto = re.sub(r"getcfg (?:'[^']*'|\"[^\"]*\"|\S+) (?:'[^']*'|\"[^\"]*\"|\S+) -f /etc/config/uLinux\.conf",
                   "", plantilla)
    assert "uLinux.conf" not in resto


def test_solo_estos_comandos_van_con_sudo():
    assert {n for n, c in todos().items() if c.sudo} == {
        "ESCUCHA_TCP", "ESCUCHA_UDP", "IPTABLES", "VLAN", "PING", "TRACEROUTE"}


def test_las_funciones_sin_validar_con_datos_reales_estan_marcadas():
    assert {n for n, c in todos().items() if c.no_probado} == {"BONDING", "VLAN", "QUFIREWALL"}


def test_vlan_distingue_que_no_haya_de_que_no_se_pueda_leer():
    # sin el fichero (modulo sin cargar) la orden termina bien y vacia; un fallo al leerlo es un error
    assert rc.VLAN.plantilla.startswith("[ ! -e /proc/net/vlan/config ] || ")
    assert rc.VLAN.valida(0, "") is None
    assert rc.VLAN.valida(1, "") is not None


def test_rutas_estaticas_distingue_que_no_haya_de_que_no_se_pueda_leer():
    assert rc.RUTAS_ESTATICAS.plantilla == (
        "[ ! -e /etc/config/staticroute.conf ] || cat /etc/config/staticroute.conf")
    assert rc.RUTAS_ESTATICAS.valida(0, "") is None
    assert rc.RUTAS_ESTATICAS.valida(1, "") is not None


SH = shutil.which("sh")


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
@pytest.mark.parametrize("hay_resolv, hay_dnsmasq", [(True, True), (True, False), (False, True), (False, False)])
def test_la_orden_de_dns_falla_si_no_puede_leer_resolv_conf(tmp_path, hay_resolv, hay_dnsmasq):
    if hay_resolv:
        (tmp_path / "resolv.conf").write_text("nameserver 192.0.2.1\n", encoding="utf-8")
    if hay_dnsmasq:
        (tmp_path / "resolv.dnsmasq").write_text("nameserver 192.0.2.2@eth0\n", encoding="utf-8")
    orden = rc.DNS.plantilla.replace("/etc/resolv.", "resolv.")
    assert "/etc/" not in orden
    r = subprocess.run([SH, "-c", orden], cwd=tmp_path, capture_output=True, encoding="utf-8")
    error = rc.DNS.valida(r.returncode, r.stdout)
    # el fichero de servidores superiores es opcional; resolv.conf, no
    assert (error is None) == hay_resolv
    if hay_resolv:
        assert "==superiores" in r.stdout and "==resolv\nnameserver 192.0.2.1" in r.stdout
        assert ("192.0.2.2@eth0" in r.stdout) == hay_dnsmasq


def test_las_concesiones_llevan_la_cuenta_de_lineas_para_saber_si_llegan_recortadas():
    assert "echo ==lineas $(grep -c" in rc.DHCP_LEASES.plantilla
    assert "tail -n %d" % rc.LINEAS_LEASES in rc.DHCP_LEASES.plantilla and rc.LINEAS_LEASES >= 1000


def test_la_presencia_de_vpn_solo_pregunta_si_el_servicio_esta_activo():
    assert rc.VPN_PRESENCIA.plantilla == "echo activo=$(getcfg QVPN Enable -f /etc/config/qpkg.conf)"


def test_los_diagnosticos_tienen_su_propio_tiempo_maximo():
    assert rc.PING.timeout == 15 and rc.TRACEROUTE.timeout == 40


def test_todo_vale_para_los_dos_sistemas():
    assert {c.sistema for c in todos().values()} == {"ambos"}
