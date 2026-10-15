# -*- coding: utf-8 -*-
"""Las ordenes de rutas y de discos externos ejecutadas en un sh de verdad, sobre una carpeta de
pruebas que hace de /share. Necesita un sh en el PATH (en Windows, el de Git); si no, se saltan.

El NAS usa BusyBox para find y wc y GNU para du y ls; aqui salen los del sh de pruebas, asi que
se comprueba la estructura de la salida y los casos de rechazo, no las cifras exactas de du."""
import os
import re
import shutil
import subprocess

import pytest

from qnap_tools.discos import comandos as dc
from qnap_tools.discos import parsers as p

SH = shutil.which("sh")
pytestmark = pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar las ordenes")


def posix(ruta):
    """C:\\Users\\x -> /c/Users/x (la forma en que el sh de Git ve una ruta de Windows)."""
    texto = str(ruta).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", texto)
    return "/%s/%s" % (m.group(1).lower(), m.group(2)) if m else texto


def lanzar(comando, tmp_path, ruta=None, cwd=None):
    """La orden con /share/ cambiado por la carpeta de pruebas; da (rc, salida)."""
    raiz = posix(tmp_path) + "/share/"
    texto = comando.render({"ruta": ruta} if ruta is not None else None).replace("/share/", raiz)
    r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                       cwd=cwd or tmp_path, env={"PATH": os.environ["PATH"]}, timeout=60)
    return r.returncode, r.stdout


@pytest.fixture
def arbol(tmp_path):
    base = tmp_path / "share" / "VOL1_DATA" / "Vms" / "mi carpeta"
    (base / "sub dir").mkdir(parents=True)
    (base / "uno.img").write_bytes(b"x" * 10)
    (base / "sub dir" / "dos con espacios.img").write_bytes(b"y" * 20)
    (tmp_path / "share" / "VOL1_DATA" / "suelto.txt").write_bytes(b"z" * 5)
    return tmp_path


# --- ruta_ocupacion ---------------------------------------------------------------------------

def test_ruta_ocupacion_de_una_carpeta_con_espacios_da_las_cinco_partes(arbol):
    rc, salida = lanzar(dc.RUTA_OCUPACION, arbol, "/share/VOL1_DATA/Vms/mi carpeta")
    assert rc == 0
    lineas = salida.splitlines()
    assert lineas[0] == "==real " + posix(arbol) + "/share/VOL1_DATA/Vms/mi carpeta"
    assert re.fullmatch(r"[0-9]+\t.*", lineas[1]) and lineas[2] == "==kib" and re.fullmatch(r"[0-9]+\t.*", lineas[3])
    assert [x.strip() for x in lineas[4:]] == ["==ficheros 2", "==carpetas 2"]       # la propia carpeta y sub dir


def test_ruta_ocupacion_de_un_fichero_funciona(arbol):
    rc, salida = lanzar(dc.RUTA_OCUPACION, arbol, "/share/VOL1_DATA/suelto.txt")
    assert rc == 0
    lineas = salida.splitlines()
    assert lineas[1].split("\t")[0] == "5" and [x.strip() for x in lineas[4:]] == ["==ficheros 1", "==carpetas 0"]


@pytest.mark.parametrize("ruta", ["/etc", "/share", "/share/VOL1_DATA/no_existe", "/tmp", "/"])
def test_ruta_ocupacion_rechaza_lo_que_no_existe_o_no_cuelga_de_share(arbol, ruta):
    rc, salida = lanzar(dc.RUTA_OCUPACION, arbol, ruta)
    assert salida.strip() == "==rechazada"


def test_ruta_ocupacion_no_ejecuta_lo_que_lleve_la_ruta(arbol, tmp_path):
    for ruta in ("/share/a'; touch hecho; '", "/share/$(touch hecho)", "/share/`touch hecho`"):
        _, salida = lanzar(dc.RUTA_OCUPACION, arbol, ruta)
        assert salida.strip() == "==rechazada"
    assert not (tmp_path / "hecho").exists()


@pytest.mark.skipif(os.name == "nt", reason="los enlaces simbolicos de Windows piden privilegios")
def test_ruta_ocupacion_sigue_un_enlace_de_share_y_rechaza_uno_que_sale(arbol):
    (arbol / "share" / "Vms").symlink_to("VOL1_DATA/Vms")
    (arbol / "share" / "fuera").symlink_to("/etc")
    _, salida = lanzar(dc.RUTA_OCUPACION, arbol, "/share/Vms/mi carpeta")
    assert salida.splitlines()[0].endswith("/share/VOL1_DATA/Vms/mi carpeta")
    _, salida = lanzar(dc.RUTA_OCUPACION, arbol, "/share/fuera")
    assert salida.strip() == "==rechazada"


# --- ruta_listado -----------------------------------------------------------------------------

def test_ruta_listado_da_cada_directorio_con_sus_ficheros_en_formato_ls(arbol):
    rc, salida = lanzar(dc.RUTA_LISTADO, arbol, "/share/VOL1_DATA/Vms/mi carpeta")
    assert rc == 0
    lineas = salida.splitlines()
    real = posix(arbol) + "/share/VOL1_DATA/Vms/mi carpeta"
    assert lineas[0] == "==real " + real
    assert (real + "/.:") in lineas and (real + "/./sub dir:") in lineas
    assert any(re.match(r"^-[rwx-]{9}\S* +[0-9]+ +[0-9]+ +[0-9]+ +10 +[0-9]{9,} uno\.img$", x) for x in lineas)
    assert any(x.endswith(" 20 " + x.split(" 20 ")[1]) and x.endswith(" dos con espacios.img") for x in lineas
               if " 20 " in x)


@pytest.mark.parametrize("ruta", ["/etc", "/share/VOL1_DATA/suelto.txt", "/share/VOL1_DATA/no_existe"])
def test_ruta_listado_rechaza_lo_que_no_es_una_carpeta_de_share(arbol, ruta):
    _, salida = lanzar(dc.RUTA_LISTADO, arbol, ruta)
    assert salida.strip() == "==rechazada"


# --- externos_montajes ------------------------------------------------------------------------

def con_proc_y_df(tmp_path, mounts, df):
    """La orden con /proc/mounts sustituido por un fichero y df por un df de pega."""
    (tmp_path / "mounts").write_text(mounts, encoding="utf-8", newline="\n")
    (tmp_path / "df.sh").write_text('echo "$@" >> "$PEGA/df_llamado"\ncat "$PEGA/df"\n', encoding="utf-8", newline="\n")
    (tmp_path / "df").write_text(df, encoding="utf-8", newline="\n")
    texto = dc.EXTERNOS_MONTAJES.render().replace("/proc/mounts", posix(tmp_path) + "/mounts")
    assert texto.count("df -P -k") == 1
    texto = texto.replace("df -P -k", "sh %s/df.sh -P -k" % posix(tmp_path))
    r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                       env={"PATH": os.environ["PATH"], "PEGA": posix(tmp_path)}, timeout=60)
    return r.returncode, r.stdout, (tmp_path / "df_llamado").read_text() if (tmp_path / "df_llamado").exists() else ""


MOUNTS = (
    "rootfs / rootfs rw 0 0\n"
    "/dev/sda1 /share/external/DEV0001_1 ufsd rw,nosuid,nodev,relatime 0 0\n"
    "/dev/sdb2 /share/external/DEV0002_1 vfat rw,relatime 0 0\n"
    "tmpfs /share tmpfs rw 0 0\n")
DF = ("Filesystem 1024-blocks Used Available Capacity Mounted on\n"
      "/dev/sda1 100 40 60 40% /share/external/DEV0001_1\n"
      "/dev/sdb2 200 20 180 10% /share/external/DEV0002_1\n")


def test_externos_montajes_da_los_montajes_externos_y_su_df(tmp_path):
    rc, salida, llamada = con_proc_y_df(tmp_path, MOUNTS, DF)
    lineas = salida.splitlines()
    assert lineas[0] == "==montajes 4"
    assert lineas[1:3] == [x for x in MOUNTS.splitlines() if "/share/external/" in x]
    assert lineas[3] == "==df" and lineas[4:] == DF.splitlines()
    assert llamada.split() == ["-P", "-k", "/share/external/DEV0001_1", "/share/external/DEV0002_1"]


def test_externos_montajes_sin_externos_no_lanza_df(tmp_path):
    rc, salida, llamada = con_proc_y_df(tmp_path, "rootfs / rootfs rw 0 0\n", DF)
    assert rc == 0 and salida.splitlines() == ["==montajes 1", "==df"] and llamada == ""


def test_externos_montajes_sin_poder_leer_los_montajes_no_dice_que_no_hay_ninguno(tmp_path):
    (tmp_path / "df.sh").write_text("echo no\n", encoding="utf-8", newline="\n")
    texto = dc.EXTERNOS_MONTAJES.render().replace("/proc/mounts", posix(tmp_path) + "/no_existe")
    r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                       env={"PATH": os.environ["PATH"]}, timeout=60)
    assert r.stdout.splitlines()[0].strip() == "==montajes"          # sin numero: el parser lo rechaza
# --- tareas_file_station ----------------------------------------------------------------------

def con_wfm(tmp_path, ficheros, vivos=()):
    """La orden con /tmp/wfm y /proc/ cambiados por carpetas de pruebas; da (rc, salida)."""
    wfm = tmp_path / "wfm"
    wfm.mkdir(exist_ok=True)
    for nombre, contenido in ficheros.items():
        (wfm / nombre).write_text(contenido, encoding="utf-8", newline="\n")
    for pid in vivos:
        (tmp_path / "proc" / str(pid)).mkdir(parents=True, exist_ok=True)
    texto = dc.TAREAS_FILE_STATION.render().replace("/tmp/wfm", posix(wfm)).replace("/proc/", posix(tmp_path) + "/proc/")
    r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                       env={"PATH": os.environ["PATH"]}, timeout=60)
    return r.returncode, r.stdout


# Los ficheros de /tmp/wfm de una copia en curso en el NAS de laboratorio (QuTS hero h6.0.2), con los
# nombres, la IP y la referencia cambiados por inventados: "clave = valor", y file_name= sin espacios
COPIA = ("pid = 11895\ncopy_file = VM01_01.img\npercent = 39.3\ncopying = 1\nend_time = 1792097149\n"
         "speed = 115343360\nfull_dest = /share/ZFS3_DATA/Maquinas/VM01/VM01_01-Copy(1).img\ncopy_number = 2\n"
         "files_count = 3\ncopy_size = 53539569664\ncopied_size = 62657991692\naverage_speed = 58885919\n")
TOTAL = "total_size = 83398104076\ntotal_number = 3\n"
VISTA = "from = /USB-DISCO\nto = /Maquinas\nname = VM01\n"
TRABAJO = "file_name=/USB-DISCO/VM01/VM01_01.img\n"
REMOTO = ("[11895]\nsource_file_1 = VM01\nsource_total = 1\nsource_path = /USB-DISCO\ndest_path = /Maquinas\nmode = 2\n"
          "reference = 0123456789abcdef0123456789abcdef\ndup = Copy\nusername = admin\nremote_addr = 192.0.2.10\n"
          "func = copy\n"
          "[11896]\nsource_path = /Otra\ndest_path = /Maquinas2\nmode = 0\ndup = Skip\nusername = luis\n"
          "remote_addr = 192.0.2.11\nfunc = move\n")
LISTA = ("11895|admin|q_from|q_to|0|0|q_name|11|0|0.0|1792096591|1792096591|-1|-1|--\n"
         "11896|luis|q_from|q_to|0|0|q_name|11|0|0.0|1792096600|1792096600|-1|-1|--\n")


def test_tareas_file_station_junta_los_campos_de_cada_fichero_de_la_tarea(tmp_path):
    rc, salida = con_wfm(tmp_path, {
        "wfm2_copy_status11895": COPIA, "wfm_total_file11895": TOTAL, "wfm_display_file_name11895": VISTA,
        "wfm_work_file_name11895": TRABAJO, "wfm2_remote_parameter": REMOTO, "wfm_copy_move.list": LISTA},
        vivos=[11895])
    assert rc == 0
    lineas = salida.splitlines()
    assert lineas[:2] == ["==wfm", "== 11895"]
    assert "copy_file = VM01_01.img" in lineas and "copied_size = 62657991692" in lineas
    assert "total_size = 83398104076" in lineas and "from = /USB-DISCO" in lineas and "name = VM01" in lineas
    assert "pid = 11895" not in lineas and not any(x.startswith("file_name") for x in lineas)
    # solo los campos de SU seccion de wfm2_remote_parameter, y nunca la IP ni la referencia
    assert "func = copy" in lineas and "dup = Copy" in lineas and "username = admin" in lineas
    assert "func = move" not in lineas and "dup = Skip" not in lineas
    assert not any("remote_addr" in x or "192.0.2" in x or "reference" in x or x.startswith("source_file")
                   for x in lineas)
    i = lineas.index("==lista")
    assert lineas[i + 1].startswith("11895|admin|") and lineas[i + 2] == "vivo=1" and len(lineas) == i + 3
    # y lo que parsea el parser sin quejarse: 62657991692 / 83398104076 = 75,1 %
    (t,) = p.tareas_file_station(salida)["tareas"]["filas"]
    assert (t["progreso_pct"], t["estado"], t["usuario"], t["origen"], t["destino"]) == (
        75.1, "en_curso", "admin", "/USB-DISCO", "/Maquinas")


def test_tareas_file_station_terminada_con_el_remote_parameter_vacio(tmp_path):
    terminada = COPIA.replace("copying = 1", "copying = 2").replace("percent = 39.3", "percent = 100.0").replace(
        "copied_size = 62657991692", "copied_size = 83398104076")
    rc, salida = con_wfm(tmp_path, {
        "wfm2_copy_status11895": terminada, "wfm_total_file11895": TOTAL, "wfm_display_file_name11895": VISTA,
        "wfm2_remote_parameter": "",
        "wfm_copy_move.list": "11895|admin|/USB-DISCO|/Maquinas|83398104076|3|q_name|11|2|100.0|1792096591|1792097331|-1|-1|--\n"})
    assert rc == 0
    (t,) = p.tareas_file_station(salida)["tareas"]["filas"]
    # sin remote_parameter el tipo sale del codigo de la lista (11 = copia)
    assert (t["estado"], t["progreso_pct"], t["tipo"], t["si_existe_destino"], t["proceso_vivo"]) == (
        "terminada", 100.0, "copy", None, False)
    assert t["usuario"] == "admin" and t["copia_renombrada"] is True


def test_tareas_file_station_sin_el_proceso_vivo_y_con_ficheros_que_faltan(tmp_path):
    rc, salida = con_wfm(tmp_path, {"wfm2_copy_status7": "copying = 2\ncopied_size = 5\n"})
    assert rc == 0
    assert salida.splitlines() == ["==wfm", "== 7", "copying = 2", "copied_size = 5", "==remote", "==lista", "vivo=0"]


def test_tareas_file_station_dos_tareas_cada_una_con_lo_suyo(tmp_path):
    rc, salida = con_wfm(tmp_path, {"wfm2_copy_status11895": COPIA, "wfm2_copy_status11896": "copying = 1\n",
                                    "wfm2_remote_parameter": REMOTO}, vivos=[11896])
    bloques = salida.split("== ")
    assert len(bloques) == 3
    uno_ = [b for b in bloques if b.startswith("11895")][0]
    dos = [b for b in bloques if b.startswith("11896")][0]
    assert "dup = Copy" in uno_ and "vivo=0" in uno_ and "dup = Skip" in dos and "vivo=1" in dos


def test_tareas_file_station_sin_la_carpeta_de_file_station_no_es_un_error(tmp_path):
    texto = dc.TAREAS_FILE_STATION.render().replace("/tmp/wfm", posix(tmp_path) + "/no_hay_wfm")
    r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                       env={"PATH": os.environ["PATH"]}, timeout=60)
    assert r.returncode == 0 and r.stdout.splitlines() == ["==sin_wfm"]
    assert p.tareas_file_station(r.stdout)["tareas"]["total"] == 0


def test_tareas_file_station_una_carpeta_vacia_da_una_lista_vacia(tmp_path):
    rc, salida = con_wfm(tmp_path, {})
    assert rc == 0 and salida.splitlines() == ["==wfm"]
