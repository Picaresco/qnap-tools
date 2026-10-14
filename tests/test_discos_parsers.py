# -*- coding: utf-8 -*-
"""Parsers de la pata de discos, contra salidas reales anonimizadas (tests/datos/discos/).

Los ficheros *_hero.txt se capturaron en un QuTS hero con las ordenes del producto
(pruebas/captura.py); los *_qts.txt y *_qts2.txt salen de la exploracion de dos QTS, el segundo
con cabina de expansion (pruebas/deriva_discos_qts.py). Los textos escritos a mano en este
fichero cubren lo que ningun NAS de pruebas tenia (un atributo por debajo de su umbral, un
contador que retrocede, getsysinfo sin privilegios) y asi se indica.
"""
from pathlib import Path

import pytest

from qnap_tools.discos import parsers as p

DATOS = Path(__file__).parent / "datos" / "discos"


def dato(nombre):
    return (DATOS / (nombre + ".txt")).read_text(encoding="utf-8")


def por(lista, clave, valor):
    (uno,) = [x for x in lista if x[clave] == valor]
    return uno


def en(lista, cabina, bahia):
    (uno,) = [x for x in lista if (x["cabina"], x["bahia"]) == (cabina, bahia)]
    return uno


# --- lista de discos (qcli_storage -d) ----------------------------------------------------------

def test_la_lista_da_puerto_dispositivo_tipo_y_uso_de_cada_disco():
    discos = p.discos_lista(dato("discos_lista_hero"))
    assert len(discos) == 8
    assert por(discos, "dispositivo", "/dev/sda") == {
        "cabina": "NAS_HOST", "puerto": "3", "dispositivo": "/dev/sda", "tipo": "SSD", "uso": "data",
        "tamano": "465.76 GB", "alias": '2.5" SATA SSD 1', "modelo": "WDC WDS500G1R0A-68A4W0"}
    nvme = por(discos, "puerto", "P2-1")
    assert nvme["dispositivo"] == "/dev/nvme1n1" and nvme["uso"] == "cache"
    assert nvme["modelo"] == "Samsung SSD 970 EVO Plus 250GB" and nvme["alias"] == "PCIe SSD 2-1"


def test_la_lista_de_qts_trae_el_disco_de_repuesto_y_la_cache_interna():
    discos = p.discos_lista(dato("discos_lista_qts"))
    assert len(discos) == 10
    assert por(discos, "puerto", "8")["uso"] == "spare" and por(discos, "puerto", "8")["tipo"] == "HDD"
    cache = por(discos, "puerto", "C1")
    assert (cache["tipo"], cache["uso"], cache["tamano"]) == ("SSD", "cache", "465.76 GB")
    assert cache["modelo"] == "Samsung SSD 850 EVO mSATA 500GB" and cache["alias"] == "mSATA SATA SSD 1"


def test_la_lista_distingue_los_discos_de_la_cabina_de_expansion():
    discos = p.discos_lista(dato("discos_lista_qts2"))
    assert len(discos) == 26
    assert [d["cabina"] for d in discos].count("EXDR#1") == 12
    # el mismo numero de puerto existe en las dos cabinas
    assert {d["dispositivo"] for d in discos if d["puerto"] == "1"} == {"/dev/sda", "/dev/sdv"}


@pytest.mark.parametrize("texto", [
    "", "qcli_storage: command not found\n",
    "Enclosure  Port  Sys_Name          Type      Size      Alias                 Signature   Partitions  Model  \n",
    # escrito a mano: una fila que no cuadra con las columnas de la cabecera
    "Enclosure  Port  Sys_Name          Type      Size      Alias                 Signature   Partitions  Model  \n"
    "NAS_HOST_LARGUISIMO 3 /dev/sda SSD:data 465.76 GB\n"])
def test_la_lista_no_inventa_discos_si_no_reconoce_la_salida(texto):
    with pytest.raises(ValueError):
        p.discos_lista(texto)


# --- reparto (qcli_storage -p) ------------------------------------------------------------------

def test_el_reparto_dice_a_que_grupo_y_pool_pertenece_cada_disco_en_hero():
    reparto = p.discos_reparto(dato("discos_reparto_hero"))
    assert len(reparto) == 8
    assert por(reparto, "dispositivo", "/dev/sda") == {
        "cabina": "NAS_HOST", "puerto": "3", "dispositivo": "/dev/sda", "uso": "data",
        "grupo": "vdev_1", "raid": "RAID 1", "pool": 1}
    assert por(reparto, "dispositivo", "/dev/sdd")["grupo"] == "vdev_7"
    cache = por(reparto, "dispositivo", "/dev/nvme1n1")
    assert (cache["uso"], cache["grupo"], cache["raid"], cache["pool"]) == ("cache", "vdev_3", "RAID 1", 256)


def test_el_reparto_de_qts_da_el_grupo_md_y_deja_vacio_el_disco_de_repuesto():
    reparto = p.discos_reparto(dato("discos_reparto_qts"))
    assert len(reparto) == 10
    assert por(reparto, "dispositivo", "/dev/sdc") == {
        "cabina": "NAS_HOST", "puerto": "1", "dispositivo": "/dev/sdc", "uso": "data",
        "grupo": "/dev/md1", "raid": "RAID 6", "pool": 1}
    repuesto = por(reparto, "dispositivo", "/dev/sdj")
    assert (repuesto["uso"], repuesto["grupo"], repuesto["raid"], repuesto["pool"]) == ("spare", None, None, None)
    assert por(reparto, "dispositivo", "/dev/sda")["grupo"] == "/dev/md2"


def test_el_reparto_cubre_la_cabina_de_expansion():
    reparto = p.discos_reparto(dato("discos_reparto_qts2"))
    assert len(reparto) == 26
    exp = por(reparto, "dispositivo", "/dev/sdv")
    assert (exp["cabina"], exp["puerto"], exp["grupo"], exp["raid"], exp["pool"]) == (
        "EXDR#1", "1", "/dev/md5", "RAID 5", 4)
    assert {r["grupo"] for r in reparto} == {"/dev/md1", "/dev/md2", "/dev/md3", "/dev/md4", "/dev/md5"}


@pytest.mark.parametrize("fichero", ["discos_reparto_hero", "discos_reparto_qts", "discos_reparto_qts2"])
def test_el_reparto_no_arrastra_nombres_de_carpeta_ni_de_volumen(fichero):
    texto = repr(p.discos_reparto(dato(fichero)))
    assert "carpeta" not in texto and "volumen" not in texto


@pytest.mark.parametrize("texto", [
    "", "error\n", "Enclosure Port Sys_Name          Size      Type   VDEV        RAID_Type     Group Pool SharedFolderName\n"])
def test_el_reparto_no_inventa_nada_si_no_reconoce_la_salida(texto):
    with pytest.raises(ValueError):
        p.discos_reparto(texto)


# --- detalle (ficheros de cabina) ---------------------------------------------------------------

def test_el_detalle_da_modelo_serie_capacidad_y_bus_de_cada_disco():
    discos = p.discos_detalle(dato("discos_detalle_hero"))
    assert len(discos) == 9
    assert en(discos, 0, 3) == {
        "cabina": 0, "bahia": 3, "dispositivo": "/dev/sda", "bus": "sata", "fabricante": "WDC",
        "modelo": "WDS500G1R0A-68A4W0", "serie": "SERIE0001", "firmware": "411000WR",
        "bytes": 976773168 * 512, "rpm": None, "estado": 0}
    assert en(discos, 0, 5)["rpm"] == 7200 and en(discos, 0, 5)["fabricante"] == "HGST"
    nvme = en(discos, 23, 1)
    assert (nvme["dispositivo"], nvme["bus"], nvme["bytes"]) == ("/dev/nvme1n1", "nvme", 488397168 * 512)
    usb = en(discos, 33, 1)
    assert (usb["bus"], usb["modelo"], usb["firmware"], usb["dispositivo"]) == ("usb", "Portable", None, "/dev/sdh")


def test_el_detalle_de_qts_tiene_el_mismo_formato():
    discos = p.discos_detalle(dato("discos_detalle_qts"))
    assert len(discos) == 12
    uno = en(discos, 0, 1)
    assert (uno["dispositivo"], uno["rpm"], uno["bytes"], uno["firmware"]) == (
        "/dev/sdc", 7200, 7814037168 * 512, "83.00A83")


def test_el_detalle_no_cuenta_los_discos_retirados():
    # el NAS guarda en enclosure_<n>_del.conf los discos que ya no estan
    discos = p.discos_detalle(dato("discos_detalle_qts2"))
    assert len(discos) == 27
    claves = [(d["cabina"], d["bahia"]) for d in discos]
    assert len(claves) == len(set(claves))
    assert {d["cabina"] for d in discos} == {0, 1, 23, 33}
    assert len([d for d in discos if d["cabina"] == 1]) == 12


def test_el_detalle_deja_sin_bus_un_codigo_que_no_conoce():
    # escrito a mano: un codigo de tipo que no ha salido en ningun NAS de pruebas
    (disco,) = p.discos_detalle(
        "== /etc/enclosure_0.conf\n[PhysicalDisk_1]\nport_id = 1\npd_sys_name = /dev/sda\ntype = 7\n"
        "model = X\ncapacity = 100\nsector_size = 4096\n")
    assert disco["bus"] is None and disco["bytes"] == 409600 and disco["serie"] is None


@pytest.mark.parametrize("texto", [
    "", "== /etc/enclosure_0.conf\n", "[PhysicalDisk_1]\nport_id = 1\n",
    "== /etc/enclosure_0.conf\n[PhysicalDisk_1]\nport_id = uno\n",
    "== /etc/enclosure_0.conf\n[PhysicalDisk_1]\ncapacity = mucha\n"])
def test_el_detalle_no_inventa_discos_si_no_reconoce_la_salida(texto):
    with pytest.raises(ValueError):
        p.discos_detalle(texto)


# --- salud segun el NAS (getsysinfo) ------------------------------------------------------------

def test_la_salud_da_temperatura_y_veredicto_de_las_bahias_ocupadas():
    salud = p.discos_salud(dato("discos_salud_hero"))
    assert [s["bahia"] for s in salud] == [3, 4, 5, 6, 7, 8]       # la 1 y la 2 estan vacias
    assert por(salud, "bahia", 3) == {
        "bahia": 3, "modelo": "WDS500G1R0A-68A4W0", "temperatura": 38, "smart": "GOOD", "estado": 0}
    assert por(salud, "bahia", 4)["temperatura"] == 37


def test_la_salud_de_qts_tiene_el_mismo_formato():
    salud = p.discos_salud(dato("discos_salud_qts2"))
    assert len(salud) == 12
    assert por(salud, "bahia", 12) == {
        "bahia": 12, "modelo": "HUS728T8TALE6L4", "temperatura": 40, "smart": "GOOD", "estado": 0}


SIN_PRIVILEGIOS = ("== 1\nmodelo=WD4003FFBX-68MU3N0\ntemperatura=0 C/32 F\nsmart=--\nestado=0\n"
                   "== 2\nmodelo=WD4003FFBX-68MU3N0\ntemperatura=0 C/32 F\nsmart=--\nestado=0\n"
                   "== 3\nmodelo=--\ntemperatura=-- C/-- F\nsmart=--\nestado=-5\n")


def test_la_salud_sin_privilegios_es_un_error_y_no_cero_grados():
    # formato visto en los tres NAS al lanzar getsysinfo sin sudo: 0 C y -- con codigo 0
    with pytest.raises(ValueError, match="privilegios"):
        p.discos_salud(SIN_PRIVILEGIOS)


def test_un_disco_que_no_da_temperatura_queda_sin_dato_no_a_cero():
    # escrito a mano: un disco sin datos entre otros que si los dan
    salud = p.discos_salud(
        "== 1\nmodelo=A\ntemperatura=0 C/32 F\nsmart=--\nestado=0\n"
        "== 2\nmodelo=B\ntemperatura=0 C/32 F\nsmart=GOOD\nestado=0\n"
        "== 3\nmodelo=C\ntemperatura=35 C/95 F\nsmart=WARNING\nestado=0\n")
    assert por(salud, "bahia", 1) == {"bahia": 1, "modelo": "A", "temperatura": None, "smart": None, "estado": 0}
    assert por(salud, "bahia", 2)["temperatura"] is None and por(salud, "bahia", 2)["smart"] == "GOOD"
    assert por(salud, "bahia", 3)["temperatura"] == 35 and por(salud, "bahia", 3)["smart"] == "WARNING"


def test_un_nas_con_todas_las_bahias_vacias_no_es_un_error():
    assert p.discos_salud("== 1\nmodelo=--\ntemperatura=-- C/-- F\nsmart=--\nestado=-5\n") == []


@pytest.mark.parametrize("texto", [
    "", "getsysinfo: not found\n", "== 1\nmodelo=A\n", "== uno\nmodelo=A\ntemperatura=1 C/33 F\nsmart=GOOD\nestado=0\n",
    "== 1\nmodelo=A\ntemperatura=caliente\nsmart=GOOD\nestado=0\n",
    "== 1\nmodelo=A\ntemperatura=35 C/95 F\nsmart=GOOD\nestado=bien\n"])
def test_la_salud_no_inventa_nada_si_no_reconoce_la_salida(texto):
    with pytest.raises(ValueError):
        p.discos_salud(texto)


# --- atributos SMART ----------------------------------------------------------------------------

def test_los_atributos_de_un_disco_traen_valor_peor_umbral_y_crudo():
    smart = p.smart_atributos(dato("smart_atributos_hero"))
    assert (smart["clase"], smart["temperatura"], len(smart["atributos"])) == ("ata", 38, 25)
    assert por(smart["atributos"], "id", 5) == {
        "id": 5, "nombre": "Retired_Block_Count", "valor": 100, "peor": 100, "umbral": 0, "crudo": 0,
        "bajo_umbral": False}
    reserva = por(smart["atributos"], "id", 232)
    assert (reserva["valor"], reserva["umbral"], reserva["crudo"], reserva["bajo_umbral"]) == (100, 4, 100, False)
    temperatura = por(smart["atributos"], "id", 194)
    assert (temperatura["valor"], temperatura["peor"], temperatura["crudo"]) == (62, 55, 38)


def test_smart_todos_da_un_bloque_por_disco_con_su_cabina_y_bahia():
    todos = p.smart_todos(dato("smart_todos_hero"))
    assert [(s["cabina"], s["bahia"]) for s in todos] == [
        (0, 3), (0, 4), (0, 5), (0, 6), (0, 7), (0, 8), (23, 1), (23, 2)]
    hdd = en(todos, 0, 5)
    assert (hdd["clase"], hdd["temperatura"], len(hdd["atributos"])) == ("ata", 41, 17)
    assert por(hdd["atributos"], "id", 5)["umbral"] == 5
    assert por(hdd["atributos"], "id", 197) == {
        "id": 197, "nombre": "Current_Pending_Sector", "valor": 100, "peor": 100, "umbral": 0, "crudo": 0,
        "bajo_umbral": False}


def test_un_nvme_trae_su_registro_de_salud_en_los_valores_crudos():
    nvme = en(p.smart_todos(dato("smart_todos_hero")), 23, 1)
    assert (nvme["clase"], nvme["temperatura"], len(nvme["atributos"])) == ("nvme", 53, 15)
    assert por(nvme["atributos"], "id", 5) == {
        "id": 5, "nombre": "Percentage Used", "valor": None, "peor": None, "umbral": None, "crudo": 22,
        "bajo_umbral": False}
    assert por(nvme["atributos"], "nombre", "Unsafe Shutdowns")["crudo"] == 14


def test_smart_todos_de_qts_y_un_disco_externo_sin_atributos():
    todos = p.smart_todos(dato("smart_todos_qts"))
    assert len(todos) == 11
    assert por(en(todos, 0, 1)["atributos"], "id", 9)["crudo"] == 46103
    externo = en(todos, 33, 1)
    assert externo["atributos"] == [] and externo["temperatura"] is None


def test_smart_todos_cubre_la_cabina_de_expansion():
    todos = p.smart_todos(dato("smart_todos_qts2"))
    assert len(todos) == 26
    assert en(todos, 1, 12)["temperatura"] == 42 and en(todos, 0, 10)["temperatura"] == 39


def test_un_atributo_en_su_umbral_o_por_debajo_queda_marcado():
    # escrito a mano: ningun disco de los NAS de pruebas estaba fallando
    smart = p.smart_atributos(
        "3,0,0,100,0,0,0,0,40,0x0000,2,255,0\n5,Reallocated_Sector_Ct,5,5,10,812,0\n"
        "197,Current_Pending_Sector,36,36,36,8,0\n9,Power,On,Hours,100,100,0,5,0\n")
    assert por(smart["atributos"], "id", 5)["bajo_umbral"] is True
    assert por(smart["atributos"], "id", 197)["bajo_umbral"] is True
    # un nombre con comas no descoloca los numeros; un umbral 0 no marca nada
    assert por(smart["atributos"], "id", 9) == {
        "id": 9, "nombre": "Power,On,Hours", "valor": 100, "peor": 100, "umbral": 0, "crudo": 5,
        "bajo_umbral": False}


def test_un_valor_crudo_que_no_es_un_numero_se_conserva_como_texto():
    # escrito a mano: formato de horas que usan algunos fabricantes
    smart = p.smart_atributos("1,0,0,100,0,0,0,0,40,0x0000,2,255,0\n9,Power_On_Hours,100,100,0,1234h+56m,0\n")
    assert por(smart["atributos"], "id", 9)["crudo"] == "1234h+56m"


@pytest.mark.parametrize("texto", [
    "", "cat: /tmp/smart/smart_0_9.info: No such file or directory\n", "25,0,0\n5,A,100,100,0,0,0\n",
    "1,0,0,100,0,0,0,0,40,0x0000,2,255,0\n5,A,100,100\n",
    "1,0,0,100,0,0,0,0,40,0x0000,2,255,0\n5,A,cien,100,0,0,0\n",
    "1,0,0,100,0,0,0,0,templado,0x0000,2,255,0\n5,A,100,100,0,0,0\n"])
def test_los_atributos_no_se_inventan_si_no_se_reconoce_el_fichero(texto):
    with pytest.raises(ValueError):
        p.smart_atributos(texto)


@pytest.mark.parametrize("texto", [
    "", "ls: /tmp/smart/: Permission denied\n", "25,0,0,100,0,0,0,0,38,0x0000,2,10,0\n",
    "== /tmp/smart/otro.info\n1,0,0,100,0,0,0,0,40,0x0000,2,255,0\n",
    "== /tmp/smart/smart_0_1.info\n== /tmp/smart/smart_0_2.info\n1,0,0,100,0,0,0,0,40,0x0000,2,255,0\n"])
def test_smart_todos_no_inventa_nada_si_no_reconoce_la_salida(texto):
    with pytest.raises(ValueError):
        p.smart_todos(texto)


# --- avisos configurados y vida de los SSD ------------------------------------------------------

def test_los_umbrales_dicen_que_avisos_por_valor_tiene_activados_el_nas():
    assert p.smart_umbrales(dato("smart_umbrales_hero")) == {
        "politica": 0,
        "avisos": [{"id": 5, "activo": False, "limite": 0}, {"id": 187, "activo": False, "limite": 0},
                   {"id": 188, "activo": False, "limite": 0}, {"id": 197, "activo": True, "limite": 0},
                   {"id": 198, "activo": True, "limite": 0}]}
    assert p.smart_umbrales(dato("smart_umbrales_qts"))["avisos"][3] == {"id": 197, "activo": True, "limite": 0}


def test_sin_fichero_de_umbrales_no_hay_avisos_configurados():
    assert p.smart_umbrales("") == {"politica": None, "avisos": []}


@pytest.mark.parametrize("texto", [
    "grep: /tmp/smart_warning.conf: Permission denied\n", "[S.M.A.R.T. ID #5]\nenable = quiza\nvalue = 0\n",
    "[Otra cosa]\nenable = 1\nvalue = 0\n", "enable = 1\n"])
def test_los_umbrales_no_se_inventan_si_no_se_reconoce_el_fichero(texto):
    with pytest.raises(ValueError):
        p.smart_umbrales(texto)


def test_la_vida_de_los_ssd_da_el_desgaste_por_cabina_y_bahia():
    assert p.ssd_vida(dato("ssd_vida_hero")) == [
        {"cabina": 0, "bahia": 3, "usado_pct": 0}, {"cabina": 0, "bahia": 4, "usado_pct": 1},
        {"cabina": 23, "bahia": 1, "usado_pct": 22}, {"cabina": 23, "bahia": 2, "usado_pct": 32}]
    assert p.ssd_vida(dato("ssd_vida_qts")) == [{"cabina": 23, "bahia": 2, "usado_pct": 72}]
    assert len(p.ssd_vida(dato("ssd_vida_qts2"))) == 4


def test_un_nas_sin_ssd_no_tiene_vida_que_dar():
    assert p.ssd_vida("") == []


def test_un_ssd_sin_dato_de_desgaste_queda_sin_valor():
    # escrito a mano: el fichero existe pero no trae el campo
    assert p.ssd_vida("== /tmp/disk/disk_0_1.info\n== /tmp/disk/disk_0_2.info\nSSD_LIFE_USED = 9\n") == [
        {"cabina": 0, "bahia": 1, "usado_pct": None}, {"cabina": 0, "bahia": 2, "usado_pct": 9}]


@pytest.mark.parametrize("texto", [
    "ls: /tmp/disk/: Permission denied\n", "SSD_LIFE_USED = 9\n",
    "== /tmp/disk/disk_0_1.info\nSSD_LIFE_USED = poco\n", "== /tmp/disk/otro.info\nSSD_LIFE_USED = 9\n"])
def test_la_vida_de_los_ssd_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.ssd_vida(texto)


# --- rendimiento (/proc/diskstats) --------------------------------------------------------------

def test_el_rendimiento_sale_de_la_diferencia_entre_las_dos_lecturas():
    r = p.diskstats(dato("diskstats_hero"))
    assert r["segundos"] == 5.0 and len(r["discos"]) == 10
    # sda en 5 s: 3 lecturas y 81 escrituras, 1040 y 5708 sectores, 16+30 ms de espera, 38 ms ocupado
    assert por(r["discos"], "dispositivo", "sda") == {
        "dispositivo": "sda", "lecturas_s": 0.6, "escrituras_s": 16.2, "leido_mb_s": 0.1,
        "escrito_mb_s": 0.56, "espera_ms": 0.55, "ocupacion_pct": 0.8}
    assert por(r["discos"], "dispositivo", "nvme0n1")["escrituras_s"] == 12.4      # 62 escrituras


def test_un_disco_parado_no_tiene_espera_media():
    r = p.diskstats(dato("diskstats_hero"))
    assert por(r["discos"], "dispositivo", "sdh") == {
        "dispositivo": "sdh", "lecturas_s": 0.0, "escrituras_s": 0.0, "leido_mb_s": 0.0,
        "escrito_mb_s": 0.0, "espera_ms": None, "ocupacion_pct": 0.0}


def lecturas(antes, despues, t0="100.00 1.00", t1="105.00 2.00"):
    return "%s\n%s\n==5s\n%s\n%s\n" % (t0, antes, t1, despues)


def test_un_contador_que_retrocede_no_da_cifras():
    # escrito a mano: un disco que se ha reconectado entre las dos lecturas empieza de cero
    r = p.diskstats(lecturas(
        "   8       0 sda 100 0 8000 50 200 0 16000 90 0 70 140\n   8      16 sdb 10 0 80 5 20 0 160 9 0 7 14",
        "   8       0 sda 3 0 24 1 2 0 16 1 0 2 2\n   8      16 sdb 20 0 2128 15 30 0 160 19 0 507 34"))
    assert por(r["discos"], "dispositivo", "sda") == {
        "dispositivo": "sda", "lecturas_s": None, "escrituras_s": None, "leido_mb_s": None,
        "escrito_mb_s": None, "espera_ms": None, "ocupacion_pct": None}
    # sdb: 10 lecturas y 10 escrituras en 5 s, 2048 sectores leidos, 20 ms de espera, 500 ms ocupado
    assert por(r["discos"], "dispositivo", "sdb") == {
        "dispositivo": "sdb", "lecturas_s": 2.0, "escrituras_s": 2.0, "leido_mb_s": 0.2,
        "escrito_mb_s": 0.0, "espera_ms": 1.0, "ocupacion_pct": 10.0}


def test_un_disco_que_no_esta_en_las_dos_lecturas_no_se_cuenta():
    r = p.diskstats(lecturas(
        "   8       0 sda 1 0 8 1 1 0 8 1 0 1 2",
        "   8       0 sda 1 0 8 1 1 0 8 1 0 1 2\n   8      16 sdb 1 0 8 1 1 0 8 1 0 1 2"))
    assert [d["dispositivo"] for d in r["discos"]] == ["sda"]


def test_la_ocupacion_no_pasa_del_cien_por_cien():
    r = p.diskstats(lecturas("   8       0 sda 0 0 0 0 0 0 0 0 0 0 0", "   8       0 sda 9 0 72 9 0 0 0 0 0 6000 9"))
    assert r["discos"][0]["ocupacion_pct"] == 100.0


@pytest.mark.parametrize("texto", [
    "",
    "100.00 1.00\n   8       0 sda 1 0 8 1 1 0 8 1 0 1 2\n",                                  # sin segunda lectura
    "   8       0 sda 1 0 8 1 1 0 8 1 0 1 2\n==5s\n   8       0 sda 1 0 8 1 1 0 8 1 0 1 2\n",  # sin reloj
    lecturas("   8       0 sda 1 0 8 1 1 0 8 1 0 1 2", "   8       0 sda 1 0 8 1 1 0 8 1 0 1 2",
             t1="100.00 1.00"),                                                             # intervalo nulo
    lecturas("   8       0 sda 1 0 8", "   8       0 sda 1 0 8"),                           # faltan contadores
    lecturas("   8       0 sda 1 0 8 1 1 0 8 x 0 1 2", "   8       0 sda 1 0 8 1 1 0 8 1 0 1 2"),
    lecturas("", "")])
def test_el_rendimiento_no_se_inventa_si_no_se_reconoce_la_salida(texto):
    with pytest.raises(ValueError):
        p.diskstats(texto)


# ==== QuTS hero ===================================================================================

# --- pools (zpool list) -------------------------------------------------------------------------

def test_los_pools_dan_tamano_y_ocupacion_en_bytes_y_su_salud():
    pools = p.pools(dato("pools_hero"))
    assert [x["pool"] for x in pools] == ["zpool1", "zpool2", "zpool256", "zpoolExt2"]
    assert por(pools, "pool", "zpool1") == {
        "pool": "zpool1", "bytes": 463856467968, "usado": 120933212160, "libre": 342923255808,
        "ocupacion_pct": 26, "dedup": 1.0, "salud": "ONLINE"}
    assert por(pools, "pool", "zpool2")["ocupacion_pct"] == 21


def test_un_pool_degradado_conserva_su_salud_tal_cual():
    # escrito a mano: ningun pool de los NAS de pruebas estaba degradado
    (pool,) = p.pools("zpool1\t1000\t900\t100\t90\t1.25x\tDEGRADED\n")
    assert (pool["salud"], pool["ocupacion_pct"], pool["dedup"]) == ("DEGRADED", 90, 1.25)


@pytest.mark.parametrize("texto", [
    "", "cannot open 'zpool1': no such pool\n", "zpool1\t1000\t900\n", "zpool1\tmil\t900\t100\t90\t1.00x\tONLINE\n",
    "zpool1\t1000\t900\t100\t90\tmucho\tONLINE\n"])
def test_los_pools_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.pools(texto)


# --- estado de los pools (zpool status -v) ------------------------------------------------------

def test_el_estado_da_la_salud_el_aviso_y_la_ultima_verificacion_de_cada_pool():
    estado = p.pools_estado(dato("pools_estado_hero"))
    assert [e["pool"] for e in estado] == ["zpool1", "zpool2", "zpool256", "zpoolExt2"]
    uno = por(estado, "pool", "zpool1")
    assert uno["estado"] == "ONLINE" and uno["accion"] is None
    assert uno["aviso"] == ("Some supported features are not enabled on the pool. The pool can still be used, "
                            "but some features are unavailable.")
    assert uno["tarea"] == {
        "tipo": "scrub", "en_curso": False, "progreso_pct": None, "errores": 0,
        "texto": "scrub repaired 0 in 0 days 00:40:19 with 0 errors on Sun Jul 19 02:40:21 2026"}
    assert uno["errores_de_datos"] == {"hay": False, "texto": "No known data errors", "ficheros": [], "total": 0}
    # un pool que nunca se ha verificado y otro sin aviso
    assert por(estado, "pool", "zpool256")["tarea"] is None
    assert por(estado, "pool", "zpoolExt2")["aviso"] is None


def test_el_estado_da_el_arbol_de_dispositivos_con_su_bahia():
    uno = por(p.pools_estado(dato("pools_estado_hero")), "pool", "zpool1")
    assert [(d["nombre"], d["nivel"]) for d in uno["dispositivos"]] == [
        ("mirror-0", 1), ("qzfs/enc_0/disk_0x3_SERIE0001_3", 2), ("qzfs/enc_0/disk_0x4_SERIE0002_3", 2)]
    assert uno["dispositivos"][0] == {
        "nombre": "mirror-0", "nivel": 1, "papel": "datos", "grupo": "mirror-0", "es_disco": False,
        "cabina": None, "bahia": None, "estado": "ONLINE", "lectura": 0, "escritura": 0, "suma": 0, "nota": None}
    assert uno["dispositivos"][1] == {
        "nombre": "qzfs/enc_0/disk_0x3_SERIE0001_3", "nivel": 2, "papel": "datos", "grupo": "mirror-0",
        "es_disco": True, "cabina": 0, "bahia": 3, "estado": "ONLINE", "lectura": 0, "escritura": 0, "suma": 0,
        "nota": None}


def test_el_estado_distingue_los_discos_de_datos_de_los_de_registro_y_cache():
    estado = p.pools_estado(dato("pools_estado_hero"))
    dos = por(estado, "pool", "zpool2")["dispositivos"]
    # cuatro discos sueltos (sin redundancia) y un espejo de registro en dos NVMe
    assert [(d["papel"], d["nivel"], d["es_disco"], d["cabina"], d["bahia"]) for d in dos] == [
        ("datos", 1, True, 0, 5), ("datos", 1, True, 0, 6), ("datos", 1, True, 0, 7), ("datos", 1, True, 0, 8),
        ("logs", 1, False, None, None), ("logs", 2, True, 23, 1), ("logs", 2, True, 23, 2)]
    assert dos[0]["grupo"] == dos[0]["nombre"] and dos[5]["grupo"] == "mirror-4"
    cache = [d for d in por(estado, "pool", "zpool256")["dispositivos"] if d["papel"] == "cache"]
    assert [(d["cabina"], d["bahia"], d["es_disco"]) for d in cache] == [(23, 1, True), (23, 2, True)]


# escrito a mano con el formato de zpool status: ningun NAS de pruebas tenia un pool degradado
DEGRADADO = (
    "  pool: zpool1\n"
    " state: DEGRADED\n"
    "status: One or more devices are faulted in response to persistent errors.\n"
    "\tSufficient replicas exist for the pool to continue functioning in a\n"
    "\tdegraded state.\n"
    "action: Replace the faulted device, or use 'zpool clear' to mark the device\n"
    "\trepaired.\n"
    "  scan: resilver in progress since Sun Oct 11 10:00:00 2026\n"
    "\t1.20T scanned out of 3.12T at 120M/s, 4h33m to go\n"
    "\t100G resilvered, 38.46% done\n"
    "config:\n"
    "\n"
    "\tNAME                                    STATE     READ WRITE CKSUM\n"
    "\tzpool1                                  DEGRADED     0     0     0\n"
    "\t  raidz1-0                              DEGRADED     0     0     0\n"
    "\t    qzfs/enc_0/disk_0x1_SERIE0001_3     ONLINE       0     0     0\n"
    "\t    replacing-1                         DEGRADED     0     0     0\n"
    "\t      qzfs/enc_0/disk_0x2_SERIE0002_3   FAULTED     12  1.5K     3  too many errors\n"
    "\t      qzfs/enc_1/disk_0x10004_SERIE0009_3  ONLINE    0     0     0  (resilvering)\n"
    "\t    qzfs/enc_0/disk_0x3_SERIE0003_3     ONLINE       0     0     0\n"
    "\tspares\n"
    "\t  qzfs/enc_0/disk_0x8_SERIE0008_3       AVAIL\n"
    "\n"
    "errors: Permanent errors have been detected in the following files:\n"
    "\n"
    "        /share/ZFS2_DATA/carpeta1/informe.docx\n"
    "        zpool1/zfs2@snapshot3:/carpeta1/otro fichero.xlsx\n")


def test_un_pool_degradado_senala_el_disco_que_falla_y_sus_errores():
    (pool,) = p.pools_estado(DEGRADADO)
    assert pool["estado"] == "DEGRADED"
    assert pool["aviso"].startswith("One or more devices are faulted") and pool["aviso"].endswith("degraded state.")
    assert pool["accion"] == "Replace the faulted device, or use 'zpool clear' to mark the device repaired."
    malo = por(pool["dispositivos"], "nombre", "qzfs/enc_0/disk_0x2_SERIE0002_3")
    assert malo == {
        "nombre": "qzfs/enc_0/disk_0x2_SERIE0002_3", "nivel": 3, "papel": "datos", "grupo": "raidz1-0",
        "es_disco": True, "cabina": 0, "bahia": 2, "estado": "FAULTED", "lectura": 12, "escritura": 1500,
        "suma": 3, "nota": "too many errors"}
    nuevo = por(pool["dispositivos"], "nombre", "qzfs/enc_1/disk_0x10004_SERIE0009_3")
    assert (nuevo["cabina"], nuevo["bahia"], nuevo["nota"], nuevo["nivel"]) == (1, 4, "(resilvering)", 3)
    assert por(pool["dispositivos"], "nombre", "replacing-1")["es_disco"] is False


def test_una_reconstruccion_en_curso_da_su_progreso():
    (pool,) = p.pools_estado(DEGRADADO)
    assert pool["tarea"] == {
        "tipo": "resilver", "en_curso": True, "progreso_pct": 38.46, "errores": None,
        "texto": "resilver in progress since Sun Oct 11 10:00:00 2026 1.20T scanned out of 3.12T at 120M/s, "
                 "4h33m to go 100G resilvered, 38.46% done"}


def test_los_discos_de_repuesto_no_tienen_contadores():
    (pool,) = p.pools_estado(DEGRADADO)
    repuesto = por(pool["dispositivos"], "papel", "spares")
    assert repuesto == {
        "nombre": "qzfs/enc_0/disk_0x8_SERIE0008_3", "nivel": 1, "papel": "spares",
        "grupo": "qzfs/enc_0/disk_0x8_SERIE0008_3", "es_disco": True, "cabina": 0, "bahia": 8, "estado": "AVAIL",
        "lectura": None, "escritura": None, "suma": None, "nota": None}


def test_los_ficheros_danados_se_listan_acotados():
    (pool,) = p.pools_estado(DEGRADADO)
    assert pool["errores_de_datos"] == {
        "hay": True, "texto": "Permanent errors have been detected in the following files:",
        "ficheros": ["/share/ZFS2_DATA/carpeta1/informe.docx", "zpool1/zfs2@snapshot3:/carpeta1/otro fichero.xlsx"],
        "total": 2}
    muchos = DEGRADADO + "".join("        /share/ZFS2_DATA/f%d\n" % i for i in range(60))
    (pool,) = p.pools_estado(muchos)
    assert pool["errores_de_datos"]["total"] == 62 and len(pool["errores_de_datos"]["ficheros"]) == p.MAX_FICHEROS


def test_una_verificacion_en_curso_no_es_una_reconstruccion():
    # escrito a mano
    texto = DEGRADADO.replace("resilver in progress", "scrub in progress").replace("100G resilvered", "0 repaired")
    (pool,) = p.pools_estado(texto)
    assert (pool["tarea"]["tipo"], pool["tarea"]["en_curso"], pool["tarea"]["progreso_pct"]) == ("scrub", True, 38.46)


@pytest.mark.parametrize("texto", [
    "", "no pools available\n", " state: ONLINE\n",
    "  pool: zpool1\n state: ONLINE\nconfig:\n\n\tNAME  STATE  READ WRITE CKSUM\n\tzpool1  ONLINE  0  0  0\n",
    "  pool: zpool1\nconfig:\n\n\tNAME  STATE  READ WRITE CKSUM\n\tzpool1  ONLINE  0  0  0\n\t  disco  ONLINE  0  0  0\n",
    "  pool: zpool1\n state: ONLINE\nconfig:\n\n\tNAME  STATE  READ WRITE CKSUM\n\tzpool1  ONLINE  0  0  0\n"
    "\t  disco  ONLINE  cero  0  0\n"])
def test_el_estado_de_los_pools_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.pools_estado(texto)


# --- datasets (zfs list) ------------------------------------------------------------------------

def test_los_datasets_dan_tamanos_en_bytes_cuota_y_propiedades():
    datasets = p.datasets(dato("datasets_hero"))
    assert len(datasets) == 32
    assert por(datasets, "nombre", "zpool1/zfs2") == {
        "nombre": "zpool1/zfs2", "pool": "zpool1", "tipo": "filesystem", "usado": 75099234304,
        "disponible": 32275259392, "referido": 75098923008, "cuota": None, "cuota_ref": 107374182400,
        "compresion_ratio": 1.1, "montaje": "/share/ZFS2_DATA", "compresion": "on", "dedup": "off",
        "cifrado": False, "clave": None}
    raiz = por(datasets, "nombre", "zpool2")
    assert (raiz["pool"], raiz["cuota_ref"], raiz["montaje"], raiz["compresion"]) == ("zpool2", None, "/zpool2", "off")


def test_un_volumen_de_bloques_no_tiene_cuota_ni_punto_de_montaje():
    zvol = por(p.datasets(dato("datasets_hero")), "nombre", "zpool1/zvol_cs_docker")
    assert (zvol["tipo"], zvol["cuota"], zvol["cuota_ref"], zvol["montaje"]) == ("volume", None, None, None)
    assert zvol["usado"] == 4469821440


def test_un_dataset_cifrado_dice_si_tiene_la_clave_cargada():
    # escrito a mano: ningun NAS de pruebas tenia carpetas cifradas
    cerrado, abierto = p.datasets(
        "zpool1/zfs5\tfilesystem\t100\t200\t100\t0\t0\t1.00x\t/share/ZFS5_DATA\ton\toff\taes-256-ccm\tunavailable\n"
        "zpool1/zfs6\tfilesystem\t100\t200\t100\t300\t0\t2.50x\t/share/ZFS6_DATA\tlz4\ton\taes-256-gcm\tavailable\n")
    assert (cerrado["cifrado"], cerrado["clave"]) == (True, "unavailable")
    assert (abierto["cifrado"], abierto["clave"], abierto["cuota"], abierto["compresion"], abierto["dedup"]) == (
        True, "available", 300, "lz4", "on")
    assert abierto["compresion_ratio"] == 2.5


@pytest.mark.parametrize("texto", [
    "", "cannot open 'x': dataset does not exist\n", "zpool1\tfilesystem\t1\t2\n",
    "zpool1\tfilesystem\tmucho\t2\t3\t0\t0\t1.00x\t/zpool1\toff\toff\toff\tnone\n"])
def test_los_datasets_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.datasets(texto)


# --- instantaneas (zfs list -t snapshot) --------------------------------------------------------

def test_las_instantaneas_dan_dataset_nombre_espacio_y_fecha():
    snaps = p.zfs_snapshots(dato("zfs_snapshots_hero"))
    assert len(snaps) == 20
    assert por(snaps, "nombre", "zpool2/zfs20@snapshot4") == {
        "nombre": "zpool2/zfs20@snapshot4", "dataset": "zpool2/zfs20", "instantanea": "snapshot4",
        "usado": 616823918592, "referido": 624439214080, "creada_epoch": 1781135108,
        "creada": "2026-06-10T23:45:08Z"}
    # de la mas antigua a la mas reciente, como las da el NAS
    assert snaps[0]["creada"] == "2021-10-25T18:48:48Z" and snaps[-1]["instantanea"] == "snapshot7"


def test_un_nas_sin_instantaneas_devuelve_una_lista_vacia():
    assert p.zfs_snapshots("") == []


@pytest.mark.parametrize("texto", [
    "cannot open: permission denied\n", "zpool1/zfs2\t1\t2\t3\n", "zpool1/zfs2@a\t1\t2\n",
    "zpool1/zfs2@a\tuno\t2\t3\n"])
def test_las_instantaneas_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.zfs_snapshots(texto)


def test_lo_retenido_por_instantaneas_da_los_bytes_de_cada_dataset():
    retenido = p.zfs_retenido(dato("zfs_retenido_hero"))
    assert len(retenido) == 32
    assert retenido["zpool2/zfs19"] == 66376134656 and retenido["zpool1/zfs1107"] == 0


@pytest.mark.parametrize("texto", ["", "cannot open: permission denied\n", "zpool1/zfs2\n",
                                   "zpool1/zfs2\tmucho\n", "zpool1/zfs2\t1\t2\n"])
def test_lo_retenido_por_instantaneas_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.zfs_retenido(texto)


# --- programacion de instantaneas (zsnapshotSchedule.conf) --------------------------------------

def test_la_programacion_separa_retenciones_y_programaciones_por_volumen():
    prog = p.snapshots_prog(dato("zfs_snapshots_prog_hero"))
    assert prog["global"] == {"lastRetentionTime": 1791932400}
    assert len(prog["retenciones"]) == 12 and [x["volumen"] for x in prog["programaciones"]] == [19, 24]
    assert por(prog["retenciones"], "volumen", 19) == {
        "volumen": 19, "retention": 1, "expiremin": 0, "keepAmount": 10, "hourAmount": 24, "dayAmount": 7,
        "weekAmount": 4, "monthAmount": 12}
    diaria = por(prog["programaciones"], "volumen", 24)
    assert (diaria["Schedule"], diaria["schedule_status"], diaria["ScheduleTime"], diaria["WeekDay"]) == (
        4, 2, 1791928800, None)
    assert por(prog["programaciones"], "volumen", 19)["Frequency"] == 30
    assert "source_lv_id" not in diaria


def test_sin_fichero_de_programacion_no_hay_nada_programado():
    assert p.snapshots_prog("") == {"global": {}, "retenciones": [], "programaciones": []}


def test_una_seccion_desconocida_de_la_programacion_se_ignora():
    # escrito a mano
    prog = p.snapshots_prog("[Otra]\nsmart = 1\n[Schedule7]\nsource_lv_id = 7\nSchedule = 4\n")
    assert prog == {"global": {}, "retenciones": [], "programaciones": [{"volumen": 7, "Schedule": 4}]}


@pytest.mark.parametrize("texto", [
    "grep: fichero: Permission denied\n", "Schedule = 4\n", "[Schedule7]\nlinea sin igual\n"])
def test_la_programacion_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.snapshots_prog(texto)


# --- iSCSI en QuTS hero (dos JSON, solo las claves elegidas) ------------------------------------

def test_el_iscsi_de_hero_da_el_servicio_y_los_iniciadores():
    assert p.zfs_iscsi(dato("zfs_iscsi_hero")) == {
        "servicio": {"activo": True, "puerto": 3260, "prefijo_iqn": "iqn.2004-04.com.example:destino-1"},
        "destinos": [], "lun": [],
        "iniciadores": [{"id": 0, "nombre": "iqn.2004-04.com.example:destino-2", "alias": "Default Policy"}]}


# escrito a mano: ningun NAS de pruebas tenia destinos ni LUN; la forma (una entrada numerada con
# "name" y "alias") es la de los iniciadores, que si se ha visto
CON_LUN = (
    '== /etc/config/hero_zfs_lun.json\n'
    '  "lun":{\n    "0":{\n      "name":"lun_0",\n    "3":{\n      "name":"copias",\n      "alias":"%s"\n'
    '== /etc/config/hero_iscsi_scst.json\n'
    '  "portal":{\n    "service_enable":false,\n    "service_port":3260,\n'
    '  "target":{\n    "0":{\n      "name":"iqn.2004-04.com.example:destino-1",\n      "alias":"destino"\n'
    '  "initiator":{}\n') % ("x" * 300)


def test_el_iscsi_de_hero_lista_destinos_y_lun_si_los_hay():
    iscsi = p.zfs_iscsi(CON_LUN)
    assert iscsi["servicio"] == {"activo": False, "puerto": 3260, "prefijo_iqn": None}
    assert iscsi["destinos"] == [{"id": 0, "nombre": "iqn.2004-04.com.example:destino-1", "alias": "destino",
                                  "activo": None, "estado": None, "portales": [], "lun": [],
                                  "acl_iniciador": None}]
    assert [(x["id"], x["nombre"]) for x in iscsi["lun"]] == [(0, "lun_0"), (3, "copias")]
    assert iscsi["lun"][0]["alias"] is None
    assert iscsi["iniciadores"] == []


def test_el_iscsi_de_hero_con_un_destino_y_un_lun_reales():
    # creados desde la web en el NAS de laboratorio (2026-10-14): la orden saca tambien las claves
    # que cuelgan mas hondo (el grupo de acceso y los LUN de cada destino)
    iscsi = p.zfs_iscsi(dato("zfs_iscsi_destino_hero"))
    assert iscsi["servicio"] == {"activo": True, "puerto": 3260, "prefijo_iqn": "iqn.2004-04.com.example:destino-1"}
    assert iscsi["destinos"] == [{
        "id": 1, "nombre": "iqn.2004-04.com.example:destino-3", "alias": "prueba", "activo": True, "estado": 0,
        "portales": ["192.0.2.10"], "lun": ["LUN_prueba"], "acl_iniciador": 0}]
    assert iscsi["lun"] == [{"id": 1, "nombre": "LUN_prueba", "alias": None, "capacidad": 2 ** 30, "fino": True,
                             "estado": 1, "dataset": "zpool1/zfs274"}]
    assert iscsi["iniciadores"] == [
        {"id": 0, "nombre": "iqn.2004-04.com.example:destino-2", "alias": "Default Policy"}]


def test_una_clave_de_iscsi_mas_honda_que_no_se_conoce_se_ignora_dentro_de_una_entrada():
    # escrito a mano: un objeto nuevo dentro de un destino cuyo nombre no se pide no tumba la lectura
    texto = dato("zfs_iscsi_destino_hero").replace(
        '      "interfaces"', '        "name":"de un objeto que no se pide"\n          "1":{\n'
                              '            "alias":"tampoco"\n      "interfaces"')
    assert p.zfs_iscsi(texto)["destinos"][0]["nombre"] == "iqn.2004-04.com.example:destino-3"


def test_el_alias_que_escribe_un_tercero_llega_acotado():
    assert len(p.zfs_iscsi(CON_LUN)["lun"][1]["alias"]) == p.MAX_TEXTO


def test_un_nas_sin_ficheros_de_iscsi_no_tiene_servicio():
    assert p.zfs_iscsi("") == {"servicio": None, "destinos": [], "lun": [], "iniciadores": []}


@pytest.mark.parametrize("texto", [
    "grep: fichero: Permission denied\n", '  "lun":{}\n', "== /etc/config/hero_zfs_lun.json\n",
    '== /etc/config/hero_zfs_lun.json\n  "lun":{\n      "name":"suelto",\n',
    '== /etc/config/hero_iscsi_scst.json\n  "portal":{\n    "service_port":muchos,\n'])
def test_el_iscsi_de_hero_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.zfs_iscsi(texto)


# ==== QTS =========================================================================================

# --- grupos md (/proc/mdstat) -------------------------------------------------------------------

def test_mdstat_da_nivel_miembros_y_mapa_de_cada_grupo():
    grupos = p.mdstat(dato("mdstat_qts"))
    assert [g["grupo"] for g in grupos] == ["md2", "md280", "md1", "md322", "md256", "md13", "md9"]
    datos = por(grupos, "grupo", "md1")
    assert (datos["activo"], datos["nivel"], datos["bytes"]) == (True, "raid6", 14601556480 * 1024)
    assert (datos["esperados"], datos["presentes"], datos["mapa"], datos["degradado"]) == (7, 7, "UUUUUUU", False)
    assert datos["tarea"] is None and len(datos["miembros"]) == 7
    assert datos["miembros"][0] == {
        "dispositivo": "sdc3", "disco": "sdc", "posicion": 9, "repuesto": False, "fallado": False}


def test_mdstat_distingue_los_miembros_de_repuesto():
    grupos = p.mdstat(dato("mdstat_qts"))
    intercambio = por(grupos, "grupo", "md322")
    assert [m["disco"] for m in intercambio["miembros"] if m["repuesto"]] == ["sdi", "sdh", "sdg", "sdf", "sde"]
    assert [m["disco"] for m in intercambio["miembros"] if not m["repuesto"]] == ["sdd", "sdc"]


def test_mdstat_cuenta_los_huecos_de_los_grupos_del_sistema():
    # los grupos del sistema de QNAP (md9, md13) se crean con sitio para 24 discos o mas: sus
    # huecos son normales; quien decide si importa es el servidor, que sabe cuales son de datos
    sistema = por(p.mdstat(dato("mdstat_qts")), "grupo", "md13")
    assert (sistema["esperados"], sistema["presentes"], sistema["degradado"]) == (24, 9, True)
    assert sistema["mapa"] == "UUUUUUUUU" + "_" * 15


def test_mdstat_saca_el_disco_de_una_particion_nvme():
    grupos = p.mdstat(dato("mdstat_qts2"))
    assert len(grupos) == 10
    assert [m["disco"] for m in por(grupos, "grupo", "md4")["miembros"]] == ["nvme0n1", "nvme1n1"]
    grande = por(grupos, "grupo", "md5")
    assert (grande["nivel"], grande["esperados"], grande["presentes"], len(grande["miembros"])) == ("raid5", 12, 12, 12)


# escrito a mano con el formato del kernel: ningun NAS de pruebas estaba reconstruyendo
RECONSTRUYENDO = (
    "Personalities : [raid1] [raid6] [raid5] [raid4] \n"
    "md1 : active raid5 sdd3[4] sdc3[2] sdb3[1](F) sda3[0]\n"
    "      8760934848 blocks super 1.0 level 5, 512k chunk, algorithm 2 [4/3] [U_UU]\n"
    "      [==>..................]  recovery = 12.3% (359795712/2920311296) finish=412.8min speed=103354K/sec\n"
    "      bitmap: 3/22 pages [12KB], 65536KB chunk\n"
    "\n"
    "md2 : active raid1 sdf3[1] sde3[0]\n"
    "      96539136 blocks super 1.0 [2/2] [UU]\n"
    "      [=>...................]  check =  8.0% (7723136/96539136) finish=11.2min speed=131072K/sec\n"
    "\n"
    "md3 : active raid1 sdh3[1] sdg3[0]\n"
    "      96539136 blocks super 1.0 [2/2] [UU]\n"
    "      \tresync=DELAYED\n"
    "\n"
    "md4 : inactive sdi3[0](S)\n"
    "      96539136 blocks super 1.0\n"
    "\n"
    "unused devices: <none>\n")


def test_una_reconstruccion_da_progreso_tiempo_y_velocidad():
    grupos = p.mdstat(RECONSTRUYENDO)
    roto = por(grupos, "grupo", "md1")
    assert (roto["esperados"], roto["presentes"], roto["mapa"], roto["degradado"]) == (4, 3, "U_UU", True)
    assert roto["tarea"] == {
        "tipo": "recovery", "progreso_pct": 12.3, "restante_min": 412.8, "velocidad_kb_s": 103354, "en_espera": False}
    assert [m["disco"] for m in roto["miembros"] if m["fallado"]] == ["sdb"]


def test_una_verificacion_y_una_tarea_en_espera_no_se_confunden_con_una_reconstruccion():
    grupos = p.mdstat(RECONSTRUYENDO)
    assert por(grupos, "grupo", "md2")["tarea"] == {
        "tipo": "check", "progreso_pct": 8.0, "restante_min": 11.2, "velocidad_kb_s": 131072, "en_espera": False}
    assert por(grupos, "grupo", "md3")["tarea"] == {
        "tipo": "resync", "progreso_pct": None, "restante_min": None, "velocidad_kb_s": None, "en_espera": True}


def test_un_grupo_inactivo_no_tiene_nivel_ni_mapa():
    parado = por(p.mdstat(RECONSTRUYENDO), "grupo", "md4")
    assert (parado["activo"], parado["nivel"], parado["mapa"], parado["esperados"], parado["degradado"]) == (
        False, None, None, None, None)
    assert parado["miembros"][0]["repuesto"] is True


def test_un_nas_sin_grupos_md_devuelve_una_lista_vacia():
    assert p.mdstat("Personalities : \nunused devices: <none>\n") == []


@pytest.mark.parametrize("texto", [
    "", "cat: /proc/mdstat: No such file or directory\n",
    "Personalities : [raid1] \nmd1 : active raid1 sdb3[1] sda3[0]\nunused devices: <none>\n",
    "Personalities : [raid1] \nmd1 : active raid1 sdb3 sda3[0]\n      96539136 blocks super 1.0 [2/2] [UU]\n"])
def test_mdstat_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.mdstat(texto)


# --- estado de cada grupo (/sys/block/md*/md) ---------------------------------------------------

def test_md_sys_da_accion_degradado_y_discrepancias():
    grupos = p.md_sys(dato("md_sys_qts"))
    assert len(grupos) == 7
    assert por(grupos, "grupo", "md1") == {
        "grupo": "md1", "nivel": "raid6", "estado": "clean", "accion": "idle", "degradado": 0, "discrepancias": 0}
    assert por(grupos, "grupo", "md13")["degradado"] == 15 and por(grupos, "grupo", "md2")["estado"] == "active"
    assert len(p.md_sys(dato("md_sys_qts2"))) == 10


def test_un_valor_que_el_grupo_no_tiene_queda_sin_dato_no_a_cero():
    # escrito a mano: un raid0 no tiene accion de sincronizacion ni contador de degradado
    (grupo,) = p.md_sys("== /sys/block/md0/md\nnivel=raid0\nestado=clean\naccion=\ndegradado=\ndiscrepancias=\n")
    assert grupo == {"grupo": "md0", "nivel": "raid0", "estado": "clean", "accion": None, "degradado": None,
                     "discrepancias": None}


@pytest.mark.parametrize("texto", [
    "", "== /sys/block/md*/md\nnivel=\nestado=\naccion=\ndegradado=\ndiscrepancias=\n", "nivel=raid1\n",
    "== /sys/block/md1/md\nnivel=raid1\nestado=clean\naccion=idle\ndegradado=poco\ndiscrepancias=0\n",
    "== /sys/block/md1/md\nnivel=raid1\n"])
def test_md_sys_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.md_sys(texto)


# --- grupos segun QTS (raid.conf) ---------------------------------------------------------------

def test_raid_conf_da_los_grupos_de_datos_con_sus_miembros_por_bahia():
    conf = p.raid_conf(dato("raid_conf_qts"))
    assert [g["id"] for g in conf["grupos"]] == [2, 1]
    datos = por(conf["grupos"], "id", 1)
    assert (datos["dispositivo"], datos["grupo"], datos["nivel"]) == ("/dev/md1", "md1", "6")
    assert datos["miembros"] == [{"cabina": 0, "bahia": n} for n in range(1, 8)] and datos["repuestos"] == []
    # la cache: dos SSD de la cabina interna 23
    assert por(conf["grupos"], "id", 2)["miembros"] == [{"cabina": 23, "bahia": 1}, {"cabina": 23, "bahia": 2}]
    assert conf["repuestos_globales"] == [{"cabina": 0, "bahia": 8}]


def test_raid_conf_numera_las_bahias_en_hexadecimal_y_la_cabina_en_la_parte_alta():
    conf = p.raid_conf(dato("raid_conf_qts2"))
    assert por(conf["grupos"], "id", 3)["miembros"] == [{"cabina": 0, "bahia": 4}, {"cabina": 0, "bahia": 11}]
    assert por(conf["grupos"], "id", 5)["miembros"] == [{"cabina": 1, "bahia": n} for n in range(1, 13)]
    assert [m["bahia"] for m in por(conf["grupos"], "id", 2)["miembros"]] == [3, 5, 6, 7, 8, 9, 10, 12]
    assert conf["repuestos_globales"] == []


def test_un_repuesto_propio_de_un_grupo_se_distingue_de_sus_miembros():
    # escrito a mano
    conf = p.raid_conf("[RAID_1]\nid = 1\ndeviceName = /dev/md1\nraidLevel = 5\ndata_0 = 1\nspare_0 = 4\n")
    assert conf["grupos"][0]["repuestos"] == [{"cabina": 0, "bahia": 4}]


def test_sin_raid_conf_no_hay_grupos():
    assert p.raid_conf("") == {"grupos": [], "repuestos_globales": []}


@pytest.mark.parametrize("texto", [
    "grep: /etc/config/raid.conf: Permission denied\n", "id = 1\n", "[RAID_1]\nid = uno\n",
    "[RAID_1]\nid = 1\ndata_0 = zz\n"])
def test_raid_conf_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.raid_conf(texto)


# --- volumenes (volume.conf) --------------------------------------------------------------------

def test_los_volumenes_dan_grupo_cifrado_cache_y_estado():
    volumenes = p.volumenes_conf(dato("volumenes_conf_qts"))
    assert [v["id"] for v in volumenes] == [1, 2, 3, 5, 7, 8, 4]
    assert por(volumenes, "id", 1) == {
        "id": 1, "nombre": "volumen1", "grupo_id": 1, "grupo": "/dev/md1", "cifrado": False,
        "cache_ssd": False, "sucio": False, "dispositivo": "/dev/mapper/cachedev1", "solo_lectura": False,
        "estado": 0, "tipo": 1, "interno": True}
    assert por(volumenes, "id", 2)["cache_ssd"] is True
    # un disco suelto (aqui el de repuesto) y un disco externo no cuelgan de ningun grupo
    suelto = por(volumenes, "id", 5)
    assert (suelto["grupo_id"], suelto["dispositivo"], suelto["estado"], suelto["cache_ssd"], suelto["tipo"]) == (
        None, "/dev/sdj", 12, None, None)
    assert por(volumenes, "id", 7)["interno"] is False
    assert por(volumenes, "id", 4)["dispositivo"] == "/dev/mapper/vg256-lv256"
    assert len(p.volumenes_conf(dato("volumenes_conf_qts2"))) == 12


def test_un_volumen_cifrado_o_sin_cerrar_bien_queda_marcado():
    # escrito a mano
    (volumen,) = p.volumenes_conf(
        "[VOL_1]\nvolId = 1\nvolName = %s\nencryption = yes\nunclean = yes\nreadOnly = yes\nstatus = -3\n" % ("x" * 400))
    assert (volumen["cifrado"], volumen["sucio"], volumen["solo_lectura"], volumen["estado"]) == (True, True, True, -3)
    assert len(volumen["nombre"]) == p.MAX_NOMBRE


def test_sin_volume_conf_no_hay_volumenes():
    assert p.volumenes_conf("") == []


@pytest.mark.parametrize("texto", [
    "grep: /etc/volume.conf: Permission denied\n", "volId = 1\n", "[VOL_1]\nvolId = uno\n",
    "[VOL_1]\nvolId = 1\nencryption = quiza\n"])
def test_los_volumenes_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.volumenes_conf(texto)


# --- pools y volumenes logicos (qlvm.conf) ------------------------------------------------------

def test_lvm_conf_da_pools_pools_ligeros_y_volumenes_logicos_en_bytes():
    lvm = p.lvm_conf(dato("lvm_conf_qts"))
    assert lvm["pools"] == [
        {"id": 1, "nombre": "vg1", "pool_ligero": 1, "umbral_pct": 95, "sobre_umbral": False,
         "reserva_instantaneas_pct": 10},
        {"id": 256, "nombre": "vg256", "pool_ligero": None, "umbral_pct": None, "sobre_umbral": False,
         "reserva_instantaneas_pct": 0}]
    assert lvm["pools_ligeros"] == [
        {"id": 1, "dispositivo": "/dev/mapper/vg1-tp1", "bytes": 28773572608 * 512, "metadatos_bytes": 134217728 * 512}]
    assert lvm["miembros"] == [{"id": 1, "dispositivo": "/dev/drbd1"}, {"id": 2, "dispositivo": "/dev/md2"}]
    assert [v["id"] for v in lvm["volumenes"]] == [1, 1312, 544, 3, 4, 545, 256]
    assert por(lvm["volumenes"], "id", 1) == {
        "id": 1, "pool": 1, "dispositivo": "/dev/mapper/vg1-lv1", "bytes": 7365197824 * 512, "umbral_pct": 90,
        "sobre_umbral": False, "nombre": "volumen1"}
    # los volumenes internos del NAS no tienen nombre de usuario; el fichero mezcla "a=b" y "a = b"
    assert por(lvm["volumenes"], "id", 544)["nombre"] is None and por(lvm["volumenes"], "id", 4)["pool"] == 1


def test_sin_qlvm_conf_no_hay_pools():
    assert p.lvm_conf("") == {"pools": [], "pools_ligeros": [], "volumenes": [], "miembros": []}


@pytest.mark.parametrize("texto", [
    "grep: /etc/config/qlvm.conf: Permission denied\n", "poolId=1\n", "[POOL_1]\npoolId=uno\n",
    "[LV_1]\nlvId=1\nlvSize=grande\n", "[POOL_1]\npoolId=1\noverThreshold = quiza\n"])
def test_lvm_conf_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.lvm_conf(texto)


# --- pools ligeros y cache en uso (dmsetup status) ----------------------------------------------

def test_dm_estado_da_la_ocupacion_de_datos_y_metadatos_de_cada_pool_ligero():
    dm = p.dm_estado(dato("dm_estado_qts"))
    assert por(dm, "tipo", "thin-pool") == {
        "nombre": "vg1-tp1-tpool", "tipo": "thin-pool", "pool": 1, "bytes": 28773572608 * 512,
        "datos_pct": 51.4, "metadatos_pct": 1.1, "modo": "rw", "fallo": False}
    varios = [d for d in p.dm_estado(dato("dm_estado_qts2")) if d["tipo"] == "thin-pool"]
    assert [(d["pool"], d["datos_pct"], d["metadatos_pct"]) for d in varios] == [
        (4, 73.0, 4.5), (3, 89.6, 1.5), (2, 85.5, 4.0), (1, 88.0, 0.1)]


def test_dm_estado_da_la_ocupacion_de_la_cache_ssd():
    assert por(p.dm_estado(dato("dm_estado_qts")), "tipo", "cache") == {
        "nombre": "vg256-lv256", "tipo": "cache", "pool": 256, "bytes": 159686656 * 512, "usado_pct": 100.0,
        "metadatos_pct": 0.1}
    assert por(p.dm_estado(dato("dm_estado_qts2")), "tipo", "cache")["usado_pct"] == 99.8


def test_dm_estado_solo_devuelve_pools_ligeros_cache_y_cifrado():
    dm = p.dm_estado(dato("dm_estado_qts"))
    assert sorted(d["tipo"] for d in dm) == ["cache", "cache_client", "thin-pool"]
    cliente = por(dm, "tipo", "cache_client")
    assert (cliente["nombre"], cliente["pool"], cliente["bloques_usados"], cliente["bloques"]) == (
        "vg1-tp1_tierdata_2", 1, 77972, 77972)


def test_un_pool_ligero_averiado_o_en_solo_lectura_queda_marcado():
    # escrito a mano con el formato del kernel
    dm = p.dm_estado(
        "vg1-tp1-tpool: 0 1000 thin-pool Fail\n"
        "vg2-tp2-tpool: 0 2000 thin-pool 7 10/100 990/1000 - out_of_data_space no_discard_passdown\n"
        "ce_cachedev1: 0 3000 crypt \ncachedev1: 0 3000 linear \nvg1-snap-1: 0 500 snapshot 16/100 16\n")
    assert dm[0] == {"nombre": "vg1-tp1-tpool", "tipo": "thin-pool", "pool": 1, "bytes": 512000,
                     "datos_pct": None, "metadatos_pct": None, "modo": None, "fallo": True}
    assert (dm[1]["datos_pct"], dm[1]["metadatos_pct"], dm[1]["modo"], dm[1]["fallo"]) == (
        99.0, 10.0, "out_of_data_space", False)
    assert dm[2] == {"nombre": "ce_cachedev1", "tipo": "crypt", "pool": None, "bytes": 1536000}
    assert len(dm) == 3


def test_un_nas_sin_pools_ligeros_devuelve_una_lista_vacia():
    assert p.dm_estado("cachedev1: 0 3000 linear \n") == []


@pytest.mark.parametrize("texto", [
    "", "dmsetup: command not found\n", "vg1-tp1-tpool: 0 1000 thin-pool 7 muchos/100 1/2 - rw\n",
    "vg1-tp1-tpool: 0 1000 thin-pool 7\n", "vg256-lv256: 0 1000 cache 8\n"])
def test_dm_estado_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.dm_estado(texto)


# --- instantaneas (snapshot.conf) ---------------------------------------------------------------

# reconstruido: la exploracion no guardo estos campos; los nombres, el orden y la relacion entre
# identificador, volumen y tamano son los del bloque real leido de un QTS el 2026-10-14
INSTANTANEAS_QTS = (
    "[Global]\nCount = 3\n[Sequence]\n"
    "[Snapshot30020]\nsnapshotId = 30020\nname = GMT+01_2026-10-07_2054\nsize = 4294967296\nexpiremin = 2880\n"
    "time = 1791399240\nvital = 0\nsnapshot_type = 0\nreplicated = 0\n"
    "[Snapshot10001]\nsnapshotId = 10001\nname = GMT+01_2026-10-13_1700\nsize = 7365197824\nexpiremin = 0\n"
    "time = 1791903632\nvital = 1\nsnapshot_type = 0\nreplicated = 1\n"
    "[Snapshot10560003]\nsnapshotId = 10560003\nname = %s\nsize = 2097152\nexpiremin = 0\n"
    "time = 1750000000\nvital = 0\nsnapshot_type = 0\n") % ("y" * 300)


def test_las_instantaneas_de_qts_dan_volumen_fecha_y_caducidad_ordenadas_por_fecha():
    snaps = p.lvm_snapshots(INSTANTANEAS_QTS)
    assert snaps["total"] == 3
    assert [s["id"] for s in snaps["instantaneas"]] == [10560003, 30020, 10001]
    assert por(snaps["instantaneas"], "id", 10001) == {
        "id": 10001, "volumen": 1, "nombre": "GMT+01_2026-10-13_1700", "bytes": 7365197824 * 512,
        "creada_epoch": 1791903632, "creada": "2026-10-13T15:00:32Z", "caduca_min": None, "vital": True,
        "replicada": True}
    otra = por(snaps["instantaneas"], "id", 30020)
    assert (otra["volumen"], otra["caduca_min"], otra["vital"], otra["replicada"]) == (3, 2880, False, False)


def test_el_volumen_de_una_instantanea_sale_de_su_identificador():
    # los volumenes de replica tienen identificadores de cuatro cifras
    snaps = p.lvm_snapshots(INSTANTANEAS_QTS)["instantaneas"]
    assert snaps[0]["volumen"] == 1056 and snaps[0]["replicada"] is None
    assert len(snaps[0]["nombre"]) == p.MAX_NOMBRE


def test_sin_snapshot_conf_no_hay_instantaneas():
    assert p.lvm_snapshots("") == {"total": None, "instantaneas": []}
    assert p.lvm_snapshots("[Global]\nCount = 0\n[Sequence]\n") == {"total": 0, "instantaneas": []}


@pytest.mark.parametrize("texto", [
    "grep: fichero: Permission denied\n", "snapshotId = 1\n", "[Snapshot30020]\nsnapshotId = treinta\n",
    "[Snapshot30020]\nname = sin identificador\n", "[Snapshot30020]\nsnapshotId = 30020\ntime = ayer\n"])
def test_las_instantaneas_de_qts_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.lvm_snapshots(texto)


def test_la_programacion_de_qts_se_lee_con_el_mismo_formato_que_la_de_hero():
    prog = p.snapshots_prog(dato("lvm_snapshots_prog_qts"))
    assert [x["volumen"] for x in prog["programaciones"]] == [1, 3]
    assert por(prog["programaciones"], "volumen", 1) == {
        "volumen": 1, "Schedule": 4, "MonthDay": 0, "WeekDay": 0, "Hour": 17, "Minute": 0,
        "ScheduleTime": 1791903601, "expiremin": 2880, "smart": 1, "snapshot_type": 0, "status": 0, "vital": 0,
        "schedule_status": 2}
    assert [x["volumen"] for x in prog["retenciones"]] == [3, 288, 2, 1, 4]
    assert len(p.snapshots_prog(dato("lvm_snapshots_prog_qts2"))["retenciones"]) == 4


# --- iSCSI en QTS (iscsi_trgt.conf) -------------------------------------------------------------

def test_el_iscsi_de_qts_da_el_servicio_y_los_iniciadores():
    assert p.lvm_iscsi(dato("lvm_iscsi_qts")) == {
        "servicio": {"activo": True, "puerto": 3260, "prefijo_iqn": "iqn.2004-04.com.example:destino-1"},
        "destinos": [], "lun": [],
        "iniciadores": [{"id": 0, "nombre": "iqn.2004-04.com.example:destino-2", "alias": "Default Policy"}]}


def test_el_iscsi_de_qts_lista_destinos_y_lun_si_los_hay():
    # escrito a mano: ningun NAS de pruebas tenia destinos ni LUN; los nombres de seccion y de
    # campo siguen el patron de la seccion de iniciadores, que si se ha visto
    iscsi = p.lvm_iscsi(
        "[iSCSIPortal]\nbServiceEnable = FALSE\nservicePort = 3260\n"
        "[target0Info]\ntargetIndex = 0\ntargetName = copias\ntargetIQN = iqn.2004-04.com.example:destino-1\n"
        "targetAlias = %s\nbTargetEnable = TRUE\ntargetStatus = 0\n"
        "[LUN3Info]\nLUNIndex = 3\nLUNName = lun_copias\nLUNCapacity = 2097152\nLUNStatus = 1\nbLUNEnable = FALSE\n"
        "[TargetKey]\n[LUNKey]\n[InitiatorKey]\n" % ("z" * 200))
    assert iscsi["servicio"] == {"activo": False, "puerto": 3260, "prefijo_iqn": None}
    (destino,) = iscsi["destinos"]
    assert (destino["id"], destino["nombre"], destino["iqn"], destino["activo"], destino["estado"]) == (
        0, "copias", "iqn.2004-04.com.example:destino-1", True, 0)
    assert len(destino["alias"]) == p.MAX_TEXTO
    assert iscsi["lun"] == [{"id": 3, "nombre": "lun_copias", "capacidad": 2097152, "estado": 1, "activo": False}]
    assert iscsi["iniciadores"] == []


def test_sin_fichero_de_iscsi_en_qts_no_hay_servicio():
    assert p.lvm_iscsi("") == {"servicio": None, "destinos": [], "lun": [], "iniciadores": []}


@pytest.mark.parametrize("texto", [
    "grep: fichero: Permission denied\n", "servicePort = 3260\n", "[iSCSIPortal]\nservicePort = muchos\n",
    "[iSCSIPortal]\nbServiceEnable = quiza\n"])
def test_el_iscsi_de_qts_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.lvm_iscsi(texto)


# ==== carpetas compartidas y ocupacion (los dos sistemas) ========================================

# --- ocupacion (df) -----------------------------------------------------------------------------

def test_la_ocupacion_da_bytes_y_porcentaje_de_cada_volumen():
    ocupacion = p.ocupacion(dato("ocupacion_hero"))
    assert len(ocupacion) == 12
    assert por(ocupacion, "montaje", "/share/ZFS2_DATA") == {
        "dispositivo": "zpool1/zfs2", "bytes": 104857600 * 1024, "usado": 73338796 * 1024,
        "libre": 31518804 * 1024, "ocupacion_pct": 70, "montaje": "/share/ZFS2_DATA"}
    # las carpetas de /share que no son un montaje salen como el tmpfs de /share: no cuentan
    assert all(o["montaje"].startswith("/share/") and o["dispositivo"] != "tmpfs" for o in ocupacion)


def test_la_ocupacion_de_qts_tiene_el_mismo_formato():
    # escrito a mano con el formato de df -P -k: de QTS solo hay guardado un df sin esas opciones
    ocupacion = p.ocupacion(
        "Filesystem           1024-blocks    Used Available Capacity Mounted on\n"
        "none                    409600    336808     72792  82% /\n"
        "/dev/mapper/cachedev1 3624002472 960495816 2663506656  27% /share/CACHEDEV1_DATA\n"
        "//192.0.2.9/copias    1000 250 750  25% /share/external/.nd/0/una carpeta con espacios\n"
        "tmpfs                    49152        44     49108   0% /share/CACHEDEV1_DATA/.samba/lock/msg.lock\n")
    assert ocupacion == [
        {"dispositivo": "/dev/mapper/cachedev1", "bytes": 3624002472 * 1024, "usado": 960495816 * 1024,
         "libre": 2663506656 * 1024, "ocupacion_pct": 27, "montaje": "/share/CACHEDEV1_DATA"},
        {"dispositivo": "//192.0.2.9/copias", "bytes": 1024000, "usado": 256000, "libre": 768000,
         "ocupacion_pct": 25, "montaje": "/share/external/.nd/0/una carpeta con espacios"}]


def test_un_nas_sin_volumenes_montados_devuelve_una_lista_vacia():
    assert p.ocupacion("Filesystem 1024-blocks Used Available Capacity Mounted on\nnone 1 1 0 100% /\n") == []


@pytest.mark.parametrize("texto", [
    "", "df: command not found\n", "none 1 1 0 100% /\n",
    "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 mucho 1 0 100% /share/X\n",
    "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 1 1\n"])
def test_la_ocupacion_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.ocupacion(texto)


# --- carpetas (smb.conf) ------------------------------------------------------------------------

def test_cada_carpeta_da_ruta_volumen_comentario_y_quien_accede():
    carpetas = p.carpetas_smb(dato("carpetas_smb_hero"))
    assert len(carpetas) == 11                      # la seccion [global] no es una carpeta
    assert por(carpetas, "nombre", "carpeta1") == {
        "nombre": "carpeta1", "ruta": "/share/ZFS2_DATA/carpeta1", "volumen": "ZFS2_DATA",
        "comentario": "System default share", "visible": True, "papelera": True, "invitados": None,
        "usuarios_validos": {"usuarios": ["root", "admin", "usuario15", "carpeta5", "usuario14"],
                             "grupos": ["everyone", "administrators"]},
        "denegados": {"usuarios": ["guest"], "grupos": []},
        "solo_lectura": {"usuarios": ["carpeta5", "usuario14"], "grupos": ["everyone"]},
        "escritura": {"usuarios": ["admin", "usuario15"], "grupos": ["administrators"]}}
    sin_comentario = por(carpetas, "nombre", "carpeta5")
    assert (sin_comentario["comentario"], sin_comentario["papelera"]) == (None, False)
    assert sin_comentario["solo_lectura"] == {"usuarios": [], "grupos": []}


def test_las_carpetas_de_qts_incluyen_las_montadas_de_otro_equipo():
    carpetas = p.carpetas_smb(dato("carpetas_smb_qts"))
    assert len(carpetas) == 34
    remota = por(carpetas, "nombre", "carpeta39 (usuario38@192.0.2.1)")
    assert (remota["ruta"], remota["volumen"], remota["comentario"]) == (
        "/share/external/.nd/0/00000000-0000-0000-0000-000000000001", "external", "comentario de ejemplo 9")
    assert por(carpetas, "nombre", "carpeta12")["volumen"] == "CACHEDEV1_DATA"


def test_el_comentario_de_una_carpeta_llega_acotado_y_sin_saltos():
    # escrito a mano: el comentario lo escribe quien administra el NAS
    (carpeta,) = p.carpetas_smb(
        "[global]\n[Datos]\n\tcomment = %s\tfin\n  path = /share/CACHEDEV1_DATA/Datos\n browseable = no\n"
        "guest ok = yes\nvalid users = ana, @todos ,\"DOMINIO\\luis\",@\"Usuarios del dominio\"\n" % ("a" * 300))
    assert len(carpeta["comentario"]) == p.MAX_COMENTARIO == 120 and "\t" not in carpeta["comentario"]
    assert (carpeta["visible"], carpeta["invitados"], carpeta["papelera"]) == (False, True, None)
    # nombres sin comillas, con dominio y con espacios
    assert carpeta["usuarios_validos"] == {"usuarios": ["ana", "DOMINIO\\luis"],
                                           "grupos": ["todos", "Usuarios del dominio"]}
    assert carpeta["denegados"] == {"usuarios": [], "grupos": []}


def test_un_nas_sin_carpetas_solo_tiene_la_seccion_global():
    assert p.carpetas_smb("[global]\ninvalid users = guest\n") == []


@pytest.mark.parametrize("texto", [
    "", "grep: /etc/config/smb.conf: No such file or directory\n", "path = /share/X\n",
    "[global]\n[Datos]\nbrowsable = quiza\n"])
def test_las_carpetas_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.carpetas_smb(texto)


# --- uso que calcula el NAS (volumeStatus.conf) -------------------------------------------------

def test_el_uso_de_cada_carpeta_viene_en_bytes_con_la_fecha_del_dato():
    uso = p.carpetas_uso(dato("carpetas_uso_hero"))
    assert len(uso) == 9
    assert por(uso, "carpeta", "carpeta1") == {
        "carpeta": "carpeta1", "usado": 74091401216, "directorios": 87, "ficheros": 152,
        "actualizado_epoch": 1790557205, "actualizado": "2026-09-28T01:00:05Z"}
    qts = p.carpetas_uso(dato("carpetas_uso_qts"))
    assert len(qts) == 34
    assert por(qts, "carpeta", "carpeta39 (usuario38@192.0.2.1)")["ficheros"] == 33149


def test_una_carpeta_sin_dato_de_uso_no_se_lista_y_sin_fichero_no_hay_ninguna():
    # escrito a mano
    assert p.carpetas_uso("[A]\n[B]\nUsed Size = 5\n") == [
        {"carpeta": "B", "usado": 5, "directorios": None, "ficheros": None, "actualizado_epoch": None,
         "actualizado": None}]
    assert p.carpetas_uso("") == []


@pytest.mark.parametrize("texto", [
    "grep: fichero: Permission denied\n", "Used Size = 5\n", "[A]\nUsed Size = mucho\n"])
def test_el_uso_de_las_carpetas_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.carpetas_uso(texto)


# --- exportaciones NFS (/etc/exports) -----------------------------------------------------------

def test_las_exportaciones_nfs_dan_carpeta_clientes_y_opciones():
    assert p.carpetas_nfs(dato("carpetas_nfs_qts")) == [{
        "ruta": "/share/CACHEDEV1_DATA/carpeta12", "carpeta": "carpeta12",
        "clientes": [{"cliente": "192.0.2.3", "escritura": False,
                      "opciones": ["sec=sys", "ro", "async", "wdelay", "insecure", "no_subtree_check",
                                   "no_root_squash"]}]}]


def test_los_clientes_de_una_misma_carpeta_se_agrupan():
    # escrito a mano: QNAP escribe una linea por cliente; el formato tambien admite varios en una
    exportadas = p.carpetas_nfs(
        "# comentario\n"
        '"/share/CACHEDEV1_DATA/Con espacios" 192.0.2.5(rw,async,fsid=00000000000000000000000000000001) \n'
        '"/share/CACHEDEV1_DATA/Con espacios" *(ro,async)\n'
        "/share/CACHEDEV2_DATA/Otra 192.0.2.0/24(rw) equipo.example(ro)\n")
    assert [e["carpeta"] for e in exportadas] == ["Con espacios", "Otra"]
    assert exportadas[0]["clientes"] == [
        {"cliente": "192.0.2.5", "escritura": True, "opciones": ["rw", "async"]},
        {"cliente": "*", "escritura": False, "opciones": ["ro", "async"]}]
    assert [c["cliente"] for c in exportadas[1]["clientes"]] == ["192.0.2.0/24", "equipo.example"]


def test_sin_exportaciones_nfs_la_lista_esta_vacia():
    assert p.carpetas_nfs("") == [] and p.carpetas_nfs(dato("carpetas_nfs_hero")) == []


@pytest.mark.parametrize("texto", [
    "cat: /etc/exports: Permission denied\n", '"/share/X sin cerrar 192.0.2.5(rw)\n', "/share/X\n"])
def test_las_exportaciones_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.carpetas_nfs(texto)


# --- enlaces de /share --------------------------------------------------------------------------

def test_los_enlaces_dicen_en_que_volumen_vive_cada_carpeta():
    enlaces = p.carpetas_enlaces(dato("carpetas_enlaces_hero"))
    assert len(enlaces) == 10
    assert por(enlaces, "carpeta", "carpeta5") == {
        "carpeta": "carpeta5", "destino": "ZFS20_DATA/carpeta5", "volumen": "ZFS20_DATA"}


def test_los_enlaces_admiten_nombres_con_espacios_y_discos_externos():
    enlaces = p.carpetas_enlaces(dato("carpetas_enlaces_qts"))
    assert len(enlaces) == 33
    assert por(enlaces, "carpeta", "carpeta39 (usuario38@192.0.2.1)") == {
        "carpeta": "carpeta39 (usuario38@192.0.2.1)",
        "destino": "external/.nd/0/00000000-0000-0000-0000-000000000001", "volumen": "external"}
    assert por(enlaces, "carpeta", "volumen6")["destino"] == "external/DEV3301_1"


def test_un_share_sin_enlaces_devuelve_una_lista_vacia():
    assert p.carpetas_enlaces("total 0\ndrwxrwxrwx  2 admin administrators  40 Sep 19  2005 HDA_DATA\n") == []


@pytest.mark.parametrize("texto", ["", "ls: /share/: No such file or directory\n", "lrwxrwxrwx 1 admin\n"])
def test_los_enlaces_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.carpetas_enlaces(texto)


def test_la_carpeta_personal_de_cada_usuario_no_esta_en_un_volumen():
    # path = %H: Samba pone ahi la carpeta de quien entra; no es una ruta del NAS
    for sistema in ("hero", "qts"):
        (personal,) = [c for c in p.carpetas_smb(dato("carpetas_smb_" + sistema)) if c["ruta"] == "%H"]
        assert personal["volumen"] is None


# ==== capturas fieles de un QTS de pruebas con las ordenes del producto ======================

def test_la_ocupacion_real_de_qts_da_solo_los_volumenes():
    # 30 lineas: los 3 volumenes y, por cada carpeta de /share que no es un montaje, su tmpfs
    ocupacion = p.ocupacion(dato("ocupacion_qtsreal"))
    assert [(o["dispositivo"], o["ocupacion_pct"]) for o in ocupacion] == [
        ("/dev/mapper/cachedev1", 27), ("/dev/mapper/cachedev3", 84), ("/dev/mapper/cachedev4", 80)]
    assert ocupacion[0] == {
        "dispositivo": "/dev/mapper/cachedev1", "bytes": 3624663744 * 1024, "usado": 960571204 * 1024,
        "libre": 2663551868 * 1024, "ocupacion_pct": 27, "montaje": "/share/CACHEDEV1_DATA"}


def test_dos_rutas_del_mismo_volumen_cuentan_una_vez():
    # escrito a mano: un enlace de /share que apunta a un volumen (HDA_DATA en un QTS antiguo)
    cabecera = "Filesystem           1024-blocks    Used Available Capacity Mounted on\n"
    linea = "/dev/mapper/cachedev1 100 40 60  40% /share/CACHEDEV1_DATA\n"
    assert len(p.ocupacion(cabecera + linea + linea)) == 1


def test_las_instantaneas_reales_de_qts():
    snaps = p.lvm_snapshots(dato("lvm_snapshots_qtsreal"))
    assert snaps["total"] == 27 and len(snaps["instantaneas"]) == 27
    assert sorted({s["volumen"] for s in snaps["instantaneas"]}) == [1, 3]
    assert snaps["instantaneas"][-1] == {
        "id": 30020, "volumen": 3, "nombre": "GMT+01_2026-10-13_2054", "bytes": 4294967296 * 512,
        "creada_epoch": 1791917678, "creada": "2026-10-13T18:54:38Z", "caduca_min": None, "vital": False,
        "replicada": True}


def test_los_contadores_reales_de_qts_incluyen_discos_externos_y_el_de_arranque():
    r = p.diskstats(dato("diskstats_qtsreal"))
    assert r["segundos"] == 5.0
    assert [d["dispositivo"] for d in r["discos"]] == ["sd" + letra for letra in "abcdefghijklm"]
    assert por(r["discos"], "dispositivo", "sdc") == {
        "dispositivo": "sdc", "lecturas_s": 171.2, "escrituras_s": 69.4, "leido_mb_s": 2.96,
        "escrito_mb_s": 0.13, "espera_ms": 2.61, "ocupacion_pct": 42.4}
    assert por(r["discos"], "dispositivo", "sdm")["espera_ms"] is None      # sin actividad en el intervalo


def test_la_salud_real_de_qts_da_las_ocho_bahias():
    salud = p.discos_salud(dato("discos_salud_qtsreal"))
    assert [s["bahia"] for s in salud] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert all(s["smart"] == "GOOD" and 20 <= s["temperatura"] <= 40 and s["estado"] == 0 for s in salud)
    assert por(salud, "bahia", 8)["modelo"] == "WD80EFZZ-68BTXN0"


def test_el_estado_real_de_md_y_del_device_mapper_de_qts():
    grupos = p.md_sys(dato("md_sys_qtsreal"))
    assert [g["grupo"] for g in grupos] == ["md1", "md13", "md2", "md256", "md280", "md322", "md9"]
    assert por(grupos, "grupo", "md1") == {
        "grupo": "md1", "nivel": "raid6", "estado": "active", "accion": "idle", "degradado": 0, "discrepancias": 0}
    dm = p.dm_estado(dato("dm_estado_qtsreal"))
    assert sorted(d["tipo"] for d in dm) == ["cache", "cache_client", "thin-pool"]
    assert por(dm, "tipo", "thin-pool")["datos_pct"] == 51.5 and por(dm, "tipo", "cache")["usado_pct"] == 100.0


# ==== de la revision final ======================================================================

# escrito a mano con el formato de ZFS: el disco que falta sale con su identificador y, en la
# nota, la ruta que tenia
AUSENTE = DEGRADADO.replace(
    "\t      qzfs/enc_0/disk_0x2_SERIE0002_3   FAULTED     12  1.5K     3  too many errors\n",
    "\t      1234567890123456789               UNAVAIL      0     0     0  "
    "was /dev/qzfs/enc_0/disk_0x2_SERIE0002_3\n")


def test_un_disco_que_falta_en_un_pool_conserva_su_bahia():
    assert AUSENTE != DEGRADADO
    (pool,) = p.pools_estado(AUSENTE)
    ausente = por(pool["dispositivos"], "estado", "UNAVAIL")
    assert (ausente["nombre"], ausente["cabina"], ausente["bahia"]) == ("1234567890123456789", 0, 2)


def test_una_seccion_de_iscsi_con_datos_que_no_se_conoce_no_pasa_por_no_hay():
    # los nombres de seccion de destinos y LUN son supuestos: si el NAS usa otros, se dice
    iscsi = p.lvm_iscsi("[iSCSIPortal]\nbServiceEnable = TRUE\nservicePort = 3260\n"
                        "[Target_0]\ntargetName = copias\n[LUN_0]\nLUNName = lun_copias\n[TargetKey]\n")
    assert iscsi["destinos"] == [] and iscsi["lun"] == []
    assert iscsi["sin_reconocer"] == ["Target_0", "LUN_0"]
    assert "sin_reconocer" not in p.lvm_iscsi(dato("lvm_iscsi_qts"))
