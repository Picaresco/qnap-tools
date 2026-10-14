# -*- coding: utf-8 -*-
"""Guardia de solo lectura: decide si un comando de shell puede ejecutarse en el NAS.

Un comando se parte en segmentos (por | ; && || y parentesis) y la primera palabra de
cada segmento debe tener una regla en pruebas/reglas/*.json que acepte sus argumentos.
Lo que no tiene regla se rechaza. Campos de una regla:
  cmd               nombre del ejecutable (sin ruta)
  sub               el primer argumento posicional debe ser uno de estos
  flags_con_valor   opciones cuyo valor no cuenta como posicional (p.ej. -c URI)
  solo_flags        las unicas opciones (argumentos que empiezan por -) admitidas
  deny              expresiones regulares; si un argumento casa, se rechaza
  requiere          argumentos que deben estar presentes
  max_posicionales  maximo de argumentos que no son opciones
  nota              evidencia de que es solo lectura
"""
import glob
import json
import os
import posixpath
import re
import shlex

AQUI = os.path.dirname(os.path.abspath(__file__))

REDIR_INOCUA = re.compile(r"2>&1|2>\s*/dev/null|(?<![0-9>&])>\s*/dev/null")
PUNTUACION = set("();<>|&")
SEPARADORES = {"|", "||", "&&", ";", "(", ")"}
PALABRAS_PREVIAS = {"do", "then", "else", "elif", "if", "while", "!", "done", "fi"}
ASIGNACION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
AYUDA = (["--help"],)
SECRETOS = re.compile(
    r"/etc/shadow|smbpasswd|ssh_host_.*key$|\.pem$|id_(rsa|dsa|ecdsa|ed25519)$|authorized_keys"
    r"|/qvpn/|ipsec\.(conf|secrets)|wg[0-9]*\.conf|privatekey|\.key$|openvpn"
)
CON_AYUDA = re.compile(r"^(virsh|docker|system-docker|qcli(_\w+)?|\w*log_tool|zpool|zfs|ethtool|nvme|mdadm|brctl)$")
OPERADOR = re.compile(r"\|\||&&|[|;()]")


def _sustitucion_entre_comillas(cmd):
    """True si hay $( dentro de comillas dobles: shlex lo dejaria pasar como texto."""
    simple = doble = False
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if simple:
            simple = c != "'"
        elif c == "\\":
            i += 1
        elif c == "'" and not doble:
            simple = True
        elif c == '"':
            doble = not doble
        elif doble and cmd.startswith("$(", i):
            return True
        i += 1
    return False


class Bloqueado(Exception):
    pass


def cargar_reglas():
    reglas = {}
    for ruta in sorted(glob.glob(os.path.join(AQUI, "reglas", "*.json"))):
        with open(ruta, encoding="utf-8") as f:
            for regla in json.load(f):
                reglas.setdefault(regla["cmd"], []).append(regla)
    return reglas


def _posicionales(regla, args):
    con_valor = set(regla.get("flags_con_valor", []))
    pos = []
    saltar = False
    for a in args:
        if saltar:
            saltar = False
        elif a in con_valor:
            saltar = True
        elif not a.startswith("-"):
            pos.append(a)
    return pos


def _fallo(regla, args):
    for a in args:
        for patron in regla.get("deny", []):
            if re.search(patron, a):
                return "argumento vetado: %s" % a
    if "solo_flags" in regla:
        for a in args:
            if a.startswith("-") and a not in regla["solo_flags"] and a not in regla.get("flags_con_valor", []):
                return "opcion no admitida: %s" % a
    for a in regla.get("requiere", []):
        if a not in args:
            return "falta el argumento obligatorio %s" % a
    pos = _posicionales(regla, args)
    if "sub" in regla and (not pos or pos[0] not in regla["sub"]):
        return "subcomando no admitido: %s" % (pos[0] if pos else "(ninguno)")
    if "max_posicionales" in regla and len(pos) > regla["max_posicionales"]:
        return "demasiados argumentos posicionales"
    return None


def comprobar(cmd, reglas=None):
    """Lanza Bloqueado si el comando no esta cubierto por las reglas."""
    if reglas is None:
        reglas = cargar_reglas()
    if "`" in cmd or "\n" in cmd or "\r" in cmd:
        raise Bloqueado("comillas invertidas o saltos de linea no admitidos")
    if _sustitucion_entre_comillas(cmd):
        raise Bloqueado("sustitucion $( ) dentro de comillas dobles no admitida")
    lex = shlex.shlex(REDIR_INOCUA.sub(" ", cmd), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    # sin comentarios: por defecto shlex descarta todo lo que sigue a un "#", y eso dejaria
    # sin analizar el resto de la orden (p.ej. tras un ${f##*/})
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError as e:
        raise Bloqueado("no se puede analizar: %s" % e)
    segmentos = [[]]
    for t in tokens:
        if t and set(t) <= PUNTUACION:
            # varios operadores pegados (p.ej. ");") cuentan como separadores sueltos
            if "".join(OPERADOR.findall(t)) != t:
                raise Bloqueado("operador no admitido: %s" % t)
            segmentos.append([])
        elif t != "$":
            segmentos[-1].append(t)
    for seg in segmentos:
        while seg and (seg[0] in PALABRAS_PREVIAS or ASIGNACION.match(seg[0])):
            seg = seg[1:]
        if not seg:
            continue
        if seg[0] == "for":
            if len(seg) < 3 or seg[2] != "in":
                raise Bloqueado("bucle for no admitido")
            continue
        for t in seg:
            if SECRETOS.search(t):
                raise Bloqueado("ruta con secretos: %s" % t)
        if seg[0].startswith("$") or "init.d" in seg[0] or seg[0].endswith(".sh"):
            raise Bloqueado("ejecutable no admitido: %s" % seg[0])
        nombre = posixpath.basename(seg[0])
        args = seg[1:]
        # uLinux.conf tiene secciones con claves: solo campo a campo con getcfg
        # (o con grep de una palabra concreta que no sea de credenciales, sin -v)
        if nombre != "getcfg" and any("uLinux.conf" in t for t in args):
            pos = [a for a in args if not a.startswith("-")]
            invertido = any(a.startswith("-") and not a.startswith("--") and "v" in a for a in args)
            if not (nombre == "grep" and pos and not invertido
                    and len(re.sub(r"[^A-Za-z]", "", pos[0])) >= 5
                    and not re.search(r"pass|key|pw|secret|commun|token|auth", pos[0], re.I)):
                raise Bloqueado("uLinux.conf solo se lee con getcfg")
        # --help solo en binarios que se sabe que lo atienden: un script que lo ignora
        # ejecuta su accion normal (md_checker dejo /tmp/disks, 2026-10-13)
        if args in [list(a) for a in AYUDA] and CON_AYUDA.match(nombre):
            continue
        if nombre not in reglas:
            raise Bloqueado("comando sin regla: %s" % nombre)
        fallos = [_fallo(r, args) for r in reglas[nombre]]
        if all(fallos):
            raise Bloqueado("%s: %s" % (nombre, fallos[0]))
