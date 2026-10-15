# -*- coding: utf-8 -*-
"""Herramientas nuevas de qnap-discos (docs/superpowers/specs/2026-10-15-qnap-tools-ficheros-y-procesos.md):
ruta_ocupacion, ruta_comparar y los discos externos con su montaje. Salidas escritas a mano con el
formato visto en el NAS de laboratorio (du, ls -lnRA --time-style=+%s, /proc/mounts y df), con
nombres inventados."""
import pytest

from test_discos_servidor import (LISTADO_COPIA, RUTA_LISTADO_UNO, RUTA_OCUPACION_UNO, SALIDA_OCUPACION, algun,
                                  dato, datos, dc, ruta_de_pega, uno)
from qnap_tools.discos import parsers as p

REAL = "/share/VOL1_DATA/Vms/copia"


def listado(*entradas, real=REAL):
    """Una salida de RUTA_LISTADO: (directorio relativo, linea de ls) en orden, con el formato de ls -R."""
    salida, actual = ["==real " + real], None
    for carpeta, linea in entradas:
        if carpeta != actual:
            salida += ["", "%s/.%s:" % (real, "/" + carpeta if carpeta else ""), "total 0"]
            actual = carpeta
        salida.append(linea)
    return "\n".join(salida) + "\n"


def fichero(nombre, tamano, epoch=1760000000, tipo="-rw-r--r--"):
    return "%s  1 0 0 %d %d %s" % (tipo, tamano, epoch, nombre)


# --- parser: ruta_ocupacion ---------------------------------------------------------------------

def test_ruta_ocupacion_de_una_carpeta():
    assert p.ruta_ocupacion(SALIDA_OCUPACION) == {
        "ruta_real": REAL, "bytes": 83400000000, "bytes_en_disco": 40000000 * 1024, "ficheros": 3,
        "carpetas": 1, "es_fichero": False}


def test_ruta_ocupacion_de_un_fichero_no_tiene_carpetas():
    texto = ("==real /share/VOL1_DATA/suelto.img\n500\t/share/VOL1_DATA/suelto.img\n==kib\n4\t/share/VOL1_DATA/suelto.img\n"
             "==ficheros 1\n==carpetas 0\n")
    d = p.ruta_ocupacion(texto)
    assert (d["ficheros"], d["carpetas"], d["es_fichero"], d["bytes"], d["bytes_en_disco"]) == (1, 0, True, 500, 4096)


def test_ruta_ocupacion_de_una_carpeta_sin_nada_dentro():
    texto = ("==real /share/VOL1_DATA/vacia\n0\t/share/VOL1_DATA/vacia\n==kib\n0\t/share/VOL1_DATA/vacia\n"
             "==ficheros 0\n==carpetas 1\n")
    d = p.ruta_ocupacion(texto)
    assert (d["ficheros"], d["carpetas"], d["es_fichero"]) == (0, 0, False)


def test_ruta_ocupacion_rechazada_dice_por_que():
    with pytest.raises(ValueError) as e:
        p.ruta_ocupacion("==rechazada\n")
    assert "/share/" in str(e.value) and "no existe" in str(e.value)


@pytest.mark.parametrize("texto", [
    "", "du: cannot access 'x'\n", SALIDA_OCUPACION.replace("==kib\n", ""),
    SALIDA_OCUPACION.replace("==ficheros 3", "==ficheros tres"), SALIDA_OCUPACION.replace("83400000000\t", "mucho\t"),
    SALIDA_OCUPACION + "sobra\n"])
def test_ruta_ocupacion_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.ruta_ocupacion(texto)


# --- parser: ruta_listado y comparacion ---------------------------------------------------------

def test_ruta_listado_da_los_ficheros_con_ruta_relativa_tamano_y_fecha():
    d = p.ruta_listado(LISTADO_COPIA)
    assert d == {"ruta_real": REAL, "carpetas": 1,
                 "ficheros": {"uno.img": (1000, 1760000000), "sub/dos.img": (500, 1760000100)}}


def test_ruta_listado_con_nombres_raros_y_otros_tipos():
    texto = listado(
        ("", fichero("mi disco - copia (1).img", 7)),
        ("", fichero("con -> flecha", 8)),
        ("", fichero("acl", 9, tipo="-rw-r--r--+")),
        ("", "lrwxrwxrwx  1 0 0 11 1760000000 enlace -> uno.img"),
        ("", "crw-rw-rw-  1 0 0 1, 3 1760000000 dispositivo"),
        ("", "drwxr-xr-x  2 0 0 2 1760000000 sub dir"),
        ("sub dir", fichero("hijo.txt", 1, epoch=5)),
        ("sub dir", fichero("a:b", 2)))
    d = p.ruta_listado(texto)
    assert d["ficheros"] == {"mi disco - copia (1).img": (7, 1760000000), "con -> flecha": (8, 1760000000),
                             "acl": (9, 1760000000), "sub dir/hijo.txt": (1, 5), "sub dir/a:b": (2, 1760000000)}
    assert d["carpetas"] == 1


def test_ruta_listado_de_una_carpeta_vacia():
    d = p.ruta_listado("==real %s\n\n%s/.:\ntotal 0\n" % (REAL, REAL))
    assert d["ficheros"] == {} and d["carpetas"] == 0


def test_ruta_listado_rechazada_y_formatos_que_no_reconoce():
    with pytest.raises(ValueError):
        p.ruta_listado("==rechazada\n")
    for texto in ("", "ls: cannot access\n", listado(("", "esto no es una linea de ls")),
                  "==real %s\n-rw-r--r-- 1 0 0 1 1 suelto\n" % REAL,                 # sin cabecera de carpeta
                  "==real %s\n/otra/ruta/.:\n" % REAL, "==real %s\n" % REAL):
        with pytest.raises(ValueError):
            p.ruta_listado(texto)


def test_ruta_listado_tiene_un_tope_de_ficheros_y_remite_a_ruta_ocupacion():
    texto = listado(*[("", fichero("f%d" % i, 1)) for i in range(5)])
    assert len(p.ruta_listado(texto, maximo=5)["ficheros"]) == 5
    with pytest.raises(ValueError) as e:
        p.ruta_listado(texto, maximo=4)
    assert "ruta_ocupacion" in str(e.value) and "4" in str(e.value)
    assert p.MAX_FICHEROS_LISTADO == 200000


def test_comparar_listados_separa_faltan_sobran_tamano_y_fecha():
    a = {"ficheros": {"igual": (1, 10), "solo_fecha": (2, 10), "falta": (3, 10), "cambia": (4, 10), "d/falta2": (5, 10)}}
    b = {"ficheros": {"igual": (1, 10), "solo_fecha": (2, 99), "sobra": (6, 10), "cambia": (40, 10)}}
    c = p.comparar_listados(a, b)
    assert c == {"coinciden": 2, "solo_fecha": 1, "faltan": ["d/falta2", "falta"], "sobran": ["sobra"],
                 "distinto_tamano": [{"ruta": "cambia", "bytes_origen": 4, "bytes_destino": 40}]}


# --- parser: externos_montajes ------------------------------------------------------------------

def test_externos_montajes_de_un_disco_ufsd():
    assert p.externos_montajes(dato("externos_montajes_hero")) == [{
        "dispositivo": "/dev/sdh1", "montaje": "/share/external/DEV3301_1", "sistema_ficheros": "ufsd",
        "bytes": 4883637168 * 1024, "usado": 1953454868 * 1024, "libre": 2930182300 * 1024, "ocupacion_pct": 40,
        "tipo": "NTFS", "etiqueta": "USB-DISCO", "sucio": False, "solo_lectura": False}]


def test_externos_montajes_sin_ningun_externo_es_una_lista_vacia():
    assert p.externos_montajes("==montajes 12\n==df\n==ufsd\n") == []


def test_externos_montajes_con_un_montaje_sin_linea_de_df_deja_las_cifras_sin_valor():
    texto = "==montajes 3\n/dev/sdb1 /share/external/DEV1 vfat rw 0 0\n==df\n==ufsd\n"
    (m,) = p.externos_montajes(texto)
    assert (m["montaje"], m["bytes"], m["usado"], m["libre"], m["ocupacion_pct"]) == ("/share/external/DEV1", None, None, None, None)


def test_externos_montajes_con_espacios_escapados_en_el_montaje():
    texto = ("==montajes 3\n/dev/sdb1 /share/external/Mi\\040disco ext4 rw 0 0\n==df\n"
             "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sdb1 100 40 60 40% /share/external/Mi disco\n==ufsd\n")
    (m,) = p.externos_montajes(texto)
    assert m["montaje"] == "/share/external/Mi disco" and m["ocupacion_pct"] == 40


@pytest.mark.parametrize("texto", [
    "", "==montajes\n==df\n", "grep: /proc/mounts: Permission denied\n", "==montajes 3\n/dev/sdb1 /share/external/x\n==df\n",
    "==montajes 3\nno es un montaje\n==df\n", "==montajes 3\n",
    "==montajes 3\n==df\nFilesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sdb1 mucho 40 60 40% /x\n"])
def test_externos_montajes_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.externos_montajes(texto)


# --- ruta_ocupacion ------------------------------------------------------------------------------

def test_ruta_ocupacion_da_las_cifras_y_antepone_share(tmp_path):
    h, mundo = uno(tmp_path)
    d = datos(h.ruta_ocupacion("hero", "/Vms/copia"))
    assert d == {"ruta": "/share/Vms/copia", "ruta_real": REAL, "bytes": 83400000000,
                 "bytes_en_disco": 40000000 * 1024, "ficheros": 3, "carpetas": 1, "es_fichero": False}
    (orden, sudo), = [(o, s) for o, s in mundo.ordenes if RUTA_OCUPACION_UNO.match(o)]
    assert sudo is True and "readlink -f /share/Vms/copia)" in orden
    assert datos(h.ruta_ocupacion("hero", "/share/Vms/copia")) == d          # tambien con /share delante


@pytest.mark.parametrize("ruta", ["Vms/copia", "/Vms/copia", "/share/Vms/copia"])
def test_la_ruta_vale_con_o_sin_barra_inicial_y_con_o_sin_share(tmp_path, ruta):
    h, _ = uno(tmp_path)
    assert datos(h.ruta_ocupacion("hero", ruta))["ruta"] == "/share/Vms/copia"


def test_ruta_ocupacion_rechazada_es_un_error_que_lo_explica(tmp_path):
    h, _ = uno(tmp_path)
    (r,) = h.ruta_ocupacion("hero", "/Vms/no_existe")
    assert r["ok"] is False and "no existe" in r["error"] and "/share/" in r["error"]


@pytest.mark.parametrize("ruta", ["", "/Vms/../etc", "Vms/../etc", "Vms/./x", "/Vms/./x", "/a\nb", "Vms/a\nb",
                                  "/" + "a" * 600, "a" * 600, None, 7])
def test_ruta_ocupacion_valida_la_ruta_antes_de_conectar(tmp_path, ruta):
    h, mundo = uno(tmp_path)
    (r,) = h.ruta_ocupacion("hero", ruta)
    assert r["ok"] is False and mundo.conexiones == 0 and "ruta" in r["error"]


def test_ruta_ocupacion_con_una_ruta_con_comillas_la_entrecomilla(tmp_path):
    h, mundo = uno(tmp_path)
    h.ruta_ocupacion("hero", "/Vms/a'; reboot; '")
    (orden,) = [o for o, _ in mundo.ordenes if RUTA_OCUPACION_UNO.match(o)]
    assert "readlink -f '/share/Vms/a'\"'\"'; reboot; '\"'\"''" in orden


def test_ruta_ocupacion_con_todos_pregunta_a_cada_nas(tmp_path):
    from test_discos_servidor import montar, nas_simulado
    h = montar(tmp_path, {"hero": nas_simulado("hero"), "qts": nas_simulado("qts")})
    r = h.ruta_ocupacion("todos", "/Vms/copia")
    assert [(x["nas"], x["ok"]) for x in r] == [("hero", True), ("qts", True)]


# --- ruta_comparar -------------------------------------------------------------------------------

def con_listados(tmp_path, origen, destino):
    h, mundo = uno(tmp_path)
    mundo.respuestas[RUTA_LISTADO_UNO] = ruta_de_pega("listado", {"listado": {
        "/share/Vms/origen": origen, "/share/Vms/destino": destino}})
    return h, mundo


def test_comparar_dos_carpetas_iguales(tmp_path):
    h, mundo = con_listados(tmp_path, LISTADO_COPIA, LISTADO_COPIA)
    d = datos(h.ruta_comparar("hero", "/Vms/origen", "/Vms/destino"))
    assert d["iguales"] is True and d["coinciden"] == 2 and d["solo_fecha"] == 0
    assert d["origen"] == {"ruta": "/share/Vms/origen", "ruta_real": REAL, "ficheros": 2, "carpetas": 1, "bytes": 1500}
    assert d["destino"]["ruta"] == "/share/Vms/destino" and d["destino"]["bytes"] == 1500
    for lista in ("faltan", "sobran", "distinto_tamano"):
        assert d[lista] == {"filas": [], "total": 0, "truncado": False}
    ordenes = [(o, s) for o, s in mundo.ordenes if RUTA_LISTADO_UNO.match(o)]
    assert len(ordenes) == 2 and all(s is True for _, s in ordenes)


def test_comparar_da_solo_las_diferencias(tmp_path):
    destino = listado(
        ("", fichero("uno.img", 999)), ("", fichero("extra.log", 5)), ("", fichero("otro.bin", 1)),
        ("sub", fichero("dos.img", 500, epoch=1)))
    h, _ = con_listados(tmp_path, LISTADO_COPIA, destino)
    d = datos(h.ruta_comparar("hero", "/Vms/origen", "/Vms/destino"))
    assert d["iguales"] is False and d["coinciden"] == 1 and d["solo_fecha"] == 1
    assert d["faltan"]["filas"] == [] and d["sobran"] == {"filas": ["extra.log", "otro.bin"], "total": 2, "truncado": False}
    assert d["distinto_tamano"]["filas"] == [{"ruta": "uno.img", "bytes_origen": 1000, "bytes_destino": 999}]


def test_comparar_con_un_destino_incompleto_dice_que_falta(tmp_path):
    h, _ = con_listados(tmp_path, LISTADO_COPIA, listado(("", fichero("uno.img", 1000))))
    d = datos(h.ruta_comparar("hero", "/Vms/origen", "/Vms/destino"))
    assert d["iguales"] is False and d["faltan"]["filas"] == ["sub/dos.img"]


def test_comparar_acepta_las_carpetas_compartidas_sin_barra(tmp_path):
    h, _ = con_listados(tmp_path, LISTADO_COPIA, LISTADO_COPIA)
    d = datos(h.ruta_comparar("hero", "Vms/origen", "Vms/destino"))
    assert d["iguales"] is True and d["origen"]["ruta"] == "/share/Vms/origen"


def test_comparar_acota_a_50_las_listas_con_su_total(tmp_path):
    muchos = listado(*[("", fichero("f%03d" % i, 1)) for i in range(120)])
    h, _ = con_listados(tmp_path, muchos, listado(("", fichero("f000", 1))))
    d = datos(h.ruta_comparar("hero", "/Vms/origen", "/Vms/destino"))
    assert d["faltan"]["total"] == 119 and len(d["faltan"]["filas"]) == 50 and d["faltan"]["truncado"] is True
    assert d["faltan"]["filas"][0] == "f001" and d["coinciden"] == 1


def test_comparar_sanea_los_nombres_de_las_diferencias(tmp_path):
    raro = "x" * 600 + "\t(nombre largo)"
    h, _ = con_listados(tmp_path, listado(("", fichero("con\ttab", 1)), ("", fichero(raro, 1))), listado(("", fichero("z", 1))))
    d = datos(h.ruta_comparar("hero", "/Vms/origen", "/Vms/destino"))
    nombres = d["faltan"]["filas"]
    assert "con tab" in nombres and all("\t" not in n and len(n) <= p.MAX_DIFERENCIA for n in nombres)


def test_comparar_con_un_lado_rechazado_es_un_error(tmp_path):
    h, _ = con_listados(tmp_path, LISTADO_COPIA, "==rechazada\n")
    (r,) = h.ruta_comparar("hero", "/Vms/origen", "/Vms/destino")
    assert r["ok"] is False and "no existe" in r["error"]


def test_comparar_valida_las_dos_rutas_antes_de_conectar(tmp_path):
    h, mundo = uno(tmp_path)
    for origen, destino in (("", "/Vms/b"), ("/Vms/a", "/Vms/../b"), ("Vms/a", "Vms/../b")):
        (r,) = h.ruta_comparar("hero", origen, destino)
        assert r["ok"] is False
    assert mundo.conexiones == 0


def test_comparar_con_mas_ficheros_del_tope_remite_a_ruta_ocupacion(tmp_path, monkeypatch):
    original = p.ruta_listado
    monkeypatch.setattr(p, "ruta_listado", lambda texto: original(texto, maximo=1))
    h, _ = con_listados(tmp_path, LISTADO_COPIA, LISTADO_COPIA)
    (r,) = h.ruta_comparar("hero", "/Vms/origen", "/Vms/destino")
    assert r["ok"] is False and "ruta_ocupacion" in r["error"]


# --- discos externos con su montaje ---------------------------------------------------------------

ENLACE_USB = "lrwxrwxrwx  1 admin administrators  22 Oct 13 17:09 Copias-USB -> external/DEV3301_1\n"


def test_un_disco_externo_trae_donde_esta_montado_y_cuanto_ocupa(tmp_path):
    h, mundo = uno(tmp_path, cambios={dc.CARPETAS_ENLACES.plantilla: dato("carpetas_enlaces_hero") + ENLACE_USB})
    (usb,) = datos(h.discos_fisicos("hero"))["externos"]
    assert (usb["montaje"], usb["sistema_ficheros"], usb["ocupacion_pct"]) == ("/share/external/DEV3301_1", "ufsd", 40)
    assert (usb["bytes_montaje"], usb["usado"], usb["libre"]) == (4883637168 * 1024, 1953454868 * 1024, 2930182300 * 1024)
    assert usb["carpetas"] == ["Copias-USB", "carpeta12"] and usb["particiones_montadas"] == 1
    assert usb["bytes"] == 9767541167 * 512                          # la capacidad del disco no cambia
    assert (dc.EXTERNOS_MONTAJES.render(), False) in mundo.ordenes


def test_un_disco_externo_sin_montar_sale_con_montaje_null(tmp_path):
    h, _ = uno(tmp_path, "qts")
    externos = datos(h.discos_fisicos("qts"))["externos"]
    montado, sin_montar = (next(e for e in externos if e["dispositivo"] == d) for d in ("/dev/sdk", "/dev/sdl"))
    assert (montado["montaje"], montado["sistema_ficheros"], montado["ocupacion_pct"]) == (
        "/share/external/DEV3307_1", "vfat", 91)
    assert sin_montar["montaje"] is None and sin_montar["ocupacion_pct"] is None and sin_montar["carpetas"] == []
    assert sin_montar["particiones_montadas"] == 0 and "errores" not in datos(h.discos_fisicos("qts"))


def test_si_no_se_pueden_leer_los_montajes_los_campos_salen_sin_valor_y_se_dice(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.EXTERNOS_MONTAJES.plantilla: (1, "", "boom\n")})
    d = datos(h.discos_fisicos("hero"))
    (usb,) = d["externos"]
    assert "montajes_externos" in d["errores"]
    assert usb["montaje"] is None and usb["particiones_montadas"] is None and usb["carpetas"] is None


def test_si_no_se_pueden_leer_los_enlaces_las_carpetas_salen_sin_valor(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_ENLACES.plantilla: (1, "", "boom\n")})
    d = datos(h.discos_fisicos("hero"))
    (usb,) = d["externos"]
    assert "carpetas" in d["errores"] and usb["montaje"] == "/share/external/DEV3301_1" and usb["carpetas"] is None


def test_el_resumen_no_lanza_la_orden_de_montajes_externos(tmp_path):
    h, mundo = uno(tmp_path)
    datos(h.almacenamiento_resumen("hero"))
    assert (dc.EXTERNOS_MONTAJES.render(), False) not in mundo.ordenes


# --- carpetas_compartidas: externo ---------------------------------------------------------------

SMB_USB = ("[Copias]\ncomment = Copias en un disco USB\npath = /share/Copias-USB\nbrowsable = yes\n"
           "[Directa]\npath = /share/external/DEV3301_1/Directa\n")


def test_una_carpeta_en_un_disco_externo_se_marca(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_ENLACES.plantilla: dato("carpetas_enlaces_hero") + ENLACE_USB,
                                  dc.CARPETAS_SMB.plantilla: dato("carpetas_smb_hero") + SMB_USB})
    filas = datos(h.carpetas_compartidas("hero"))["carpetas"]["filas"]
    externas = sorted(f["nombre"] for f in filas if f["externo"])
    assert externas == ["Copias", "Directa", "carpeta12"]
    assert all(f["externo"] is False for f in filas if f["nombre"] not in externas)


def test_sin_los_enlaces_no_se_sabe_si_una_carpeta_esta_en_un_externo(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_ENLACES.plantilla: (1, "", "boom\n"),
                                  dc.CARPETAS_SMB.plantilla: dato("carpetas_smb_hero") + SMB_USB})
    filas = {f["nombre"]: f for f in datos(h.carpetas_compartidas("hero"))["carpetas"]["filas"]}
    assert filas["Directa"]["externo"] is True and filas["Copias"]["externo"] is None


def test_la_carpeta_personal_no_es_un_disco_externo(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_SMB.plantilla: dato("carpetas_smb_hero") + "[homes]\npath = %H\n"})
    filas = {f["nombre"]: f for f in datos(h.carpetas_compartidas("hero"))["carpetas"]["filas"]}
    assert filas["homes"]["externo"] is False
