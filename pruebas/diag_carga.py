# -*- coding: utf-8 -*-
"""Diagnostico de carga de un NAS: que discos y que procesos concentran la E/S.

Uso: python diag_carga.py <nas> [segundos]
Solo lectura: todos los comandos pasan por la guardia. Muestrea /proc dos veces.
"""
import re
import sys

import guardia
import ro

SEP = "=====CORTE====="


def lanzar(cli, cmd, sudo_pass=None, timeout=60):
    guardia.comprobar(cmd)
    return ro.ejecutar(cli, cmd, sudo_pass, timeout)[1]


def diskstats(texto):
    datos = {}
    for linea in texto.splitlines():
        p = linea.split()
        if len(p) >= 14 and p[0].isdigit():
            # lecturas, sectores leidos, ms leyendo, escrituras, sectores escritos, ms escribiendo, en curso, ms ocupado
            datos[p[2]] = [int(p[i]) for i in (3, 5, 6, 7, 9, 10, 11, 12)]
    return datos


def proc_io(texto):
    datos = {}
    for m in re.finditer(r"/proc/(\d+)/io:(read_bytes|write_bytes):\s*(\d+)", texto):
        datos.setdefault(m.group(1), {})[m.group(2)] = int(m.group(3))
    return datos


def main():
    nas = sys.argv[1]
    seg = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    env = ro.leer_env()
    clave = env["QNAP_PASSWORD"]
    cli, via = ro.conectar(env, nas)

    print("== carga, memoria e intercambio")
    print(lanzar(cli, "date; cat /proc/loadavg; grep -c ^processor /proc/cpuinfo; "
                      "grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree|Dirty|Writeback):' /proc/meminfo; "
                      "cat /proc/pressure/io 2>/dev/null").rstrip())

    cmd_io = "grep -H -E '^(read_bytes|write_bytes):' /proc/[0-9]*/io 2>/dev/null"
    cmd = ("cat /proc/diskstats; grep -E '^(pswpin|pswpout|pgpgin|pgpgout) ' /proc/vmstat; echo %s; "
           "%s; echo %s; sleep %d; "
           "cat /proc/diskstats; grep -E '^(pswpin|pswpout|pgpgin|pgpgout) ' /proc/vmstat; echo %s; "
           "%s; echo %s; ps") % (SEP, cmd_io, SEP, seg, SEP, cmd_io, SEP)
    partes = lanzar(cli, cmd, clave, timeout=seg + 45).split(SEP)
    d1, io1, d2, io2, ps = partes[0], partes[1], partes[2], partes[3], partes[4]

    print("\n== discos y volumenes en %d s (solo los que tienen actividad)" % seg)
    print("%-12s %8s %8s %9s %9s %7s %7s %6s" % ("disp", "lect/s", "escr/s", "MB_l/s", "MB_e/s", "ms_l", "ms_e", "%ocup"))
    a, b = diskstats(d1), diskstats(d2)
    filas = []
    for dev in b:
        if dev not in a:
            continue
        dl, dsl, dml, de, dse, dme, _, docup = [y - x for x, y in zip(a[dev], b[dev])]
        if dl + de == 0:
            continue
        filas.append((docup, dev, dl / seg, de / seg, dsl / 2048.0 / seg, dse / 2048.0 / seg,
                      dml / dl if dl else 0, dme / de if de else 0, docup / (seg * 10.0), b[dev][6]))
    for f in sorted(filas, reverse=True)[:45]:
        print("%-12s %8.1f %8.1f %9.2f %9.2f %7.1f %7.1f %6.1f  en_curso=%d" % f[1:])

    print("\n== paginacion e intercambio en %d s" % seg)
    v1 = dict(l.split() for l in d1.splitlines() if re.match(r"^(psw|pgpg)", l))
    v2 = dict(l.split() for l in d2.splitlines() if re.match(r"^(psw|pgpg)", l))
    for k in sorted(v2):
        print("%-8s %10.1f /s" % (k, (int(v2[k]) - int(v1.get(k, v2[k]))) / float(seg)))

    nombres = {}
    for linea in ps.splitlines():
        p = linea.split(None, 4)
        if len(p) >= 5 and p[0].isdigit():
            nombres[p[0]] = p[4][:90]
    print("\n== procesos por E/S de disco en %d s" % seg)
    print("%7s %10s %10s  %s" % ("pid", "MB_leidos", "MB_escr", "proceso"))
    x, y = proc_io(io1), proc_io(io2)
    filas = []
    for pid in y:
        if pid in x:
            r = y[pid].get("read_bytes", 0) - x[pid].get("read_bytes", 0)
            w = y[pid].get("write_bytes", 0) - x[pid].get("write_bytes", 0)
            if r + w > 0:
                filas.append((r + w, pid, r / 1048576.0, w / 1048576.0, nombres.get(pid, "?")))
    for f in sorted(filas, reverse=True)[:20]:
        print("%7s %10.2f %10.2f  %s" % f[1:])

    print("\n== procesos bloqueados en disco (estado D), 6 muestras cada 2 s")
    print(lanzar(cli, "for i in 1 2 3 4 5 6; do ps | awk '$4 ~ /^D/' | cut -c1-110; echo --; sleep 2; done", clave).rstrip())
    cli.close()


if __name__ == "__main__":
    main()
