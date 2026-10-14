# -*- coding: utf-8 -*-
"""Dobles de prueba: un NAS simulado detras de un sustituto de paramiko.SSHClient.

Mundo guarda que acepta el NAS y que responde a cada orden, y registra lo que recibe.
ClienteFalso implementa lo que transporte.Conexion usa de paramiko.SSHClient.
"""
import shlex

import time

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

CUELGA = object()  # respuesta especial: la orden no termina nunca
PREFIJO_SUDO = "sudo -S -p '' sh -c "
SERMON = (
    "\nWe trust you have received the usual lecture from the local System\n"
    "Administrator. It usually boils down to these three things:\n\n"
    "    #1) Respect the privacy of others.\n"
    "    #2) Think before you type.\n"
    "    #3) With great power comes great responsibility.\n\n"
)


def crear_clave(ruta):
    """Escribe una clave privada ed25519 real (formato OpenSSH) para las pruebas."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    clave = Ed25519PrivateKey.generate()
    ruta.write_bytes(clave.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption()))


_CLAVE_DE_HOST = []


def clave_de_host():
    """Una clave real (la misma en toda la sesion) para lo que se guarda en known_hosts."""
    if not _CLAVE_DE_HOST:
        _CLAVE_DE_HOST.append(paramiko.ECDSAKey.generate())
    return _CLAVE_DE_HOST[0]


class ClaveFalsa:
    def __init__(self, texto):
        self._texto = texto
        self.fingerprint = "SHA256:huella-de-" + texto

    def get_base64(self):
        return self._texto

    def get_name(self):
        return "ssh-ed25519"


class Mundo:
    def __init__(self, respuestas=None, acepta_clave=True, acepta_contrasena=True,
                 contrasena="secreto", host_fijado=True, host_cambiado=False,
                 error_conexion=None, sudo_con_sermon=False, salida_tardia=False,
                 sin_fin_de_salida=False, retardo_fijar=0):
        # orden exacta (o expresion regular compilada) -> respuesta, que puede ser:
        #   str                 salida con codigo 0
        #   (rc, salida, error) respuesta completa (salida y error pueden ser bytes)
        #   CUELGA              no termina
        #   funcion(orden, sudo) que devuelve cualquiera de las anteriores
        self.respuestas = dict(respuestas or {})
        self.acepta_clave = acepta_clave
        self.acepta_contrasena = acepta_contrasena
        self.contrasena = contrasena
        self.host_fijado = host_fijado
        self.host_cambiado = host_cambiado
        self.error_conexion = error_conexion
        self.sudo_con_sermon = sudo_con_sermon
        # True: la segunda mitad de la salida llega despues del codigo de salida de la orden
        self.salida_tardia = salida_tardia
        # True: la orden termina pero el fin de fichero no llega (un hijo retiene la salida)
        self.sin_fin_de_salida = sin_fin_de_salida
        # segundos entre cargar known_hosts y guardarlo al fijar el host (para ver carreras)
        self.retardo_fijar = retardo_fijar
        self.keepalives = []        # segundos pedidos en cada conexion establecida
        self.caida = False          # True: la sesion se ha cortado
        self.parcial = ""           # lo que llega antes de colgarse una orden CUELGA
        self.ordenes = []           # [(orden sin envoltorio, sudo)]
        self.enviado = []           # texto tal cual llego a exec_command
        self.stdin = []             # lo escrito en stdin en cada orden
        self.intentos = []          # [(metodo, usuario)]
        self.conexiones = 0         # conexiones establecidas
        self.fijaciones = 0         # veces que se acepto y guardo la clave de host
        self.clientes = []

    def cliente(self):
        """Fabrica de clientes: se pasa a Conexion como sustituto de paramiko.SSHClient."""
        c = ClienteFalso(self)
        self.clientes.append(c)
        return c

    def cortar(self):
        """Corta las sesiones abiertas; una conexion nueva vuelve a funcionar."""
        for c in self.clientes:
            c.conectado = False

    def responder(self, orden, sudo):
        r = self.respuestas.get(orden)
        if r is None:
            for clave, valor in self.respuestas.items():
                if hasattr(clave, "search") and clave.search(orden):
                    r = valor
                    break
        if r is None:
            return 127, "", "sh: orden no programada en el NAS simulado: %s" % orden
        if callable(r):
            r = r(orden, sudo)
        if r is CUELGA:
            return CUELGA
        if isinstance(r, (str, bytes)):
            return 0, r, ""
        return r


class ClienteFalso:
    def __init__(self, mundo):
        self.mundo = mundo
        self.politica = None
        self.hosts_cargados = None
        self.argumentos = None
        self.conectado = False
        self.cerrado = False

    def load_host_keys(self, ruta):
        self.hosts_cargados = ruta
        self.hosts = paramiko.HostKeys(ruta)

    def set_missing_host_key_policy(self, politica):
        self.politica = politica

    def connect(self, hostname, port=22, username=None, password=None, pkey=None, **resto):
        m = self.mundo
        self.argumentos = dict(hostname=hostname, port=port, username=username, **resto)
        if m.error_conexion is not None:
            raise m.error_conexion
        if m.host_cambiado:
            raise paramiko.BadHostKeyException(hostname, ClaveFalsa("AAAAnueva"), ClaveFalsa("AAAAfijada"))
        if not m.host_fijado:
            if isinstance(self.politica, paramiko.AutoAddPolicy):
                m.host_fijado = True
                m.fijaciones += 1
                if self.hosts_cargados:
                    # como AutoAddPolicy: la clave queda guardada ANTES de autenticar, y se
                    # guarda la copia cargada al principio, no lo que haya ahora en el fichero
                    time.sleep(m.retardo_fijar)
                    nombre = hostname if port == 22 else "[%s]:%d" % (hostname, port)
                    self.hosts.add(nombre, clave_de_host().get_name(), clave_de_host())
                    self.hosts.save(self.hosts_cargados)
            else:
                self.politica.missing_host_key(self, hostname, ClaveFalsa("AAAAnueva"))
        metodo = "clave" if pkey is not None else "contrasena"
        m.intentos.append((metodo, username))
        if pkey is not None:
            aceptado = m.acepta_clave
        else:
            aceptado = m.acepta_contrasena and password == m.contrasena
        if not aceptado:
            raise paramiko.AuthenticationException("Authentication failed.")
        self.conectado = True
        m.conexiones += 1

    def exec_command(self, orden, timeout=None):
        if not self.conectado or self.cerrado or self.mundo.caida:
            raise paramiko.SSHException("SSH session not active")
        canal = CanalFalso(self.mundo, orden)
        return FlujoFalso(canal), FlujoFalso(canal), FlujoFalso(canal)

    def close(self):
        self.cerrado = True
        self.conectado = False

    def get_transport(self):
        return self

    def set_keepalive(self, segundos):
        self.mundo.keepalives.append(segundos)

    def get_remote_server_key(self):
        return ClaveFalsa("AAAAfijada")


class FlujoFalso:
    def __init__(self, canal):
        self.channel = canal

    def write(self, texto):
        self.channel.escrito += texto

    def flush(self):
        pass


class CanalFalso:
    def __init__(self, mundo, enviado):
        self.mundo = mundo
        mundo.enviado.append(enviado)
        if enviado.startswith(PREFIJO_SUDO):
            self.sudo = True
            self.orden = shlex.split(enviado[len(PREFIJO_SUDO):])[0]
        else:
            self.sudo = False
            self.orden = enviado
        mundo.ordenes.append((self.orden, self.sudo))
        self.escrito = ""
        self.stdin_cerrado = False
        self.cerrado = False
        self._listo = False

    def _preparar(self):
        # La respuesta se decide al empezar a leer: depende de lo escrito en stdin
        if self._listo:
            return
        self._listo = True
        m = self.mundo
        m.stdin.append(self.escrito)
        self._cuelga = False
        if self.sudo and self.escrito != m.contrasena + "\n":
            rc, out, err = 1, "", "Sorry, try again.\nsudo: 1 incorrect password attempt\n"
        else:
            r = m.responder(self.orden, self.sudo)
            if r is CUELGA:
                self._cuelga = True
                rc, out, err = -1, m.parcial, ""
            else:
                rc, out, err = r
            if self.sudo and m.sudo_con_sermon:
                err = SERMON + (err.decode("utf-8") if isinstance(err, bytes) else err)
        self.rc = rc
        self._out = out if isinstance(out, bytes) else out.encode("utf-8")
        self._err = err if isinstance(err, bytes) else err.encode("utf-8")
        self._tarde = b""
        if m.salida_tardia and not self._cuelga:
            mitad = len(self._out) // 2
            self._out, self._tarde = self._out[:mitad], self._out[mitad:]

    def recv_ready(self):
        self._preparar()
        return bool(self._out)

    def recv(self, n):
        trozo, self._out = self._out[:n], self._out[n:]
        return trozo

    def recv_stderr_ready(self):
        self._preparar()
        return bool(self._err)

    def recv_stderr(self, n):
        trozo, self._err = self._err[:n], self._err[n:]
        return trozo

    def exit_status_ready(self):
        self._preparar()
        if self._cuelga:
            return False
        # lo que faltaba de la salida llega una vez que la orden ya ha dado su codigo
        self._out += self._tarde
        self._tarde = b""
        return True

    @property
    def eof_received(self):
        self._preparar()
        return not (self._cuelga or self._tarde or self.mundo.sin_fin_de_salida)

    @property
    def closed(self):
        return self.cerrado

    def recv_exit_status(self):
        return self.rc

    def shutdown_write(self):
        self.stdin_cerrado = True

    def close(self):
        self.cerrado = True
