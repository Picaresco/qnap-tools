# -*- coding: utf-8 -*-
"""Perfil de un NAS: sistema (QuTS hero o QTS), modelo, firmware y paquetes instalados.

Se averigua con una sola orden, sin sudo. Lo que cambia de un NAS a otro (sistema de
almacenamiento, carpeta de cada paquete) se toma de aqui y nunca se fija en el codigo.
"""
import re
from dataclasses import dataclass, field

from .comandos import Comando

PAQUETES = ("QKVM", "container-station")
SISTEMAS = ("hero", "qts")
RUTA_VALIDA = re.compile(r"/[A-Za-z0-9_./-]{1,200}")

# La version sale de /etc/default_config: la de /etc/config puede quedarse obsoleta tras
# una actualizacion (visto en un QuTS hero real). hero = hay ZFS.
DETECCION = Comando(
    "deteccion",
    "echo sistema=$([ -x /sbin/zpool ] && echo hero || echo qts); "
    "echo modelo=$(getcfg System Model -f /etc/default_config/uLinux.conf); "
    "echo firmware=$(getcfg System Version -f /etc/default_config/uLinux.conf); "
    "echo build=$(getcfg System 'Build Number' -f /etc/default_config/uLinux.conf); "
    "echo nombre=$(hostname); "
    "for q in %s; do "
    "echo paquete.$q.enable=$(getcfg $q Enable -f /etc/config/qpkg.conf); "
    "echo paquete.$q.ruta=$(getcfg $q Install_Path -f /etc/config/qpkg.conf); "
    "done" % " ".join(PAQUETES),
)


class DeteccionFallida(Exception):
    pass


@dataclass(frozen=True)
class Perfil:
    sistema: str
    modelo: str
    firmware: str
    build: str
    nombre: str
    paquetes: dict = field(default_factory=dict)
    avisos: tuple = ()


def detectar(con) -> Perfil:
    r = con.ejecutar(DETECCION.render(), sudo=False, timeout=DETECCION.timeout)
    if r.agotado:
        raise DeteccionFallida(
            "%s: no respondio a tiempo (%d s) al identificar el sistema" % (con.destino, DETECCION.timeout))
    if r.rc != 0:
        raise DeteccionFallida(
            "%s: la orden que identifica el sistema termino con codigo %d" % (con.destino, r.rc))
    campos = {}
    for linea in r.salida.splitlines():
        if "=" in linea:
            clave, valor = linea.split("=", 1)
            campos[clave.strip()] = valor.strip()
    if campos.get("sistema") not in SISTEMAS or not campos.get("firmware"):
        raise DeteccionFallida(
            "%s: no se pudo identificar el sistema del NAS (no parece un QNAP con QTS o QuTS hero)"
            % con.destino)
    paquetes = {}
    avisos = []
    for nombre in PAQUETES:
        ruta = campos.get("paquete.%s.ruta" % nombre, "")
        if campos.get("paquete.%s.enable" % nombre, "").upper() != "TRUE" or not ruta:
            continue
        if not RUTA_VALIDA.fullmatch(ruta) or ".." in ruta:
            avisos.append("paquete %s: su ruta de instalacion no es valida y no se usara" % nombre)
            continue
        paquetes[nombre] = ruta
    return Perfil(
        sistema=campos["sistema"],
        modelo=campos.get("modelo", ""),
        firmware=campos["firmware"],
        build=campos.get("build", ""),
        nombre=campos.get("nombre", ""),
        paquetes=paquetes,
        avisos=tuple(avisos),
    )
