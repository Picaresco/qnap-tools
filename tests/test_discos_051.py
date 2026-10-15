# -*- coding: utf-8 -*-
"""0.5.1 de qnap-discos: el tipo real de los discos externos (ufsd) con su etiqueta, si estan sucios o
en solo lectura, y el aviso de las programaciones de instantaneas de QuTS hero. Datos de un disco USB
generico visto en el NAS de laboratorio (la etiqueta cambiada por USB-DISCO)."""
import os
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from test_discos_servidor import algun, dato, datos, dc, discos_srv, por, uno
from test_discos_shell import posix
from qnap_tools.discos import parsers as p

SH = shutil.which("sh")
MONTAJE_NTFS = ("/dev/sdh1 /share/external/DEV3301_1 ufsd rw,relatime,nls=utf8,fmask=111,dmask=0,force 0 0")
DF = ("Filesystem 1024-blocks Used Available Capacity Mounted on\n"
      "/dev/sdh1 4883637168 1953454868 2930182300 40% /share/external/DEV3301_1\n")


def salida(montaje=MONTAJE_NTFS, ufsd="== sdh1\nvolinfo=NTFS\nlabel=USB-DISCO\ndirty=0\n", df=DF, n=5):
    return "==montajes %d\n%s\n==df\n%s==ufsd\n%s" % (n, montaje, df, ufsd)


# --- parser: el tipo real, la etiqueta, sucio y solo lectura -------------------------------------------

def test_un_disco_ufsd_trae_su_tipo_real_la_etiqueta_y_si_esta_sucio():
    (m,) = p.externos_montajes(dato("externos_montajes_hero"))
    assert m["sistema_ficheros"] == "ufsd" and m["tipo"] == "NTFS"
    assert (m["etiqueta"], m["sucio"], m["solo_lectura"]) == ("USB-DISCO", False, False)
    assert m["montaje"] == "/share/external/DEV3301_1" and m["ocupacion_pct"] == 40


def test_un_montaje_con_ro_en_las_opciones_esta_en_solo_lectura():
    (m,) = p.externos_montajes(salida(montaje=MONTAJE_NTFS.replace(" rw,", " ro,")))
    assert m["solo_lectura"] is True


def test_errors_remount_ro_no_es_ro():
    (m,) = p.externos_montajes(salida(montaje=MONTAJE_NTFS.replace(" rw,", " rw,errors=remount-ro,")))
    assert m["solo_lectura"] is False


@pytest.mark.parametrize("dirty, esperado", [("1", True), ("0", False), ("", None), ("quizas", None)])
def test_dirty_se_lee_como_booleano_y_si_no_se_entiende_queda_sin_valor(dirty, esperado):
    (m,) = p.externos_montajes(salida(ufsd="== sdh1\nvolinfo=NTFS\nlabel=USB-DISCO\ndirty=%s\n" % dirty))
    assert m["sucio"] is esperado


def test_un_montaje_que_no_es_ufsd_usa_el_tipo_de_proc_mounts_y_no_tiene_etiqueta():
    (m,) = p.externos_montajes(salida(montaje="/dev/sdk1 /share/external/DEV3307_1 vfat rw,relatime 0 0", ufsd=""))
    assert (m["tipo"], m["sistema_ficheros"], m["etiqueta"], m["sucio"], m["solo_lectura"]) == (
        "vfat", "vfat", None, None, False)


def test_si_volinfo_no_se_pudo_leer_el_tipo_es_el_de_proc_mounts():
    (m,) = p.externos_montajes(salida(ufsd="== sdh1\nvolinfo=\nlabel=\ndirty=\n"))
    assert (m["tipo"], m["etiqueta"], m["sucio"]) == ("ufsd", None, None)


def test_varios_montajes_ufsd_y_otros_cada_uno_con_lo_suyo():
    montajes = (MONTAJE_NTFS + "\n/dev/sdi1 /share/external/DEV3302_1 ufsd rw 0 0\n"
                "/dev/sdk1 /share/external/DEV3307_1 ext4 ro,relatime 0 0")
    ufsd = ("== sdh1\nvolinfo=NTFS\nlabel=USB-DISCO\ndirty=0\n== sdi1\nvolinfo=exFAT\nlabel=Otro disco\ndirty=1\n")
    df = DF + "/dev/sdi1 100 40 60 40% /share/external/DEV3302_1\n"
    r = {m["dispositivo"]: m for m in p.externos_montajes(salida(montajes, ufsd, df, n=7))}
    assert r["/dev/sdh1"]["tipo"] == "NTFS" and r["/dev/sdi1"]["tipo"] == "exFAT"
    assert (r["/dev/sdi1"]["etiqueta"], r["/dev/sdi1"]["sucio"]) == ("Otro disco", True)
    assert r["/dev/sdk1"]["tipo"] == "ext4" and r["/dev/sdk1"]["solo_lectura"] is True


def test_los_textos_de_un_tercero_se_sanean():
    (m,) = p.externos_montajes(salida(ufsd="== sdh1\nvolinfo=NTFS\nlabel=" + "x\ty" * 300 + "\ndirty=0\n"))
    assert "\t" not in m["etiqueta"] and len(m["etiqueta"]) <= p.MAX_NOMBRE


@pytest.mark.parametrize("texto", [
    "==montajes 5\n%s\n==df\n" % MONTAJE_NTFS,                                  # sin la parte de ufsd
    salida(ufsd="suelto\n"), salida(ufsd="== sdh1\nvolinfo=NTFS\n"),
    salida(ufsd="== sdh1\nvolinfo=NTFS\nlabel=x\ndirty=0\nextra=1\n"),
    salida(ufsd="volinfo=NTFS\nlabel=x\ndirty=0\n")])
def test_el_montaje_externo_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.externos_montajes(texto)


# --- herramienta: discos_fisicos ------------------------------------------------------------------------

def test_discos_fisicos_da_tipo_etiqueta_sucio_y_solo_lectura_de_cada_externo(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.discos_fisicos("hero"))
    (usb,) = d["externos"]
    assert (usb["tipo"], usb["etiqueta"], usb["sucio"], usb["solo_lectura"]) == ("NTFS", "USB-DISCO", False, False)
    assert usb["sistema_ficheros"] == "ufsd" and d["avisos"] == []


def test_un_externo_en_solo_lectura_y_un_volumen_sucio_salen_en_los_avisos(tmp_path):
    ro = dato("externos_montajes_hero").replace(" ufsd rw,", " ufsd ro,").replace("dirty=0", "dirty=1")
    h, _ = uno(tmp_path, cambios={dc.EXTERNOS_MONTAJES.plantilla: ro})
    d = datos(h.discos_fisicos("hero"))
    assert algun(d["avisos"], "cabina 33, bahia 1", "solo lectura")
    assert algun(d["avisos"], "cabina 33, bahia 1", "sucio")
    assert (d["externos"][0]["solo_lectura"], d["externos"][0]["sucio"]) == (True, True)


def test_un_externo_sin_montar_no_tiene_tipo_ni_avisos(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.discos_fisicos("qts"))
    sin_montar = next(e for e in d["externos"] if e["dispositivo"] == "/dev/sdl")
    assert (sin_montar["tipo"], sin_montar["etiqueta"], sin_montar["sucio"], sin_montar["solo_lectura"]) == (
        None, None, None, None)
    assert d["avisos"] == []
    montado = next(e for e in d["externos"] if e["dispositivo"] == "/dev/sdk")
    assert (montado["tipo"], montado["etiqueta"], montado["solo_lectura"]) == ("vfat", None, False)


def test_si_no_se_pueden_leer_los_montajes_no_hay_avisos_de_externos_y_se_dice(tmp_path):
    h, _ = uno(tmp_path, cambios={dc.EXTERNOS_MONTAJES.plantilla: (1, "", "boom\n")})
    d = datos(h.discos_fisicos("hero"))
    assert "montajes_externos" in d["errores"] and d["avisos"] == []
    assert d["externos"][0]["tipo"] is None and d["externos"][0]["solo_lectura"] is None


# --- la orden en un sh de verdad -----------------------------------------------------------------------

@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar las ordenes")
class TestEnShell:
    def lanzar(self, tmp_path, mounts, ufsd):
        """La orden con /proc/ sustituido por una carpeta de pruebas y df por uno de pega."""
        proc = tmp_path / "proc"
        (proc / "fs" / "ufsd").mkdir(parents=True, exist_ok=True)
        (proc / "mounts").write_text(mounts, encoding="utf-8", newline="\n")
        for particion, ficheros in ufsd.items():
            (proc / "fs" / "ufsd" / particion).mkdir(parents=True, exist_ok=True)
            for nombre, contenido in ficheros.items():
                (proc / "fs" / "ufsd" / particion / nombre).write_text(contenido, encoding="utf-8", newline="\n")
        (tmp_path / "df.sh").write_text('cat "$PEGA/df"\n', encoding="utf-8", newline="\n")
        (tmp_path / "df").write_text(DF, encoding="utf-8", newline="\n")
        texto = dc.EXTERNOS_MONTAJES.render().replace("/proc/", posix(tmp_path) + "/proc/")
        texto = texto.replace("df -P -k", "sh %s/df.sh -P -k" % posix(tmp_path))
        r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                           env={"PATH": os.environ["PATH"], "PEGA": posix(tmp_path)}, timeout=60)
        return r.returncode, r.stdout

    def test_lee_volinfo_label_y_dirty_de_cada_particion_ufsd(self, tmp_path):
        mounts = ("rootfs / rootfs rw 0 0\n" + MONTAJE_NTFS + "\n"
                  "/dev/sdk1 /share/external/DEV3307_1 vfat rw 0 0\n"
                  "/dev/sdi1 /share/external/DEV3302_1 ufsd rw 0 0\n")
        ufsd = {"sdh1": {"volinfo": "NTFS\n4096\n1220931961\n", "label": "USB-DISCO\n", "dirty": "0\n"},
                "sdi1": {"volinfo": "exFAT\n", "label": "Mi disco\n", "dirty": "1\n"},
                "sdk1": {"volinfo": "NO SE LEE\n", "label": "no\n", "dirty": "9\n"}}
        rc, texto = self.lanzar(tmp_path, mounts, ufsd)
        assert rc == 0
        lineas = texto.splitlines()
        i = lineas.index("==ufsd")
        assert lineas[i + 1:] == ["== sdh1", "volinfo=NTFS", "label=USB-DISCO", "dirty=0",
                                  "== sdi1", "volinfo=exFAT", "label=Mi disco", "dirty=1"]
        por_dispositivo = {m["dispositivo"]: m for m in p.externos_montajes(texto)}
        assert por_dispositivo["/dev/sdh1"]["tipo"] == "NTFS" and por_dispositivo["/dev/sdk1"]["tipo"] == "vfat"

    def test_con_ficheros_de_ufsd_que_faltan_salen_vacios_y_el_parser_los_acepta(self, tmp_path):
        rc, texto = self.lanzar(tmp_path, MONTAJE_NTFS + "\n", {})
        assert rc == 0 and texto.splitlines()[-4:] == ["== sdh1", "volinfo=", "label=", "dirty="]
        (m,) = p.externos_montajes(texto)
        assert (m["tipo"], m["etiqueta"], m["sucio"]) == ("ufsd", None, None)

    def test_sin_externos_no_hay_particiones_ufsd(self, tmp_path):
        rc, texto = self.lanzar(tmp_path, "rootfs / rootfs rw 0 0\n", {})
        assert rc == 0 and texto.splitlines() == ["==montajes 1", "==df", "==ufsd"]


# --- tareas_file_station: las terminadas desaparecen --------------------------------------------------

def test_se_avisa_de_que_file_station_borra_las_tareas_terminadas():
    from pathlib import Path
    docstring = discos_srv.Herramientas.tareas_file_station.__doc__
    readme = [x for x in (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8").splitlines()
              if x.startswith("| `tareas_file_station`")]
    for texto in (docstring, discos_srv.INSTRUCCIONES, readme[0]):
        assert "borra" in texto and "17 minutos" in texto and "terminad" in texto


# --- instantaneas: aviso de programaciones (QuTS hero) -------------------------------------------------

def con_ahora(monkeypatch, texto):
    ahora = datetime.strptime(texto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    monkeypatch.setattr(discos_srv, "ahora", lambda: ahora)


def test_una_programacion_con_schedule_negativo_se_avisa_como_desactivada(tmp_path, monkeypatch):
    con_ahora(monkeypatch, "2026-10-15T12:00:00Z")
    h, _ = uno(tmp_path)
    d = datos(h.snapshots("hero"))
    assert d["avisos"] == [
        "volumen 19 (zfs19): programacion de instantaneas desactivada (Schedule -4); la ultima es de 2026-09-24"]
    assert "deducido" in d["programacion"]["nota"] and "Schedule" in d["programacion"]["nota"]


def test_una_programacion_activa_con_la_ultima_instantanea_reciente_no_avisa(tmp_path, monkeypatch):
    con_ahora(monkeypatch, "2026-10-15T12:00:00Z")           # la ultima de zfs24 es del 13 a las 22:00Z
    h, _ = uno(tmp_path)
    assert not algun(datos(h.snapshots("hero"))["avisos"], "volumen 24")


def test_una_programacion_activa_con_la_ultima_de_hace_mas_de_dos_dias_avisa(tmp_path, monkeypatch):
    con_ahora(monkeypatch, "2026-10-20T00:00:00Z")
    h, _ = uno(tmp_path)
    avisos = datos(h.snapshots("hero"))["avisos"]
    assert "volumen 24: tiene programacion activa pero su ultima instantanea es de hace 6 dias" in avisos


def test_el_limite_son_dos_dias_justos(tmp_path, monkeypatch):
    h, _ = uno(tmp_path)
    con_ahora(monkeypatch, "2026-10-15T22:00:03Z")           # exactamente dos dias despues
    assert not algun(datos(h.snapshots("hero"))["avisos"], "volumen 24")
    con_ahora(monkeypatch, "2026-10-15T22:00:04Z")
    assert algun(datos(h.snapshots("hero"))["avisos"], "volumen 24", "hace 2 dias")


def test_una_programacion_activa_sin_ninguna_instantanea_avisa(tmp_path, monkeypatch):
    con_ahora(monkeypatch, "2026-10-15T12:00:00Z")
    sin = "".join(x for x in dato("zfs_snapshots_hero").splitlines(True) if "zpool1/zfs24@" not in x)
    h, _ = uno(tmp_path, cambios={dc.SNAPSHOTS_HERO.plantilla: sin})
    assert "volumen 24: tiene programacion activa pero no tiene ninguna instantanea" in datos(h.snapshots("hero"))["avisos"]


def test_una_programacion_desactivada_sin_instantaneas_lo_dice(tmp_path, monkeypatch):
    con_ahora(monkeypatch, "2026-10-15T12:00:00Z")
    sin = "".join(x for x in dato("zfs_snapshots_hero").splitlines(True) if "zpool2/zfs19@" not in x)
    h, _ = uno(tmp_path, cambios={dc.SNAPSHOTS_HERO.plantilla: sin})
    assert algun(datos(h.snapshots("hero"))["avisos"], "volumen 19 (zfs19)", "desactivada", "no tiene ninguna instantanea")


def test_un_schedule_cero_o_que_no_es_un_numero_no_avisa(tmp_path, monkeypatch):
    con_ahora(monkeypatch, "2027-01-01T00:00:00Z")
    prog = dato("zfs_snapshots_prog_hero").replace("Schedule = -4", "Schedule = 0").replace("Schedule = 4", "Schedule = x")
    h, _ = uno(tmp_path, cambios={dc.SNAPSHOTS_PROG_HERO.plantilla: prog})
    assert datos(h.snapshots("hero"))["avisos"] == []


def test_las_instantaneas_internas_no_cuentan_como_ultima(tmp_path, monkeypatch):
    # solo hay la :init: del volumen: es la que crea el NAS al crear la carpeta, no la programacion
    con_ahora(monkeypatch, "2026-10-15T12:00:00Z")
    solo_init = "".join(x for x in dato("zfs_snapshots_hero").splitlines(True)
                        if "zpool1/zfs24@" not in x or ":init:" in x)
    h, _ = uno(tmp_path, cambios={dc.SNAPSHOTS_HERO.plantilla: solo_init})
    assert algun(datos(h.snapshots("hero"))["avisos"], "volumen 24", "no tiene ninguna instantanea")


def test_en_qts_no_se_avisa_de_la_programacion_porque_el_signo_no_esta_visto(tmp_path, monkeypatch):
    con_ahora(monkeypatch, "2030-01-01T00:00:00Z")
    h, _ = uno(tmp_path, "qts")
    d = datos(h.snapshots("qts"))
    assert d["avisos"] == []
