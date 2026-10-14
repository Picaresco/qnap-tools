# -*- coding: utf-8 -*-
"""La prueba de efectos del laboratorio: como lee el listado del NAS y que da por nuevo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pruebas"))
import efectos  # noqa: E402

LISTADO = """\
/tmp:
total 8
drwxr-xr-x 2 admin administrators 40 2026-10-14 03:00:00.000000000 +0200 vacia
-rw-r--r-- 1 admin administrators 12 2026-10-14 03:00:01.000000000 +0200 con espacio.txt
lrwxrwxrwx 1 admin administrators  4 2026-10-14 03:00:02.000000000 +0200 enlace -> /etc

/tmp/vacia:
total 0

/share/homes/usuario:
total 0
"""


def test_el_listado_da_ficheros_con_tamano_y_fecha_y_tambien_las_carpetas():
    datos = efectos.leer_listado(LISTADO)
    assert datos["/tmp/con espacio.txt"] == ("12", "2026-10-14 03:00:01.000000000")
    # una carpeta nueva y vacia (lo que deja un cliente la primera vez que se usa) tiene que verse
    assert {"/tmp/", "/tmp/vacia/", "/share/homes/usuario/"} <= set(datos)
    assert "/tmp/enlace" not in datos and "/tmp/vacia" not in datos


def test_una_carpeta_nueva_cuenta_como_cambio():
    antes = efectos.leer_listado(LISTADO)
    despues = efectos.leer_listado(LISTADO + "\n/share/homes/usuario/.docker:\ntotal 0\n")
    assert efectos.cambios(antes, despues) == {"/share/homes/usuario/.docker/"}
    assert efectos.cambios(despues, antes) == {"/share/homes/usuario/.docker/ (borrado)"}


def test_lo_que_aparece_con_una_orden_y_sigue_al_final_se_senala_aunque_no_se_repita():
    inicial = {"/tmp/a": ("1", "x")}
    final = {"/tmp/a": ("2", "y"), "/home/u/.docker/": ("carpeta", ""), "/tmp/b": ("1", "x")}
    vistos = {"/tmp/a", "/home/u/.docker/", "/tmp/c", "/tmp/d (borrado)"}
    # /tmp/a ya existia (solo cambio); /tmp/c aparecio y se fue; .docker aparecio y sigue
    assert efectos.nuevos_que_siguen(vistos, inicial, final) == ["/home/u/.docker/"]
