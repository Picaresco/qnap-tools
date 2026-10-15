# -*- coding: utf-8 -*-
"""Ejecucion de comandos sobre uno o todos los NAS del inventario.

Flota mantiene una conexion por NAS (reutilizada, y reabierta una vez si se cae), serializa
las ordenes contra un mismo NAS y reparte entre NAS en paralelo. Un fallo nunca se devuelve
como dato vacio: lanzar() levanta ErrorComando y por_nas() lo convierte en la entrada de
error de ese NAS, sin tapar a los demas.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from . import inventario
from .comandos import ParametroInvalido
from .deteccion import DeteccionFallida, detectar
from .transporte import AutenticacionFallida, Conexion, ErrorConexion

MAX_PARALELO = 4


class ErrorComando(Exception):
    pass


def recortar(filas, maximo=200):
    """Acota una lista larga y dice si se ha cortado."""
    return {"filas": filas[:maximo], "total": len(filas), "truncado": len(filas) > maximo}


def _comprobar(nombre, comando, r):
    """Salida de un comando ya ejecutado, o ErrorComando si no es de fiar."""
    if r.agotado:
        raise ErrorComando(
            "%s: la consulta %s no termino en %d s (tiempo maximo)"
            % (nombre, comando.id, comando.timeout))
    if r.rc == -1:
        # defensa: el transporte ya lo rechaza, y ningun validador (valida=None incluido)
        # puede dar por buena una salida de una orden que no llego a terminar
        raise ErrorComando("%s: la consulta %s termino sin codigo de salida (orden interrumpida)"
                           % (nombre, comando.id))
    if comando.valida is not None:
        error = comando.valida(r.rc, r.salida)
        if error:
            detalle = r.error.strip().splitlines()
            raise ErrorComando("%s: la consulta %s fallo: %s%s" % (
                nombre, comando.id, error, (" (%s)" % detalle[-1][:200]) if detalle else ""))
    return r.salida


def lanzar_en(con, comando, valores=None):
    """Ejecuta un Comando en una conexion suelta (alta, enrolado), con la misma validacion."""
    r = con.ejecutar(comando.render(valores), sudo=comando.sudo, timeout=comando.timeout)
    return _comprobar(con.nas.nombre, comando, r)


class _Via:
    """Lo que detectar() necesita de una conexion, pasando por el reintento de la flota."""

    def __init__(self, flota, nas):
        self._flota = flota
        self._nas = nas
        self.destino = nas.destino

    def ejecutar(self, orden, sudo=False, timeout=20):
        return self._flota._ejecutar(self._nas, orden, sudo, timeout)


class Flota:
    def __init__(self, cfg, fabrica_conexion=Conexion):
        self.cfg = cfg
        self._fabrica = fabrica_conexion
        self._conexiones = {}
        self._perfiles = {}
        self._candados = {}
        self._guardia = threading.Lock()

    def inventario(self):
        # Se relee en cada consulta: el alta la hace otro proceso (qnap-flota)
        return inventario.cargar(self.cfg.inventario)

    def _candado(self, nombre):
        with self._guardia:
            return self._candados.setdefault(nombre, threading.RLock())

    def _soltar(self, nombre):
        con = self._conexiones.pop(nombre, None)
        if con is not None:
            con.cerrar()

    def _conexion(self, nas):
        """Conexion abierta con este NAS. Se llama con su candado tomado."""
        con = self._conexiones.get(nas.nombre)
        if con is not None and con.nas != nas:
            # la entrada del inventario ha cambiado: la conexion no vale (ni el perfil)
            self._soltar(nas.nombre)
            con = None
        if con is None:
            # una deteccion por conexion: tras reconectar, el firmware o los paquetes pueden
            # haber cambiado
            self._perfiles.pop(nas.nombre, None)
            con = self._fabrica(nas, self.cfg)
            con.conectar()
            self._conexiones[nas.nombre] = con
        return con

    def _ejecutar(self, nas, orden, sudo, timeout):
        con = self._conexion(nas)
        try:
            r = con.ejecutar(orden, sudo=sudo, timeout=timeout)
        except AutenticacionFallida:
            raise            # sudo rechazo la contrasena: reintentar solo sumaria fallos
        except ErrorConexion:
            # la conexion reutilizada se habia caido: se reabre una vez
            self._soltar(nas.nombre)
            r = self._conexion(nas).ejecutar(orden, sudo=sudo, timeout=timeout)
        if r.agotado:
            # no se sabe como queda una sesion con una orden a medias (ni si la conexion sigue
            # viva): la siguiente consulta abre una nueva en vez de volver a esperar sobre esta
            self._soltar(nas.nombre)
        return r

    def perfil(self, nas, refrescar=False):
        """Sistema, modelo y paquetes activos del NAS. Se detecta una vez por conexion;
        con refrescar=True se vuelve a preguntar (un paquete se puede activar despues)."""
        with self._candado(nas.nombre):
            self._conexion(nas)
            perfil = self._perfiles.get(nas.nombre)
            if perfil is None or refrescar:
                perfil = detectar(_Via(self, nas))
                self._perfiles[nas.nombre] = perfil
            return perfil

    def lanzar(self, nas, comando, valores=None):
        """Ejecuta un Comando en un NAS y devuelve su salida, ya validada."""
        orden = comando.render(valores)     # un parametro invalido no llega ni a conectar
        with self._candado(nas.nombre):
            if comando.sistema != "ambos":
                sistema = self.perfil(nas).sistema
                if sistema != comando.sistema:
                    raise ErrorComando(
                        "%s: la consulta %s solo existe en %s y este NAS es %s"
                        % (nas.nombre, comando.id, comando.sistema, sistema))
            r = self._ejecutar(nas, orden, comando.sudo, comando.timeout)
        return _comprobar(nas.nombre, comando, r)

    def metodo(self, nas):
        """Con que ha entrado la conexion de este NAS: 'clave' o 'contrasena'."""
        with self._candado(nas.nombre):
            return self._conexion(nas).metodo

    def olvidar(self, nombre):
        """Cierra la conexion y descarta el perfil de un NAS (baja del inventario)."""
        with self._candado(nombre):
            self._soltar(nombre)
            self._perfiles.pop(nombre, None)

    def _sanear(self, texto):
        if self.cfg.contrasena:
            texto = texto.replace(self.cfg.contrasena, "***")
        return texto

    def _sin_contrasena(self, dato):
        """La contrasena fuera de todo texto de una respuesta, tambien de los datos: un registro
        del NAS puede traer lo que alguien tecleo en el campo de usuario de la web."""
        if isinstance(dato, str):
            return self._sanear(dato)
        if isinstance(dato, dict):
            return {self._sin_contrasena(k): self._sin_contrasena(v) for k, v in dato.items()}
        if isinstance(dato, (list, tuple)):
            return type(dato)(self._sin_contrasena(x) for x in dato)
        return dato

    def por_nas(self, nombre, funcion):
        """Aplica funcion(nas) a un NAS o a todos y devuelve una entrada por NAS."""
        try:
            lista = inventario.resolver(self.inventario(), nombre)
        except (inventario.NasDesconocido, inventario.InventarioInvalido) as e:
            return [{"nas": nombre, "ok": False, "error": self._sanear(str(e))}]

        def uno(nas):
            try:
                return {"nas": nas.nombre, "ok": True, "datos": self._sin_contrasena(funcion(nas))}
            except (ErrorConexion, ErrorComando, ParametroInvalido, DeteccionFallida) as e:
                error = str(e)
            except Exception as e:
                error = "%s: %s" % (e.__class__.__name__, e)
            return {"nas": nas.nombre, "ok": False, "error": self._sanear(error)}

        if len(lista) == 1:
            return [uno(lista[0])]
        with ThreadPoolExecutor(max_workers=min(MAX_PARALELO, len(lista))) as ex:
            return list(ex.map(uno, lista))

    def cerrar(self):
        for nombre in list(self._conexiones):
            with self._candado(nombre):
                self._soltar(nombre)
