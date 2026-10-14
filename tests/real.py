# -*- coding: utf-8 -*-
"""Apoyo para las pruebas contra un NAS real (solo el de laboratorio, y solo a peticion).

Se activan con QNAP_TOOLS_PRUEBA_REAL=1 y leen host y credencial del .env del proyecto,
que no se versiona. Son de solo lectura sobre el NAS.
"""
import os
from pathlib import Path

import pytest

from qnap_tools import config
from qnap_tools.inventario import Nas

RAIZ = Path(__file__).resolve().parent.parent
ACTIVAS = os.environ.get("QNAP_TOOLS_PRUEBA_REAL") == "1"
solo_real = pytest.mark.skipif(
    not ACTIVAS, reason="prueba contra un NAS real: definir QNAP_TOOLS_PRUEBA_REAL=1")


def leer_env():
    datos = {}
    with open(RAIZ / ".env", encoding="utf-8-sig") as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                clave, valor = linea.split("=", 1)
                datos[clave.strip()] = valor.strip()
    return datos


def nas_de_laboratorio():
    env = leer_env()
    return Nas("nas1", env["QNAP_HOST"], int(env.get("QNAP_PORT", "22")))


def cfg_de_laboratorio(carpeta):
    env = leer_env()
    return config.cargar({"QNAP_TOOLS_USER": env["QNAP_USER"],
                          "QNAP_TOOLS_PASSWORD": env["QNAP_PASSWORD"],
                          "QNAP_TOOLS_DATA": str(carpeta)})
