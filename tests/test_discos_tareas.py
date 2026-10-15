# -*- coding: utf-8 -*-
"""tareas_file_station: las tareas en segundo plano de File Station que hay en /tmp/wfm.

Los datos estan escritos a mano con el formato visto en el NAS de laboratorio (nombres de campo del
diseno), con rutas y usuarios inventados. El progreso se calcula (copied_size / total_size): el
percent de QNAP es otra cosa."""
import pytest

from test_discos_servidor import algun, dato, datos, dc, por, uno
from qnap_tools.discos import parsers as p


def tarea(pid, **cambios):
    """Un bloque de la salida de la orden, con los valores de una copia en curso salvo los que se cambien."""
    c = {"copy_file": "disco_01.img", "percent": "39.3", "copying": "1", "end_time": "1760003600",
         "speed": "115343360", "full_dest": "/share/VOL1_DATA/Vms/copia2/disco_01.img", "copy_number": "1",
         "files_count": "2", "copy_size": "50000000000", "copied_size": "60000000000",
         "average_speed": "100000000", "total_size": "80000000000", "total_number": "3",
         "from": "/Vms/origen", "to": "/Vms/copia2", "name": "origen"}
    remoto = {"source_path": "/Vms/origen", "dest_path": "/Vms/copia2", "mode": "0", "dup": "Copy",
              "username": "ana", "func": "copy"}
    lista = cambios.pop("lista", "%s|ana|q_from|q_to|0|0|q_name|11|0|0.0|1760003000|1760003000|-1|-1|--" % pid)
    vivo = cambios.pop("vivo", "1")
    remoto = cambios.pop("remoto", remoto)
    c.update(cambios)
    cuerpo = ["%s = %s" % (k, v) for k, v in c.items()] + ["==remote"] + ["%s = %s" % (k, v) for k, v in remoto.items()]
    return "\n".join(["== %s" % pid] + cuerpo + ["==lista"] + ([lista] if lista else []) + ["vivo=" + vivo]) + "\n"


def salida(*tareas):
    return "==wfm\n" + "".join(tareas)


# --- parser ----------------------------------------------------------------------------------------

def test_una_copia_en_curso_con_su_progreso_calculado():
    r = p.tareas_file_station(salida(tarea(4101)))
    (t,) = r["tareas"]["filas"]
    assert t["pid"] == 4101 and t["tipo"] == "copy" and t["estado"] == "en_curso" and t["proceso_vivo"] is True
    assert (t["bytes_total"], t["bytes_copiados"]) == (80000000000, 60000000000)
    assert t["progreso_pct"] == 75.0                              # no el 39.3 de percent
    assert t["velocidad_media"] == 100000000 and t["restante_s"] == 200
    assert (t["fichero_actual"], t["fichero_n"], t["ficheros_total"]) == ("disco_01.img", 1, 2)
    assert (t["usuario"], t["origen"], t["destino"], t["elemento"]) == ("ana", "/Vms/origen", "/Vms/copia2", "origen")
    assert t["ultima_actualizacion"] == "2025-10-09T09:53:20Z" and t["si_existe_destino"] == "Copy"
    assert t["inicio"] == "2025-10-09T09:43:20Z"
    assert "no_probado" not in t and r["avisos"] == [] and r["en_curso"] == 1


def test_la_copia_en_curso_de_la_muestra_real_sale_al_75_por_ciento():
    # muestra 2 de una copia real (nombres inventados): percent decia 39,3 y el progreso real es 75,1
    r = p.tareas_file_station(dato("tareas_file_station_hero"))
    t = por(r["tareas"]["filas"], "pid", 11895)
    assert (t["progreso_pct"], t["restante_s"], t["estado"], t["fichero_n"], t["ficheros_total"]) == (
        75.1, 352, "en_curso", 2, 3)
    assert t["bytes_total"] == 83398104076 and t["bytes_copiados"] == 62657991692
    assert t["destino_fichero"] == "/share/ZFS3_DATA/Maquinas/VM01/VM01_01-Copy(1).img"


def test_una_copia_terminada_sale_al_cien_por_cien_y_sin_restante():
    lista = "3990|ana|/Vms/origen|/Vms/copia|80000000000|3|Mis VMs|11|2|100.0|1760000000|1760000900|-1|-1|--"
    texto = salida(tarea(3990, copying="2", percent="100.0", copied_size="80000000000", vivo="0", lista=lista,
                         remoto={}, copy_number="2", copy_file="Mis VMs", end_time="1760000900",
                         **{"from": "/Vms/origen", "to": "/Vms/copia", "name": "Mis VMs"}))
    r = p.tareas_file_station(texto)
    (t,) = r["tareas"]["filas"]
    assert (t["estado"], t["progreso_pct"], t["restante_s"], t["proceso_vivo"]) == ("terminada", 100.0, None, False)
    # al terminar, wfm2_remote_parameter queda vacio: el tipo sale del codigo de la lista (11 = copia)
    assert t["tipo"] == "copy" and t["si_existe_destino"] is None and "no_probado" not in t
    assert r["en_curso"] == 0 and r["avisos"] == []


def test_una_tarea_terminada_con_otro_codigo_sale_no_probada():
    # visto en el NAS de laboratorio (nombres inventados): codigo 13 de /Vms a /Vms, 0 bytes y 4
    # elementos, recorriendo la carpeta de metadatos de una VM; no se sabe que operacion es
    lista = "21658|ana|/Vms|/Vms|0|4|q_name|13|2|100.0|1760000000|1760000000|-1|-1|--"
    bloque = ("== 21658\npid = 21658\ncopy_file = VM01\npercent = 100.0\ncopying = 2\nend_time = 1760000000\n"
              "speed = 0\nfiles_count = 4\ncopy_number = 4\ntotal_size = 0\ntotal_number = 4\nfrom = /Vms\n"
              "to = /Vms\nname = VM01\n==remote\n==lista\n%s\nvivo=0\n" % lista)
    (t,) = p.tareas_file_station("==wfm\n" + bloque)["tareas"]["filas"]
    assert (t["tipo"], t["estado"], t["no_probado"]) == ("codigo 13", "terminada", True)
    assert (t["bytes_total"], t["progreso_pct"], t["ficheros_total"]) == (0, None, 4)


def test_una_copia_cuyo_proceso_ya_no_esta_se_interrumpio():
    r = p.tareas_file_station(salida(tarea(4101, vivo="0")))
    (t,) = r["tareas"]["filas"]
    assert t["estado"] == "interrumpida" and t["restante_s"] is None and r["en_curso"] == 0
    assert algun(r["avisos"], "4101", "se interrumpio")


@pytest.mark.parametrize("copying", ["0", "3", "-1", "x"])
def test_un_estado_de_la_tarea_que_no_es_ni_en_curso_ni_terminada_se_interrumpio(copying):
    r = p.tareas_file_station(salida(tarea(7, copying=copying)))
    assert r["tareas"]["filas"][0]["estado"] == "interrumpida" and algun(r["avisos"], "se interrumpio")


def test_un_destino_renombrado_con_copy_avisa_de_que_no_sustituye_al_existente():
    r = p.tareas_file_station(salida(tarea(
        4101, full_dest="/share/VOL1_DATA/Vms/copia2/disco_01-Copy(1).img")))
    (t,) = r["tareas"]["filas"]
    assert t["copia_renombrada"] is True
    assert algun(r["avisos"], "4101", "ya tenia ese fichero", "no lo sustituye")


def test_una_copia_terminada_con_otro_nombre_tambien_lo_dice():
    r = p.tareas_file_station(salida(tarea(
        9, copying="2", vivo="0", full_dest="/share/VOL1_DATA/Vms/copia2/disco_01-Copy(2).img")))
    assert r["tareas"]["filas"][0]["copia_renombrada"] is True
    assert algun(r["avisos"], "tarea 9", "ya tenia ese fichero", "escribio una copia con otro nombre")


def test_sin_aviso_de_copia_renombrada_en_una_copia_normal():
    r = p.tareas_file_station(salida(tarea(4101)))
    assert r["tareas"]["filas"][0]["copia_renombrada"] is False and r["avisos"] == []


def test_la_ip_de_quien_lanzo_la_tarea_no_sale_aunque_estuviera_en_los_datos():
    texto = salida(tarea(4101, remoto={"source_path": "/Vms/origen", "dup": "Copy", "username": "ana",
                                       "func": "copy", "remote_addr": "192.0.2.77"}))
    import json
    assert "192.0.2.77" not in json.dumps(p.tareas_file_station(texto))


def test_una_tarea_que_no_es_copy_se_lee_pero_sale_no_probada():
    r = p.tareas_file_station(salida(tarea(55, remoto={"func": "move", "username": "ana", "dup": "Copy"})))
    (t,) = r["tareas"]["filas"]
    assert t["tipo"] == "move" and t["no_probado"] is True


def test_sin_tareas_y_sin_carpeta_de_file_station():
    assert p.tareas_file_station("==wfm\n")["tareas"] == {"filas": [], "total": 0, "truncado": False}
    r = p.tareas_file_station("==sin_wfm\n")
    assert r["tareas"]["total"] == 0 and r["en_curso"] == 0 and r["avisos"] == []


def test_las_tareas_salen_de_la_mas_reciente_a_la_mas_antigua():
    r = p.tareas_file_station(salida(tarea(1, end_time="1760000000"), tarea(2, end_time="1760009999"),
                                     tarea(3, end_time="1760005000")))
    assert [t["pid"] for t in r["tareas"]["filas"]] == [2, 3, 1]


def test_los_nombres_de_un_tercero_se_sanean_y_se_acotan():
    r = p.tareas_file_station(salida(tarea(1, copy_file="a\tb" + "x" * 900, name="n\x01m")))
    (t,) = r["tareas"]["filas"]
    assert "\t" not in t["fichero_actual"] and len(t["fichero_actual"]) <= p.MAX_RUTA_REAL and t["elemento"] == "n m"


def test_los_datos_que_faltan_salen_sin_valor_y_no_se_inventan_ceros():
    sueltos = {k: "" for k in ("copied_size", "total_size", "average_speed", "end_time")}
    r = p.tareas_file_station(salida(tarea(1, **sueltos)))
    (t,) = r["tareas"]["filas"]
    assert t["progreso_pct"] is None and t["restante_s"] is None and t["ultima_actualizacion"] is None


@pytest.mark.parametrize("texto", [
    "", "ls: /tmp/wfm: No such file\n", "==wfm\nsuelto=1\n", "==wfm\n== abc\n", "==wfm\n== 5\nvivo=quizas\n",
    "==wfm\n== 5\ncopy_file=x\n", "==wfm\n== 5\nno es una clave\nvivo=1\n"])
def test_tareas_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.tareas_file_station(texto)


# --- herramienta -----------------------------------------------------------------------------------

def test_tareas_file_station_en_hero_da_la_terminada_y_la_que_sigue_en_curso(tmp_path):
    h, mundo = uno(tmp_path)
    d = datos(h.tareas_file_station("hero"))
    assert d["en_curso"] == 1 and d["tareas"]["total"] == 2
    en_curso = por(d["tareas"]["filas"], "pid", 11895)
    assert (en_curso["estado"], en_curso["progreso_pct"], en_curso["restante_s"]) == ("en_curso", 75.1, 352)
    assert por(d["tareas"]["filas"], "pid", 11790)["estado"] == "terminada"
    assert algun(d["avisos"], "11895", "no lo sustituye")                    # full_dest -Copy(1)
    assert (dc.TAREAS_FILE_STATION.render(), False) in mundo.ordenes         # sin sudo


def test_tareas_file_station_sin_file_station_es_una_lista_vacia_y_no_un_error(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.tareas_file_station("qts"))
    assert d["tareas"]["total"] == 0 and d["en_curso"] == 0


def test_tareas_file_station_con_una_salida_ilegible_es_un_error(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.TAREAS_FILE_STATION.plantilla: "algo raro\n"})
    (r,) = h.tareas_file_station("hero")
    assert r["ok"] is False and "tareas_file_station" in r["error"]


def test_los_datos_de_prueba_de_las_tareas_no_llevan_ip_ni_datos_reales():
    texto = dato("tareas_file_station_hero")
    import re
    assert not re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", texto) and "remote_addr" not in texto
