# -*- coding: utf-8 -*-
import pytest

from qnap_tools import comandos
from qnap_tools.comandos import Comando, ParametroInvalido

IFACE = Comando("x", "ip -s link show {iface}", {"iface": "interfaz"})


# --- render -----------------------------------------------------------------

def test_render_sustituye_el_parametro():
    assert IFACE.render({"iface": "eth0"}) == "ip -s link show eth0"


@pytest.mark.parametrize("valor", [
    "eth0; reboot", "$(reboot)", "eth0 && x", "a'b", "a b", "", "x" * 300,
    "-s", "--help", "eth0\n", "eth0\nreboot", "`id`", "a|b", "a>b", "a\\b", 'a"b',
])
def test_render_rechaza_valores_peligrosos(valor):
    with pytest.raises(ParametroInvalido):
        IFACE.render({"iface": valor})


def test_render_falta_un_parametro():
    with pytest.raises(ParametroInvalido) as e:
        IFACE.render({})
    assert "iface" in str(e.value)


def test_render_sobra_un_parametro():
    with pytest.raises(ParametroInvalido) as e:
        IFACE.render({"iface": "eth0", "otro": "x"})
    assert "otro" in str(e.value)


def test_render_sin_parametros():
    c = Comando("y", "ip -br link")
    assert c.render() == "ip -br link"
    assert c.render({}) == "ip -br link"


def test_render_acepta_enteros():
    c = Comando("z", "getsysinfo hdtmp {bahia}", {"bahia": "bahia"})
    assert c.render({"bahia": 3}) == "getsysinfo hdtmp 3"


@pytest.mark.parametrize("valor", [True, 3.0, None, ["3"], b"3"])
def test_render_rechaza_tipos_que_no_son_texto_ni_entero(valor):
    c = Comando("z", "getsysinfo hdtmp {bahia}", {"bahia": "bahia"})
    with pytest.raises(ParametroInvalido):
        c.render({"bahia": valor})


def test_render_no_toca_las_llaves_propias_del_shell():
    texto = "for f in /sys/class/net/*; do echo ${f##*/}; done | awk '{print $1}'"
    assert Comando("a", texto).render() == texto


def test_render_repite_el_parametro_las_veces_que_aparezca():
    c = Comando("r", "echo {n}; cat /proc/{n}/stat", {"n": "entero"})
    assert c.render({"n": "12"}) == "echo 12; cat /proc/12/stat"


def test_el_error_nombra_el_parametro_y_el_tipo_esperado():
    with pytest.raises(ParametroInvalido) as e:
        IFACE.render({"iface": "eth0; reboot"})
    assert "iface" in str(e.value) and "interfaz" in str(e.value)


@pytest.mark.parametrize("tipo,valor", [
    ("interfaz", "eth0"), ("interfaz", "br-000000000003"), ("interfaz", "veth0000001@if271"),
    ("interfaz", "eth0.100"), ("interfaz", "qvs0"),
    ("destino", "192.0.2.1"), ("destino", "nas.example.org"), ("destino", "2001:db8::1"),
    ("entero", "50"), ("bahia", "12"),
    ("uuid", "12345678-9abc-4def-8123-456789abcdef"),
    ("nombre", "mi_contenedor-1.2"), ("fecha", "2026-10-13"),
    ("palabra", "firmware"), ("palabra", "ab"), ("palabra", "smb_2.1"), ("palabra", "copia:diaria/2"),
    ("palabra", "usuario@equipo"), ("palabra", "a" * 40),
    ("nivel", "0"), ("nivel", "7"),
    # pid de Linux: de 1 a 4194304 (pid_max de 64 bits)
    ("pid", "1"), ("pid", "4242"), ("pid", "999999"), ("pid", "1000000"), ("pid", "4194303"),
    ("pid", "4194304"),
    ("ruta", "/share/Vms/carpeta-1"), ("ruta", "/Vms"), ("ruta", "/"), ("ruta", "/a/..b/.c/d..e"),
    ("ruta", "/" + "a" * 511),
])
def test_valores_validos_por_tipo(tipo, valor):
    c = Comando("t", "echo {v}", {"v": tipo})
    assert c.render({"v": valor}) == "echo " + valor


@pytest.mark.parametrize("tipo,valor", [
    ("destino", "-c"), ("destino", "a b"), ("destino", "."),
    ("entero", "1234567"), ("entero", "-1"), ("entero", "1e3"),
    ("bahia", "1234"), ("bahia", "a"),
    ("uuid", "no-es-un-uuid"), ("uuid", "12345678-9abc-4def-8123-456789abcdefx"),
    ("nombre", "../x"), ("nombre", "-rf"), ("nombre", "a/b"),
    ("fecha", "hoy"), ("fecha", "2026-10-13 10:00"),
    # texto de busqueda en un registro: nada que cierre una comilla, encadene una orden, haga de
    # opcion o de comodin, ni mas largo de la cuenta
    ("palabra", ""), ("palabra", "a"), ("palabra", "a" * 41), ("palabra", "-k"), ("palabra", " ab"),
    ("palabra", "ab "), ("palabra", "it's"), ("palabra", 'di"jo'), ("palabra", "a;b"), ("palabra", "a$b"),
    ("palabra", "a|b"), ("palabra", "a\\b"), ("palabra", "a`b"), ("palabra", "a%b"), ("palabra", "a*b"),
    ("palabra", "a\nb"), ("palabra", "a(b)"), ("palabra", "a&b"), ("palabra", "' OR 1=1 --"),
    # nivel de un mensaje del kernel: de 0 (emergencia) a 7 (depuracion)
    ("nivel", "8"), ("nivel", "10"), ("nivel", "-1"), ("nivel", ""), ("nivel", "3 "),
    ("pid", "0"), ("pid", "00"), ("pid", "01"), ("pid", "-1"), ("pid", "4194305"), ("pid", "4194310"),
    ("pid", "5000000"), ("pid", "41943040"), ("pid", "1e3"), ("pid", ""), ("pid", "12 "), ("pid", "1;id"),
    # ruta: absoluta, sin segmentos . ni .., sin caracteres de control y de hasta 512 caracteres
    ("ruta", ""), ("ruta", "Vms/x"), ("ruta", "-rf"), ("ruta", "./x"), ("ruta", "/a/../b"), ("ruta", "/a/./b"),
    ("ruta", "/.."), ("ruta", "/."), ("ruta", "/a/.."), ("ruta", "/a/."), ("ruta", "/a/../"), ("ruta", "/a/./"),
    ("ruta", "/a\nb"), ("ruta", "/a\x00b"), ("ruta", "/a\tb"), ("ruta", "/a\x7fb"), ("ruta", "/a\r"),
    ("ruta", "/a\n"), ("ruta", "/" + "a" * 512), ("ruta", "/a/" + "b" * 600),
])
def test_valores_invalidos_por_tipo(tipo, valor):
    c = Comando("t", "echo {v}", {"v": tipo})
    with pytest.raises(ParametroInvalido):
        c.render({"v": valor})


def test_el_tipo_pid_admite_exactamente_de_1_a_4194304():
    import random
    tipo = comandos.TIPOS["pid"]
    ventanas = [range(0, 3000)] + [range(c - 12, c + 12) for c in (
        10 ** 6, 4 * 10 ** 6, 4100000, 4190000, 4194000, 4194300, 4194304)]
    azar = random.Random(1)
    muestra = [azar.randrange(0, 5000000) for _ in range(20000)]
    for n in [n for v in ventanas for n in v] + muestra:
        assert bool(tipo.fullmatch(str(n))) is (1 <= n <= 4194304), n
    assert not tipo.fullmatch("0001") and not tipo.fullmatch("+5")


def test_una_ruta_con_espacios_y_signos_viaja_entrecomillada():
    c = Comando("t", "du -s {ruta}", {"ruta": "ruta"})
    assert c.render({"ruta": "/share/Mis VMs/it's; $(x)"}) == "du -s '/share/Mis VMs/it'\"'\"'s; $(x)'"
    assert c.render({"ruta": "/share/mi\xf1a"}) == "du -s '/share/mi\xf1a'"


def test_el_mensaje_de_una_ruta_no_valida_la_describe():
    c = Comando("t", "du -s {ruta}", {"ruta": "ruta"})
    with pytest.raises(ParametroInvalido) as e:
        c.render({"ruta": "/a/../b"})
    assert "ruta" in str(e.value) and "512" in str(e.value) and ".." in str(e.value)


def test_un_texto_de_busqueda_con_espacios_viaja_entrecomillado():
    c = Comando("t", "log_tool -q -v -k {texto}", {"texto": "palabra"})
    assert c.render({"texto": "Virtualization Station"}) == "log_tool -q -v -k 'Virtualization Station'"
    # un registro en castellano lleva acentos
    assert c.render({"texto": "configuraci\xf3n"}) == "log_tool -q -v -k 'configuraci\xf3n'"


# --- errores al definir un comando --------------------------------------------

@pytest.mark.parametrize("plantilla", [
    "sudo id",                      # el sudo lo pone el transporte
    "id; sudo reboot",
    "echo x > /tmp/a",              # escribir en un fichero
    "cat /etc/hosts >> /tmp/a",
    "ls 2> /tmp/errores",
    "echo `id`",
    "ip link\nreboot",
])
def test_plantilla_prohibida(plantilla):
    with pytest.raises(ValueError):
        Comando("p", plantilla)


@pytest.mark.parametrize("plantilla", [
    "ls /x 2>/dev/null",
    "ls /x 2> /dev/null",
    "ls /x 2>&1",
    "ls /x >/dev/null 2>&1; echo $?",
    "cat /proc/mdstat | grep -c md",
])
def test_plantilla_con_redirecciones_inocuas(plantilla):
    assert Comando("p", plantilla).render() == plantilla


def test_marcador_sin_declarar():
    with pytest.raises(ValueError) as e:
        Comando("p", "ip link show {iface}")
    assert "iface" in str(e.value)


def test_parametro_declarado_que_no_se_usa():
    with pytest.raises(ValueError) as e:
        Comando("p", "ip link", {"iface": "interfaz"})
    assert "iface" in str(e.value)


def test_tipo_de_parametro_desconocido():
    with pytest.raises(ValueError):
        Comando("p", "ip link show {iface}", {"iface": "raro"})


@pytest.mark.parametrize("extra", [{"sistema": "windows"}, {"timeout": 0}, {"timeout": -5}])
def test_campos_fuera_de_rango(extra):
    with pytest.raises(ValueError):
        Comando("p", "ip link", **extra)


def test_identificador_vacio():
    with pytest.raises(ValueError):
        Comando("", "ip link")


# --- validadores de salida -----------------------------------------------------

def test_no_vacia():
    assert comandos.no_vacia(0, "") is not None
    assert comandos.no_vacia(0, "  \n ") is not None
    assert comandos.no_vacia(0, "x") is None


def test_rc_cero():
    assert comandos.rc_cero(0, "") is None
    error = comandos.rc_cero(1, "x")
    assert error is not None and "1" in error


def test_todas_devuelve_el_primer_error():
    v = comandos.todas(comandos.rc_cero, comandos.no_vacia)
    assert "codigo" in v(2, "")
    assert v(0, "") == comandos.no_vacia(0, "")
    assert v(0, "x") is None


def test_por_defecto_un_comando_exige_codigo_cero_y_salida():
    c = Comando("d", "ip -br link")
    assert c.valida(0, "") is not None
    assert c.valida(1, "x") is not None
    assert c.valida(0, "x") is None


def test_se_puede_desactivar_la_validacion_de_forma_explicita():
    assert Comando("d", "ip rule", valida=None).valida is None




def test_el_mensaje_de_una_palabra_no_valida_dice_cuanto_puede_medir():
    c = Comando("p", "log_tool -k {texto}", {"texto": "palabra"})
    assert c.render({"texto": "ab"}).endswith("ab") and c.render({"texto": "x" * 40})
    for valor in ("a", "x" * 41):
        with pytest.raises(ParametroInvalido, match="2 a 40 caracteres"):
            c.render({"texto": valor})
