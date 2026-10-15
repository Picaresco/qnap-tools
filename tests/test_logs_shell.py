# -*- coding: utf-8 -*-
"""Las ordenes de procesos con tuberias, ejecutadas en un shell de verdad: ps y ls se sustituyen
por funciones de pega, /proc por una carpeta con ficheros escritos a mano (nombres inventados), y
el resto (grep, tr, head, cat, cut) es el de verdad.

Necesita un sh en el PATH (en Windows, el de Git); si no lo hay, se saltan."""
import os
import shutil
import subprocess

import pytest

from qnap_tools.logs import comandos as lc
from qnap_tools.logs import parsers as p

SH = shutil.which("sh")
pytestmark = pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar las ordenes")
PID = 4242
STATUS = ("Name:\trsync\nUmask:\t0022\nState:\tD (disk sleep)\nTgid:\t4242\nPid:\t4242\nPPid:\t1\n"
          "Uid:\t1000\t1000\t1000\t1000\nGid:\t100\t100\t100\t100\nVmPeak:\t   10000 kB\nVmRSS:\t    9004 kB\n"
          "Threads:\t1\n")
IO = ("rchar: 90000000\nwchar: 80000000\nsyscr: 1200\nsyscw: 900\nread_bytes: 70000000\n"
      "write_bytes: 60000000\ncancelled_write_bytes: 0\n")
FD = ("total 0\nlrwx------ 1 admin administrators 64 Oct 15 10:00 0 -> /dev/null\n"
      "lr-x------ 1 admin administrators 64 Oct 15 10:00 3 -> /share/carpeta1/origen/fichero 1.bin\n"
      "lr-x------ 1 admin administrators 64 Oct 15 10:00 5 -> pipe:[1001]\n")
PS = ("  PID  PPID  Uid     Stat VSZ  VmSize TIME   ELAPSED Command\n"
      "    1     0 admin    S   4896   2176   0:04 250:44  init\n"
      "    2     0 admin    SW     0          0:00 250:44  [kthreadd]\n"
      "  364     1 admin    S N 907m  12760   0:00 268:44  /usr/local/bin/servicio1 -n -d\n")


def posix(ruta):
    return str(ruta).replace("\\", "/")


def sh(texto, pega):
    r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                       env={"PEGA": posix(pega), "PATH": os.environ["PATH"]}, timeout=60)
    return r.returncode, r.stdout


def proceso(tmp_path, cmdline=b"rsync\0-a\0/share/carpeta1/origen\0--token\0abc123def\0", io=IO, existe=True):
    """Una carpeta /proc de pega con un proceso."""
    pega = tmp_path / "pega"
    carpeta = pega / "proc" / str(PID)
    (pega / "proc").mkdir(parents=True)
    if existe:
        carpeta.mkdir()
        (carpeta / "status").write_text(STATUS, encoding="utf-8", newline="\n")
        (carpeta / "cmdline").write_bytes(cmdline)
        if io is not None:
            (carpeta / "io").write_text(io, encoding="utf-8", newline="\n")
    (pega / "fd.txt").write_text(FD, encoding="utf-8", newline="\n")
    return pega


def detalle(pega, pid=PID):
    texto = lc.PROCESOS_DETALLE.render({"pid": pid}).replace("/proc/", posix(pega) + "/proc/")
    # readlink y ls de pega: la carpeta de trabajo y los descriptores
    previo = 'readlink() { echo /share/carpeta1; }; ls() { cat "$PEGA/fd.txt"; }; '
    return sh(previo + texto, pega)


def test_el_detalle_de_un_proceso_se_lee_de_punta_a_punta(tmp_path):
    rc, salida = detalle(proceso(tmp_path))
    assert rc == 0 and salida.rstrip().endswith("==fin")
    # grep deja solo los campos pedidos
    assert "Umask" not in salida and "VmPeak" not in salida and "Gid" not in salida
    d = p.procesos_detalle(salida)
    assert (d["nombre"], d["estado"], d["ppid"], d["uid"], d["memoria"]) == ("rsync", "D (disk sleep)", 1, 1000, 9004 * 1024)
    # los \0 de cmdline pasan a espacios y la credencial se tapa
    assert d["orden"] == "rsync -a /share/carpeta1/origen --token ***"
    assert d["directorio"] == "/share/carpeta1"
    assert d["io"]["leidos_de_disco"] == 70000000
    assert d["ficheros_abiertos"]["rutas"]["filas"] == ["/dev/null", "/share/carpeta1/origen/fichero 1.bin"]
    assert d["ficheros_abiertos"]["tuberias"] == 1 and "errores" not in d


def test_un_pid_que_no_existe_lo_dice_la_orden(tmp_path):
    rc, salida = detalle(proceso(tmp_path, existe=False))
    assert rc == 0 and salida.strip() == "==noexiste"
    assert p.procesos_detalle(salida) is None


def test_la_orden_larga_de_un_proceso_se_corta_a_2000_bytes_en_el_nas(tmp_path):
    larga = b"programa\0" + b"a" * 5000 + b"\0--password\0clave-inventada-2\0"
    rc, salida = detalle(proceso(tmp_path, cmdline=larga))
    cmdline = salida.split("==cmdline\n")[1].split("==cwd")[0].strip()
    assert rc == 0 and len(cmdline) == 2000
    # la clave queda mas alla del corte, y el parser recorta a 300
    assert "clave-inventada" not in salida and len(p.procesos_detalle(salida)["orden"]) == 300


def test_sin_io_se_lee_el_resto_y_se_dice(tmp_path):
    rc, salida = detalle(proceso(tmp_path, io=None))
    assert rc == 0
    d = p.procesos_detalle(salida)
    assert d["io"] is None and "io" in d["errores"] and d["ficheros_abiertos"]["total"] == 3


def test_un_proceso_sin_orden_no_deja_pegadas_las_partes(tmp_path):
    # un hilo del kernel tiene el cmdline vacio: sin el echo final, "==cwd" quedaria en la misma linea
    rc, salida = detalle(proceso(tmp_path, cmdline=b""))
    assert rc == 0 and "\n==cwd\n" in salida
    assert p.procesos_detalle(salida)["orden"] is None


def test_la_lista_de_procesos_se_corta_a_400_caracteres_por_linea(tmp_path):
    pega = tmp_path / "pega"
    pega.mkdir()
    larga = "%5d %5d %-8.8s %-4s%4s %6s %6s %6s  %s\n" % (77, 1, "admin", "S", "100", "100", "0:00", "1:00",
                                                         "programa " + "a" * 600)
    (pega / "ps.txt").write_text(PS + larga, encoding="utf-8", newline="\n")
    texto = lc.PROCESOS_LISTA.render().replace(lc.PS_COLUMNAS, 'cat "$PEGA/ps.txt"', 1)
    assert texto != lc.PROCESOS_LISTA.render()
    rc, salida = sh(texto, pega)
    assert rc == 0 and max(len(linea) for linea in salida.splitlines()) == 400
    ps = p.procesos_lista(salida)
    assert [x["pid"] for x in ps] == [1, 364, 77] and len(ps[2]["orden"]) == 300
    assert ps[1]["estado"] == "SN" and ps[1]["memoria_virtual"] == 907 * 1024 * 1024
