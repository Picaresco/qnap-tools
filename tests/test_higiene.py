# -*- coding: utf-8 -*-
"""Lo que se versiona no lleva datos reales de ningun NAS: ni en los datos de prueba ni en
los valores de ejemplo escritos a mano en las propias pruebas."""
import re
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "pruebas"))
import anonimiza  # noqa: E402

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# los unicos UUID que puede haber en las pruebas: los que pone el anonimizador y estos de ejemplo
UUID_DE_EJEMPLO = re.compile(
    r"00000000-0000-0000-0000-[0-9a-f]{12}|aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa|"
    r"12345678-9abc-4def-8123-456789abcdef|1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d|"
    r"9A8B7C6D-b65c-20b3-35e5-0123456789ab")
DATOS = sorted(p for p in (AQUI / "datos").rglob("*.txt"))


def test_hay_datos_que_revisar():
    assert len(DATOS) > 100


@pytest.mark.parametrize("fichero", DATOS, ids=lambda p: "%s/%s" % (p.parent.name, p.name))
def test_ningun_dato_de_prueba_tiene_algo_que_parezca_real(fichero):
    texto = fichero.read_text(encoding="utf-8")
    # las rutas bajo /share y los textos entre comillas solo se revisan donde se anonimizan
    pata = fichero.parent.name
    assert anonimiza.revisar(texto, rutas=pata == "virtualizacion", comillas=pata == "logs") == []


def test_los_uuid_escritos_en_las_pruebas_son_de_ejemplo():
    # un UUID copiado de la salida de un NAS para hacer de ejemplo es un dato real versionado
    reales = []
    for fichero in sorted(AQUI.rglob("*.py")) + DATOS:
        if fichero.name == Path(__file__).name:
            continue
        for uuid in UUID.findall(fichero.read_text(encoding="utf-8")):
            if not UUID_DE_EJEMPLO.fullmatch(uuid):
                reales.append("%s: %s" % (fichero.name, uuid))
    assert reales == []


def test_todo_el_codigo_python_versionado_es_ascii():
    # regla del proyecto: solo ASCII en los .py (un caracter con acento se escribe con su escape)
    import subprocess
    raiz = Path(__file__).resolve().parent.parent
    ficheros = subprocess.run(["git", "-C", str(raiz), "ls-files", "*.py"], capture_output=True, text=True,
                              check=True).stdout.split()
    assert len(ficheros) > 50
    malos = [f for f in ficheros if (raiz / f).exists() and not (raiz / f).read_bytes().isascii()]
    assert malos == []
