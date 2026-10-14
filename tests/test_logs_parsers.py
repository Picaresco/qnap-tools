# -*- coding: utf-8 -*-
"""Parsers de los tres registros del NAS (eventos, accesos y avisos) sobre salidas reales
anonimizadas: *_hero.txt de un QuTS hero de laboratorio y *_qts.txt de un QTS de pruebas.
Lo escrito a mano se indica."""
from pathlib import Path

import pytest

from qnap_tools.logs import parsers as p

DATOS = Path(__file__).parent / "datos" / "logs"
FIN = "Done. Return value is 0\n"
CAB_EVT = ("event_id,event_type,event_date,event_time,event_user,event_ip,event_comp,event_desc,event_msgid,"
           "event_timet,event_app_id,event_app_name,event_category_id,event_category,event_client_id,"
           "event_client_app,event_client_agent,\n")
CAB_CONN = ("conn_id,conn_type,conn_date,conn_time,conn_user,conn_ip,conn_comp,conn_res,conn_serv,conn_action,"
            "conn_app,conn_action_result,conn_client_id,conn_client_app,conn_client_agent,\n")
CAB_NOTICE = ("id,severity,server,action,serviceName,facility,time,endtime,user,ip,client,desc,msgCode,varNum,"
              "varContent,name,status,uid,gid,link_id,link_option,title,\n")


def dato(nombre):
    return (DATOS / (nombre + ".txt")).read_text(encoding="utf-8")


def por_id(filas, id_):
    (x,) = [x for x in filas if x["id"] == id_]
    return x


# ==== eventos ===================================================================================

def test_la_lista_de_eventos_da_cada_fila_con_sus_columnas():
    filas = p.evt_lista(dato("evt_lista_hero"))
    assert len(filas) == 20 and [f["id"] for f in filas] == sorted((f["id"] for f in filas), reverse=True)
    assert filas[0] == {
        "id": 3770, "fecha": "2026-10-14 03:01:01", "gravedad": "informacion", "usuario": None, "ip": None,
        "equipo": "localhost", "aplicacion": "Malware Remover", "categoria": "General",
        "descripcion": "[Malware Remover] Scan completed.", "cliente": "localhost"}


def test_una_fila_de_evento_con_el_agente_del_navegador_partido_por_comas_se_lee_entera():
    # el agente de usuario lleva "(KHTML, like Gecko)": la coma no puede mover las columnas
    f = por_id(p.evt_lista(dato("evt_lista_hero")), 3760)
    assert f["descripcion"] == '[User Groups] Edited the permission settings of user group "texto4".'
    assert f["usuario"] == "admin" and f["ip"] == "192.0.2.2" and f["equipo"] is None
    assert f["aplicacion"] == "User Groups" and f["cliente"] == "carpeta7 Desktop"


def test_la_lista_de_eventos_de_un_qts_y_la_busqueda_por_texto():
    filas = p.evt_lista(dato("evt_lista_qts"))
    assert len(filas) == 20
    f = por_id(filas, 47572)
    assert f["descripcion"].startswith("[Storage & Snapshots] Reached volume/LUN snapshot limit.")
    assert f["categoria"] == "Snapshot"
    encontrados = p.evt_lista(dato("evt_palabra_qts"))
    assert encontrados and all("Storage" in f["descripcion"] for f in encontrados)


def test_la_descripcion_de_un_evento_se_reconstruye_aunque_lleve_comas():
    # a mano: comas en la descripcion y en el agente a la vez
    fila = ("5,  1,2026-10-14,03:00:00,pepe,192.0.2.1,equipo1,[App] uno, dos, tres.,  7,1791939600,A1,App,"
            "C001,General,---,carpeta1 Desktop,Mozilla/5.0 (KHTML, like Gecko) Chrome/1,\n")
    (f,) = p.evt_lista("Query database...\n" + CAB_EVT + fila + FIN)
    assert f["descripcion"] == "[App] uno, dos, tres." and f["gravedad"] == "aviso"
    assert f["aplicacion"] == "App" and f["cliente"] == "carpeta1 Desktop"


def test_una_linea_que_no_empieza_por_un_id_es_la_continuacion_de_la_anterior():
    # a mano: una descripcion con un salto de linea dentro
    filas = ("6,  2,2026-10-14,03:00:00,---,---,localhost,[App] primera parte\n"
             "segunda parte., 19,1791939600,A1,App,C001,General,---,localhost,---,\n"
             "5,  0,2026-10-14,02:00:00,---,---,localhost,[App] otra., 19,1791939600,A1,App,C001,General,---,"
             "localhost,---,\n")
    uno, dos = p.evt_lista("Query database...\n" + CAB_EVT + filas + FIN)
    assert uno["descripcion"] == "[App] primera parte segunda parte." and uno["gravedad"] == "error"
    assert dos["id"] == 5 and dos["descripcion"] == "[App] otra."


def test_las_columnas_se_toman_de_la_cabecera_y_no_de_su_posicion():
    # a mano: otra version de la utilidad que pusiera el usuario detras de la ip
    cabecera = CAB_EVT.replace("event_user,event_ip,", "event_ip,event_user,")
    fila = "5,  0,2026-10-14,03:00:00,192.0.2.1,pepe,localhost,[App] x., 19,1791939600,A1,App,C001,General,---,localhost,---,\n"
    (f,) = p.evt_lista(cabecera + fila + FIN)
    assert f["usuario"] == "pepe" and f["ip"] == "192.0.2.1"


def test_una_gravedad_desconocida_se_da_con_su_codigo():
    fila = "5,  7,2026-10-14,03:00:00,---,---,localhost,[App] x., 19,1791939600,A1,App,C001,General,---,localhost,---,\n"
    (f,) = p.evt_lista(CAB_EVT + fila + FIN)
    assert f["gravedad"] == "7"


@pytest.mark.parametrize("salida", [
    "",                                                       # no respondio
    "Query database...\n" + CAB_EVT,                          # se corto antes del final
    "Query database...\nDone. Return value is -1\n",          # la utilidad dice que fallo
    "Open database fail\nDone. Return value is 0\n",          # algo que no es una consulta
    CAB_EVT + "5,  0,2026-10-14,03:00:00,---,---\n" + FIN,     # fila con menos columnas
    CAB_EVT + "hola\n" + FIN,                                 # continuacion sin fila delante
])
def test_lo_que_no_es_una_respuesta_completa_de_la_utilidad_es_un_error(salida):
    with pytest.raises(ValueError):
        p.evt_lista(salida)


def test_sin_resultados_la_utilidad_solo_imprime_la_linea_final_y_eso_es_una_lista_vacia():
    # medido en un NAS real: una consulta sin filas no imprime ni la cabecera
    salida = "Query database search count [3]...\n\t date1 [2099-01-01]...\n\t date2 [2099-12-31]...\n" + FIN
    assert p.evt_lista(salida) == []


def test_el_recuento_de_eventos_resta_la_linea_final_y_da_el_primero_y_el_ultimo():
    r = p.evt_recuento(dato("evt_recuento_hero"))
    assert r["por_gravedad"] == {"informacion": 3720, "aviso": 34, "error": 16}
    assert r["primero"]["id"] == 1 and r["primero"]["fecha"] == "2026-01-15 22:14:18"
    assert r["ultimo"]["id"] == 3770
    q = p.evt_recuento(dato("evt_recuento_qts"))
    assert q["por_gravedad"] == {"informacion": 46177, "aviso": 530, "error": 868}
    assert q["primero"]["fecha"] < q["ultimo"]["fecha"]


def test_un_registro_de_eventos_vacio_no_tiene_primero_ni_ultimo():
    salida = ("==gravedad 1 1\n==gravedad 2 1\n==gravedad 3 1\n==primero\nQuery database...\n" + FIN
              + "==ultimo\nQuery database...\n" + FIN)
    assert p.evt_recuento(salida) == {"por_gravedad": {"informacion": 0, "aviso": 0, "error": 0},
                                      "primero": None, "ultimo": None}


@pytest.mark.parametrize("cambio", [
    ("==gravedad 2 35", "==gravedad 2 0"),      # sin la linea final: la utilidad no respondio
    ("==gravedad 3 17\n", ""),                  # falta una gravedad
    ("==ultimo", "==final"),                    # falta una parte
    ("==gravedad 3 17", "==gravedad 4 17"),     # gravedad que no se pidio
])
def test_un_recuento_incompleto_es_un_error(cambio):
    with pytest.raises(ValueError):
        p.evt_recuento(dato("evt_recuento_hero").replace(*cambio))


# ==== accesos ===================================================================================

def test_la_lista_de_accesos_da_servicio_y_accion_con_su_nombre_y_su_codigo():
    filas = p.conn_lista(dato("conn_lista_hero"))
    assert len(filas) == 20
    assert filas[0] == {
        "id": 15487, "fecha": "2026-10-14 04:27:20", "tipo": "informacion", "usuario": "usuario1",
        "ip": "192.0.2.2", "equipo": None, "recurso": None, "servicio": "SSH (7)",
        "accion": "inicio de sesion (10)", "aplicacion": None, "cliente": None}
    assert filas[1]["accion"] == "cierre de sesion (11)"


def test_los_accesos_de_un_qts_y_sus_extremos():
    filas = p.conn_lista(dato("conn_lista_qts"))
    assert por_id(filas, 18434571)["servicio"] == "SAMBA (1)" and por_id(filas, 18434571)["equipo"] == "equipo2"
    e = p.conn_extremos(dato("conn_extremos_qts"))
    assert e["primero"]["recurso"] == "carpeta28/usuario1/ruta1.pst"
    assert e["primero"]["accion"] == "escribir (3)" and e["primero"]["fecha"] == "2026-04-30 11:05:52"
    assert e["ultimo"]["id"] == 18434571


def test_un_acceso_con_comas_en_el_recurso_y_codigos_desconocidos():
    # a mano
    fila = "9,1,2026-10-14,03:00:00,pepe,192.0.2.1,equipo1,carpeta1/a, b.txt,42,99,---,0,---,---,---,\n"
    (f,) = p.conn_lista("Query database...\n" + CAB_CONN + fila + FIN)
    assert f["recurso"] == "carpeta1/a, b.txt" and f["tipo"] == "aviso"
    assert f["servicio"] == "42" and f["accion"] == "99"


def test_sin_accesos_la_lista_esta_vacia_y_sin_final_es_un_error():
    assert p.conn_lista("Query database...\n" + FIN) == []
    assert p.conn_extremos("==primero\nQuery database...\n" + FIN + "==ultimo\nQuery database...\n" + FIN) == {
        "primero": None, "ultimo": None}
    with pytest.raises(ValueError):
        p.conn_lista("Query database...\n" + CAB_CONN)
    with pytest.raises(ValueError):
        p.conn_extremos("==primero\nQuery database...\n" + FIN)


# ==== avisos ====================================================================================

def test_la_lista_de_avisos_da_la_fecha_en_utc():
    filas = p.notice_lista(dato("notice_lista_hero"))
    assert len(filas) == 20
    # el mismo momento que el evento 3770 de la lista de eventos (03:01:01 en la hora del NAS, +02:00)
    assert filas[0] == {
        "id": 5750, "fecha": "2026-10-14T01:01:01Z", "gravedad": "informacion", "origen": "0",
        "servicio": None, "accion": None, "usuario": "System", "ip": "127.0.0.1", "equipo": "localhost",
        "descripcion": "[Malware Remover] Scan completed.", "aplicacion": None, "codigo": None}


def test_un_aviso_de_acceso_fallido_lleva_servicio_y_accion():
    f = por_id(p.notice_lista(dato("notice_lista_hero")), 5748)
    assert f["gravedad"] == "aviso" and f["origen"] == "registro de accesos (9)"
    assert f["servicio"] == "SSH (7)" and f["accion"] == "inicio de sesion fallido (9)"
    assert f["descripcion"] == "usuario1 Login Fail (SSH/SFTP)"


def test_la_descripcion_de_un_aviso_se_reconstruye_aunque_lleve_comas():
    f = por_id(p.notice_lista(dato("notice_lista_hero")), 5736)
    assert f["descripcion"] == "App Center Finish booting process, begin to install/update application(s)..."
    assert f["origen"] == "sistema (17)" and f["aplicacion"] == "QPKGD_BOOTING" and f["codigo"] == "MSG_SY_004"
    q = p.notice_lista(dato("notice_lista_qts"))
    assert por_id(q, 26114229)["descripcion"].endswith("RAID group: 1, Blocks repaired: 0.")
    assert por_id(q, 26114229)["origen"] == "almacenamiento (12)"
    assert por_id(q, 26114225)["gravedad"] == "0"


def test_la_hora_de_un_aviso_no_depende_del_cambio_de_hora():
    # a mano: un aviso de enero (10:00:00 en la hora del NAS, +01:00)
    fila = "1,  3,  0,  0,System, 17,1768899600,1768899600,System,127.0.0.1,localhost,[x] y.,  0,  0,   ,   ,  0, -1,100,   ,   ,   ,\n"
    (f,) = p.notice_lista("Query database...\n" + CAB_NOTICE + fila + FIN)
    assert f["fecha"] == "2026-01-20T09:00:00Z" and f["gravedad"] == "error"


def test_una_lista_de_avisos_sin_su_linea_final_es_un_error():
    with pytest.raises(ValueError):
        p.notice_lista("Query database...\n" + CAB_NOTICE)


def test_el_resumen_de_avisos_cuenta_por_gravedad_y_por_origen():
    r = p.notice_resumen(dato("notice_resumen_hero"))
    assert r == {
        "total": 247,
        "por_gravedad": {"error": 4, "aviso": 6, "5": 1, "informacion": 236},
        "por_origen": {"registro de eventos (8)": 8, "registro de accesos (9)": 2, "aplicaciones (13)": 167,
                       "0": 4, "10": 4, "sistema (17)": 40, "noticias (20)": 17, "tareas (99)": 5}}
    q = p.notice_resumen(dato("notice_resumen_qts"))
    assert q["total"] == 10000 and q["por_gravedad"]["aviso"] == 9967


def test_un_resumen_de_avisos_sin_avisos_o_sin_final():
    assert p.notice_resumen("      1 Done. Return value is 0\n") == {"total": 0, "por_gravedad": {}, "por_origen": {}}
    with pytest.raises(ValueError):
        p.notice_resumen("      4   3,  8\n")
    with pytest.raises(ValueError):
        p.notice_resumen("      4   3,  8\n      1 Done. Return value is 1\n")


# ==== kernel ====================================================================================

def test_los_niveles_del_kernel_van_con_su_nombre_y_su_numero():
    n = p.kmsg_niveles(dato("kmsg_niveles_hero"))
    assert n == {"lineas": 4293, "desde": "2026-09-27 23:20:37 +02:00",
                 "por_nivel": {"alerta (1)": 4, "error (3)": 20, "aviso (4)": 885, "nota (5)": 240,
                               "informacion (6)": 2362, "depuracion (7)": 782},
                 "sin_nivel": 0}
    q = p.kmsg_niveles(dato("kmsg_niveles_qts"))
    assert q["por_nivel"]["critico (2)"] == 10 and q["sin_nivel"] == 0


def test_un_registro_del_kernel_vacio_o_que_no_se_pudo_leer():
    assert p.kmsg_niveles("==lineas 0 /etc/logs/kmsg\n==primera\n==niveles\n") == {
        "lineas": 0, "desde": None, "por_nivel": {}, "sin_nivel": 0}
    with pytest.raises(ValueError):
        p.kmsg_niveles("==lineas\n==primera\n==niveles\n")       # wc no pudo leer el fichero


def test_las_ultimas_lineas_del_kernel_con_su_fecha_su_nivel_y_su_cuenta():
    k = p.kmsg_lineas(dato("kmsg_lineas_hero"))
    assert k["total"] == 24 and len(k["lineas"]) == 20
    assert k["lineas"][-1] == {"fecha": "2026-10-13 17:14:39 +02:00", "nivel": "error (3)",
                               "texto": "failed to prefill DIMM database from DMI data"}
    assert k["lineas"][-3]["texto"] == "kvm_amd: CPU 1 isn't AMD or Hygon"
    q = p.kmsg_lineas(dato("kmsg_lineas_qts"))
    assert q["total"] == 189 and any(x["nivel"] == "critico (2)" for x in q["lineas"])


def test_una_linea_del_kernel_se_acota_y_pierde_los_caracteres_de_control():
    # a mano: texto de un dispositivo con caracteres de control y muy largo
    linea = "2026-10-13 17:14:03 +02:00 <3> [   1.0] usb: \x1b[31mrojo\x07 " + "x" * 400
    k = p.kmsg_lineas("==lineas 1\n" + linea + "\n")
    (x,) = k["lineas"]
    assert "\x1b" not in x["texto"] and "\x07" not in x["texto"] and len(x["texto"]) <= p.MAX_TEXTO
    assert x["texto"].startswith("usb:")


def test_una_linea_del_kernel_sin_el_formato_de_siempre_llega_tal_cual():
    k = p.kmsg_lineas("==lineas 1\notra cosa <3> rara\n")
    assert k["lineas"] == [{"fecha": None, "nivel": None, "texto": "otra cosa <3> rara"}]


def test_sin_la_cuenta_las_lineas_del_kernel_son_un_error():
    with pytest.raises(ValueError):
        p.kmsg_lineas("2026-10-13 17:14:03 +02:00 <3> [   1.0] x\n")
    with pytest.raises(ValueError):
        p.kmsg_lineas("==lineas \n")


def test_la_cola_del_kernel_en_vivo():
    d = p.dmesg(dato("dmesg_hero"))
    assert d["total"] == 1932 and len(d["lineas"]) == 20
    assert d["lineas"][-1] == {"segundos": 35571.237288,
                               "texto": "ext2 filesystem being mounted at /tmp/config supports timestamps "
                                        "until 2038-01-19 (0x7fffffff)"}
    assert p.dmesg(dato("dmesg_qts"))["total"] == 3646
    with pytest.raises(ValueError):
        p.dmesg("==lineas 0\n")          # un kernel en marcha siempre tiene mensajes


# ==== hardware ==================================================================================

def test_los_sensores_dan_grados_y_vueltas():
    assert p.sensores(dato("sensores_hero")) == {
        "cpu_c": 56, "sistema_c": 41, "ventiladores": [{"ventilador": 1, "rpm": 1368}]}
    q = p.sensores(dato("sensores_qts"))
    assert [v["ventilador"] for v in q["ventiladores"]] == [1, 2, 3, 4] and q["cpu_c"] == 38


def test_un_ventilador_parado_es_un_dato_y_no_un_error():
    s = p.sensores("cpu=50 C/122 F\nsistema=40 C/104 F\nventiladores=1\nventilador1=0 RPM\n")
    assert s["ventiladores"] == [{"ventilador": 1, "rpm": 0}]


@pytest.mark.parametrize("salida", [
    # lo que da getsysinfo sin privilegios de root (medido en los dos NAS)
    "cpu=\nsistema=0 C/32 F\nventiladores=1\nventilador1=0 RPM\n",
    "cpu=56 C/132 F\nsistema=0 C/32 F\nventiladores=1\nventilador1=1368 RPM\n",
    "cpu=56 C/132 F\nsistema=--\nventiladores=1\nventilador1=1368 RPM\n",
    "cpu=56 C/132 F\nsistema=41 C/106 F\nventiladores=1\nventilador1=--\n",
    "cpu=56 C/132 F\nsistema=41 C/106 F\nventiladores=1\nventilador1=\n",
    "cpu=56 C/132 F\nsistema=41 C/106 F\nventiladores=2\nventilador1=1368 RPM\n",   # falta uno
    "cpu=56 C/132 F\nsistema=41 C/106 F\nventiladores=\n",
])
def test_los_centinelas_de_getsysinfo_son_un_error_y_no_cero_grados(salida):
    with pytest.raises(ValueError):
        p.sensores(salida)


def test_las_cabinas_con_su_estado():
    c = p.chasis(dato("chasis_hero"))
    assert [x["cabina"] for x in c] == [0, 23, 32, 33]
    assert c[0] == {"cabina": 0, "id": "root", "fabricante": "QNAP", "modelo": "TS-h686", "estado": 0,
                    "protocolo": 0, "bahias": 8, "ventiladores": 1, "sensores_temperatura": 1}
    assert p.chasis(dato("chasis_qts"))[0]["ventiladores"] == 4
    with pytest.raises(ValueError):
        p.chasis("=====\n=====\n")


def test_las_fuentes_que_tiene_el_modelo():
    assert p.fuentes(dato("fuentes_hero")) == {"fuentes": 1, "redundantes": False}
    assert p.fuentes(dato("fuentes_qts")) == {"fuentes": 2, "redundantes": True}
    assert p.fuentes("fuentes=1\nredundante=\n") == {"fuentes": 1, "redundantes": None}
    with pytest.raises(ValueError):
        p.fuentes("fuentes=\nredundante=0\n")


def test_un_sai_desactivado_frente_a_uno_que_no_responde_y_a_uno_en_servicio():
    s = p.sai(dato("sai_hero"))
    assert s == {"estado": "desactivado", "modelo": "PhxTec-A1000", "red": "OK", "bateria": "OK",
                 "apagar_en_min": 5, "sais": [], "error": "Error: Connection failure: Connection refused"}
    # a mano: activado y el servicio no contesta, o contesta con un SAI
    activo = dato("sai_hero").replace("activo=FALSE", "activo=TRUE")
    assert p.sai(activo)["estado"] == "no responde"
    en_servicio = activo.replace("Error: Connection failure: Connection refused\n==rc 1", "qnapups\n==rc 0")
    s = p.sai(en_servicio)
    assert s["estado"] == "responde" and s["sais"] == ["qnapups"] and s["error"] is None
    assert p.sai("activo=\nmodelo=\nred=\nbateria=\napagar_en=\n==upsc\n==rc 0\n")["estado"] == "sin configurar"
    with pytest.raises(ValueError):
        p.sai("activo=FALSE\n")                          # se corto antes de upsc


# ==== sistema ===================================================================================

def test_la_carga_y_la_memoria():
    c = p.carga(dato("carga_hero"))
    assert c == {"encendido_s": 41669, "carga": [0.82, 0.77, 0.91], "hilos": 4,
                 "memoria": {"total": 32771296 * 1024, "disponible": 7547544 * 1024,
                             "intercambio": 63736824 * 1024, "intercambio_libre": 63736824 * 1024}}
    assert p.carga(dato("carga_qts"))["encendido_s"] == 4049086
    with pytest.raises(ValueError):
        p.carga("==encendido\n==carga\n==hilos 4\n==memoria\n")


def test_el_firmware_instalado_y_las_fechas_de_comprobacion_y_actualizacion():
    assert p.firmware(dato("firmware_hero")) == {
        "version": "6.0.2", "compilacion": "20260819", "ultima_comprobacion": "2026-10-13 18:37:30",
        "ultima_actualizacion": "2026-08-27 01:14:39", "comprobacion_automatica": True}
    f = p.firmware("version=5.2.9\ncompilacion=20260514\ncomprobado=\nactualizado=\ncomprobar=\n")
    assert f["ultima_comprobacion"] is None and f["comprobacion_automatica"] is None
    with pytest.raises(ValueError):
        p.firmware("version=\ncompilacion=\ncomprobado=\nactualizado=\ncomprobar=\n")


def test_la_politica_de_actualizacion_automatica():
    a = p.firmware_auto(dato("firmware_auto_hero"))
    assert a == {"configurada": True, "importantes": True, "recomendadas": True, "ultimas": True,
                 "version": 3, "modo": 2, "modo_v3": 1,
                 "programa": {"tipo": 0, "hora": "23:00", "dia_semana": 1, "dia": 1}}
    vacia = "leido=5.2.9\n" + "".join("%s=\n" % k for k in ("importantes", "recomendadas", "ultimas", "version",
                                                             "modo", "modo_v3", "programa", "hora", "minuto",
                                                             "dia_semana", "dia"))
    assert p.firmware_auto(vacia) == {"configurada": False}
    with pytest.raises(ValueError):
        p.firmware_auto(vacia.replace("leido=5.2.9", "leido="))      # uLinux.conf no se pudo leer


def test_las_aplicaciones_de_registro_y_seguridad():
    a = p.apps(dato("apps_hero"))
    assert a["paquetes"] == 18
    assert a["apps"][0] == {"nombre": "QuLog", "instalada": True, "version": "3.0.1.1061", "activa": True}
    assert {"nombre": "SecurityCounselor", "instalada": False, "version": None, "activa": None} in a["apps"]
    with pytest.raises(ValueError):
        p.apps("==paquetes 0\nQuLog\n")              # qpkg.conf no se pudo leer


def test_los_motores_de_registro_en_marcha():
    m = p.motores(dato("motores_hero"))
    assert m == {"rsyslogd": 1, "qLogEngined": 1, "qNoticeEngined": 1, "qulogd": 2, "qulogdb": 1, "ncdb": 1}
    assert p.motores("  PID  Uid     VmSize Stat Command\n") == {
        "rsyslogd": 0, "qLogEngined": 0, "qNoticeEngined": 0, "qulogd": 0, "qulogdb": 0, "ncdb": 0}
    with pytest.raises(ValueError):
        p.motores("")                                # ps no respondio


def test_los_volcados_de_cuelgues_guardados():
    v = p.volcados(dato("volcados_hero"))
    assert v["volcados"][0] == {"fichero": "pstore_1_202608270120.log", "fecha": "2026-08-27 01:20", "bytes": 504645}
    assert [x["fecha"] for x in v["volcados"]] == sorted((x["fecha"] for x in v["volcados"]), reverse=True)
    assert v["procesos_forzados_al_apagar"] == {"fecha": "2026-09-28T22:17:00Z", "bytes": 126}
    q = p.volcados(dato("volcados_qts"))
    assert len(q["volcados"]) == 4 and q["volcados"][-1]["fecha"] == "2020-09-25 18:06"
    sin = p.volcados("4096 1635186683 /etc/logs/qsync\n")
    assert sin == {"volcados": [], "procesos_forzados_al_apagar": None}
    with pytest.raises(ValueError):
        p.volcados("")                               # stat no listo nada


# ==== alertas ===================================================================================

def test_la_configuracion_de_alertas():
    assert p.alertas(dato("alertas_hero")) == {"nivel": 0, "zumbador": True, "aviso_espacio_libre": True,
                                              "espacio_minimo_mb": 3072}
    assert p.alertas(dato("alertas_qts"))["nivel"] == 2
    with pytest.raises(ValueError):
        p.alertas("nivel=\nzumbador=\naviso_espacio=\nespacio_minimo=\n")


def test_el_servidor_syslog_solo_da_sus_claves_conocidas():
    s = p.syslog(dato("syslog_hero"))
    assert s == {"activo": True, "tcp": {"activo": True, "puerto": 514}, "udp": {"activo": True, "puerto": 514},
                 "mensajes_del_kernel": True, "fichero": {"carpeta": "carpeta1", "nombre": "messages", "tamano_mb": 50},
                 "aviso_por_correo": False}
    # a mano: una clave que no se conoce (p. ej. un destinatario) no sale nunca
    con_secreto = dato("syslog_hero") + "alert mail address = alguien@example.org\nalert mail password = x\n"
    assert p.syslog(con_secreto) == s
    assert p.syslog("") is None
    with pytest.raises(ValueError):
        p.syslog("[Global]\nalgo = x\n")


def test_una_descripcion_con_numeros_entre_comas_no_descuadra_las_columnas():
    # a mano: "1, 2, 3, 4" pareceria el codigo y la hora del evento si solo se miraran dos columnas
    fila = ("5,  2,2026-10-14,03:00:00,---,---,localhost,[Hardware] Disks 1, 2, 3, 4 removed., 19,1791939600,"
            "A227,Hardware,C001,General,---,localhost,Mozilla/5.0 (KHTML, like Gecko),\n")
    (f,) = p.evt_lista(CAB_EVT + fila + FIN)
    assert f["descripcion"] == "[Hardware] Disks 1, 2, 3, 4 removed."
    assert f["aplicacion"] == "Hardware" and f["categoria"] == "General" and f["cliente"] == "localhost"


def test_un_recurso_que_imita_las_columnas_siguientes_da_error_y_no_cambia_el_servicio_ni_la_accion():
    # a mano: un fichero que alguien llama "a,7,9,b.txt" no puede hacerse pasar por un acceso SSH fallido
    fila = "9,0,2026-10-14,03:00:00,usuario1,192.0.2.1,equipo1,carpeta1/a,7,9,b.txt,1,3,---,0,---,---,---,\n"
    with pytest.raises(ValueError):
        p.conn_lista(CAB_CONN + fila + FIN)
    # con comas que no imitan nada, el recurso sale entero
    fila = "9,0,2026-10-14,03:00:00,usuario1,192.0.2.1,equipo1,carpeta1/a, b.txt,1,3,---,0,---,---,---,\n"
    (f,) = p.conn_lista(CAB_CONN + fila + FIN)
    assert f["recurso"] == "carpeta1/a, b.txt" and f["servicio"] == "SAMBA (1)" and f["accion"] == "escribir (3)"


def test_el_cliente_de_un_evento_puede_ser_el_nombre_de_una_aplicacion():
    # a mano, con la forma de una fila real de Container Station: el cliente es la aplicacion
    fila = ('4001,  0,2026-05-05,10:20:30,admin,---,localhost,[Container Station] Stopped application '
            '"aplicacion1".,2026,1777969230,A214,Container Station,C002,Applications,aplicacion1,Container Station,'
            'Docker Compose version v1.2.3,\n')
    (f,) = p.evt_lista(CAB_EVT + fila + FIN)
    assert f["descripcion"] == '[Container Station] Stopped application "aplicacion1".'
    assert f["aplicacion"] == "Container Station" and f["categoria"] == "Applications"


def test_una_fila_que_se_puede_partir_de_dos_maneras_es_un_error_y_no_una_eleccion():
    # a mano: el recurso imita todas las columnas que lo siguen
    fila = "9,0,2026-10-14,03:00:00,usuario1,192.0.2.1,equipo1,a,7,9,x,0,---,b.txt,1,3,---,0,---,---,---,\n"
    with pytest.raises(ValueError):
        p.conn_lista(CAB_CONN + fila + FIN)


def test_la_hora_de_un_evento_tiene_que_cuadrar_con_su_fecha():
    # a mano: un "epoch" que no es el de la fecha de la fila no ancla la descripcion
    fila = ("5,  2,2026-10-14,03:00:00,---,---,localhost,[App] a, 7, 1700000000, b., 19,1791939600,A1,App,C001,"
            "General,---,localhost,---,\n")
    (f,) = p.evt_lista(CAB_EVT + fila + FIN)
    assert f["descripcion"] == "[App] a, 7, 1700000000, b." and f["aplicacion"] == "App"


def test_un_evento_sin_codigo_de_mensaje_se_lee():
    # a mano, con la forma de filas reales de QuTS hero: sin codigo, ni aplicacion ni categoria
    fila = ('4002,  0,2026-05-06,11:22:33,---,---,localhost,[Storage & Snapshots] Finished recycling dedup table '
            'of storage pool "texto1".,---,1778059353,---,---,---,---,---,localhost,---,\n')
    (f,) = p.evt_lista(CAB_EVT + fila + FIN)
    assert f["descripcion"].endswith('storage pool "texto1".') and f["aplicacion"] is None and f["categoria"] is None
