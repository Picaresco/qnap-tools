# -*- coding: utf-8 -*-
"""Inventario de NAS: nombre, host y puerto de cada equipo. Sin secretos.

Fichero TOML con una tabla [nas.<nombre>] por equipo. La credencial comun de la flota
vive en la configuracion del plugin, no aqui.
"""
import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

NOMBRE_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
HOST_VALIDO = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.:-]{0,251}[A-Za-z0-9])?")
USUARIO_VALIDO = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}")
AUTH = ("auto", "clave", "contrasena")
TODOS = "todos"
CAMPOS = ("host", "port", "user", "auth")


class InventarioInvalido(ValueError):
    pass


class NasDesconocido(Exception):
    pass


@dataclass(frozen=True)
class Nas:
    nombre: str
    host: str
    port: int = 22
    user: str | None = None
    auth: str = "auto"

    @property
    def destino(self):
        """Como se nombra este NAS en los mensajes de error."""
        return "%s (%s:%d)" % (self.nombre, self.host, self.port)

    def __post_init__(self):
        # fullmatch: con match(), "casa\n" pasaria por el $ de la expresion
        if (not isinstance(self.nombre, str) or not NOMBRE_VALIDO.fullmatch(self.nombre)
                or self.nombre == TODOS):
            raise InventarioInvalido(
                "nombre de NAS no valido: %r (minusculas, digitos, - y _, hasta 32 caracteres; "
                "'%s' esta reservado)" % (self.nombre, TODOS))
        if not isinstance(self.host, str) or not HOST_VALIDO.fullmatch(self.host):
            raise InventarioInvalido("NAS %s: host no valido: %r" % (self.nombre, self.host))
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise InventarioInvalido("NAS %s: puerto no valido: %r" % (self.nombre, self.port))
        if self.user is not None and (
                not isinstance(self.user, str) or not USUARIO_VALIDO.fullmatch(self.user)):
            raise InventarioInvalido("NAS %s: usuario no valido: %r" % (self.nombre, self.user))
        if self.auth not in AUTH:
            raise InventarioInvalido(
                "NAS %s: auth no valido: %r (%s)" % (self.nombre, self.auth, ", ".join(AUTH)))


def cargar(ruta) -> dict[str, Nas]:
    ruta = Path(ruta)
    try:
        # utf-8-sig: tolera el BOM que anaden algunos editores de Windows
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as e:
        raise InventarioInvalido("no se pudo leer el inventario %s: %s" % (ruta, e)) from None
    try:
        datos = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as e:
        raise InventarioInvalido("el inventario %s no es TOML valido: %s" % (ruta, e)) from None
    sobran = sorted(k for k in datos if k != "nas")
    if sobran:
        raise InventarioInvalido(
            "inventario %s: entrada desconocida %s; cada NAS va en una tabla [nas.<nombre>]"
            % (ruta, ", ".join(sobran)))
    tabla = datos.get("nas", {})
    if not isinstance(tabla, dict):
        raise InventarioInvalido("inventario %s: 'nas' debe ser una tabla [nas.<nombre>]" % ruta)
    nas = {}
    for nombre, campos in tabla.items():
        if not isinstance(campos, dict):
            raise InventarioInvalido("inventario %s: [nas.%s] debe ser una tabla" % (ruta, nombre))
        sobran = sorted(set(campos) - set(CAMPOS))
        if sobran:
            raise InventarioInvalido(
                "inventario %s: NAS %s: clave desconocida %s (validas: %s)"
                % (ruta, nombre, ", ".join(sobran), ", ".join(CAMPOS)))
        if "host" not in campos:
            raise InventarioInvalido("inventario %s: NAS %s: falta host" % (ruta, nombre))
        try:
            nas[nombre] = Nas(nombre, campos["host"], campos.get("port", 22),
                              campos.get("user"), campos.get("auth", "auto"))
        except InventarioInvalido as e:
            raise InventarioInvalido("inventario %s: %s" % (ruta, e)) from None
    return nas


def guardar(ruta, nas: dict[str, Nas]) -> None:
    ruta = Path(ruta)
    lineas = ["# Inventario de qnap-tools. Sin secretos: la credencial vive en la configuracion",
              "# del plugin. Una tabla [nas.<nombre>] por equipo.", ""]
    for nombre in sorted(nas):
        n = nas[nombre]
        if n.nombre != nombre:
            raise InventarioInvalido("la entrada %r contiene el NAS %r" % (nombre, n.nombre))
        lineas.append("[nas.%s]" % nombre)
        lineas.append("host = %s" % json.dumps(n.host))
        lineas.append("port = %d" % n.port)
        if n.user is not None:
            lineas.append("user = %s" % json.dumps(n.user))
        if n.auth != "auto":
            lineas.append("auth = %s" % json.dumps(n.auth))
        lineas.append("")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # escritura atomica: temporal en la misma carpeta y sustitucion
    fd, temporal = tempfile.mkstemp(dir=str(ruta.parent), prefix=".inventario-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lineas))
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def resolver(nas: dict[str, Nas], nombre: str) -> list[Nas]:
    if not nas:
        raise NasDesconocido(
            "el inventario esta vacio: da de alta un NAS con la herramienta nas_alta")
    if nombre == TODOS:
        return [nas[k] for k in sorted(nas)]
    if nombre not in nas:
        raise NasDesconocido(
            "no hay ningun NAS llamado %r en el inventario; validos: %s (o '%s')"
            % (nombre, ", ".join(sorted(nas)), TODOS))
    return [nas[nombre]]
