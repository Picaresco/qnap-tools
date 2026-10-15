# -*- coding: utf-8 -*-
"""Arreglos de la revision de codigo de la 0.4.4 en qnap-discos (docs/review-verification.md):
M6, M9, M11, L16, L17, L18, L22, L29 y L30. Escritos a mano con el formato visto en OpenZFS
(zpool list de un pool que no se puede abrir) y en el kernel (dmsetup status)."""
import pytest

from test_discos_parsers import AUSENTE
from test_discos_servidor import OCUPACION_QTS, algun, dato, datos, dc, por, uno
from qnap_tools import servidor
from qnap_tools.comandos import Comando
from qnap_tools.discos import parsers as p

FALLIDO = (1, "", "boom\n")


# --- M9: un pool que no se puede abrir sale con "-" en todo menos el nombre y la salud -----------

POOL_CAIDO = "zpool1\t-\t-\t-\t-\t-\tFAULTED\n"


def pools_con_uno_caido():
    lineas = dato("pools_hero").splitlines(True)
    assert lineas[0].startswith("zpool1\t")
    return POOL_CAIDO + "".join(lineas[1:])


def test_un_pool_que_no_se_puede_abrir_sale_con_las_cifras_sin_valor():
    (pool,) = p.pools(POOL_CAIDO)
    assert pool == {"pool": "zpool1", "bytes": None, "usado": None, "libre": None, "ocupacion_pct": None,
                    "dedup": None, "salud": "FAULTED"}


def test_el_resumen_de_hero_con_un_pool_caido_no_se_cae_y_conserva_el_aviso(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.POOLS.plantilla: pools_con_uno_caido(), dc.POOLS_ESTADO.plantilla: AUSENTE})
    d = datos(h.almacenamiento_resumen("hero"))
    assert algun(d["avisos"], "zpool1", "UNAVAIL")
    caido = por(d["pools"], "pool", "zpool1")
    assert (caido["salud"], caido["bytes"], caido["ocupacion_pct"]) == ("FAULTED", None, None)
    assert por(d["pools"], "pool", "zpool2")["ocupacion_pct"] == 21


# --- M11: volumen cifrado bloqueado en hero ------------------------------------------------------

def hero_con_zfs2_bloqueado(tmp_path, clave="unavailable", quitar_de_df=True):
    ds = dato("datasets_hero").splitlines(True)
    (i,) = [i for i, linea in enumerate(ds) if linea.startswith("zpool1/zfs2\t")]
    campos = ds[i].rstrip("\n").split("\t")
    campos[11], campos[12] = "aes-256-ccm", clave
    ds[i] = "\t".join(campos) + "\n"
    cambios = {dc.DATASETS.plantilla: "".join(ds)}
    if quitar_de_df:
        cambios[dc.OCUPACION.plantilla] = "".join(
            linea for linea in dato("ocupacion_hero").splitlines(True) if "ZFS2_DATA" not in linea)
    return uno(tmp_path, cambios=cambios)[0]


@pytest.mark.parametrize("clave", ["unavailable", "unavail", "otra cosa"])
def test_el_resumen_de_hero_avisa_de_un_volumen_cifrado_que_no_esta_montado(tmp_path, clave):
    d = datos(hero_con_zfs2_bloqueado(tmp_path, clave).almacenamiento_resumen("hero"))
    assert algun(d["avisos"], "ZFS2_DATA", "no esta montado", "clave no esta cargada")


def test_volumenes_de_hero_avisa_de_un_volumen_cifrado_que_no_esta_montado(tmp_path):
    d = datos(hero_con_zfs2_bloqueado(tmp_path).volumenes("hero"))
    assert algun(d["avisos"], "ZFS2_DATA", "no esta montado")
    assert por(d["volumenes"]["filas"], "dataset", "zpool1/zfs2")["clave"] == "unavailable"


def test_un_volumen_que_df_no_ve_se_avisa_aunque_no_este_cifrado(tmp_path):
    h = hero_con_zfs2_bloqueado(tmp_path)
    d = datos(h.almacenamiento_resumen("hero"))
    assert algun(d["avisos"], "ZFS2_DATA", "no esta montado")
    h, _ = uno(tmp_path, cambios={dc.OCUPACION.plantilla: "".join(
        linea for linea in dato("ocupacion_hero").splitlines(True) if "ZFS3_DATA" not in linea)})
    d = datos(h.almacenamiento_resumen("hero"))
    assert algun(d["avisos"], "ZFS3_DATA", "no esta montado") and not algun(d["avisos"], "ZFS3_DATA", "clave")


def test_un_volumen_cifrado_con_la_clave_cargada_no_da_aviso(tmp_path):
    h = hero_con_zfs2_bloqueado(tmp_path, clave="avail", quitar_de_df=False)
    assert not algun(datos(h.almacenamiento_resumen("hero"))["avisos"], "ZFS2_DATA")
    assert datos(h.volumenes("hero"))["avisos"] == []


def test_con_los_datos_reales_de_hero_ningun_volumen_sale_como_no_montado(tmp_path):
    h, _ = uno(tmp_path)
    assert not algun(datos(h.almacenamiento_resumen("hero"))["avisos"], "no esta montado")
    assert datos(h.volumenes("hero"))["avisos"] == []


def test_si_df_no_se_lee_volumenes_de_hero_sigue_y_lo_dice(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.OCUPACION.plantilla: FALLIDO})
    d = datos(h.volumenes("hero"))
    assert "ocupacion" in d["errores"] and d["avisos"] == [] and d["volumenes"]["total"] == 12


# --- L16: un bloque que fallo no es un cero --------------------------------------------------------

def test_carpetas_compartidas_sin_nfs_ni_enlaces_no_da_ceros(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_NFS.plantilla: FALLIDO, dc.CARPETAS_ENLACES.plantilla: FALLIDO})
    d = datos(h.carpetas_compartidas("hero"))
    assert {"nfs", "enlaces"} <= set(d["errores"])
    assert d["nfs_exportadas"] is None and d["sin_smb"] is None


def test_carpetas_compartidas_con_todo_leido_sigue_dando_cuentas(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.carpetas_compartidas("hero"))
    assert isinstance(d["nfs_exportadas"], int) and isinstance(d["sin_smb"], list) and "errores" not in d


# --- L17: lo que no se pudo leer sale tambien en los avisos ------------------------------------------

def test_qts_sin_dmsetup_avisa_de_que_faltan_avisos(tmp_path):
    h, _ = uno(tmp_path, "qts", cambios={dc.DM_ESTADO.plantilla: FALLIDO})
    d = datos(h.almacenamiento_resumen("qts"))
    assert "pools_ligeros" in d["errores"]
    assert algun(d["avisos"], "no se ha podido leer todo", "errores")


def test_qts_sin_volume_conf_avisa_de_que_faltan_avisos_de_volumen(tmp_path):
    sin_tercero = "".join(linea for linea in OCUPACION_QTS.splitlines(True) if "cachedev3" not in linea)
    h, _ = uno(tmp_path, "qts", cambios={dc.OCUPACION.plantilla: sin_tercero})
    assert algun(datos(h.almacenamiento_resumen("qts"))["avisos"], "no esta montado")
    h, _ = uno(tmp_path, "qts", cambios={dc.OCUPACION.plantilla: sin_tercero, dc.VOLUMENES_CONF.plantilla: FALLIDO})
    d = datos(h.almacenamiento_resumen("qts"))
    assert "nombres_de_volumen" in d["errores"] and algun(d["avisos"], "no se ha podido leer todo")


def test_sin_errores_no_hay_aviso_de_lectura(tmp_path):
    for sistema in ("hero", "qts"):
        h, _ = uno(tmp_path, sistema)
        d = datos(h.almacenamiento_resumen(sistema))
        assert "errores" not in d and not algun(d["avisos"], "no se ha podido")


# --- L18: la medicion no depende de las etiquetas --------------------------------------------------

def test_rendimiento_sin_qcli_storage_conserva_la_medicion(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.DISCOS_LISTA.plantilla: FALLIDO})
    d = datos(h.rendimiento_discos("hero"))
    assert "discos_lista" in d["errores"] and d["discos"]
    assert all(f["puerto"] is None for f in d["discos"]) and any(f["bahia"] is not None for f in d["discos"])


def test_rendimiento_sin_el_detalle_conserva_la_medicion(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.DISCOS_DETALLE.plantilla: FALLIDO})
    d = datos(h.rendimiento_discos("hero"))
    assert "discos_detalle" in d["errores"] and d["discos"]
    assert all(f["bahia"] is None and f["modelo"] is None for f in d["discos"])


def test_rendimiento_sin_diskstats_sigue_cayendo_entero(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.DISKSTATS.plantilla: FALLIDO})
    (r,) = h.rendimiento_discos("hero")
    assert r["ok"] is False


def test_rendimiento_con_todo_leido_no_trae_errores(tmp_path):
    h, _ = uno(tmp_path)
    assert "errores" not in datos(h.rendimiento_discos("hero"))


# --- L22 (discos): el mensaje habla de cabina, no de bahia -----------------------------------------

@pytest.mark.parametrize("cabina, bahia, quien", [(-1, 3, "cabina"), (1000, 3, "cabina"), (0, -1, "bahia"),
                                                  (True, 3, "cabina")])
def test_disco_smart_dice_que_numero_no_vale(tmp_path, cabina, bahia, quien):
    h, mundo = uno(tmp_path)
    (r,) = h.disco_smart("hero", bahia, cabina=cabina)
    assert r["ok"] is False and r["error"].startswith("%s debe ser un numero" % quien), r["error"]
    assert "se esperaba" not in r["error"] and mundo.conexiones == 0


# --- L29: un fichero SMART a medio escribir no tumba el de los demas discos --------------------------

def smart_con_un_fichero_vacio():
    return dato("smart_todos_hero") + "== /tmp/smart/smart_0_99.info\n"


def test_smart_todos_aisla_un_fichero_vacio():
    r = p.smart_todos(smart_con_un_fichero_vacio())
    malo = por(r, "bahia", 99)
    assert malo["temperatura"] is None and malo["atributos"] == [] and malo["error"]
    sanos = [x for x in r if x["bahia"] != 99]
    assert len(sanos) == 8
    assert all("error" not in x for x in sanos)


def test_smart_todos_aisla_una_linea_cortada():
    texto = dato("smart_todos_hero").rstrip("\n").rsplit(",", 3)[0] + "\n"
    r = p.smart_todos(texto)
    assert len(r) == 8 and sum(1 for x in r if "error" in x) == 1


def test_smart_todos_sigue_rechazando_lo_que_no_es_un_listado():
    with pytest.raises(ValueError):
        p.smart_todos("ls: /tmp/smart/: Permission denied\n")


def test_discos_fisicos_con_el_fichero_de_un_disco_ilegible_avisa_de_ese_disco(tmp_path):
    texto = dato("smart_todos_hero")
    vacio = texto.replace(texto[texto.index("== /tmp/smart/smart_0_3.info"):texto.index("== /tmp/smart/smart_0_4.info")],
                          "== /tmp/smart/smart_0_3.info\n")
    h, _ = uno(tmp_path, cambios={dc.SMART_TODOS.plantilla: vacio})
    d = datos(h.discos_fisicos("hero"))
    filas = d["discos"]["filas"]
    malo = next(f for f in filas if (f["cabina"], f["bahia"]) == (0, 3))
    assert malo["temperatura"] is None and algun(malo["avisos"], "datos SMART no se han podido leer")
    assert sum(1 for f in filas if f["temperatura"] is not None) == 7
    assert "smart" not in d.get("errores", {})


def test_una_temperatura_rara_en_una_bahia_vacia_no_tumba_la_salud():
    base = dato("discos_salud_hero")
    texto = base.replace("== 1\nmodelo=--\ntemperatura=-- C/-- F", "== 1\nmodelo=--\ntemperatura=--", 1)
    assert texto != base
    assert len(p.discos_salud(texto)) == len(p.discos_salud(base))


def test_una_temperatura_rara_en_una_bahia_ocupada_sigue_siendo_un_error():
    base = dato("discos_salud_hero")
    texto = base.replace("temperatura=38 C/100 F", "temperatura=38", 1)
    assert texto != base
    with pytest.raises(ValueError):
        p.discos_salud(texto)


# --- L30: Fail, Error y needs_check de device-mapper ---------------------------------------------

def con_linea(linea):
    return dato("dm_estado_qts") + linea + "\n"


@pytest.mark.parametrize("linea, nombre", [
    ("vg9-tp9-tpool: 0 1000 thin-pool Error", "vg9-tp9-tpool"),
    ("vg9-tp9-tpool: 0 1000 thin-pool Fail", "vg9-tp9-tpool"),
    ("vg9-lv9: 0 1000 cache Fail", "vg9-lv9"),
    ("vg9-lv9: 0 1000 cache Error", "vg9-lv9")])
def test_fail_y_error_del_kernel_no_rompen_el_parseo(linea, nombre):
    dm = p.dm_estado(con_linea(linea))
    malo = por(dm, "nombre", nombre)
    assert malo["fallo"] is True
    assert (malo.get("datos_pct"), malo.get("usado_pct"), malo.get("metadatos_pct")) == (None, None, None)


def test_las_lineas_sanas_siguen_sin_fallo_ni_comprobacion():
    dm = p.dm_estado(dato("dm_estado_qts"))
    for d in dm:
        if d["tipo"] in ("thin-pool", "cache"):
            assert d["fallo"] is False and d["necesita_comprobar"] is False


def test_needs_check_se_lee_en_el_pool_y_en_la_cache_sin_depender_de_la_posicion():
    base = dato("dm_estado_qts")
    pool = base.replace(" - 1024", " needs_check 1024")
    cache = base.replace("rw - ", "rw needs_check ")
    assert pool != base and cache != base
    assert por(p.dm_estado(pool), "tipo", "thin-pool")["necesita_comprobar"] is True
    assert por(p.dm_estado(cache), "tipo", "cache")["necesita_comprobar"] is True
    # una marca propia de QNAP al final no se confunde con needs_check
    assert por(p.dm_estado(base), "tipo", "thin-pool")["necesita_comprobar"] is False


@pytest.mark.parametrize("antes, despues, trozos", [
    (" - 1024", " needs_check 1024", ("vg1", "needs_check")),
    ("rw - ", "rw needs_check ", ("cache SSD", "needs_check")),
    ("cache 8 2022/3932160 2048 77972/77972 0 1 metadata2 2 migration_threshold 2048 rw - ", "cache Fail",
     ("cache SSD", "en fallo"))])
def test_los_avisos_de_volumenes_recogen_needs_check_y_la_cache_en_fallo(tmp_path, antes, despues, trozos):
    dm = dato("dm_estado_qts")
    assert dm.count(antes) == 1
    h, _ = uno(tmp_path, "qts", cambios={dc.DM_ESTADO.plantilla: dm.replace(antes, despues)})
    assert algun(datos(h.volumenes("qts"))["avisos"], *trozos)
    assert algun(datos(h.almacenamiento_resumen("qts"))["avisos"], *trozos)


def test_una_cache_en_fallo_no_tira_los_datos_de_los_pools(tmp_path):
    dm = dato("dm_estado_qts").replace(
        "cache 8 2022/3932160 2048 77972/77972 0 1 metadata2 2 migration_threshold 2048 rw - ", "cache Fail")
    h, _ = uno(tmp_path, "qts", cambios={dc.DM_ESTADO.plantilla: dm})
    d = datos(h.volumenes("qts"))
    assert "errores" not in d and d["pools"][0]["datos_pct"] == 51.4


# --- M6: la marca no_probado sale de Comando.no_probado, no de cada herramienta --------------------

class _Flota:
    def lanzar(self, nas, comando, valores=None):
        return "salida"


class _Contexto:
    flota = _Flota()

    def sanear(self, texto):
        return texto


def test_todo_comando_no_probado_marca_su_resultado_si_es_un_dict():
    base = servidor.Base(_Contexto())
    marcado, normal = Comando("marcado", "echo x", no_probado=True), Comando("normal", "echo y")
    assert base._leer("nas", marcado, lambda s: {"a": 1}) == {"a": 1, "no_probado": True}
    assert base._opcional("nas", marcado, lambda s: {"a": 1}) == {"a": 1, "no_probado": True}
    errores = {}
    assert base._extra("nas", errores, "x", marcado, lambda s: {"a": 1}) == {"a": 1, "no_probado": True}
    assert base._leer("nas", normal, lambda s: {"a": 1}) == {"a": 1}
    assert base._leer("nas", marcado, lambda s: [1, 2]) == [1, 2]       # solo se marcan los dict


def test_la_marca_no_hace_pasar_un_error_por_datos():
    class Cae(_Flota):
        def lanzar(self, nas, comando, valores=None):
            raise servidor.ErrorComando("sin respuesta")

    class Ctx(_Contexto):
        flota = Cae()

    base = servidor.Base(Ctx())
    marcado = Comando("marcado", "echo x", no_probado=True)
    errores = {}
    assert base._extra("nas", errores, "x", marcado, lambda s: {}) is None and "x" in errores


def test_los_avisos_smart_configurados_llevan_la_marca_en_las_dos_herramientas(tmp_path):
    h, _ = uno(tmp_path)
    assert datos(h.disco_smart("hero", 3))["avisos_configurados"]["no_probado"] is True
    assert dc.SMART_UMBRALES.no_probado and dc.ISCSI_QTS.no_probado


def test_iscsi_de_qts_sigue_marcado_aunque_la_herramienta_ya_no_lo_ponga(tmp_path):
    h, _ = uno(tmp_path, "qts")
    assert datos(h.iscsi("qts"))["no_probado"] is True
    h, _ = uno(tmp_path)
    assert "no_probado" not in datos(h.iscsi("hero"))
