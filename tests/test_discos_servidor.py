# -*- coding: utf-8 -*-
"""Las 9 herramientas de qnap-discos sobre dos NAS simulados (un QuTS hero y un QTS) que
responden con salidas reales anonimizadas. Lo que no hay capturado de QTS (df con las
opciones del producto, instantaneas, contadores de disco) se suple aqui y asi se indica."""
import asyncio
import dataclasses
import re
from pathlib import Path

import pytest

import falsos
from test_discos_parsers import AUSENTE, DEGRADADO, INSTANTANEAS_QTS, SIN_PRIVILEGIOS
from qnap_tools import inventario as inv
from qnap_tools import servidor
from qnap_tools.comandos import Comando
from qnap_tools.deteccion import DETECCION
from qnap_tools.discos import comandos as dc
from qnap_tools.discos import servidor as discos_srv
from qnap_tools.inventario import Nas
from qnap_tools.transporte import Conexion

DATOS = Path(__file__).parent / "datos"
ENTORNO = {"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto"}
SMART_UNO = re.compile(r"^cat /tmp/smart/smart_([0-9]+)_([0-9]+)\.info$")
# escrito a mano con el formato visto en el QTS de pruebas: sus volumenes y, por cada carpeta
# de /share que no es un montaje, el tmpfs de /share
OCUPACION_QTS = (
    "Filesystem           1024-blocks    Used Available Capacity Mounted on\n"
    "/dev/mapper/cachedev1 3624002472 960495816 2663506656  27% /share/CACHEDEV1_DATA\n"
    "/dev/mapper/cachedev3 2113653512 1711559300 402094212  84% /share/CACHEDEV3_DATA\n"
    "/dev/mapper/cachedev4 1064194024 850501160 213692864  80% /share/CACHEDEV4_DATA\n"
    "tmpfs                    16384         0     16384   0% /share\n"
    "tmpfs                    16384         0     16384   0% /share\n")
LLAMADAS = {"almacenamiento_resumen": (), "discos_fisicos": (), "disco_smart": (3,), "raid_estado": (),
            "volumenes": (), "snapshots": (), "carpetas_compartidas": (), "iscsi": (),
            "rendimiento_discos": ()}


def dato(nombre):
    return (DATOS / "discos" / (nombre + ".txt")).read_text(encoding="utf-8")


def sin_captura(sistema):
    """Salidas de las ordenes de las que no hay captura de ese sistema."""
    if sistema == "hero":
        return {}
    return {"ocupacion": OCUPACION_QTS, "lvm_snapshots": INSTANTANEAS_QTS, "diskstats": dato("diskstats_hero")}


def smart_de(sistema):
    """Responde a 'cat smart_<cabina>_<bahia>.info' con el bloque de ese disco de la captura."""
    bloques, actual = {}, None
    for linea in dato("smart_todos_" + sistema).splitlines(True):
        if linea.startswith("== "):
            actual = bloques.setdefault(linea.strip()[3:], [])
        else:
            actual.append(linea)

    def responde(orden, sudo):
        ruta = orden.split(" ", 1)[1]
        if ruta not in bloques:
            return 1, "", "cat: %s: No such file or directory\n" % ruta
        return "".join(bloques[ruta])
    return responde


def nas_simulado(sistema, **extra):
    """Un NAS simulado: a cada orden de su sistema responde con su salida real."""
    respuestas = {DETECCION.render(): (DATOS / ("deteccion_%s.txt" % sistema)).read_text(encoding="utf-8")}
    suplidas = sin_captura(sistema)
    for comando in vars(dc).values():
        if not isinstance(comando, Comando) or comando.sistema not in ("ambos", sistema) or comando.params:
            continue
        fichero = DATOS / "discos" / ("%s_%s.txt" % (comando.id, sistema))
        respuestas[comando.render()] = (
            fichero.read_text(encoding="utf-8") if fichero.exists() else suplidas[comando.id])
    respuestas[SMART_UNO] = smart_de(sistema)
    return falsos.Mundo(respuestas, **extra)


def montar(tmp_path, mundos, entorno=None):
    """Herramientas de discos sobre NAS simulados: un Mundo por nombre de NAS."""
    entorno = dict(ENTORNO if entorno is None else entorno, QNAP_TOOLS_DATA=str(tmp_path))

    def fabrica(nas, cfg):
        return Conexion(nas, cfg, fabrica=mundos[nas.nombre].cliente)
    ctx = servidor.Contexto(entorno, fabrica_conexion=fabrica)
    nas = {n: Nas(n, "192.0.2.%d" % (i + 10)) for i, n in enumerate(sorted(mundos))}
    inv.guardar(Path(tmp_path) / "inventario.toml", nas)
    return discos_srv.Herramientas(ctx)


def uno(tmp_path, sistema="hero", cambios=None):
    """Un solo NAS simulado; 'cambios' sustituye la respuesta a algunas ordenes (por su texto)."""
    mundo = nas_simulado(sistema)
    for orden, respuesta in (cambios or {}).items():
        assert orden in mundo.respuestas, orden
        mundo.respuestas[orden] = respuesta
    return montar(tmp_path, {sistema: mundo}), mundo


def datos(resultado):
    (r,) = resultado
    assert r["ok"] is True, r
    return r["datos"]


def por(lista, clave, valor):
    (x,) = [x for x in lista if x[clave] == valor]
    return x


def en(lista, cabina, bahia):
    (x,) = [x for x in lista if (x["cabina"], x["bahia"]) == (cabina, bahia)]
    return x


def algun(avisos, *trozos):
    return any(all(t in a for t in trozos) for a in avisos)


def mdstat_degradado():
    """El mdstat del QTS de pruebas con el grupo de datos sin su cuarto disco y reconstruyendo."""
    texto = dato("mdstat_qts")
    assert "sdf3[10] " in texto and "[7/7] [UUUUUUU]" in texto
    return texto.replace("sdf3[10] ", "").replace(
        "[7/7] [UUUUUUU]",
        "[7/6] [UUU_UUU]\n      [==>..................]  recovery = 12.3% (359795712/2920311296) "
        "finish=412.8min speed=103354K/sec")


# --- lo que vale para todas ---------------------------------------------------------------------

def test_cada_herramienta_responde_en_los_dos_sistemas_y_solo_lanza_ordenes_del_suyo(tmp_path):
    mundos = {"hero": nas_simulado("hero"), "qts": nas_simulado("qts")}
    h = montar(tmp_path, mundos)
    assert sorted(LLAMADAS) == sorted(discos_srv.HERRAMIENTAS)
    for nombre, extra in LLAMADAS.items():
        r = getattr(h, nombre)("todos", *extra)
        assert [(e["nas"], e["ok"]) for e in r] == [("hero", True), ("qts", True)], (nombre, r)
    for sistema, mundo in mundos.items():
        suyas = {c.render() for c in vars(dc).values()
                 if isinstance(c, Comando) and not c.params and c.sistema in ("ambos", sistema)}
        suyas.add(DETECCION.render())
        for orden, _ in mundo.ordenes:
            assert orden in suyas or SMART_UNO.match(orden), (sistema, orden)
        assert mundo.conexiones == 1          # todas por la misma conexion


def test_el_servidor_solo_lanza_ordenes_definidas_y_con_sudo_solo_las_marcadas(tmp_path):
    mundos = {"hero": nas_simulado("hero"), "qts": nas_simulado("qts")}
    h = montar(tmp_path, mundos)
    for nombre, extra in LLAMADAS.items():
        getattr(h, nombre)("todos", *extra)
    definidas = {c.render(): c.sudo for c in vars(dc).values() if isinstance(c, Comando) and not c.params}
    definidas[DETECCION.render()] = False
    for mundo in mundos.values():
        for orden, sudo in mundo.ordenes:
            if SMART_UNO.match(orden):
                assert sudo is dc.SMART_ATRIBUTOS.sudo is True
            else:
                assert orden in definidas and definidas[orden] is sudo, orden


def test_no_hay_ninguna_orden_de_discos_que_no_use_alguna_herramienta(tmp_path):
    mundos = {"hero": nas_simulado("hero"), "qts": nas_simulado("qts")}
    h = montar(tmp_path, mundos)
    for nombre, extra in LLAMADAS.items():
        getattr(h, nombre)("todos", *extra)
    lanzadas = {s: {orden for orden, _ in m.ordenes} for s, m in mundos.items()}
    sin_uso = []
    for nombre, c in vars(dc).items():
        if not isinstance(c, Comando):
            continue
        for sistema in ("hero", "qts"):
            if c.sistema not in ("ambos", sistema):
                continue
            usada = (any(SMART_UNO.match(o) for o in lanzadas[sistema]) if c.params
                     else c.render() in lanzadas[sistema])
            if not usada:
                sin_uso.append((nombre, sistema))
    assert sin_uso == []


def test_el_servidor_registra_las_nueve_herramientas_con_descripcion(tmp_path):
    mcp = discos_srv.construir(dict(ENTORNO, QNAP_TOOLS_DATA=str(tmp_path)))
    herramientas = asyncio.run(mcp.list_tools())
    assert sorted(t.name for t in herramientas) == [
        "almacenamiento_resumen", "carpetas_compartidas", "disco_smart", "discos_fisicos", "iscsi",
        "raid_estado", "rendimiento_discos", "snapshots", "volumenes"]
    assert all(t.description and len(t.description) > 40 for t in herramientas)
    assert all("nas" in t.inputSchema["required"] for t in herramientas)
    (smart,) = [t for t in herramientas if t.name == "disco_smart"]
    assert set(smart.inputSchema["properties"]) == {"nas", "bahia", "cabina"}
    assert smart.inputSchema["required"] == ["nas", "bahia"]


def test_el_servidor_arranca_aunque_falte_la_credencial():
    assert len(asyncio.run(discos_srv.construir({}).list_tools())) == 9


def test_un_nas_desconocido_y_la_falta_de_credencial_se_dicen_en_el_error(tmp_path):
    h, _ = uno(tmp_path)
    (r,) = h.discos_fisicos("otro")
    assert r["ok"] is False and "otro" in r["error"]
    sin = montar(tmp_path, {"hero": nas_simulado("hero")}, entorno={})
    (r,) = sin.volumenes("hero")
    assert r["ok"] is False and "contrasena" in r["error"].lower()


def test_la_contrasena_no_sale_en_un_error(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.DISCOS_LISTA.plantilla: (1, "", "fallo raro con secreto dentro\n")})
    (r,) = h.discos_fisicos("hero")
    assert r["ok"] is False and "secreto" not in r["error"] and "***" in r["error"]


# --- discos_fisicos -----------------------------------------------------------------------------

def test_discos_fisicos_reune_todo_lo_que_se_sabe_de_cada_disco(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.discos_fisicos("hero"))
    assert d["discos"]["total"] == 8 and "errores" not in d
    assert en(d["discos"]["filas"], 0, 3) == {
        "cabina": 0, "bahia": 3, "puerto": "3", "unidad": "NAS_HOST", "dispositivo": "/dev/sda",
        "tipo": "SSD", "uso": "data", "bus": "sata", "fabricante": "WDC", "modelo": "WDS500G1R0A-68A4W0",
        "serie": "SERIE0001", "firmware": "411000WR", "bytes": 976773168 * 512, "rpm": None,
        "temperatura": 38, "smart": "GOOD", "vida_usada_pct": 0, "grupo": "vdev_1", "raid": "RAID 1",
        "pool": 1, "avisos": []}
    nvme = en(d["discos"]["filas"], 23, 1)
    assert (nvme["puerto"], nvme["bus"], nvme["uso"], nvme["temperatura"], nvme["vida_usada_pct"]) == (
        "P2-1", "nvme", "cache", 53, 22)
    # el veredicto del NAS solo existe para las bahias de la cabina principal
    assert nvme["smart"] is None and (nvme["grupo"], nvme["pool"]) == ("vdev_3", 256)
    assert d["resumen"] == {"total": 8, "por_tipo": {"HDD": 4, "SSD": 4}, "por_uso": {"cache": 2, "data": 6},
                            "con_aviso": 0}


def test_discos_fisicos_separa_los_discos_externos(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.discos_fisicos("hero"))
    assert d["externos"] == [{"cabina": 33, "bahia": 1, "dispositivo": "/dev/sdh", "bus": "usb",
                              "fabricante": "Seagate", "modelo": "Portable", "bytes": 9767541167 * 512}]


def test_discos_fisicos_en_qts_con_repuesto_y_cache_interna(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.discos_fisicos("qts"))
    assert d["discos"]["total"] == 10 and len(d["externos"]) == 2
    repuesto = en(d["discos"]["filas"], 0, 8)
    assert (repuesto["uso"], repuesto["grupo"], repuesto["pool"], repuesto["smart"]) == ("spare", None, None, "GOOD")
    cache = en(d["discos"]["filas"], 23, 2)
    assert (cache["puerto"], cache["grupo"], cache["vida_usada_pct"], cache["temperatura"]) == (
        "C2", "/dev/md2", 72, 33)
    assert en(d["discos"]["filas"], 0, 1)["grupo"] == "/dev/md1"
    assert d["resumen"]["por_uso"] == {"cache": 2, "data": 7, "spare": 1}


def test_getsysinfo_sin_privilegios_sale_como_error_en_su_bloque_y_no_como_cero_grados(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.DISCOS_SALUD.plantilla: SIN_PRIVILEGIOS})
    d = datos(h.discos_fisicos("hero"))
    assert "privilegios" in d["errores"]["veredicto"]
    assert all(x["smart"] is None for x in d["discos"]["filas"])
    # la temperatura sale de los ficheros SMART, que si se han leido
    assert en(d["discos"]["filas"], 0, 3)["temperatura"] == 38


def test_sin_sudo_los_discos_salen_sin_temperatura_y_el_error_se_dice(tmp_path):
    negado = (1, "", "Permission denied\n")
    h, _ = uno(tmp_path, cambios={dc.DISCOS_SALUD.plantilla: negado, dc.SMART_TODOS.plantilla: negado})
    d = datos(h.discos_fisicos("hero"))
    assert set(d["errores"]) == {"veredicto", "smart"}
    assert d["discos"]["total"] == 8
    assert all(x["temperatura"] is None and x["smart"] is None for x in d["discos"]["filas"])
    assert en(d["discos"]["filas"], 0, 3)["modelo"] == "WDS500G1R0A-68A4W0"


def test_un_disco_con_sectores_pendientes_o_mal_veredicto_lleva_su_aviso(tmp_path):
    smart = dato("smart_todos_hero")
    pendiente = "197,Current_Pending_Sector,100,100,0,0,0\n"
    assert pendiente in smart
    h, _ = uno(tmp_path, cambios={
        dc.SMART_TODOS.plantilla: smart.replace(pendiente, "197,Current_Pending_Sector,100,100,0,8,0\n", 1),
        dc.DISCOS_SALUD.plantilla: dato("discos_salud_hero").replace("smart=GOOD", "smart=WARNING", 1)})
    d = datos(h.discos_fisicos("hero"))
    assert en(d["discos"]["filas"], 0, 5)["avisos"] == ["8 sectores pendientes"]
    assert algun(en(d["discos"]["filas"], 0, 3)["avisos"], "WARNING")
    assert d["resumen"]["con_aviso"] == 2


def test_un_atributo_bajo_su_umbral_y_un_ssd_gastado_llevan_aviso(tmp_path):
    smart = dato("smart_todos_hero")
    reserva = "232,Available_Reservd_Space,100,100,4,100,0\n"
    assert reserva in smart
    h, _ = uno(tmp_path, cambios={
        dc.SMART_TODOS.plantilla: smart.replace(reserva, "232,Available_Reservd_Space,3,3,4,2,0\n", 1),
        dc.SSD_VIDA.plantilla: dato("ssd_vida_hero").replace("SSD_LIFE_USED = 32", "SSD_LIFE_USED = 95")})
    d = datos(h.discos_fisicos("hero"))
    assert algun(en(d["discos"]["filas"], 0, 3)["avisos"], "232", "umbral")
    assert algun(en(d["discos"]["filas"], 23, 2)["avisos"], "95 %")


def sin_bloque_smart(sistema, cabina, bahia):
    """La salida de SMART_TODOS sin el fichero de un disco."""
    return re.sub(r"== /tmp/smart/smart_%d_%d\.info\n(?:(?!== ).*\n)*" % (cabina, bahia), "",
                  dato("smart_todos_" + sistema))


def test_un_disco_sin_fichero_smart_lleva_su_aviso(tmp_path):
    smart = sin_bloque_smart("hero", 0, 5)
    assert "smart_0_5" not in smart and "smart_0_6" in smart
    h, _ = uno(tmp_path, cambios={dc.SMART_TODOS.plantilla: smart})
    d = datos(h.discos_fisicos("hero"))
    assert algun(en(d["discos"]["filas"], 0, 5)["avisos"], "sin datos SMART")
    assert en(d["discos"]["filas"], 0, 6)["avisos"] == []
    assert d["resumen"]["con_aviso"] == 1


def test_un_disco_de_la_cabina_principal_sin_veredicto_del_nas_lleva_su_aviso(tmp_path):
    salud = re.sub(r"== 5\nmodelo=[^\n]*\n", "== 5\nmodelo=--\n", dato("discos_salud_hero"))
    assert salud != dato("discos_salud_hero")
    h, _ = uno(tmp_path, cambios={dc.DISCOS_SALUD.plantilla: salud})
    d = datos(h.discos_fisicos("hero"))
    assert algun(en(d["discos"]["filas"], 0, 5)["avisos"], "veredicto SMART")
    # los NVMe de la ranura interna no tienen veredicto del NAS (getsysinfo solo ve la cabina 0)
    assert en(d["discos"]["filas"], 23, 1)["avisos"] == []
    assert d["resumen"]["con_aviso"] == 1


def test_sin_poder_leer_el_smart_no_se_avisa_disco_por_disco(tmp_path):
    negado = (1, "", "Permission denied\n")
    h, _ = uno(tmp_path, cambios={dc.DISCOS_SALUD.plantilla: negado, dc.SMART_TODOS.plantilla: negado})
    d = datos(h.discos_fisicos("hero"))
    assert d["resumen"]["con_aviso"] == 0 and set(d["errores"]) == {"veredicto", "smart"}


def test_sin_ningun_fichero_de_desgaste_con_ssd_presentes_se_dice_en_errores(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.SSD_VIDA.plantilla: ""})
    d = datos(h.discos_fisicos("hero"))
    assert "desgaste" in d["errores"]["vida_ssd"]
    assert all(x["vida_usada_pct"] is None for x in d["discos"]["filas"])


def test_un_ssd_sin_fichero_de_desgaste_entre_otros_que_lo_tienen_no_es_un_error(tmp_path):
    # en el QTS de pruebas una de las dos SSD de cache no tiene fichero de desgaste
    h, _ = uno(tmp_path, "qts")
    d = datos(h.discos_fisicos("qts"))
    assert "vida_ssd" not in d.get("errores", {})


# --- disco_smart --------------------------------------------------------------------------------

@pytest.mark.parametrize("bahia", ["1; reboot", -1, 1000, "", "3 4", None, True, 2.5, "$(reboot)"])
def test_disco_smart_rechaza_una_bahia_no_valida_sin_conectar(tmp_path, bahia):
    h, mundo = uno(tmp_path)
    (r,) = h.disco_smart("hero", bahia)
    assert r["ok"] is False and "bahia" in r["error"]
    assert mundo.conexiones == 0 and mundo.ordenes == []


def test_disco_smart_rechaza_una_cabina_no_valida_sin_conectar(tmp_path):
    h, mundo = uno(tmp_path)
    (r,) = h.disco_smart("hero", 3, cabina="0; reboot")
    assert r["ok"] is False and "cabina" in r["error"] and mundo.ordenes == []


def test_disco_smart_dice_que_bahias_hay_si_la_pedida_no_existe(tmp_path):
    h, mundo = uno(tmp_path)
    (r,) = h.disco_smart("hero", 9)
    assert r["ok"] is False
    assert "no hay disco en la cabina 0, bahia 9" in r["error"]
    assert "0/3, 0/4, 0/5, 0/6, 0/7, 0/8, 23/1, 23/2" in r["error"]
    assert not any(SMART_UNO.match(orden) for orden, _ in mundo.ordenes)


def test_disco_smart_da_los_atributos_de_un_disco_sata(tmp_path):
    h, mundo = uno(tmp_path)
    d = datos(h.disco_smart("hero", 3))
    assert d["disco"]["modelo"] == "WDS500G1R0A-68A4W0" and d["disco"]["puerto"] == "3"
    assert (d["clase"], d["temperatura"], len(d["atributos"]), d["en_aviso"], d["nvme"]) == ("ata", 38, 25, [], None)
    assert por(d["atributos"], "id", 194)["crudo"] == 38
    assert d["sectores"] == {"reasignados": 0}          # este SSD no da los otros dos contadores
    assert ("cat /tmp/smart/smart_0_3.info", True) in mundo.ordenes
    # los avisos por valor que tiene configurados el NAS, sin validar su significado
    assert d["avisos_configurados"]["no_probado"] is True
    assert [a["id"] for a in d["avisos_configurados"]["avisos"] if a["activo"]] == [197, 198]


def test_disco_smart_de_un_disco_duro_da_sus_contadores_de_sectores(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.disco_smart("qts", 1))
    assert d["sectores"] == {"reasignados": 0, "pendientes": 0, "incorregibles": 0}
    assert d["disco"]["dispositivo"] == "/dev/sdc" and d["temperatura"] == 32


def test_disco_smart_de_un_nvme_resume_su_registro_de_salud(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.disco_smart("hero", 1, cabina=23))
    assert (d["clase"], d["temperatura"], d["sectores"]) == ("nvme", 53, None)
    assert d["nvme"] == {"aviso_critico": 0, "reserva_pct": 100, "reserva_umbral_pct": 10, "desgaste_pct": 22,
                         "ciclos": 480, "horas": 5780, "apagados_bruscos": 14, "errores_de_medio": 0,
                         "entradas_de_error": 590}
    assert d["disco"]["puerto"] == "P2-1"


def test_disco_smart_marca_los_atributos_en_aviso(tmp_path):
    h, mundo = uno(tmp_path)
    mundo.respuestas[SMART_UNO] = (
        "3,0,0,100,0,0,0,0,40,0x0000,2,255,0\n5,Reallocated_Sector_Ct,5,5,10,812,0\n"
        "197,Current_Pending_Sector,100,100,0,8,0\n9,Power_On_Hours,100,100,0,5,0\n")
    d = datos(h.disco_smart("hero", 3))
    assert [a["id"] for a in d["en_aviso"]] == [5]
    assert d["sectores"] == {"reasignados": 812, "pendientes": 8}


def test_disco_smart_sin_poder_leer_el_fichero_es_un_error(tmp_path):
    h, mundo = uno(tmp_path)
    mundo.respuestas[SMART_UNO] = (1, "", "cat: /tmp/smart/smart_0_3.info: Permission denied\n")
    (r,) = h.disco_smart("hero", 3)
    assert r["ok"] is False and "smart_atributos" in r["error"]


# --- raid_estado --------------------------------------------------------------------------------

def test_raid_estado_en_hero_da_los_pools_con_sus_discos_por_bahia(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.raid_estado("hero"))
    assert d["sistema"] == "hero" and d["avisos"] == []
    assert [(x["pool"], x["interno"]) for x in d["pools"]] == [
        ("zpool1", False), ("zpool2", False), ("zpool256", True), ("zpoolExt2", True)]
    uno_ = por(d["pools"], "pool", "zpool1")
    assert uno_["estado"] == "ONLINE" and uno_["con_problemas"] == [] and uno_["tarea"]["tipo"] == "scrub"
    assert [(x["cabina"], x["bahia"]) for x in uno_["dispositivos"] if x["es_disco"]] == [(0, 3), (0, 4)]


def test_un_pool_degradado_se_destaca_en_raid_estado(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.POOLS_ESTADO.plantilla: DEGRADADO})
    d = datos(h.raid_estado("hero"))
    (pool,) = d["pools"]
    assert [x["nombre"] for x in pool["con_problemas"]] == [
        "raidz1-0", "replacing-1", "qzfs/enc_0/disk_0x2_SERIE0002_3"]
    assert algun(d["avisos"], "zpool1", "DEGRADED")
    assert algun(d["avisos"], "cabina 0, bahia 2", "FAULTED", "too many errors")
    assert algun(d["avisos"], "zpool1", "reconstruccion", "38.46")
    assert algun(d["avisos"], "zpool1", "errores de datos", "2 ficheros")
    # un disco de repuesto disponible o uno reconstruyendose no son un problema
    assert not algun(d["avisos"], "bahia 8") and not algun(d["avisos"], "cabina 1, bahia 4")


def test_raid_estado_en_qts_separa_los_grupos_de_datos_de_los_del_sistema(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.raid_estado("qts"))
    assert d["sistema"] == "qts" and d["avisos"] == []     # los huecos de md9 y md13 son normales
    assert [g["grupo"] for g in d["grupos"] if not g["sistema"]] == ["md2", "md1"]
    assert sorted(g["grupo"] for g in d["grupos"] if g["sistema"]) == ["md13", "md256", "md280", "md322", "md9"]
    md1 = por(d["grupos"], "grupo", "md1")
    assert (md1["id"], md1["nivel"], md1["estado"], md1["accion"], md1["discrepancias"]) == (
        1, "raid6", "clean", "idle", 0)
    assert (md1["esperados"], md1["presentes"], md1["mapa"], md1["degradado"], md1["faltan"]) == (
        7, 7, "UUUUUUU", False, [])
    assert sorted((m["cabina"], m["bahia"]) for m in md1["miembros"]) == [(0, n) for n in range(1, 8)]
    assert sorted((m["cabina"], m["bahia"]) for m in por(d["grupos"], "grupo", "md2")["miembros"]) == [(23, 1), (23, 2)]
    assert d["repuestos_globales"] == [{"cabina": 0, "bahia": 8}]


def test_un_grupo_md_degradado_se_destaca_y_dice_que_bahia_falta(tmp_path):
    h, _ = uno(tmp_path, "qts", cambios={dc.MDSTAT.plantilla: mdstat_degradado()})
    d = datos(h.raid_estado("qts"))
    md1 = por(d["grupos"], "grupo", "md1")
    assert (md1["degradado"], md1["presentes"], md1["faltan"]) == (True, 6, [{"cabina": 0, "bahia": 4}])
    assert md1["tarea"]["tipo"] == "recovery"
    assert algun(d["avisos"], "md1", "degradado", "6 de 7", "cabina 0, bahia 4")
    assert algun(d["avisos"], "md1", "reconstruccion", "12.3")
    assert not algun(d["avisos"], "md9") and not algun(d["avisos"], "md13")


def test_raid_estado_falla_si_no_puede_leer_el_estado(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.POOLS_ESTADO.plantilla: (1, "", "cannot open\n")})
    (r,) = h.raid_estado("hero")
    assert r["ok"] is False and "pools_estado" in r["error"]


# --- almacenamiento_resumen ---------------------------------------------------------------------

def test_el_resumen_de_hero_da_pools_volumenes_y_discos(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.almacenamiento_resumen("hero"))
    assert (d["sistema"], d["modelo"], d["firmware"]) == ("hero", "TS-X85", "6.0.2")
    assert por(d["pools"], "pool", "zpool1") == {
        "pool": "zpool1", "salud": "ONLINE", "bytes": 463856467968, "usado": 120933212160,
        "libre": 342923255808, "ocupacion_pct": 26, "interno": False}
    assert len(d["pools"]) == 4 and len(d["volumenes"]) == 12
    assert por(d["volumenes"], "volumen", "ZFS2_DATA") == {
        "volumen": "ZFS2_DATA", "bytes": 104857600 * 1024, "usado": 73338796 * 1024, "libre": 31518804 * 1024,
        "ocupacion_pct": 70}
    assert d["discos"] == {"total": 8, "por_tipo": {"HDD": 4, "SSD": 4}, "por_uso": {"cache": 2, "data": 6},
                           "con_aviso": 0}
    # lo unico que hay que mirar en este NAS: un volumen por encima del 80 %
    assert d["avisos"] == ["volumen ZFS19_DATA al 81 % de ocupacion"]


def test_el_resumen_de_qts_da_grupos_y_volumenes_con_su_nombre(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.almacenamiento_resumen("qts"))
    assert (d["sistema"], d["modelo"]) == ("qts", "TS-X83XU") and "pools" not in d
    assert d["grupos"] == [
        {"grupo": "md2", "nivel": "raid1", "bytes": 96539136 * 1024, "esperados": 2, "presentes": 2,
         "degradado": False, "tarea": None},
        {"grupo": "md1", "nivel": "raid6", "bytes": 14601556480 * 1024, "esperados": 7, "presentes": 7,
         "degradado": False, "tarea": None}]
    assert [(v["volumen"], v["nombre"], v["ocupacion_pct"]) for v in d["volumenes"]] == [
        ("CACHEDEV1_DATA", "volumen1", 27), ("CACHEDEV3_DATA", "volumen2", 84), ("CACHEDEV4_DATA", "volumen3", 80)]
    assert d["avisos"] == ["volumen CACHEDEV3_DATA (volumen2) al 84 % de ocupacion",
                           "volumen CACHEDEV4_DATA (volumen3) al 80 % de ocupacion"]
    assert d["discos"]["total"] == 10


def test_un_pool_degradado_y_un_disco_con_aviso_salen_en_los_avisos_del_resumen(tmp_path):
    pendiente = "197,Current_Pending_Sector,100,100,0,0,0\n"
    h, _ = uno(tmp_path, cambios={
        dc.POOLS_ESTADO.plantilla: DEGRADADO,
        dc.SMART_TODOS.plantilla: dato("smart_todos_hero").replace(pendiente, "197,Current_Pending_Sector,100,100,0,8,0\n", 1)})
    d = datos(h.almacenamiento_resumen("hero"))
    assert algun(d["avisos"], "zpool1", "DEGRADED") and algun(d["avisos"], "reconstruccion")
    assert algun(d["avisos"], "disco de la cabina 0, bahia 5", "8 sectores pendientes")
    assert d["discos"]["con_aviso"] == 1


def test_un_grupo_md_degradado_sale_en_los_avisos_del_resumen(tmp_path):
    h, _ = uno(tmp_path, "qts", cambios={dc.MDSTAT.plantilla: mdstat_degradado()})
    d = datos(h.almacenamiento_resumen("qts"))
    assert algun(d["avisos"], "md1", "degradado")
    assert por(d["grupos"], "grupo", "md1")["degradado"] is True


def test_el_resumen_dice_lo_que_no_ha_podido_mirar(tmp_path):
    negado = (1, "", "Permission denied\n")
    h, _ = uno(tmp_path, cambios={dc.DISCOS_SALUD.plantilla: negado, dc.SMART_TODOS.plantilla: negado})
    d = datos(h.almacenamiento_resumen("hero"))
    assert set(d["errores"]) == {"veredicto", "smart"}
    assert algun(d["avisos"], "no se ha podido comprobar", "discos")


@pytest.mark.parametrize("sistema", ["hero", "qts"])
def test_el_resumen_sin_la_lista_de_discos_da_igual_el_estado_de_la_redundancia(tmp_path, sistema):
    h, _ = uno(tmp_path, sistema, cambios={dc.DISCOS_LISTA.plantilla: (1, "", "qcli_storage: error\n")})
    d = datos(h.almacenamiento_resumen(sistema))
    assert "discos_lista" in d["errores"]["discos"]
    assert d["discos"] is None
    assert algun(d["avisos"], "no se ha podido", "discos")
    assert ("pools" in d) if sistema == "hero" else (len(d["grupos"]) == 2)
    assert len(d["volumenes"]) > 0


def test_el_resumen_con_un_grupo_degradado_y_sin_lista_de_discos_avisa_del_grupo(tmp_path):
    h, _ = uno(tmp_path, "qts", cambios={dc.MDSTAT.plantilla: mdstat_degradado(),
                                        dc.DISCOS_DETALLE.plantilla: (1, "", "")})
    d = datos(h.almacenamiento_resumen("qts"))
    assert algun(d["avisos"], "md1", "degradado") and "discos" in d["errores"]


def test_un_pool_casi_lleno_sale_en_los_avisos(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.POOLS.plantilla: dato("pools_hero").replace("\t26\t", "\t91\t")})
    d = datos(h.almacenamiento_resumen("hero"))
    assert algun(d["avisos"], "pool zpool1", "91 %")


# --- volumenes ----------------------------------------------------------------------------------

def test_volumenes_en_hero_da_las_carpetas_volumen_con_sus_propiedades(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.volumenes("hero"))
    assert d["sistema"] == "hero" and d["volumenes"]["total"] == 12 and "errores" not in d
    assert por(d["volumenes"]["filas"], "dataset", "zpool1/zfs2") == {
        "dataset": "zpool1/zfs2", "pool": "zpool1", "volumen": "ZFS2_DATA", "montaje": "/share/ZFS2_DATA",
        "bytes": 107374182400, "usado": 75098923008, "libre": 32275259392, "ocupacion_pct": 70,
        "cuota": 107374182400, "en_el_pool": 75099234304,
        "compresion": "on", "compresion_ratio": 1.1, "dedup": "off", "cifrado": False, "clave": None,
        "carpetas": ["carpeta1"]}
    # el tamano es lo que guarda mas lo que le queda libre: lo mismo que dice df
    libre = por(d["volumenes"]["filas"], "dataset", "zpool1/zfs24")
    assert libre["bytes"] == 1232789504 + 243462886524 and libre["ocupacion_pct"] == 1
    assert libre["cuota"] is None
    assert [z["dataset"] for z in d["volumenes_de_bloques"]] == ["zpool1/zvol_cs_docker", "zpool1/zvol_cs_system-docker"]
    assert d["internos"] == 18
    assert d["cache_ssd"] == [{"pool": "zpool256", "cabina": 23, "bahia": 1, "estado": "ONLINE"},
                              {"pool": "zpool256", "cabina": 23, "bahia": 2, "estado": "ONLINE"}]


def test_volumenes_en_qts_cruza_la_configuracion_con_la_ocupacion(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.volumenes("qts"))
    assert d["sistema"] == "qts" and d["volumenes"]["total"] == 3 and "errores" not in d
    assert d["avisos"] == []
    assert por(d["volumenes"]["filas"], "id", 2) == {
        "id": 2, "lv": 3, "nombre": "volumen2", "grupo": "/dev/md1", "pool": 1, "dispositivo": "/dev/mapper/cachedev3",
        "volumen": "CACHEDEV3_DATA", "montaje": "/share/CACHEDEV3_DATA", "bytes": 4294967296 * 512,
        "usado": 1711559300 * 1024, "libre": 402094212 * 1024, "ocupacion_pct": 84, "cifrado": False,
        "cache_ssd": True, "sucio": False, "solo_lectura": False, "estado": 0, "umbral_pct": 95,
        "sobre_umbral": False}
    assert d["pools"] == [{
        "id": 1, "nombre": "vg1", "bytes": 28773572608 * 512, "datos_pct": 51.4, "metadatos_pct": 1.1,
        "modo": "rw", "fallo": False, "umbral_pct": 95, "sobre_umbral": False, "reserva_instantaneas_pct": 10}]
    assert d["cache_ssd"] == {"usado_pct": 100.0, "metadatos_pct": 0.1, "bytes": 159686656 * 512}
    assert sorted(o["id"] for o in d["otros"]) == [4, 5, 7, 8]


def test_volumenes_en_qts_sin_sudo_no_da_la_ocupacion_de_los_pools_pero_si_lo_demas(tmp_path):
    h, _ = uno(tmp_path, "qts", cambios={dc.DM_ESTADO.plantilla: (1, "", "Permission denied\n")})
    d = datos(h.volumenes("qts"))
    assert "dm_estado" in d["errores"]["pools_ligeros"]
    assert d["pools"][0]["datos_pct"] is None and d["pools"][0]["bytes"] == 28773572608 * 512
    assert d["volumenes"]["total"] == 3 and d["cache_ssd"] is None


def test_un_volumen_cifrado_o_danado_se_ve_en_volumenes(tmp_path):
    conf = dato("volumenes_conf_qts")
    h, _ = uno(tmp_path, "qts", cambios={dc.VOLUMENES_CONF.plantilla: conf.replace(
        "encryption = no\nssdCache = no\nunclean = no", "encryption = yes\nssdCache = no\nunclean = yes", 1)})
    d = datos(h.volumenes("qts"))
    uno_ = por(d["volumenes"]["filas"], "id", 1)
    assert (uno_["cifrado"], uno_["sucio"]) == (True, True)


# --- snapshots ----------------------------------------------------------------------------------

def test_snapshots_en_hero_da_las_recientes_la_cuenta_y_la_programacion(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.snapshots("hero"))
    # 12 son las instantaneas iniciales que crea el propio NAS con cada carpeta
    assert (d["total"], d["internas"]) == (20, 12)
    assert d["recientes"]["total"] == 8 and d["recientes"]["truncado"] is False
    assert d["recientes"]["filas"][0] == {
        "volumen": "zpool1/zfs24", "instantanea": "snapshot7", "usado": 229376, "referido": 1232916480,
        "creada": "2026-10-13T22:00:03Z"}
    # lo retenido es lo que liberaria borrar las instantaneas (usedbysnapshots de cada dataset), no
    # la suma del "used" de cada una: lo que comparten dos instantaneas no cuenta en ninguna
    assert d["por_volumen"] == [
        {"volumen": "zpool1/zfs24", "instantaneas": 5, "ultima": "2026-10-13T22:00:03Z", "retenido_bytes": 154705920},
        {"volumen": "zpool2/zfs19", "instantaneas": 2, "ultima": "2026-09-24T23:36:21Z",
         "retenido_bytes": 66376134656},
        {"volumen": "zpool2/zfs20", "instantaneas": 1, "ultima": "2026-06-10T23:45:08Z",
         "retenido_bytes": 616824066048}]
    assert d["retenido_bytes"] == sum(int(linea.split("\t")[1]) for linea in dato("zfs_retenido_hero").splitlines())
    assert d["retenido_bytes"] > sum(int(linea.split("\t")[1]) for linea in dato("zfs_snapshots_hero").splitlines())
    assert [x["volumen"] for x in d["programacion"]["programaciones"]] == [19, 24]
    assert len(d["programacion"]["retenciones"]) == 12 and "nota" in d["programacion"]


def test_snapshots_en_hero_sin_poder_leer_lo_retenido_da_lo_demas_y_lo_dice(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.SNAPSHOTS_RETENIDO_HERO.plantilla: (1, "", "permission denied\n")})
    d = datos(h.snapshots("hero"))
    assert d["retenido_bytes"] is None and "retenido" in d["errores"]
    assert d["total"] == 20 and all(x["retenido_bytes"] is None for x in d["por_volumen"])


def test_snapshots_en_qts_pone_nombre_al_volumen(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.snapshots("qts"))
    assert (d["total"], d["internas"], d["retenido_bytes"]) == (3, 0, None)
    assert d["recientes"]["filas"][0] == {
        "volumen": 1, "nombre_volumen": "volumen1", "instantanea": "GMT+01_2026-10-13_1700",
        "creada": "2026-10-13T15:00:32Z", "caduca_min": None, "vital": True, "replicada": True}
    assert [(x["volumen"], x["nombre_volumen"], x["instantaneas"]) for x in d["por_volumen"]] == [
        (1, "volumen1", 1), (3, "volumen2", 1), (1056, None, 1)]
    assert [x["volumen"] for x in d["programacion"]["programaciones"]] == [1, 3]


def test_el_volumen_de_una_instantanea_de_qts_es_el_lv_de_la_herramienta_de_volumenes(tmp_path):
    # visto en un NAS real: el volumen con id 2 es el volumen logico 3, y las instantaneas dicen 3
    h, _ = uno(tmp_path, "qts")
    por_lv = {v["lv"]: v["nombre"] for v in datos(h.volumenes("qts"))["volumenes"]["filas"]}
    assert por_lv == {1: "volumen1", 3: "volumen2", 4: "volumen3"}
    con_nombre = [x for x in datos(h.snapshots("qts"))["por_volumen"] if x["nombre_volumen"]]
    assert len(con_nombre) == 2 and all(por_lv[x["volumen"]] == x["nombre_volumen"] for x in con_nombre)


@pytest.mark.parametrize("sistema, lista, programa", [
    ("hero", dc.SNAPSHOTS_HERO, dc.SNAPSHOTS_PROG_HERO), ("qts", dc.SNAPSHOTS_QTS, dc.SNAPSHOTS_PROG_QTS)])
def test_un_nas_sin_instantaneas_responde_bien_y_vacio(tmp_path, sistema, lista, programa):
    h, _ = uno(tmp_path, sistema, cambios={lista.plantilla: "", programa.plantilla: ""})
    d = datos(h.snapshots(sistema))
    assert d["total"] == 0 and d["recientes"] == {"filas": [], "total": 0, "truncado": False}
    assert d["por_volumen"] == [] and d["programacion"]["programaciones"] == []


def test_muchas_instantaneas_llegan_recortadas_con_su_cuenta(tmp_path):
    muchas = "".join("zpool1/zfs2@s%d\t10\t20\t%d\n" % (i, 1700000000 + i) for i in range(300))
    h, _ = uno(tmp_path, cambios={dc.SNAPSHOTS_HERO.plantilla: muchas})
    d = datos(h.snapshots("hero"))
    assert d["total"] == 300 and d["recientes"]["truncado"] is True
    assert len(d["recientes"]["filas"]) == discos_srv.MAX_RECIENTES and d["recientes"]["total"] == 300
    assert d["recientes"]["filas"][0]["instantanea"] == "s299"       # la mas reciente, primero
    assert d["por_volumen"] == [{"volumen": "zpool1/zfs2", "instantaneas": 300, "ultima": "2023-11-14T22:18:19Z",
                                 "retenido_bytes": 147456}]


def test_no_poder_leer_las_instantaneas_es_un_error_y_no_una_lista_vacia(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.SNAPSHOTS_HERO.plantilla: (1, "", "cannot open: permission denied\n")})
    (r,) = h.snapshots("hero")
    assert r["ok"] is False and "zfs_snapshots" in r["error"]
    h, _ = uno(tmp_path, "qts", cambios={dc.SNAPSHOTS_QTS.plantilla: (2, "", "grep: Permission denied\n")})
    (r,) = h.snapshots("qts")
    assert r["ok"] is False and "lvm_snapshots" in r["error"]


# --- carpetas_compartidas -----------------------------------------------------------------------

def test_carpetas_da_ruta_acceso_uso_y_papelera_de_cada_una(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.carpetas_compartidas("hero"))
    assert d["carpetas"]["total"] == 11 and "errores" not in d
    assert por(d["carpetas"]["filas"], "nombre", "carpeta1") == {
        "nombre": "carpeta1", "ruta": "/share/ZFS2_DATA/carpeta1", "volumen": "ZFS2_DATA",
        "comentario": "System default share", "visible": True, "papelera": True, "invitados": None,
        "usuarios_validos": {"usuarios": ["root", "admin", "usuario15", "carpeta5", "usuario14"],
                             "grupos": ["everyone", "administrators"], "total": 7},
        "denegados": {"usuarios": ["guest"], "grupos": [], "total": 1},
        "solo_lectura": {"usuarios": ["carpeta5", "usuario14"], "grupos": ["everyone"], "total": 3},
        "escritura": {"usuarios": ["admin", "usuario15"], "grupos": ["administrators"], "total": 3},
        "uso": {"usado": 74091401216, "directorios": 87, "ficheros": 152, "actualizado": "2026-09-28T01:00:05Z"},
        "nfs": []}
    assert d["nfs_exportadas"] == 0


def test_carpetas_en_qts_con_una_exportada_por_nfs(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.carpetas_compartidas("qts"))
    assert d["carpetas"]["total"] == 34 and d["nfs_exportadas"] == 1
    assert por(d["carpetas"]["filas"], "nombre", "carpeta12")["nfs"] == [
        {"cliente": "192.0.2.3", "escritura": False,
         "opciones": ["sec=sys", "ro", "async", "wdelay", "insecure", "no_subtree_check", "no_root_squash"]}]
    remota = por(d["carpetas"]["filas"], "nombre", "carpeta39 (usuario38@192.0.2.1)")
    assert remota["volumen"] == "external" and remota["uso"]["ficheros"] == 33149


def test_una_lista_de_acceso_enorme_llega_acotada_con_su_cuenta(tmp_path):
    muchos = ",".join('"u%d"' % i for i in range(500))
    smb = dato("carpetas_smb_hero").replace('write list = "admin","usuario15",@"administrators"',
                                           "write list = " + muchos, 1)
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_SMB.plantilla: smb})
    d = datos(h.carpetas_compartidas("hero"))
    escritura = por(d["carpetas"]["filas"], "nombre", "carpeta1")["escritura"]
    assert escritura["total"] == 500 and len(escritura["usuarios"]) == discos_srv.MAX_NOMBRES


def test_carpetas_sin_poder_leer_el_uso_lo_dice_y_da_el_resto(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_USO.plantilla: (2, "", "grep: Permission denied\n"),
                                  dc.CARPETAS_NFS.plantilla: (1, "", "cat: Permission denied\n")})
    d = datos(h.carpetas_compartidas("hero"))
    assert set(d["errores"]) == {"uso", "nfs"} and d["carpetas"]["total"] == 11
    carpeta = por(d["carpetas"]["filas"], "nombre", "carpeta1")
    assert carpeta["uso"] is None and carpeta["nfs"] is None      # no se sabe: ni cero ni "no exportada"


def test_carpetas_sin_smb_conf_es_un_error(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_SMB.plantilla: (2, "", "grep: /etc/config/smb.conf: No such file\n")})
    (r,) = h.carpetas_compartidas("hero")
    assert r["ok"] is False and "carpetas_smb" in r["error"]


def test_las_carpetas_que_no_estan_en_smb_se_listan_aparte(tmp_path):
    enlaces = dato("carpetas_enlaces_hero") + (
        "lrwxrwxrwx  1 admin administrators  17 Oct 13 17:09 SoloNFS -> ZFS20_DATA/SoloNFS\n")
    h, _ = uno(tmp_path, cambios={dc.CARPETAS_ENLACES.plantilla: enlaces})
    d = datos(h.carpetas_compartidas("hero"))
    assert {"carpeta": "SoloNFS", "volumen": "ZFS20_DATA"} in d["sin_smb"]


# --- iscsi --------------------------------------------------------------------------------------

def test_iscsi_en_hero_da_el_servicio_y_los_volumenes_de_bloques(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.iscsi("hero"))
    assert "no_probado" not in d
    assert d["servicio"] == {"activo": True, "puerto": 3260, "prefijo_iqn": "iqn.2004-04.com.example:destino-1"}
    assert d["destinos"] == [] and d["lun"] == [] and len(d["iniciadores"]) == 1
    assert d["volumenes_de_bloques"] == [
        {"dataset": "zpool1/zvol_cs_docker", "usado": 4469821440, "referido": 4469821440},
        {"dataset": "zpool1/zvol_cs_system-docker", "usado": 970743808, "referido": 970743808}]


def test_iscsi_en_hero_con_un_destino_y_un_lun(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.LUNS_HERO.plantilla: dato("zfs_iscsi_destino_hero")})
    d = datos(h.iscsi("hero"))
    assert [(x["alias"], x["lun"], x["portales"]) for x in d["destinos"]] == [
        ("prueba", ["LUN_prueba"], ["192.0.2.10"])]
    assert [(x["nombre"], x["capacidad"], x["fino"]) for x in d["lun"]] == [("LUN_prueba", 2 ** 30, True)]


def test_iscsi_en_qts_da_el_servicio_y_los_iniciadores(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.iscsi("qts"))
    assert d["no_probado"] is True and d["servicio"]["activo"] is True and d["servicio"]["puerto"] == 3260
    assert d["iniciadores"] == [{"id": 0, "nombre": "iqn.2004-04.com.example:destino-2", "alias": "Default Policy"}]
    assert "volumenes_de_bloques" not in d


@pytest.mark.parametrize("sistema, comando", [("hero", dc.LUNS_HERO), ("qts", dc.ISCSI_QTS)])
def test_un_nas_sin_iscsi_responde_bien_y_sin_servicio(tmp_path, sistema, comando):
    h, _ = uno(tmp_path, sistema, cambios={comando.plantilla: ""})
    d = datos(h.iscsi(sistema))
    assert d["servicio"] is None and d["destinos"] == [] and d["lun"] == []


@pytest.mark.parametrize("sistema, comando", [("hero", dc.LUNS_HERO), ("qts", dc.ISCSI_QTS)])
def test_no_poder_leer_la_configuracion_de_iscsi_es_un_error(tmp_path, sistema, comando):
    h, _ = uno(tmp_path, sistema, cambios={comando.plantilla: (2, "", "grep: Permission denied\n")})
    (r,) = h.iscsi(sistema)
    assert r["ok"] is False and comando.id in r["error"]


# --- rendimiento_discos -------------------------------------------------------------------------

def test_rendimiento_ordena_los_discos_por_ocupacion_y_los_situa_en_su_bahia(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.rendimiento_discos("hero"))
    assert d["segundos"] == 5.0 and len(d["discos"]) == 10
    assert d["discos"][0] == {
        "dispositivo": "sde", "cabina": 0, "bahia": 7, "puerto": "7", "modelo": "HUS726T4TALA6L4",
        "lecturas_s": 0.0, "escrituras_s": 9.2, "leido_mb_s": 0.0, "escrito_mb_s": 0.11, "espera_ms": 2.39,
        "ocupacion_pct": 2.1}
    assert d["mas_cargado"] == {"dispositivo": "sde", "cabina": 0, "bahia": 7, "ocupacion_pct": 2.1}
    assert [x["ocupacion_pct"] for x in d["discos"]] == sorted((x["ocupacion_pct"] for x in d["discos"]), reverse=True)
    # el disco de arranque del NAS no esta en ninguna bahia; el externo, en su cabina
    assert por(d["discos"], "dispositivo", "sdg")["cabina"] is None
    assert (por(d["discos"], "dispositivo", "sdh")["cabina"], por(d["discos"], "dispositivo", "sdh")["puerto"]) == (33, None)


def test_rendimiento_sin_actividad_no_senala_a_ningun_disco(tmp_path):
    quieto = "100.00 1.00\n   8       0 sda 1 0 8 1 1 0 8 1 0 1 2\n==5s\n105.00 2.00\n   8       0 sda 1 0 8 1 1 0 8 1 0 1 2\n"
    h, _ = uno(tmp_path, cambios={dc.DISKSTATS.plantilla: quieto})
    d = datos(h.rendimiento_discos("hero"))
    assert d["mas_cargado"] is None and d["discos"][0]["ocupacion_pct"] == 0.0


def test_rendimiento_que_no_termina_es_un_error(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "DISKSTATS", dataclasses.replace(dc.DISKSTATS, timeout=1))
    h, _ = uno(tmp_path, cambios={dc.DISKSTATS.plantilla: falsos.CUELGA})
    (r,) = h.rendimiento_discos("hero")
    assert r["ok"] is False and "no termino" in r["error"]


# --- casos que los datos reales ensenaron ---------------------------------------------------------

def test_el_desgaste_de_un_nvme_no_se_toma_por_sectores_reasignados(tmp_path):
    # en el fichero SMART de un NVMe el numero 5 es "Percentage Used", no sectores reasignados
    h, _ = uno(tmp_path)
    d = datos(h.discos_fisicos("hero"))
    assert en(d["discos"]["filas"], 23, 1)["avisos"] == [] and en(d["discos"]["filas"], 23, 2)["avisos"] == []


def test_un_nvme_con_aviso_critico_o_errores_de_medio_lleva_su_aviso(tmp_path):
    smart = dato("smart_todos_hero")
    assert "0,Critial Warning,0,0,0,0,0\n" in smart and "160,Media and Data Integrity Errors,0,0,0,0,0\n" in smart
    h, _ = uno(tmp_path, cambios={dc.SMART_TODOS.plantilla: smart.replace(
        "0,Critial Warning,0,0,0,0,0\n", "0,Critial Warning,0,0,0,4,0\n", 1).replace(
        "160,Media and Data Integrity Errors,0,0,0,0,0\n", "160,Media and Data Integrity Errors,0,0,0,7,0\n", 1)})
    avisos = en(datos(h.discos_fisicos("hero"))["discos"]["filas"], 23, 1)["avisos"]
    assert algun(avisos, "aviso critico", "4") and algun(avisos, "7 errores de medio") and len(avisos) == 2


def test_un_grupo_que_qts_tiene_configurado_y_no_esta_montado_se_destaca(tmp_path):
    # escrito a mano: el kernel no ha montado el grupo de datos
    texto = dato("mdstat_qts")
    inicio = texto.index("md1 : active raid6")
    sin_md1 = texto[:inicio] + texto[texto.index("md322 :"):]
    h, _ = uno(tmp_path, "qts", cambios={dc.MDSTAT.plantilla: sin_md1})
    d = datos(h.raid_estado("qts"))
    md1 = por(d["grupos"], "grupo", "md1")
    assert (md1["ausente"], md1["activo"], md1["sistema"], len(md1["faltan"])) == (True, False, False, 7)
    assert algun(d["avisos"], "md1", "no esta montado")
    assert algun(datos(h.almacenamiento_resumen("qts"))["avisos"], "md1", "no esta montado")


def test_un_miembro_fallado_de_un_grupo_md_se_dice_con_su_bahia(tmp_path):
    texto = dato("mdstat_qts")
    assert "sdf3[10] " in texto
    h, _ = uno(tmp_path, "qts", cambios={dc.MDSTAT.plantilla: texto.replace("sdf3[10] ", "sdf3[10](F) ").replace(
        "[7/7] [UUUUUUU]", "[7/6] [UUU_UUU]")})
    d = datos(h.raid_estado("qts"))
    assert algun(d["avisos"], "md1", "cabina 0, bahia 4", "fallado")
    assert por(d["grupos"], "grupo", "md1")["faltan"] == [{"cabina": 0, "bahia": 4}]


def test_un_volumen_de_qts_que_no_esta_montado_sale_sin_ocupacion(tmp_path):
    # escrito a mano: un volumen cifrado sin desbloquear no aparece en df
    sin_tercero = "".join(l for l in OCUPACION_QTS.splitlines(True) if "cachedev3" not in l)
    h, _ = uno(tmp_path, "qts", cambios={dc.OCUPACION.plantilla: sin_tercero})
    volumen = por(datos(h.volumenes("qts"))["volumenes"]["filas"], "id", 2)
    assert (volumen["montaje"], volumen["usado"], volumen["ocupacion_pct"]) == (None, None, None)
    assert volumen["bytes"] == 4294967296 * 512


# --- de la revision final -----------------------------------------------------------------------

def test_la_ocupacion_de_un_volumen_de_hero_no_cuenta_instantaneas_ni_reserva(tmp_path):
    # zfs20 guarda 22 GB y retiene 7 TB en instantaneas; zfs1 tiene todo su espacio reservado
    h, _ = uno(tmp_path)
    filas = datos(h.volumenes("hero"))["volumenes"]["filas"]
    zfs20 = por(filas, "dataset", "zpool2/zfs20")
    assert (zfs20["usado"], zfs20["ocupacion_pct"], zfs20["en_el_pool"]) == (22475030528, 0, 7221509312512)
    assert por(filas, "dataset", "zpool1/zfs1")["ocupacion_pct"] == 1
    # y coincide, volumen a volumen, con lo que dice df en el resumen
    resumen = {v["volumen"]: v["ocupacion_pct"] for v in datos(h.almacenamiento_resumen("hero"))["volumenes"]}
    assert {v["volumen"]: v["ocupacion_pct"] for v in filas} == resumen


def test_un_grupo_de_datos_degradado_se_avisa_aunque_no_este_en_raid_conf(tmp_path):
    # sin raid.conf (o con otra disposicion) no se sabe que bahia falta, pero el aviso no se pierde
    h, _ = uno(tmp_path, "qts", cambios={dc.MDSTAT.plantilla: mdstat_degradado(), dc.RAID_CONF.plantilla: ""})
    d = datos(h.raid_estado("qts"))
    md1 = por(d["grupos"], "grupo", "md1")
    assert (md1["sistema"], md1["degradado"], md1["sin_configuracion"], md1["faltan"]) == (False, True, True, [])
    assert algun(d["avisos"], "md1", "degradado", "6 de 7") and algun(d["avisos"], "md1", "reconstruccion")
    # los del sistema se reconocen por su numero y sus huecos siguen sin avisar
    assert sorted(g["grupo"] for g in d["grupos"] if g["sistema"]) == ["md13", "md256", "md280", "md322", "md9"]
    assert not algun(d["avisos"], "md9") and not algun(d["avisos"], "md13")
    assert algun(datos(h.almacenamiento_resumen("qts"))["avisos"], "md1", "degradado")


def avisos_de_volumenes_y_resumen(h):
    return datos(h.volumenes("qts"))["avisos"], datos(h.almacenamiento_resumen("qts"))["avisos"]


def test_un_volumen_en_solo_lectura_o_sucio_sale_en_los_avisos(tmp_path):
    conf = dato("volumenes_conf_qts")
    cambiado = conf.replace("unclean = no", "unclean = yes", 1).replace("readOnly = no", "readOnly = yes", 1)
    assert cambiado.count("yes") == conf.count("yes") + 2
    h, _ = uno(tmp_path, "qts", cambios={dc.VOLUMENES_CONF.plantilla: cambiado})
    for avisos in avisos_de_volumenes_y_resumen(h):
        assert algun(avisos, "cachedev1", "volumen1", "solo lectura") and algun(avisos, "cachedev1", "sucio")


def test_un_volumen_con_un_estado_que_no_es_el_normal_sale_en_los_avisos(tmp_path):
    conf = dato("volumenes_conf_qts")
    h, _ = uno(tmp_path, "qts", cambios={dc.VOLUMENES_CONF.plantilla: conf.replace("status = 0", "status = -3", 1)})
    for avisos in avisos_de_volumenes_y_resumen(h):
        assert algun(avisos, "cachedev1", "estado -3")


def test_un_volumen_que_no_esta_montado_sale_en_los_avisos(tmp_path):
    sin_tercero = "".join(l for l in OCUPACION_QTS.splitlines(True) if "cachedev3" not in l)
    h, _ = uno(tmp_path, "qts", cambios={dc.OCUPACION.plantilla: sin_tercero})
    for avisos in avisos_de_volumenes_y_resumen(h):
        assert algun(avisos, "cachedev3", "volumen2", "no esta montado")


def test_un_volumen_o_un_pool_sobre_su_umbral_sale_en_los_avisos(tmp_path):
    lvm = dato("lvm_conf_qts")
    todos = lvm.replace("overThreshold = no", "overThreshold = yes").replace("overThreshold=no", "overThreshold=yes")
    h, _ = uno(tmp_path, "qts", cambios={dc.LVM_CONF.plantilla: todos})
    for avisos in avisos_de_volumenes_y_resumen(h):
        assert algun(avisos, "pool vg1", "umbral") and algun(avisos, "cachedev3", "umbral")


@pytest.mark.parametrize("antes, despues, trozos", [
    ("thin-pool 333526 88286/8388608 14453087/28099192 - rw ", "thin-pool Fail ", ("vg1", "fallo")),
    (" - rw no_discard_passdown", " - ro no_discard_passdown", ("vg1", "modo ro")),
    ("thin-pool 333526 88286/8388608", "thin-pool 333526 7717519/8388608", ("vg1", "metadatos", "92"))])
def test_un_pool_ligero_averiado_en_solo_lectura_o_sin_metadatos_sale_en_los_avisos(tmp_path, antes, despues, trozos):
    # escrito a mano sobre la linea real del pool, con el formato del kernel
    dm = dato("dm_estado_qts")
    assert dm.count(antes) == 1
    h, _ = uno(tmp_path, "qts", cambios={dc.DM_ESTADO.plantilla: dm.replace(antes, despues)})
    for avisos in avisos_de_volumenes_y_resumen(h):
        assert algun(avisos, *trozos)


def test_el_aviso_de_un_disco_que_falta_en_un_pool_dice_su_bahia(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.POOLS_ESTADO.plantilla: AUSENTE})
    assert algun(datos(h.raid_estado("hero"))["avisos"], "zpool1", "cabina 0, bahia 2", "UNAVAIL")
