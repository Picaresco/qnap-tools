# -*- coding: utf-8 -*-
"""Transporte SSH hacia un NAS: autenticacion mixta, sudo por stdin y clave de host fijada.

- Autenticacion: segun el inventario, clave del ordenador y/o contrasena comun.
- sudo: el NAS siempre pide contrasena; se envuelve la orden en `sudo -S -p '' sh -c ...`
  y la contrasena viaja por stdin, nunca en el texto de la orden.
- Clave de host: se fija en el alta (fijar_host=True) en un known_hosts propio. Despues,
  un host sin fijar o con la clave cambiada se rechaza.
"""
import re
import shlex
import threading
import time
from dataclasses import dataclass

import paramiko

ORDEN_AUTH = {"auto": ("clave", "contrasena"), "clave": ("clave",), "contrasena": ("contrasena",)}
SERMON_SUDO = re.compile(r"(?s)\s*We trust you have received the usual lecture.*?great responsibility\.\s*")
SUDO_RECHAZA = re.compile(r"incorrect password attempt|Sorry, try again|no password was provided")
TROZO = 65536
LATIDO = 30        # segundos entre latidos SSH: una conexion muerta se descubre sin esperar al TCP
GRACIA_FIN = 2.0   # espera maxima del fin de la salida una vez que la orden ha terminado
_FIJANDO = threading.Lock()     # una sola conexion a la vez puede escribir en known_hosts


class ErrorConexion(Exception):
    pass


class HostCambiado(ErrorConexion):
    pass


class HostSinFijar(ErrorConexion):
    pass


class AutenticacionFallida(ErrorConexion):
    pass


@dataclass(frozen=True)
class Resultado:
    rc: int
    salida: str
    error: str
    agotado: bool = False


def nombre_host(nas):
    """Como nombra paramiko a este NAS en known_hosts."""
    return nas.host if nas.port == 22 else "[%s]:%d" % (nas.host, nas.port)


def host_fijado(cfg, nas) -> bool:
    """Si la clave de host de este NAS ya esta guardada en known_hosts."""
    if not cfg.known_hosts.exists():
        return False
    return paramiko.HostKeys(str(cfg.known_hosts)).lookup(nombre_host(nas)) is not None


def olvidar_host(cfg, nas) -> bool:
    """Quita de known_hosts la clave fijada de un NAS (para poder darlo de alta de nuevo)."""
    if not cfg.known_hosts.exists():
        return False
    hosts = paramiko.HostKeys(str(cfg.known_hosts))
    nombre = nombre_host(nas)
    borrado = False
    while hosts.lookup(nombre) is not None:
        del hosts[nombre]
        borrado = True
    if borrado:
        hosts.save(str(cfg.known_hosts))
    return borrado


class _SinFijar(Exception):
    pass


class _Rechazar(paramiko.MissingHostKeyPolicy):
    """Fuera del alta, un host cuya clave no esta fijada no se acepta."""

    def missing_host_key(self, client, hostname, key):
        raise _SinFijar()


class Conexion:
    def __init__(self, nas, cfg, fabrica=paramiko.SSHClient):
        self.nas = nas
        self.cfg = cfg
        self._fabrica = fabrica
        self._cli = None
        self.metodo = None

    @property
    def usuario(self):
        return self.nas.user or self.cfg.usuario

    @property
    def destino(self):
        return self.nas.destino

    def _limpio(self, texto):
        texto = str(texto) or texto.__class__.__name__
        if self.cfg.contrasena:
            texto = texto.replace(self.cfg.contrasena, "***")
        return texto

    def _cliente(self, fijar_host):
        cli = self._fabrica()
        hosts = self.cfg.known_hosts
        if fijar_host:
            hosts.parent.mkdir(parents=True, exist_ok=True)
            hosts.touch(exist_ok=True)
        if hosts.exists():
            # con el fichero cargado, paramiko rechaza un host conocido con otra clave
            cli.load_host_keys(str(hosts))
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy() if fijar_host else _Rechazar())
        return cli

    def _metodos(self):
        """Metodos a intentar, y la clave cargada si alguno la usa."""
        metodos = list(ORDEN_AUTH[self.nas.auth])
        if "clave" not in metodos:
            return metodos, None
        motivo = None
        clave = None
        if not self.cfg.clave.exists():
            motivo = "no existe la clave SSH de este ordenador (%s)" % self.cfg.clave
        else:
            try:
                clave = paramiko.PKey.from_path(str(self.cfg.clave))
            except Exception as e:
                motivo = "la clave SSH %s no se puede leer (%s)" % (self.cfg.clave, e.__class__.__name__)
        if motivo:
            if self.nas.auth == "clave":
                raise ErrorConexion("%s: %s; ejecuta nas_enrolar" % (self.destino, motivo))
            metodos.remove("clave")
        return metodos, clave

    def conectar(self, fijar_host=False):
        if fijar_host:
            # al aceptar un host nuevo, paramiko guarda known_hosts entero desde la copia que
            # cargo al empezar: dos conexiones que fijan host a la vez perderian una huella
            with _FIJANDO:
                return self._conectar(fijar_host)
        return self._conectar(fijar_host)

    def _conectar(self, fijar_host):
        self.cerrar()
        metodos, clave = self._metodos()
        for metodo in metodos:
            cli = self._cliente(fijar_host)
            credencial = {"pkey": clave} if metodo == "clave" else {"password": self.cfg.contrasena}
            try:
                cli.connect(hostname=self.nas.host, port=self.nas.port, username=self.usuario,
                            timeout=15, banner_timeout=30, auth_timeout=30,
                            allow_agent=False, look_for_keys=False, **credencial)
            except paramiko.BadHostKeyException:
                cli.close()
                raise HostCambiado(
                    "%s: la clave de host SSH no es la que se fijo en el alta; no se conecta ni se "
                    "envia la credencial. Si el NAS se ha reinstalado, dalo de baja (nas_baja) y "
                    "de alta de nuevo (nas_alta)" % self.destino) from None
            except _SinFijar:
                cli.close()
                raise HostSinFijar(
                    "%s: su clave de host SSH no esta fijada en este ordenador. Si el NAS ya "
                    "esta en el inventario (ordenador nuevo o inventario importado), ejecuta "
                    "nas_enrolar; si es un NAS nuevo, dalo de alta con nas_alta"
                    % self.destino) from None
            except paramiko.AuthenticationException:
                cli.close()
                continue
            except (paramiko.SSHException, OSError, EOFError) as e:
                cli.close()
                raise ErrorConexion(
                    "%s: no se pudo conectar: %s" % (self.destino, self._limpio(e))) from None
            cli.get_transport().set_keepalive(LATIDO)
            self._cli = cli
            self.metodo = metodo
            return metodo
        raise AutenticacionFallida(
            "%s: el NAS rechazo al usuario %s (probado: %s). Comprueba que pertenece a "
            "administrators, que tiene permiso de SSH y la contrasena configurada en el plugin"
            % (self.destino, self.usuario, ", ".join(metodos)))

    def huella_host(self):
        """Tipo y huella SHA256 de la clave de host del NAS, para cotejarla con la del equipo."""
        if self._cli is None:
            return None
        try:
            clave = self._cli.get_transport().get_remote_server_key()
            return "%s %s" % (clave.get_name(), clave.fingerprint)
        except Exception:
            return None

    def ejecutar(self, orden, sudo=False, timeout=20):
        if self._cli is None:
            raise ErrorConexion("%s: sin conexion abierta" % self.destino)
        texto = "sudo -S -p '' sh -c " + shlex.quote(orden) if sudo else orden
        try:
            stdin, stdout, _ = self._cli.exec_command(texto, timeout=timeout)
            canal = stdout.channel
            if sudo:
                stdin.write(self.cfg.contrasena + "\n")
                stdin.flush()
            # stdin cerrado: una orden que lea de la entrada recibe fin de fichero
            canal.shutdown_write()
        except (paramiko.SSHException, OSError, EOFError) as e:
            raise ErrorConexion(
                "%s: se perdio la conexion: %s" % (self.destino, self._limpio(e))) from None

        # Lectura por sondeo de salida y error a la vez, con un plazo total: leer una
        # entera y luego la otra puede bloquearse, y el timeout de paramiko es por lectura.
        # El codigo de salida puede llegar antes que el final de la salida: que la orden
        # haya terminado no basta para dejar de leer, hace falta el fin de fichero. Se le
        # da un margen por si un proceso hijo retiene la salida abierta.
        fin = time.monotonic() + timeout
        fin_gracia = None
        salida, error = bytearray(), bytearray()
        agotado = False
        try:
            while True:
                # se miran ANTES de leer: si ya eran ciertos y no queda nada, esta todo leido
                terminada = canal.exit_status_ready()
                sin_mas_salida = canal.eof_received or canal.closed
                leido = False
                while canal.recv_ready():
                    salida += canal.recv(TROZO)
                    leido = True
                while canal.recv_stderr_ready():
                    error += canal.recv_stderr(TROZO)
                    leido = True
                if leido:
                    continue
                ahora = time.monotonic()
                if terminada:
                    if sin_mas_salida:
                        break
                    if fin_gracia is None:
                        fin_gracia = ahora + GRACIA_FIN
                    if ahora >= fin_gracia:
                        break
                elif ahora >= fin:
                    agotado = True
                    break
                time.sleep(0.01)
            rc = -1 if agotado else canal.recv_exit_status()
        except (paramiko.SSHException, OSError, EOFError) as e:
            raise ErrorConexion(
                "%s: se perdio la conexion: %s" % (self.destino, self._limpio(e))) from None
        if agotado:
            canal.close()
        texto_salida = salida.decode("utf-8", "replace")
        texto_error = error.decode("utf-8", "replace")
        if sudo:
            texto_error = SERMON_SUDO.sub("", texto_error, count=1)
            if rc != 0 and not agotado and SUDO_RECHAZA.search(texto_error):
                raise AutenticacionFallida(
                    "%s: sudo no acepto la contrasena del usuario %s" % (self.destino, self.usuario))
        return Resultado(rc, texto_salida, texto_error, agotado)

    def cerrar(self):
        if self._cli is not None:
            try:
                self._cli.close()
            finally:
                self._cli = None
                self.metodo = None
