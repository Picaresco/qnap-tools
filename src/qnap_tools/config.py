# -*- coding: utf-8 -*-
"""Configuracion de los servidores: credencial comun y carpeta de datos, leidas del entorno.

El plugin de Claude Code pasa la credencial por variables de entorno (userConfig -> env).
La contrasena no se escribe nunca en disco ni aparece en repr().
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

# Un marcador ${...} que ha llegado sin sustituir no es un valor
SIN_SUSTITUIR = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_.]*\}")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    usuario: str
    contrasena: str = field(repr=False)
    datos: Path
    inventario: Path
    clave: Path
    known_hosts: Path


def _valor(entorno, nombre):
    v = entorno.get(nombre)
    if not v or SIN_SUSTITUIR.fullmatch(v.strip()):
        return None
    return v


def cargar(entorno: Mapping[str, str] = os.environ) -> Config:
    usuario = (_valor(entorno, "QNAP_TOOLS_USER") or "").strip()
    contrasena = _valor(entorno, "QNAP_TOOLS_PASSWORD")
    faltan = [n for n, v in (("QNAP_TOOLS_USER", usuario), ("QNAP_TOOLS_PASSWORD", contrasena)) if not v]
    if faltan:
        raise ConfigError(
            "falta configurar %s: en Claude Code, /plugin configure qnap-tools "
            "(usuario SSH comun de la flota y su contrasena)" % " y ".join(faltan))
    datos = Path(_valor(entorno, "QNAP_TOOLS_DATA") or _valor(entorno, "CLAUDE_PLUGIN_DATA")
                 or Path.home() / ".qnap-tools")
    inventario = _valor(entorno, "QNAP_TOOLS_INVENTARIO")
    return Config(
        usuario=usuario,
        contrasena=contrasena,
        datos=datos,
        inventario=Path(inventario) if inventario else datos / "inventario.toml",
        clave=datos / "id_ed25519",
        known_hosts=datos / "known_hosts",
    )
