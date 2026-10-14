# -*- coding: utf-8 -*-
import pytest

from qnap_tools import inventario as inv
from qnap_tools.inventario import Nas


def dos():
    return {
        "casa": Nas("casa", "192.0.2.10"),
        "otro": Nas("otro", "nas.example.org", 223, user="pepe", auth="contrasena"),
    }


def test_fichero_inexistente_es_inventario_vacio(tmp_path):
    assert inv.cargar(tmp_path / "no-existe.toml") == {}


def test_ida_y_vuelta_con_campos_opcionales(tmp_path):
    ruta = tmp_path / "inventario.toml"
    inv.guardar(ruta, dos())
    assert inv.cargar(ruta) == dos()


def test_el_fichero_es_toml_legible_y_omite_los_valores_por_defecto(tmp_path):
    ruta = tmp_path / "inventario.toml"
    inv.guardar(ruta, dos())
    texto = ruta.read_text(encoding="utf-8")
    assert "[nas.casa]" in texto
    assert 'host = "192.0.2.10"' in texto
    assert "port = 22" in texto
    bloque_casa = texto.split("[nas.casa]")[1].split("[nas.otro]")[0]
    assert "user" not in bloque_casa and "auth" not in bloque_casa
    assert 'user = "pepe"' in texto and 'auth = "contrasena"' in texto


def test_guardar_crea_la_carpeta_y_no_deja_temporales(tmp_path):
    ruta = tmp_path / "datos" / "inventario.toml"
    inv.guardar(ruta, dos())
    assert [p.name for p in ruta.parent.iterdir()] == ["inventario.toml"]


def test_guardar_sustituye_el_contenido_anterior(tmp_path):
    ruta = tmp_path / "inventario.toml"
    inv.guardar(ruta, dos())
    inv.guardar(ruta, {"casa": Nas("casa", "192.0.2.10")})
    assert list(inv.cargar(ruta)) == ["casa"]


def test_resolver_todos_devuelve_orden_alfabetico():
    nas = {"zeta": Nas("zeta", "192.0.2.3"), "alfa": Nas("alfa", "192.0.2.1")}
    assert [n.nombre for n in inv.resolver(nas, "todos")] == ["alfa", "zeta"]


def test_resolver_un_nombre():
    assert inv.resolver(dos(), "otro") == [dos()["otro"]]


def test_resolver_desconocido_lista_los_validos():
    with pytest.raises(inv.NasDesconocido) as e:
        inv.resolver(dos(), "nope")
    assert "nope" in str(e.value)
    assert "casa" in str(e.value) and "otro" in str(e.value)


def test_resolver_con_inventario_vacio_lo_dice():
    with pytest.raises(inv.NasDesconocido) as e:
        inv.resolver({}, "todos")
    assert "vacio" in str(e.value)


@pytest.mark.parametrize("nombre", ["Mal Nombre", "", "con.punto", "a" * 33, "-empieza", "todos", "casa\n"])
def test_nombre_invalido(nombre):
    with pytest.raises(inv.InventarioInvalido):
        Nas(nombre, "192.0.2.10")


@pytest.mark.parametrize("host", ["a b", "", "host;reboot", "$(x)", "-x", "a" * 300])
def test_host_invalido(host):
    with pytest.raises(inv.InventarioInvalido):
        Nas("casa", host)


@pytest.mark.parametrize("port", [0, 65536, -1, "22", True])
def test_puerto_invalido(port):
    with pytest.raises(inv.InventarioInvalido):
        Nas("casa", "192.0.2.10", port)


def test_auth_invalida():
    with pytest.raises(inv.InventarioInvalido):
        Nas("casa", "192.0.2.10", auth="lo-que-sea")


def test_usuario_invalido():
    with pytest.raises(inv.InventarioInvalido):
        Nas("casa", "192.0.2.10", user="pe pe")


def test_fichero_corrupto_da_error_con_la_ruta(tmp_path):
    ruta = tmp_path / "inventario.toml"
    ruta.write_text("esto no es [toml", encoding="utf-8")
    with pytest.raises(inv.InventarioInvalido) as e:
        inv.cargar(ruta)
    assert "inventario.toml" in str(e.value)


def test_entrada_sin_host_da_error_con_el_nombre(tmp_path):
    ruta = tmp_path / "inventario.toml"
    ruta.write_text("[nas.casa]\nport = 22\n", encoding="utf-8")
    with pytest.raises(inv.InventarioInvalido) as e:
        inv.cargar(ruta)
    assert "casa" in str(e.value) and "host" in str(e.value)


def test_tabla_fuera_de_nas_da_error_en_vez_de_ignorarse(tmp_path):
    # [casa] en lugar de [nas.casa]: ignorarlo dejaria un inventario vacio sin explicacion
    ruta = tmp_path / "inventario.toml"
    ruta.write_text('[casa]\nhost = "192.0.2.10"\n', encoding="utf-8")
    with pytest.raises(inv.InventarioInvalido) as e:
        inv.cargar(ruta)
    assert "casa" in str(e.value) and "[nas." in str(e.value)


def test_fichero_con_bom_se_lee(tmp_path):
    ruta = tmp_path / "inventario.toml"
    ruta.write_bytes(b'\xef\xbb\xbf[nas.casa]\nhost = "192.0.2.10"\n')
    assert inv.cargar(ruta) == {"casa": Nas("casa", "192.0.2.10")}


def test_clave_desconocida_da_error(tmp_path):
    ruta = tmp_path / "inventario.toml"
    ruta.write_text('[nas.casa]\nhost = "192.0.2.10"\npuerto = 22\n', encoding="utf-8")
    with pytest.raises(inv.InventarioInvalido) as e:
        inv.cargar(ruta)
    assert "puerto" in str(e.value)
