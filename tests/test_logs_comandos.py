# -*- coding: utf-8 -*-
"""Coherencia de las ordenes de la pata de registros: todas son de solo lectura."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pruebas"))
import guardia  # noqa: E402  (la guardia de solo lectura del laboratorio)

from qnap_tools.comandos import Comando, ParametroInvalido  # noqa: E402
from qnap_tools.logs import comandos as lc  # noqa: E402

EJEMPLOS = {"entero": "20", "fecha": "2026-10-01", "palabra": "Virtualization Station", "nombre": "web-1",
            "nivel": "3", "pid": "4242"}
DE_REGISTROS = {"EVT_LISTA", "EVT_PALABRA", "EVT_RECUENTO", "CONN_LISTA", "CONN_EXTREMOS", "NOTICE_LISTA",
                "NOTICE_RESUMEN"}
UTILIDADES = ("log_tool", "conn_log_tool", "notice_log_tool")
# las opciones de consulta de las utilidades (las demas crean, borran o cambian la base)
OPCIONES_DE_CONSULTA = {"-q", "-v", "-e", "-d", "-g", "-k", "-s", "-l", "-o"}
SECRETOS = re.compile(r"shadow|smbpasswd|ssh_host|id_rsa|id_ed25519|authorized_keys|qvpn/|ipsec|passwd|"
                      r"\[Alert\]|'Alert'.*(Mail|SMTP|Pass|SMS)|smtp|\.credentials|qulogdb|ncdb", re.I)


DE_SISTEMA = {"KMSG_NIVELES", "KMSG_LINEAS", "DMESG", "SENSORES", "CHASIS", "FUENTES", "SAI", "CARGA",
              "FIRMWARE", "FIRMWARE_AUTO", "APPS", "MOTORES", "VOLCADOS", "ALERTAS", "SYSLOG",
              "PROCESOS_LISTA", "PROCESOS_DETALLE"}


def todos():
    return {nombre: valor for nombre, valor in vars(lc).items() if isinstance(valor, Comando)}


def de_registros():
    return {n: c for n, c in todos().items() if n in DE_REGISTROS}


def test_estan_las_ordenes_de_los_registros():
    assert DE_REGISTROS <= set(todos())


def test_estan_las_ordenes_de_kernel_hardware_sistema_y_alertas():
    assert DE_SISTEMA <= set(todos())


def test_los_identificadores_son_unicos():
    ids = [c.id for c in todos().values()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_cada_orden_pasa_la_guardia_de_solo_lectura_del_laboratorio(nombre):
    comando = todos()[nombre]
    guardia.comprobar(comando.render({p: EJEMPLOS[t] for p, t in comando.params.items()}))


def test_la_guardia_del_laboratorio_sigue_bloqueando_lo_que_cambia_un_registro():
    for texto in ("log_tool -c", "log_tool -r", "log_tool -f", "log_tool -a x", "log_tool -q -v -y 1",
                  "conn_log_tool -f", "notice_log_tool -R 1", "conn_log_tool -q -v -b 10"):
        with pytest.raises(guardia.Bloqueado):
            guardia.comprobar(texto)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ninguna_orden_toca_secretos(nombre):
    assert not SECRETOS.search(todos()[nombre].plantilla)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_las_utilidades_de_registro_van_siempre_con_q_v_sin_sudo_y_solo_con_opciones_de_consulta(nombre):
    c = todos()[nombre]
    plantilla = c.plantilla
    for utilidad in UTILIDADES:
        usos = re.findall(r"(?<![a-z_])%s\b([^;|)]*)" % utilidad, plantilla)
        for opciones in usos:
            assert opciones.startswith(" -q -v"), (nombre, utilidad, opciones)
            assert set(re.findall(r"(?<![A-Za-z0-9])-[A-Za-z-]+", opciones)) <= OPCIONES_DE_CONSULTA, opciones
        if usos:
            # con sudo, log_tool altera la base de eventos (medido en los dos sistemas)
            assert c.sudo is False, nombre


@pytest.mark.parametrize("nombre", sorted(de_registros()))
def test_toda_lista_va_acotada_en_filas(nombre):
    plantilla = de_registros()[nombre].plantilla
    for orden in re.findall(r"(?:%s) -q -v[^;|)]*-s 1[23][^;|)]*" % "|".join(UTILIDADES), plantilla):
        assert re.search(r"-l 0 -o (\{limite\}|1(?![0-9]))", orden), orden


def test_los_recuentos_cuentan_tambien_la_linea_final_de_la_utilidad():
    # sin la linea final no se sabe si la utilidad respondio: un recuento 0 seria mentira
    for c in (lc.EVT_RECUENTO, lc.NOTICE_RESUMEN):
        assert "Done" in c.plantilla


@pytest.mark.parametrize("comando, malos", [
    ("EVT_LISTA", {"gravedad": ["x", "-1", "1; reboot"], "desde": ["ayer", "2026-10-01; x"],
                   "hasta": ["", "2026/10/01"], "limite": ["10 20", "-5"]}),
    ("EVT_PALABRA", {"texto": ["it's", "a;b", "-k", "", "' OR 1=1 --", "a" * 41]}),
    ("CONN_LISTA", {"tipo": ["x"], "limite": ["1e3"]}),
])
def test_los_parametros_se_validan_antes_de_componer_la_orden(comando, malos):
    c = todos()[comando]
    buenos = {p: EJEMPLOS[t] for p, t in c.params.items()}
    for parametro, valores in malos.items():
        for valor in valores:
            with pytest.raises(ParametroInvalido):
                c.render(dict(buenos, **{parametro: valor}))


def test_las_fechas_en_segundos_no_dependen_del_desfase_horario_de_hoy():
    # un desfase de hoy no vale para un aviso de antes del cambio de hora: se dan en UTC
    for c in (lc.NOTICE_LISTA, lc.VOLCADOS):
        assert "date" not in c.plantilla and "==zona" not in c.plantilla, c.id


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_getsysinfo_solo_va_en_ordenes_con_sudo_y_validador(nombre):
    # sin root devuelve "0 C" o "--" con codigo 0: sin sudo y sin validador mentiria
    c = todos()[nombre]
    if "getsysinfo" in c.plantilla:
        assert c.sudo is True and c.valida is not None, nombre


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ninguna_orden_lee_ulinux_conf_entero_ni_los_destinatarios_de_alertas(nombre):
    plantilla = todos()[nombre].plantilla
    # uLinux.conf solo se consulta clave a clave con getcfg (el de fabrica, con -f)
    for m in re.finditer(r"\S*uLinux\.conf", plantilla):
        antes = plantilla[:m.start()]
        assert antes.rstrip().endswith("-f") and "getcfg" in antes.rsplit(";", 1)[-1], (nombre, plantilla)
    # de la seccion de alertas solo se lee el nivel: el resto son destinatarios y credenciales
    for clave in re.findall(r"getcfg Alert ('[^']*'|\S+)", plantilla):
        assert clave == "'Alert Level'", (nombre, clave)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_hal_app_solo_enumera_y_ninguna_orden_pide_ayuda(nombre):
    plantilla = todos()[nombre].plantilla
    for uso in re.findall(r"hal_app([^;|)]*)", plantilla):
        assert uso.strip() == "--se_enum", (nombre, uso)
    # "--help" no es inocuo en un QNAP: hay utilidades que ejecutan su accion
    assert "--help" not in plantilla and " -h " not in plantilla + " "


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_todo_recorte_con_tail_lleva_antes_su_cuenta(nombre):
    # "tail -n 1" lee la ultima linea de un fichero (como acaba un volcado): no recorta una lista
    plantilla = todos()[nombre].plantilla.replace("tail -n 1 ", "")
    if "tail" in plantilla:
        assert "==lineas" in plantilla.split("tail")[0], nombre


@pytest.mark.parametrize("comando, malos", [
    ("KMSG_LINEAS", {"nivel": ["8", "-1", "12", "3; reboot", ""], "lineas": ["x", "10 20"]}),
    ("DMESG", {"lineas": ["-5", "1e3"]}),
])
def test_los_parametros_del_kernel_se_validan_antes_de_componer_la_orden(comando, malos):
    c = todos()[comando]
    buenos = {p: EJEMPLOS[t] for p, t in c.params.items()}
    for parametro, valores in malos.items():
        for valor in valores:
            with pytest.raises(ParametroInvalido):
                c.render(dict(buenos, **{parametro: valor}))


def test_el_nivel_del_kernel_se_busca_sin_el_signo_mayor():
    # una plantilla no puede llevar ">": el patron usa un punto en su lugar
    assert lc.KMSG_LINEAS.render({"nivel": "3", "lineas": "5"}).count("' <[0-3]. '") == 2


def test_la_lista_de_procesos_no_lleva_sudo_ni_parametros_y_el_detalle_si_lleva_sudo_y_un_pid():
    assert lc.PROCESOS_LISTA.sudo is False and lc.PROCESOS_LISTA.params == {}
    assert lc.PROCESOS_LISTA.plantilla.startswith(lc.PS_COLUMNAS)
    assert lc.PROCESOS_DETALLE.sudo is True and lc.PROCESOS_DETALLE.params == {"pid": "pid"}


def test_el_detalle_de_un_proceso_no_lee_las_variables_de_entorno_ni_escribe():
    # environ lleva claves; la orden se lee con tr (sin redirigir con ">") y acotada
    plantilla = lc.PROCESOS_DETALLE.plantilla
    assert "environ" not in plantilla and "maps" not in plantilla and "mem" not in plantilla.replace("VmRSS", "")
    assert ">" not in plantilla.replace("2>&1", "") and "head -c 2000" in plantilla
    assert plantilla.count("/proc/{pid}") == plantilla.count("{pid}")      # nada fuera del proceso pedido


@pytest.mark.parametrize("valor", ["0", "-1", "4194305", "1;reboot", "$(id)", "1 2", "", "abc", "1e3", "../1"])
def test_el_pid_se_valida_antes_de_componer_la_orden(valor):
    with pytest.raises(ParametroInvalido):
        lc.PROCESOS_DETALLE.render({"pid": valor})


def test_el_pid_viaja_sin_comillas_porque_son_cifras():
    orden = lc.PROCESOS_DETALLE.render({"pid": "4242"})
    assert "/proc/4242/status" in orden and "/proc/4242/fd" in orden and "{pid}" not in orden
