# -*- coding: utf-8 -*-
"""Coherencia de las ordenes de la pata de discos: todas son de solo lectura."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pruebas"))
import guardia  # noqa: E402  (la guardia de solo lectura del laboratorio)

from qnap_tools.comandos import Comando, ParametroInvalido  # noqa: E402
from qnap_tools.discos import comandos as dc  # noqa: E402

EJEMPLOS = {"bahia": "3", "md": "md1", "nvme": "nvme0", "entero": "5", "nombre": "x", "ruta": "/share/x"}
SECRETOS = re.compile(
    r"shadow|smbpasswd|ssh_host|\.pem|id_rsa|id_ed25519|authorized_keys|qvpn/|openvpn|"
    r"ipsec\.(conf|secrets)|wg[0-9]*\.conf|privatekey|nm\.conf|chap|InitiatorKey", re.I)
# lo que el diseno deja fuera aunque exista en el NAS
VETADO = re.compile(
    r"\bdu |\bfind |ls -[A-Za-z]*R|smartctl|\blvs\b|\bpvs\b|\bvgs\b|lvdisplay|dmsetup table|"
    r"get_hd_smartinfo|md_checker|hdparm|qcli_(?!storage\b)")
COMUNES = {"DISCOS_LISTA", "DISCOS_REPARTO", "DISCOS_DETALLE", "DISCOS_SALUD", "SMART_TODOS",
           "SMART_ATRIBUTOS", "SMART_UMBRALES", "SSD_VIDA", "DISKSTATS", "OCUPACION", "CARPETAS_SMB",
           "CARPETAS_USO", "CARPETAS_NFS", "CARPETAS_ENLACES", "RUTA_OCUPACION", "RUTA_LISTADO",
           "EXTERNOS_MONTAJES", "TAREAS_FILE_STATION", "RUTA_LISTAR"}
# du, find y ls -R solo para medir y comparar una ruta pedida, resuelta y dentro de /share/
RECORREN_RUTAS = {"RUTA_OCUPACION", "RUTA_LISTADO"}
SOLO_HERO = {"POOLS", "POOLS_ESTADO", "DATASETS", "SNAPSHOTS_HERO", "SNAPSHOTS_PROG_HERO", "LUNS_HERO",
             "SNAPSHOTS_RETENIDO_HERO"}
SOLO_QTS = {"MDSTAT", "MD_SYS", "RAID_CONF", "VOLUMENES_CONF", "LVM_CONF", "DM_ESTADO", "SNAPSHOTS_QTS",
            "SNAPSHOTS_PROG_QTS", "ISCSI_QTS"}
CON_SUDO = {"DISCOS_SALUD", "SMART_TODOS", "SMART_ATRIBUTOS", "DM_ESTADO", "RUTA_OCUPACION", "RUTA_LISTADO",
            "RUTA_LISTAR"}
# se leen con el formato visto, pero ningun NAS de pruebas tenia con que validarlas
NO_PROBADO = {"ISCSI_QTS", "SMART_UMBRALES"}
SH = shutil.which("sh")


def todos():
    return {nombre: valor for nombre, valor in vars(dc).items() if isinstance(valor, Comando)}


def en_carpeta(orden, tmp_path, raiz="/tmp/"):
    """Ejecuta la orden con /tmp/ cambiado por una carpeta de pruebas; da (rc, salida)."""
    local = orden.replace(raiz, "")
    assert raiz.rstrip("/") not in local
    r = subprocess.run([SH, "-c", local], cwd=tmp_path, capture_output=True, encoding="utf-8")
    return r.returncode, r.stdout


def test_estan_todas_las_ordenes_previstas_y_ninguna_mas():
    assert set(todos()) == COMUNES | SOLO_HERO | SOLO_QTS


def test_cada_orden_vale_para_el_sistema_previsto():
    assert {n for n, c in todos().items() if c.sistema == "hero"} == SOLO_HERO
    assert {n for n, c in todos().items() if c.sistema == "qts"} == SOLO_QTS
    assert {n for n, c in todos().items() if c.sistema == "ambos"} == COMUNES


def test_la_captura_da_valores_validos_a_todas_las_ordenes_con_parametros():
    # pruebas/efectos.py --producto discos aborta si falta el valor de los parametros de una orden
    import captura
    detalle = (Path(__file__).parent / "datos" / "discos" / "discos_detalle_hero.txt").read_text(encoding="utf-8")
    valores = captura.valores_reales("discos", {"DISCOS_DETALLE": detalle}.__getitem__, "hero")
    con_parametros = {n: c for n, c in todos().items() if c.params}
    assert set(con_parametros) == {"SMART_ATRIBUTOS", "RUTA_OCUPACION", "RUTA_LISTADO", "RUTA_LISTAR"}
    for nombre, comando in con_parametros.items():
        assert valores.get(nombre), nombre
        guardia.comprobar(comando.render(valores[nombre]))
    assert valores["RUTA_OCUPACION"] == {"ruta": "/share/Public"} == valores["RUTA_LISTAR"] == valores["RUTA_LISTADO"]


def test_los_identificadores_son_unicos():
    ids = [c.id for c in todos().values()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_cada_orden_pasa_la_guardia_de_solo_lectura_del_laboratorio(nombre):
    comando = todos()[nombre]
    texto = comando.render({p: EJEMPLOS[tipo] for p, tipo in comando.params.items()})
    guardia.comprobar(texto)          # lanza guardia.Bloqueado si algo no esta permitido


def test_la_guardia_del_laboratorio_sigue_bloqueando_escrituras():
    # si esto dejara de fallar, la prueba anterior no demostraria nada
    for texto in ("rm -rf /tmp/x", "mdadm --stop /dev/md1", "zpool scrub zpool1", "zfs destroy zpool1/zfs2",
                  "nvme format /dev/nvme0", "mdadm /dev/md1 --fail /dev/sda3", "echo x; reboot"):
        with pytest.raises(guardia.Bloqueado):
            guardia.comprobar(texto)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ninguna_orden_toca_rutas_con_secretos(nombre):
    assert not SECRETOS.search(todos()[nombre].plantilla)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ninguna_orden_usa_lo_que_el_diseno_deja_fuera(nombre):
    if nombre in RECORREN_RUTAS:
        return
    assert not VETADO.search(todos()[nombre].plantilla)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ulinux_conf_solo_se_lee_campo_a_campo_con_getcfg(nombre):
    plantilla = todos()[nombre].plantilla
    resto = re.sub(r"getcfg (?:'[^']*'|\"[^\"]*\"|\S+) (?:'[^']*'|\"[^\"]*\"|\S+) -f /etc/config/uLinux\.conf",
                   "", plantilla)
    assert "uLinux.conf" not in resto


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ningun_fichero_de_configuracion_se_lee_entero(nombre):
    # de /etc/config y de los .conf de /etc solo salen campos elegidos con grep o getcfg
    plantilla = todos()[nombre].plantilla
    assert not re.search(r"\bcat [^;|&]*(/etc/config/|/etc/[A-Za-z0-9_*.-]+\.conf)", plantilla)


def test_solo_estas_ordenes_van_con_sudo():
    assert {n for n, c in todos().items() if c.sudo} == CON_SUDO


def test_qcli_storage_nunca_va_con_sudo_y_getsysinfo_siempre():
    for nombre, c in todos().items():
        if "qcli_storage" in c.plantilla:
            assert not c.sudo, nombre       # con sudo no termina en un NAS grande
        if "getsysinfo hd" in c.plantilla.replace("getsysinfo hdnum", ""):
            assert c.sudo, nombre           # sin sudo devuelve 0 C y -- sin dar error


def test_las_funciones_sin_validar_con_datos_reales_estan_marcadas():
    assert {n for n, c in todos().items() if c.no_probado} == NO_PROBADO


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ningun_filtro_es_por_exclusion(nombre):
    # "todo menos lo secreto" deja pasar el secreto que no se conocia: solo listas blancas
    assert not re.search(r"grep [^|;&]*-[A-Za-z]*v", todos()[nombre].plantilla)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_zpool_y_zfs_solo_se_usan_para_consultar(nombre):
    for programa, orden in re.findall(r"\b(zpool|zfs) ([a-z-]+)", todos()[nombre].plantilla):
        assert orden in ("list", "status", "get"), (programa, orden)


# --- discos y salud ---------------------------------------------------------------------------

def test_el_detalle_de_los_discos_pide_campos_concretos_de_cada_cabina():
    plantilla = dc.DISCOS_DETALLE.plantilla
    assert plantilla.startswith("for f in /etc/enclosure_*.conf; do echo \"== $f\"; grep -E ")
    for campo in ("port_id", "pd_sys_name", "type", "vendor", "model", "serial_no", "revision",
                  "capacity", "sector_size", "rotation_speed", "status"):
        assert re.search(r"[(|]%s[|)]" % campo, plantilla), campo
    # ni los identificadores WWN ni las pruebas de velocidad que guarda el NAS
    assert "wwn" not in plantilla and "speed =" not in plantilla and "tcg" not in plantilla


def test_la_salud_separa_cada_valor_en_su_linea():
    # getsysinfo no termina sus respuestas en salto de linea: sin esto salen pegadas
    plantilla = dc.DISCOS_SALUD.plantilla
    for campo, sub in (("modelo", "hdmodel"), ("temperatura", "hdtmp"), ("smart", "hdsmart"),
                       ("estado", "hdstatus")):
        assert "echo %s=$(getsysinfo %s $b)" % (campo, sub) in plantilla
    assert 'echo "== $b"' in plantilla


def test_la_salud_solo_pregunta_por_las_bahias_que_tiene_el_nas():
    plantilla = dc.DISCOS_SALUD.plantilla
    assert plantilla.startswith("n=$(getsysinfo hdnum); for b in 1 2 3 ")
    assert "[ $b -le $n ] && " in plantilla
    assert plantilla.endswith('; [ -n "$n" ]')      # sin numero de bahias, la orden falla
    assert dc.DISCOS_SALUD.timeout >= 30


# --- SMART ------------------------------------------------------------------------------------

def test_los_atributos_smart_se_piden_por_cabina_y_bahia():
    assert dc.SMART_ATRIBUTOS.render({"cabina": "0", "bahia": 3}) == "cat /tmp/smart/smart_0_3.info"
    assert dc.SMART_ATRIBUTOS.render({"cabina": 23, "bahia": "1"}) == "cat /tmp/smart/smart_23_1.info"


@pytest.mark.parametrize("valores", [
    {"cabina": "0", "bahia": "1; reboot"}, {"cabina": "0", "bahia": "../x"}, {"cabina": "0", "bahia": "*"},
    {"cabina": "0 1", "bahia": "1"}, {"cabina": "0", "bahia": ""}, {"cabina": "0", "bahia": "-1"},
    {"cabina": "0", "bahia": "1234"}, {"cabina": "0"}])
def test_los_atributos_smart_rechazan_una_bahia_que_no_es_un_numero(valores):
    with pytest.raises(ParametroInvalido):
        dc.SMART_ATRIBUTOS.render(valores)


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_smart_todos_marca_cada_fichero_y_no_lee_los_que_no_son_de_atributos(tmp_path):
    (tmp_path / "smart").mkdir()
    (tmp_path / "smart" / "smart_0_1.info").write_text("2,0\n5,A,100,100,0,0,0\n", encoding="utf-8")
    (tmp_path / "smart" / "smart_23_2.info").write_text("1,4\n", encoding="utf-8")
    (tmp_path / "smart" / "nvme_ctemp_23_2").write_text("no\n", encoding="utf-8")
    rc, salida = en_carpeta(dc.SMART_TODOS.plantilla, tmp_path)
    assert dc.SMART_TODOS.valida(rc, salida) is None
    assert salida == "== smart/smart_0_1.info\n2,0\n5,A,100,100,0,0,0\n== smart/smart_23_2.info\n1,4\n"


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
@pytest.mark.parametrize("hay_carpeta", [True, False])
def test_smart_todos_falla_si_no_hay_ficheros_o_no_se_puede_entrar_en_la_carpeta(tmp_path, hay_carpeta):
    if hay_carpeta:
        (tmp_path / "smart").mkdir()
    rc, salida = en_carpeta(dc.SMART_TODOS.plantilla, tmp_path)
    assert salida == ""
    assert dc.SMART_TODOS.valida(rc, salida) is not None


def test_los_umbrales_distinguen_que_no_haya_fichero_de_que_no_se_pueda_leer():
    assert dc.SMART_UMBRALES.plantilla.startswith("[ ! -e /tmp/smart_warning.conf ] || grep -E ")
    assert dc.SMART_UMBRALES.valida(0, "") is None
    assert dc.SMART_UMBRALES.valida(2, "") is not None


# --- vida de los SSD --------------------------------------------------------------------------

@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_la_vida_de_los_ssd_marca_cada_fichero(tmp_path):
    (tmp_path / "disk").mkdir()
    (tmp_path / "disk" / "disk_0_3.info").write_text("[INFO]\nSSD_LIFE_USED = 7\nOTRO = 1\n", encoding="utf-8")
    (tmp_path / "disk" / "disk_23_1.info").write_text("[INFO]\n", encoding="utf-8")
    rc, salida = en_carpeta(dc.SSD_VIDA.plantilla, tmp_path)
    assert dc.SSD_VIDA.valida(rc, salida) is None
    assert salida == "== disk/disk_0_3.info\nSSD_LIFE_USED = 7\n== disk/disk_23_1.info\n"


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
@pytest.mark.parametrize("hay_carpeta", [True, False])
def test_un_nas_sin_ssd_no_es_un_error(tmp_path, hay_carpeta):
    if hay_carpeta:
        (tmp_path / "disk").mkdir()
    rc, salida = en_carpeta(dc.SSD_VIDA.plantilla, tmp_path)
    assert (rc, salida) == (0, "")
    assert dc.SSD_VIDA.valida(rc, salida) is None


def test_la_vida_de_los_ssd_falla_si_la_carpeta_existe_y_no_se_puede_listar():
    assert dc.SSD_VIDA.plantilla.endswith("; [ ! -d /tmp/disk ] || ls /tmp/disk/ >/dev/null")
    assert dc.SSD_VIDA.valida(2, "") is not None


# --- rendimiento ------------------------------------------------------------------------------

def test_el_rendimiento_son_dos_lecturas_con_su_reloj_separadas_cinco_segundos():
    lectura = "cat /proc/uptime; grep -E ' (sd[a-z]+|nvme[0-9]+n[0-9]+) ' /proc/diskstats"
    assert dc.DISKSTATS.plantilla == "%s; sleep 5; echo ==5s; %s" % (lectura, lectura)
    assert dc.DISKSTATS.timeout >= 20 and not dc.DISKSTATS.sudo


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_el_rendimiento_solo_trae_discos_enteros(tmp_path):
    # en QuTS hero /proc/diskstats pasa de 800 lineas (un zd por volumen): se filtra en el NAS
    (tmp_path / "uptime").write_text("100.00 50.00\n", encoding="utf-8")
    (tmp_path / "diskstats").write_text(
        "   8       0 sda 1 2 3\n   8       1 sda1 1 2 3\n 259       0 nvme0n1 4 5 6\n"
        " 259       1 nvme0n1p1 4 5 6\n   9       1 md1 7 8 9\n 230       0 zd0 7 8 9\n"
        "   8     416 sdaa 1 1 1\n   7       0 loop0 0 0 0\n", encoding="utf-8")
    orden = dc.DISKSTATS.plantilla.replace("/proc/", "").replace("sleep 5", "sleep 0")
    r = subprocess.run([SH, "-c", orden], cwd=tmp_path, capture_output=True, encoding="utf-8")
    lectura = "100.00 50.00\n   8       0 sda 1 2 3\n 259       0 nvme0n1 4 5 6\n   8     416 sdaa 1 1 1\n"
    assert r.stdout == lectura + "==5s\n" + lectura
    assert dc.DISKSTATS.valida(r.returncode, r.stdout) is None


# --- QuTS hero: pools, datasets, instantaneas y LUN ---------------------------------------------

def test_los_tamanos_de_zfs_se_piden_en_bytes_y_sin_cabecera():
    for comando in (dc.POOLS, dc.DATASETS, dc.SNAPSHOTS_HERO):
        assert re.match(r"(zpool|zfs) list -H -p ", comando.plantilla), comando.id


def test_los_pools_no_piden_la_fragmentacion_que_el_zfs_de_qnap_no_tiene():
    assert dc.POOLS.plantilla == "zpool list -H -p -o name,size,alloc,free,cap,dedup,health"


def test_el_estado_de_los_pools_incluye_los_ficheros_danados():
    assert dc.POOLS_ESTADO.plantilla == "zpool status -v"


def test_los_datasets_traen_cifrado_compresion_y_deduplicacion_en_la_misma_orden():
    assert dc.DATASETS.plantilla.endswith(
        " -t filesystem,volume -o name,type,used,avail,refer,quota,refquota,compressratio,mountpoint,"
        "compression,dedup,encryption,keystatus")


def test_las_instantaneas_salen_ordenadas_por_fecha_y_sin_tuberia_que_tape_un_fallo():
    assert dc.SNAPSHOTS_HERO.plantilla == "zfs list -H -p -t snapshot -o name,used,refer,creation -s creation"
    # un NAS sin instantaneas no devuelve nada, y no es un error; un zfs que falla, si
    assert dc.SNAPSHOTS_HERO.valida(0, "") is None
    assert dc.SNAPSHOTS_HERO.valida(1, "") is not None


def test_la_programacion_de_instantaneas_no_trae_el_texto_libre_y_admite_que_no_haya_fichero():
    plantilla = dc.SNAPSHOTS_PROG_HERO.plantilla
    fichero = "/etc/config/qsnapshot/zsnapshotSchedule.conf"
    assert plantilla.startswith("[ ! -s %s ] || grep -E " % fichero) and plantilla.endswith(" " + fichero)
    assert "description" not in plantilla
    assert dc.SNAPSHOTS_PROG_HERO.valida(0, "") is None
    assert dc.SNAPSHOTS_PROG_HERO.valida(2, "") is not None


JSON_LUN = """{
  "bitmap_group":{
    "lun_bitmap":{
      "bitmap00":"00000001"
    }
  },
  "lun":{
    "0":{
      "name":"lun_0",
      "chap_secret":"no-debe-salir",
      "otra_cosa":"tampoco"
    }
  }
}
"""
JSON_ISCSI = """{
  "portal":{
    "service_enable":true,
    "service_port":3260,
    "iqn_prefix":"iqn.2004-04.com.example",
    "version":1
  },
  "target":{},
  "initiator":{
    "0":{
      "initiator_id":0,
      "name":"iqn.2004-04.com.example:all",
      "alias":"Default Policy",
      "mutual_chap_password":"no-debe-salir"
    }
  }
}
"""


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_de_los_json_de_iscsi_solo_salen_las_claves_elegidas(tmp_path):
    (tmp_path / "hero_zfs_lun.json").write_text(JSON_LUN, encoding="utf-8")
    (tmp_path / "hero_iscsi_scst.json").write_text(JSON_ISCSI, encoding="utf-8")
    rc, salida = en_carpeta(dc.LUNS_HERO.plantilla, tmp_path, "/etc/config/")
    assert dc.LUNS_HERO.valida(rc, salida) is None
    assert salida == (
        '== hero_zfs_lun.json\n  "lun":{\n    "0":{\n      "name":"lun_0"\n'
        '== hero_iscsi_scst.json\n  "portal":{\n    "service_enable":true\n    "service_port":3260\n'
        '    "iqn_prefix":"iqn.2004-04.com.example"\n  "target":{}\n  "initiator":{\n    "0":{\n'
        '      "initiator_id":0\n      "name":"iqn.2004-04.com.example:all"\n      "alias":"Default Policy"\n')
    assert "no-debe-salir" not in salida and "bitmap" not in salida


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_un_json_de_iscsi_en_una_sola_linea_no_deja_escapar_sus_claves(tmp_path):
    # si otro firmware escribiera el JSON sin saltos de linea, un grep por lineas lo sacaria
    # entero, secretos incluidos: la orden solo saca la clave y su valor, y aqui falla
    compacto = JSON_ISCSI.replace("\n", "").replace(" ", "")
    (tmp_path / "hero_iscsi_scst.json").write_text(compacto + "\n", encoding="utf-8")
    rc, salida = en_carpeta(dc.LUNS_HERO.plantilla, tmp_path, "/etc/config/")
    assert "no-debe-salir" not in salida and salida == "== hero_iscsi_scst.json\n"
    assert dc.LUNS_HERO.valida(rc, salida) is not None
    # y con varias claves en una linea solo sale la primera, con su valor
    (tmp_path / "hero_iscsi_scst.json").write_text(
        '{\n  "initiator":{\n    "0":{\n      "name":"a", "mutual_chap_password":"no-debe-salir"\n', encoding="utf-8")
    rc, salida = en_carpeta(dc.LUNS_HERO.plantilla, tmp_path, "/etc/config/")
    assert salida == '== hero_iscsi_scst.json\n  "initiator":{\n    "0":{\n      "name":"a"\n'


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_un_nas_sin_ficheros_de_iscsi_no_es_un_error(tmp_path):
    rc, salida = en_carpeta(dc.LUNS_HERO.plantilla, tmp_path, "/etc/config/")
    assert (rc, salida) == (0, "")
    assert dc.LUNS_HERO.valida(rc, salida) is None
    (tmp_path / "hero_iscsi_scst.json").write_text(JSON_ISCSI, encoding="utf-8")
    rc, salida = en_carpeta(dc.LUNS_HERO.plantilla, tmp_path, "/etc/config/")
    assert rc == 0 and salida.startswith("== hero_iscsi_scst.json\n")


# --- QTS: grupos md, volumenes, pools ligeros, instantaneas e iSCSI -----------------------------

def test_mdstat_se_lee_tal_cual_y_sin_sudo():
    assert dc.MDSTAT.plantilla == "cat /proc/mdstat" and not dc.MDSTAT.sudo


def test_el_estado_de_cada_grupo_md_sale_con_cada_valor_en_su_linea():
    plantilla = dc.MD_SYS.plantilla
    assert plantilla.startswith('for d in /sys/block/md*/md; do echo "== $d"; ')
    for campo, fichero in (("nivel", "level"), ("estado", "array_state"), ("accion", "sync_action"),
                           ("degradado", "degraded"), ("discrepancias", "mismatch_cnt")):
        assert "echo %s=$(cat $d/%s 2>/dev/null)" % (campo, fichero) in plantilla


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_un_grupo_md_sin_alguno_de_sus_ficheros_deja_ese_valor_vacio(tmp_path):
    # un raid0 no tiene sync_action ni degraded: el valor queda vacio, no desplaza a los demas
    md = tmp_path / "md0" / "md"
    md.mkdir(parents=True)
    (md / "level").write_text("raid0\n", encoding="utf-8")
    (md / "array_state").write_text("clean\n", encoding="utf-8")
    rc, salida = en_carpeta(dc.MD_SYS.plantilla, tmp_path, "/sys/block/")
    assert salida == "== md0/md\nnivel=raid0\nestado=clean\naccion=\ndegradado=\ndiscrepancias=\n"
    assert dc.MD_SYS.valida(rc, salida) is None


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_de_raid_conf_salen_los_miembros_por_bahia_y_no_sus_identificadores(tmp_path):
    (tmp_path / "raid.conf").write_text(
        "[Global]\nglobalSpare0 = 8, 5000AAAAAAAAAAAA\n\n[Remove]\n\n[RAID_1]\n"
        "uuid = 11111111:22222222:33333333:44444444\nid = 1\npartNo = 3\ndeviceName = /dev/md1\n"
        "raidLevel = 6\ndata_0 = 1, 5000BBBBBBBBBBBB\ndata_1 = 1000a, SERIEREAL123\nscrubStatus = 1\n",
        encoding="utf-8")
    rc, salida = en_carpeta(dc.RAID_CONF.plantilla, tmp_path, "/etc/config/")
    assert dc.RAID_CONF.valida(rc, salida) is None
    assert salida == ("[Global]\nglobalSpare0 = 8\n[Remove]\n[RAID_1]\nid = 1\ndeviceName = /dev/md1\n"
                      "raidLevel = 6\ndata_0 = 1\ndata_1 = 1000a\n")


QTS_CONF = {"RAID_CONF": "/etc/config/raid.conf", "VOLUMENES_CONF": "/etc/volume.conf",
            "LVM_CONF": "/etc/config/qlvm.conf", "SNAPSHOTS_QTS": "/etc/config/qsnapshot/snapshot.conf",
            "SNAPSHOTS_PROG_QTS": "/etc/config/qsnapshot/snapshotSchedule.conf",
            "ISCSI_QTS": "/etc/config/iscsi_trgt.conf"}


@pytest.mark.parametrize("nombre", sorted(QTS_CONF))
def test_cada_fichero_de_qts_se_lee_por_campos_y_admite_no_existir(nombre):
    comando, fichero = todos()[nombre], QTS_CONF[nombre]
    assert comando.plantilla.startswith("[ ! -s %s ] || grep " % fichero), comando.plantilla
    assert comando.plantilla.endswith(" " + fichero)
    assert comando.valida(0, "") is None           # sin fichero no hay nada, y no es un error
    assert comando.valida(2, "") is not None       # un fichero que no se puede leer, si


def test_ningun_fichero_de_qts_trae_identificadores_ni_texto_libre():
    for nombre in QTS_CONF:
        plantilla = todos()[nombre].plantilla
        assert not re.search(r"[(|](uuid|memberUuid|description|export_path|owner|remote_host)[|)]", plantilla, re.I)


def test_los_campos_con_y_sin_espacio_antes_del_igual_se_leen_igual():
    # qlvm.conf mezcla "poolId=1" y "threshold = 95"
    for nombre in ("VOLUMENES_CONF", "LVM_CONF", "SNAPSHOTS_QTS", "SNAPSHOTS_PROG_QTS", "ISCSI_QTS"):
        assert re.search(r"\) \?=' ", todos()[nombre].plantilla), nombre


def test_el_estado_del_device_mapper_no_usa_table_y_va_con_sudo():
    # "dmsetup table" ensena las claves de los volumenes cifrados; "status", no
    assert dc.DM_ESTADO.plantilla == "dmsetup status" and dc.DM_ESTADO.sudo


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_del_iscsi_de_qts_no_salen_las_claves_chap(tmp_path):
    (tmp_path / "iscsi_trgt.conf").write_text(
        "[iSCSIPortal]\nbServiceEnable = TRUE\nservicePort = 3260\ntargetIQNPrefix = iqn.2004-04.com.example\n"
        "[target0Info]\ntargetName = copias\nbCHAPEnable = TRUE\nCHAPUserName = usuario\nCHAPPasswd = no-debe-salir\n"
        "[InitiatorKey]\niqn.2004-04.com.example:all = no-debe-salir\n", encoding="utf-8")
    rc, salida = en_carpeta(dc.ISCSI_QTS.plantilla, tmp_path, "/etc/config/")
    assert dc.ISCSI_QTS.valida(rc, salida) is None
    assert salida == ("[iSCSIPortal]\nbServiceEnable = TRUE\nservicePort = 3260\n"
                      "targetIQNPrefix = iqn.2004-04.com.example\n[target0Info]\ntargetName = copias\n"
                      "[InitiatorKey]\n")


# --- carpetas compartidas y ocupacion -----------------------------------------------------------

def test_la_ocupacion_se_pide_solo_de_los_volumenes_en_kilobytes_y_sin_lineas_partidas():
    # -P: una linea por montaje aunque el dispositivo tenga un nombre largo. Sin tuberia. Con
    # los montajes de volumen como argumentos df no consulta los demas: una carpeta remota
    # caida lo dejaria colgado (el df de QNAP es BusyBox y no tiene -l).
    assert dc.OCUPACION.plantilla == "df -P -k /share/*_DATA" and not dc.OCUPACION.sudo


def test_la_ocupacion_se_valida_por_su_salida_y_no_por_el_codigo_de_df():
    # df termina con 1 en un NAS sin ningun volumen ("can't find mount point"), pero da la
    # cabecera; sin cabecera no ha habido respuesta
    assert dc.OCUPACION.valida(1, "Filesystem 1024-blocks Used Available Capacity Mounted on\n") is None
    assert dc.OCUPACION.valida(1, "") is not None


def test_de_smb_conf_solo_salen_los_campos_de_cada_carpeta():
    plantilla = dc.CARPETAS_SMB.plantilla
    assert plantilla.startswith("grep -E '^\\[|^[[:space:]]*(") and plantilla.endswith(") *=' /etc/config/smb.conf")
    for campo in ("path", "comment", "valid users", "invalid users", "read list", "write list", "browsable",
                  "browseable", "guest ok", "recycle bin"):
        assert re.search(r"[(|]%s[|)]" % campo, plantilla), campo
    # ni contrasenas del dominio, ni scripts, ni la lista de equipos admitidos
    for fuera in ("passw", "secret", "script", "hosts allow", "idmap", "ldap"):
        assert fuera not in plantilla
    # sin smb.conf no hay "ninguna carpeta": es un fallo
    assert dc.CARPETAS_SMB.valida(2, "") is not None and dc.CARPETAS_SMB.valida(0, "") is not None


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden")
def test_de_smb_conf_no_salen_los_ajustes_globales_sensibles(tmp_path):
    (tmp_path / "smb.conf").write_text(
        "[global]\npasswd program = /bin/passwd %u\nldap admin dn = cn=admin\ninvalid users = guest\n"
        "[Datos]\n\tcomment = uno\n  path = /share/CACHEDEV1_DATA/Datos\nhosts allow = 192.0.2.0/24\n"
        "valid users = \"ana\",@\"todos\"\nrecycle bin = yes\n", encoding="utf-8")
    rc, salida = en_carpeta(dc.CARPETAS_SMB.plantilla, tmp_path, "/etc/config/")
    assert salida == ("[global]\ninvalid users = guest\n[Datos]\n\tcomment = uno\n"
                      "  path = /share/CACHEDEV1_DATA/Datos\nvalid users = \"ana\",@\"todos\"\nrecycle bin = yes\n")
    assert dc.CARPETAS_SMB.valida(rc, salida) is None


def test_el_uso_por_carpeta_y_las_exportaciones_admiten_no_existir():
    for comando, fichero in ((dc.CARPETAS_USO, "/etc/config/volumeStatus.conf"), (dc.CARPETAS_NFS, "/etc/exports")):
        assert comando.plantilla.startswith("[ ! -s %s ] || " % fichero) and comando.plantilla.endswith(" " + fichero)
        assert comando.valida(0, "") is None and comando.valida(2, "") is not None
    assert "Used Size" in dc.CARPETAS_USO.plantilla and "Latest Update Time" in dc.CARPETAS_USO.plantilla


def test_las_carpetas_se_listan_sin_recorrer_su_contenido():
    assert dc.CARPETAS_ENLACES.plantilla == "ls -l /share/"
