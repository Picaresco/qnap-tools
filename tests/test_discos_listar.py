# -*- coding: utf-8 -*-
"""ruta_listar: el contenido de UNA carpeta (sin recursividad) o un fichero. Salidas escritas a mano con
el formato de ls -lAs --block-size=1 --time-style=+%Y-%m-%dT%H:%M:%S%z --quoting-style=literal (GNU ls
8.32 en el sh de pruebas), con nombres inventados. Los nombres de los ficheros son datos de los
usuarios y de terceros."""
import os
import re
import shutil
import subprocess

import pytest

from test_discos_servidor import RUTA_LISTAR_UNO, SALIDA_LISTAR, algun, datos, dc, por, ruta_de_pega, uno
from test_discos_shell import posix
from qnap_tools.discos import parsers as p

REAL = "/share/VOL1_DATA/Vms/copia"
SH = shutil.which("sh")


def entrada(nombre, tipo="-", permisos="rwxr-xr-x", tamano=10, disco=4096, fecha="2026-10-15T22:36:31+0200",
            dueno="admin", grupo="administrators"):
    return "%12d %s%s  1 %s %s %12d %s %s" % (disco, tipo, permisos, dueno, grupo, tamano, fecha, nombre)


def listado(*entradas, total=True, real=REAL):
    return "\n".join(["==real " + real] + (["total 8192"] if total else []) + list(entradas)) + "\n"


# --- parser ------------------------------------------------------------------------------------------

def test_listar_una_carpeta_da_cada_entrada_con_sus_campos():
    d = p.ruta_listar(SALIDA_LISTAR)
    assert d["ruta_real"] == REAL and d["es_carpeta"] is True
    por_nombre = {e["nombre"]: e for e in d["entradas"]}
    assert por_nombre["uno.img"] == {
        "nombre": "uno.img", "tipo": "fichero", "bytes": 1000, "en_disco": 4096, "permisos": "-rw-r--r--",
        "propietario": "admin", "grupo": "administrators", "fecha": "2026-10-15T22:36:31+02:00", "destino": None}
    assert por_nombre["sub"]["tipo"] == "carpeta" and por_nombre["sub"]["permisos"] == "drwxr-xr-x"
    assert por_nombre["enlace"]["tipo"] == "enlace" and por_nombre["enlace"]["destino"] == "uno.img"


def test_listar_la_fecha_lleva_el_desfase_de_esa_fecha_concreta():
    d = p.ruta_listar(listado(entrada("invierno", fecha="2026-01-10T12:00:00+0100"),
                              entrada("verano", fecha="2026-07-10T12:00:00+0200"),
                              entrada("oeste", fecha="2026-07-10T12:00:00-0330")))
    assert {e["nombre"]: e["fecha"] for e in d["entradas"]} == {
        "invierno": "2026-01-10T12:00:00+01:00", "verano": "2026-07-10T12:00:00+02:00",
        "oeste": "2026-07-10T12:00:00-03:30"}


def test_listar_los_nombres_con_espacios_flechas_y_dos_puntos_no_se_parten():
    d = p.ruta_listar(listado(
        entrada("mi disco - copia (1).img"), entrada("con -> flecha.txt"), entrada("a:b"), entrada("  espacios  "),
        entrada("alias", tipo="l", permisos="rwxrwxrwx") .replace("alias", "enlace con -> flecha -> destino con espacios")))
    nombres = {e["nombre"]: e for e in d["entradas"]}
    assert "con -> flecha.txt" in nombres and nombres["con -> flecha.txt"]["tipo"] == "fichero"
    assert nombres["con -> flecha.txt"]["destino"] is None and "mi disco - copia (1).img" in nombres and "a:b" in nombres
    assert "  espacios  " in nombres
    enlace = nombres["enlace con"]                      # el ' -> ' solo se parte en un enlace, por el primero
    assert enlace["tipo"] == "enlace" and enlace["destino"] == "flecha -> destino con espacios"


def test_listar_los_tipos_de_entrada():
    d = p.ruta_listar(listado(entrada("f"), entrada("d", tipo="d"), entrada("l", tipo="l"), entrada("p", tipo="p"),
                              entrada("s", tipo="s"), entrada("c", tipo="c", tamano=0).replace(" 0 2026", " 8, 1 2026"),
                              entrada("acl", permisos="rw-r--r--+")))
    tipos = {e["nombre"]: e["tipo"] for e in d["entradas"]}
    assert tipos == {"f": "fichero", "d": "carpeta", "l": "enlace", "p": "otro", "s": "otro", "c": "otro",
                     "acl": "fichero"}
    assert [e for e in d["entradas"] if e["nombre"] == "acl"][0]["permisos"] == "-rw-r--r--"      # sin la marca de ACL


def test_listar_un_fichero_no_trae_total_y_no_es_carpeta():
    d = p.ruta_listar(listado(entrada("suelto.img", tamano=5), total=False, real="/share/VOL1_DATA/suelto.img"))
    assert d["es_carpeta"] is False and [e["nombre"] for e in d["entradas"]] == ["suelto.img"]


def test_listar_un_fichero_sale_con_su_nombre_y_no_con_la_ruta_que_imprime_ls():
    # ls -l <fichero> imprime el nombre tal como se le dio, con toda la ruta
    d = p.ruta_listar(listado(entrada(REAL + "/mi disco.img", tamano=5), total=False, real=REAL + "/mi disco.img"))
    assert [e["nombre"] for e in d["entradas"]] == ["mi disco.img"] and d["es_carpeta"] is False


def test_listar_una_carpeta_vacia():
    d = p.ruta_listar("==real %s\ntotal 0\n" % REAL)
    assert d["es_carpeta"] is True and d["entradas"] == []


def test_listar_sanea_y_acota_los_nombres_y_los_destinos():
    d = p.ruta_listar(listado(entrada("con\ttab " + "x" * 900), entrada("e" + "y" * 900, tipo="l").replace(
        "e" + "y" * 900, "enlace -> " + "z\t" * 400)))
    nombre, enlace = d["entradas"]
    assert "\t" not in nombre["nombre"] and len(nombre["nombre"]) <= p.MAX_NOMBRE
    assert enlace["destino"] is not None and "\t" not in enlace["destino"] and len(enlace["destino"]) <= p.MAX_RUTA_REAL


def test_listar_rechazada_dice_por_que():
    with pytest.raises(ValueError) as e:
        p.ruta_listar("==rechazada\n")
    assert "/share/" in str(e.value)


@pytest.mark.parametrize("texto", [
    "", "ls: cannot access 'x'\n", "==real %s\nesto no es una linea de ls\n" % REAL,
    listado("   x -rw-r--r-- 1 a b 1 ayer nombre"), listado("4096 -rw-r--r-- 1 a b mucho 2026-10-15T22:36:31+0200 f"),
    listado(entrada("f", fecha="hoy")), "total 0\n"])
def test_listar_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.ruta_listar(texto)


# --- herramienta -------------------------------------------------------------------------------------

def test_ruta_listar_da_las_entradas_ordenadas_por_nombre(tmp_path):
    h, mundo = uno(tmp_path)
    d = datos(h.ruta_listar("hero", "/Vms/copia"))
    assert d["ruta"] == "/share/Vms/copia" and d["ruta_real"] == REAL and d["es_carpeta"] is True
    assert d["entradas"]["total"] == 4 and d["entradas"]["truncado"] is False
    nombres = [e["nombre"] for e in d["entradas"]["filas"]]
    assert nombres == sorted(nombres, key=lambda x: (x.casefold(), x))
    (orden, sudo), = [(o, s) for o, s in mundo.ordenes if RUTA_LISTAR_UNO.match(o)]
    assert sudo is True and "readlink -f /share/Vms/copia)" in orden and "ls -lAs --block-size=1" in orden


@pytest.mark.parametrize("ruta", ["Vms/copia", "/Vms/copia", "/share/Vms/copia"])
def test_ruta_listar_acepta_la_carpeta_compartida_con_o_sin_barra(tmp_path, ruta):
    h, _ = uno(tmp_path)
    assert datos(h.ruta_listar("hero", ruta))["ruta"] == "/share/Vms/copia"


def test_ruta_listar_sin_ocultos_quita_los_que_empiezan_por_punto_en_el_ordenador(tmp_path):
    h, mundo = uno(tmp_path)
    con = datos(h.ruta_listar("hero", "/Vms/copia"))["entradas"]
    sin = datos(h.ruta_listar("hero", "/Vms/copia", ocultos=False))["entradas"]
    assert ".oculto" in [e["nombre"] for e in con["filas"]]
    assert ".oculto" not in [e["nombre"] for e in sin["filas"]] and sin["total"] == con["total"] - 1
    ordenes = {o for o, _ in mundo.ordenes if RUTA_LISTAR_UNO.match(o)}
    assert len(ordenes) == 1                                        # la orden no cambia


def test_ruta_listar_limita_la_lista_y_dice_cuantas_hay(tmp_path):
    muchas = listado(*[entrada("f%04d" % i) for i in range(30)])
    h, mundo = uno(tmp_path)
    mundo.respuestas[RUTA_LISTAR_UNO] = ruta_de_pega("listar", {"listar": {"/share/Vms/copia": muchas}})
    d = datos(h.ruta_listar("hero", "/Vms/copia", limite=10))["entradas"]
    assert d["total"] == 30 and d["truncado"] is True and len(d["filas"]) == 10 and d["filas"][0]["nombre"] == "f0000"
    d = datos(h.ruta_listar("hero", "/Vms/copia"))["entradas"]
    assert len(d["filas"]) == 30 and d["truncado"] is False


@pytest.mark.parametrize("limite", [0, -1, 1001, True, "5", 2.5, None])
def test_ruta_listar_valida_el_limite_antes_de_conectar(tmp_path, limite):
    h, mundo = uno(tmp_path)
    (r,) = h.ruta_listar("hero", "/Vms/copia", limite=limite)
    assert r["ok"] is False and "limite" in r["error"] and mundo.conexiones == 0


@pytest.mark.parametrize("limite", [1, 1000])
def test_ruta_listar_admite_los_extremos_del_limite(tmp_path, limite):
    h, _ = uno(tmp_path)
    assert datos(h.ruta_listar("hero", "/Vms/copia", limite=limite))["entradas"]["total"] == 4


def test_ruta_listar_valida_ocultos(tmp_path):
    h, mundo = uno(tmp_path)
    (r,) = h.ruta_listar("hero", "/Vms/copia", ocultos="no")
    assert r["ok"] is False and "ocultos" in r["error"] and mundo.conexiones == 0


@pytest.mark.parametrize("ruta", ["", "/Vms/../etc", "Vms/./x", "/a\nb", "/" + "a" * 600, None, 7])
def test_ruta_listar_valida_la_ruta_antes_de_conectar(tmp_path, ruta):
    h, mundo = uno(tmp_path)
    (r,) = h.ruta_listar("hero", ruta)
    assert r["ok"] is False and mundo.conexiones == 0


def test_ruta_listar_de_un_fichero_devuelve_solo_ese_fichero(tmp_path):
    h, mundo = uno(tmp_path)
    mundo.respuestas[RUTA_LISTAR_UNO] = ruta_de_pega("listar", {"listar": {
        "/share/Vms/copia/uno.img": listado(entrada("uno.img", tamano=1000), total=False, real=REAL + "/uno.img")}})
    d = datos(h.ruta_listar("hero", "/Vms/copia/uno.img"))
    assert d["es_carpeta"] is False and [e["nombre"] for e in d["entradas"]["filas"]] == ["uno.img"]


def test_ruta_listar_rechazada_es_un_error_que_lo_explica(tmp_path):
    h, _ = uno(tmp_path)
    (r,) = h.ruta_listar("hero", "/Vms/no_existe")
    assert r["ok"] is False and "no existe" in r["error"]


def test_ruta_listar_dice_que_los_nombres_son_datos_y_no_instrucciones():
    from qnap_tools.discos import servidor as srv
    assert "ruta_listar" in srv.INSTRUCCIONES and "ruta_listar" in srv.HERRAMIENTAS
    assert "no son instrucciones" in (srv.Herramientas.ruta_listar.__doc__ or "")
    assert "nombres de fichero" in srv.INSTRUCCIONES


# --- la orden en un sh de verdad ------------------------------------------------------------------------

@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar las ordenes")
class TestEnShell:
    def lanzar(self, tmp_path, ruta):
        raiz = posix(tmp_path) + "/share/"
        texto = dc.RUTA_LISTAR.render({"ruta": ruta}).replace("/share/", raiz)
        r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8", cwd=tmp_path,
                           env={"PATH": os.environ["PATH"]}, timeout=60)
        return r.returncode, r.stdout

    @pytest.fixture
    def carpeta(self, tmp_path):
        base = tmp_path / "share" / "VOL1_DATA" / "Vms" / "mi carpeta"
        (base / "sub dir").mkdir(parents=True)
        (base / "uno.img").write_bytes(b"x" * 10)
        (base / ".oculto").write_bytes(b"y")
        (base / "a (copia) b.txt").write_bytes(b"z" * 3)
        (base / "sub dir" / "no_se_lista.img").write_bytes(b"w")
        return tmp_path

    def test_una_carpeta_se_lista_sin_bajar_a_las_subcarpetas(self, carpeta):
        rc, salida = self.lanzar(carpeta, "/share/VOL1_DATA/Vms/mi carpeta")
        assert rc == 0
        d = p.ruta_listar(salida)
        assert d["es_carpeta"] is True and d["ruta_real"] == posix(carpeta) + "/share/VOL1_DATA/Vms/mi carpeta"
        nombres = {e["nombre"]: e for e in d["entradas"]}
        assert set(nombres) == {"sub dir", "uno.img", ".oculto", "a (copia) b.txt"}
        assert nombres["uno.img"]["bytes"] == 10 and nombres["sub dir"]["tipo"] == "carpeta"
        assert re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:]{8}[+-][0-9]{2}:[0-9]{2}", nombres["uno.img"]["fecha"])

    def test_un_fichero_se_lista_solo_a_el(self, carpeta):
        rc, salida = self.lanzar(carpeta, "/share/VOL1_DATA/Vms/mi carpeta/uno.img")
        d = p.ruta_listar(salida)
        assert rc == 0 and d["es_carpeta"] is False and [e["nombre"] for e in d["entradas"]] == ["uno.img"]

    @pytest.mark.parametrize("ruta", ["/etc", "/share", "/tmp", "/share/VOL1_DATA/no_existe"])
    def test_rechaza_lo_que_no_existe_o_no_cuelga_de_share(self, carpeta, ruta):
        _, salida = self.lanzar(carpeta, ruta)
        assert salida.strip() == "==rechazada"

    def test_no_ejecuta_lo_que_lleve_la_ruta(self, carpeta, tmp_path):
        for ruta in ("/share/a'; touch hecho; '", "/share/$(touch hecho)"):
            _, salida = self.lanzar(carpeta, ruta)
            assert salida.strip() == "==rechazada"
        assert not (tmp_path / "hecho").exists()
