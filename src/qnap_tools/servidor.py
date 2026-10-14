# -*- coding: utf-8 -*-
"""Lo comun a todos los servidores MCP del paquete.

Contexto carga la configuracion la primera vez que una herramienta la necesita: asi el
servidor arranca aunque falte la credencial y es la propia herramienta la que lo dice en el
chat, en vez de aparecer como un servidor caido.
"""
import os

from mcp.server.fastmcp import FastMCP

from . import config
from .comandos import ParametroInvalido
from .ejecutor import ErrorComando, Flota
from .transporte import AutenticacionFallida, Conexion


class Contexto:
    def __init__(self, entorno=None, fabrica_conexion=Conexion):
        self._entorno = entorno
        self._fabrica = fabrica_conexion
        self._flota = None

    @property
    def flota(self) -> Flota:
        """La flota de este proceso. Lanza ConfigError si falta la credencial."""
        if self._flota is None:
            cfg = config.cargar(os.environ if self._entorno is None else self._entorno)
            self._flota = Flota(cfg, fabrica_conexion=self._fabrica)
        return self._flota

    @property
    def cfg(self):
        return self.flota.cfg

    def conexion(self, nas):
        """Conexion suelta, fuera de las que la flota reutiliza (alta y enrolado)."""
        return self._fabrica(nas, self.cfg)

    def por_nas(self, nombre, funcion):
        try:
            flota = self.flota
        except config.ConfigError as e:
            return [{"nas": nombre, "ok": False, "error": str(e)}]
        return flota.por_nas(nombre, funcion)

    def sanear(self, texto):
        """Quita la contrasena de un texto que va a salir del servidor."""
        if self._flota is not None and self._flota.cfg.contrasena:
            texto = texto.replace(self._flota.cfg.contrasena, "***")
        return texto


class Base:
    """Lo comun a las herramientas de cada pata: lanzar una orden y leerla con su parser."""

    def __init__(self, ctx):
        self.ctx = ctx

    def _leer(self, nas, comando, parser, valores=None):
        """Lanza un Comando y devuelve su salida ya interpretada."""
        salida = self.ctx.flota.lanzar(nas, comando, valores)
        try:
            return parser(salida)
        except ValueError as e:
            raise ErrorComando("%s: la consulta %s dio una salida inesperada: %s"
                               % (nas.nombre, comando.id, e))

    def _opcional(self, nas, comando, parser, valores=None):
        """Como _leer, para un dato accesorio: si la orden falla, sudo no acepta la
        contrasena o el parametro no es valido, el error va en su sitio y no se pierde el
        resto de la respuesta. Perder la conexion si tumba la respuesta entera."""
        try:
            return self._leer(nas, comando, parser, valores)
        except (ErrorComando, ParametroInvalido, AutenticacionFallida) as e:
            return {"error": self.ctx.sanear(str(e))}

    def _extra(self, nas, errores, clave, comando, parser, valores=None):
        """Dato accesorio: si no se puede leer, el error queda apuntado y devuelve None."""
        datos = self._opcional(nas, comando, parser, valores)
        if isinstance(datos, dict) and set(datos) == {"error"}:
            errores[clave] = datos["error"]
            return None
        return datos

    def _no_probado(self, nas, comando, parser):
        """Bloque de una funcion sin validar con datos reales."""
        datos = self._opcional(nas, comando, parser)
        if isinstance(datos, list):
            datos = {"filas": datos}
        return dict({"no_probado": True}, **datos)


def crear(nombre, instrucciones, entorno=None, fabrica_conexion=Conexion):
    """Servidor MCP vacio y su contexto; cada pata registra despues sus herramientas."""
    return FastMCP(nombre, instructions=instrucciones), Contexto(entorno, fabrica_conexion)
