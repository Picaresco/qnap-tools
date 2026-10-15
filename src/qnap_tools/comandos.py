# -*- coding: utf-8 -*-
"""Comandos de plantilla fija: lo unico que se ejecuta en un NAS.

Cada orden que lanza una herramienta es un Comando definido en el codigo. No hay comando
libre. Los parametros que entran en una plantilla se validan contra un tipo estricto y se
entrecomillan; una plantilla que escribe en un fichero o lleva sudo no se puede ni definir
(el sudo lo anade el transporte en los comandos marcados).
"""
import re
import shlex
from dataclasses import dataclass, field
from typing import Callable, Mapping

# Tipos de parametro. Se comparan con fullmatch (un $ dejaria pasar un salto de linea final)
# y ninguno admite empezar por "-", para que un valor no pueda colarse como opcion.
TIPOS = {
    "interfaz": re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:-]{0,31}"),
    "destino": re.compile(r"[A-Za-z0-9]([A-Za-z0-9.:-]{0,251}[A-Za-z0-9])?"),
    "entero": re.compile(r"[0-9]{1,6}"),
    "bahia": re.compile(r"[0-9]{1,3}"),
    "uuid": re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    "nombre": re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"),
    "fecha": re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}"),
    # texto que se busca en un registro: letras (tambien con acento), cifras, espacio y
    # _ . : @ / -; nada que cierre una comilla, encadene una orden o haga de comodin
    "palabra": re.compile(r"\w[\w .:@/-]{0,38}[\w.:@/-]"),
    "nivel": re.compile(r"[0-7]"),               # nivel de un mensaje del kernel
    # identificador de proceso: de 1 a 4194304 (pid_max), sin ceros a la izquierda
    "pid": re.compile(r"[1-9][0-9]{0,5}|[1-3][0-9]{6}|40[0-9]{5}|41[0-8][0-9]{4}|419[0-3][0-9]{3}"
                      r"|4194[0-2][0-9]{2}|419430[0-4]"),
    # ruta absoluta de un fichero o carpeta: hasta 512 caracteres, sin segmentos "." ni ".." y sin
    # caracteres de control; el resto (espacios, comillas, $) lo entrecomilla render
    "ruta": re.compile(r"(?=.{1,512}\Z)(?!.*/\.{1,2}(?:/|\Z))/[^\x00-\x1f\x7f]*"),
}
# Como se nombra un tipo en el mensaje de un valor no valido, cuando el nombre solo no basta
DESCRIPCION = {"palabra": "palabra o frase de 2 a 40 caracteres",
               "ruta": "ruta absoluta de hasta 512 caracteres, sin segmentos . ni .."}
SISTEMAS = ("ambos", "hero", "qts")

MARCADOR = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
REDIRECCION_INOCUA = re.compile(r"2>&1|2>\s*/dev/null|(?<![0-9&>])>\s*/dev/null")
SUDO = re.compile(r"\bsudo\b")


class ParametroInvalido(ValueError):
    pass


# --- validadores de salida: None si vale, o el texto del error -------------------

def rc_cero(rc: int, salida: str):
    if rc != 0:
        return "el comando termino con codigo %d" % rc
    return None


def no_vacia(rc: int, salida: str):
    if not salida.strip():
        return "el comando no devolvio nada"
    return None


def todas(*validadores):
    def valida(rc, salida):
        for v in validadores:
            error = v(rc, salida)
            if error:
                return error
        return None
    return valida


estricta = todas(rc_cero, no_vacia)


@dataclass(frozen=True)
class Comando:
    id: str
    plantilla: str
    params: Mapping[str, str] = field(default_factory=dict)
    sudo: bool = False
    timeout: int = 20
    sistema: str = "ambos"
    # Por defecto, codigo 0 y salida no vacia. valida=None lo desactiva de forma explicita.
    valida: Callable[[int, str], str | None] | None = estricta
    no_probado: bool = False

    def __post_init__(self):
        if not self.id:
            raise ValueError("comando sin identificador")
        p = self.plantilla
        if "\n" in p or "\r" in p or "`" in p:
            raise ValueError("comando %s: saltos de linea y comillas invertidas no admitidos" % self.id)
        if SUDO.search(p):
            raise ValueError("comando %s: la plantilla no lleva sudo; se marca con sudo=True" % self.id)
        if ">" in REDIRECCION_INOCUA.sub(" ", p):
            raise ValueError("comando %s: la plantilla redirige a un fichero" % self.id)
        usados = set(MARCADOR.findall(p))
        declarados = set(self.params)
        if usados - declarados:
            raise ValueError("comando %s: marcador sin declarar: %s"
                             % (self.id, ", ".join(sorted(usados - declarados))))
        if declarados - usados:
            raise ValueError("comando %s: parametro declarado que no se usa: %s"
                             % (self.id, ", ".join(sorted(declarados - usados))))
        for nombre, tipo in self.params.items():
            if tipo not in TIPOS:
                raise ValueError("comando %s: tipo de parametro desconocido: %s" % (self.id, tipo))
        if self.sistema not in SISTEMAS:
            raise ValueError("comando %s: sistema desconocido: %s" % (self.id, self.sistema))
        if type(self.timeout) is not int or self.timeout <= 0:
            raise ValueError("comando %s: timeout no valido: %r" % (self.id, self.timeout))

    def render(self, valores: Mapping[str, object] | None = None) -> str:
        valores = dict(valores or {})
        faltan = sorted(set(self.params) - set(valores))
        if faltan:
            raise ParametroInvalido("falta el parametro %s" % ", ".join(faltan))
        sobran = sorted(set(valores) - set(self.params))
        if sobran:
            raise ParametroInvalido("parametro no admitido: %s" % ", ".join(sobran))
        listos = {}
        for nombre, tipo in self.params.items():
            valor = valores[nombre]
            if type(valor) is int:
                valor = str(valor)
            if not isinstance(valor, str) or not TIPOS[tipo].fullmatch(valor):
                raise ParametroInvalido(
                    "parametro %s no valido (se esperaba %s): %s"
                    % (nombre, DESCRIPCION.get(tipo, tipo), repr(valor)[:60]))
            listos[nombre] = shlex.quote(valor)
        return MARCADOR.sub(lambda m: listos[m.group(1)], self.plantilla)
