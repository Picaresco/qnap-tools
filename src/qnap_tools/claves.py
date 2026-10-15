# -*- coding: utf-8 -*-
"""Par de claves SSH de este ordenador (ed25519), en la carpeta de datos del plugin.

Cada ordenador tiene su propia clave privada, que no sale de el; lo que se instala en los
NAS es la parte publica. La proteccion de la privada es la de la carpeta de datos (el perfil
del usuario); en sistemas POSIX se crea ademas con permisos 600.
"""
import os
import re
import socket

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _comentario():
    equipo = re.sub(r"[^A-Za-z0-9_.-]", "-", socket.gethostname() or "equipo")[:60]
    return "qnap-tools@" + equipo


def asegurar(cfg) -> str:
    """Crea el par si no existe y devuelve la linea publica (tipo, clave y comentario)."""
    ruta_privada = cfg.clave
    ruta_publica = ruta_privada.with_name(ruta_privada.name + ".pub")
    if ruta_privada.exists() and ruta_privada.stat().st_size == 0:
        # un cierre entre crear el fichero y escribirlo lo deja a 0 bytes: no es una clave
        # (nada se ha podido instalar con ella) y se vuelve a generar
        ruta_privada.unlink()
    if ruta_privada.exists():
        try:
            privada = serialization.load_ssh_private_key(ruta_privada.read_bytes(), password=None)
        except (ValueError, UnsupportedAlgorithm) as e:
            raise ValueError(
                "la clave privada %s no se puede leer (%s); borra ese fichero para generar otra "
                "y ejecuta nas_enrolar para instalarla en los NAS"
                % (ruta_privada, e.__class__.__name__)) from None
    else:
        ruta_privada.parent.mkdir(parents=True, exist_ok=True)
        privada = Ed25519PrivateKey.generate()
        cuerpo = privada.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption())
        # O_EXCL: si otro proceso la acaba de crear, no se pisa
        fd = os.open(str(ruta_privada), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(cuerpo)
    publica = privada.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode("ascii")
    if ruta_publica.exists():
        # se conserva la linea ya escrita (y su comentario) mientras sea de esta clave:
        # es la que esta instalada en los NAS
        linea = ruta_publica.read_text(encoding="utf-8").strip()
        if linea.startswith(publica + " "):
            return linea
    linea = "%s %s" % (publica, _comentario())
    ruta_publica.write_text(linea + "\n", encoding="utf-8")
    return linea
