# -*- coding: utf-8 -*-
"""Arnes de pruebas de solo lectura contra los NAS del .env.

  ro.py check "cmd" ...                 solo pasa la guardia, no conecta
  ro.py run <nas> [--sudo] [--max N] "cmd" ...
  ro.py sql <nas> [--sudo] <ruta_db> "SELECT ..."
  ro.py bateria <nas> <catalogo.json>   cada comando sin sudo y con sudo; guarda salidas
  ro.py alta <nas>                      instala la clave publica de este PC y la prueba

Todo comando pasa por guardia.comprobar(); el arnes anade sudo, nunca el comando.
Nunca imprime la contrasena.
"""
import json
import os
import re
import shlex
import sys

import paramiko

import guardia

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
CLAVE = os.path.join(AQUI, "claves", "id_ed25519")
HOSTS = os.path.join(AQUI, "claves", "known_hosts")
NAS = {
    "nas1": ("QNAP_HOST", "QNAP_PORT"),
    "nas2": ("NAS2_HOST", "NAS2_PORT"),
    "nas3": ("NAS3_HOST", "NAS3_PORT"),
}
# NAS donde la clave de pruebas NO esta instalada: se entra directamente por contrasena.
# Ofrecer antes una clave que el NAS no tiene deja un intento fallido en cada conexion, y con
# cuatro seguidos el sshd de ese NAS corto durante un rato las conexiones nuevas de este equipo
# ("Error reading SSH protocol banner", 2026-10-14).
SIN_CLAVE = ("nas3",)
QVS_LIBS = "LD_LIBRARY_PATH=/QVS/usr/lib:/QVS/usr/lib64:/QVS/lib"
SQL_OK = re.compile(r"^\s*(select\b|pragma\s+(table_info|table_list|index_list|database_list)\b)", re.I)
SQL_SCRIPT = (
    "import sqlite3,sys\n"
    "c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro&immutable=1',uri=True)\n"
    "q=c.execute(sys.argv[2])\n"
    "print('\\t'.join(d[0] for d in q.description))\n"
    "for r in q.fetchmany(300):\n"
    "    print('\\t'.join('' if v is None else str(v) for v in r))\n"
)


def leer_env():
    datos = {}
    with open(os.path.join(RAIZ, ".env"), encoding="utf-8-sig") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            datos[clave.strip()] = valor.strip()
    return datos


def conectar(env, nas, con_clave=True):
    host, puerto = NAS[nas]
    args = dict(
        hostname=env[host],
        port=int(env.get(puerto, "22")),
        username=env["QNAP_USER"],
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )
    # Clave de host fijada en la primera conexion (known_hosts propio, no versionado).
    # Con el fichero cargado, paramiko rechaza (BadHostKeyException) un host conocido
    # cuya clave haya cambiado; AutoAddPolicy solo actua con hosts nunca vistos.
    os.makedirs(os.path.dirname(HOSTS), exist_ok=True)
    if not os.path.exists(HOSTS):
        open(HOSTS, "a", encoding="utf-8").close()
    cli = paramiko.SSHClient()
    cli.load_host_keys(HOSTS)
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if con_clave and nas not in SIN_CLAVE and os.path.exists(CLAVE):
        try:
            cli.connect(key_filename=CLAVE, **args)
            return cli, "clave"
        except paramiko.AuthenticationException:
            pass
    cli.connect(password=env["QNAP_PASSWORD"], **args)
    return cli, "contrasena"


def ejecutar(cli, cmd, sudo_pass=None, timeout=40):
    """Devuelve (rc, salida); rc=-1 si vence el tiempo."""
    if sudo_pass is not None:
        cmd = "sudo -S -p '' sh -c " + shlex.quote(cmd)
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    if sudo_pass is not None:
        stdin.write(sudo_pass + "\n")
        stdin.flush()
    stdin.close()
    try:
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
    except Exception:
        stdout.channel.close()
        return -1, "[tiempo agotado tras %d s]" % timeout
    # sudo suelta su sermon por stderr la primera vez: fuera
    err = re.sub(r"(?s)\s*We trust you have received.*?great responsibility\.\s*", "", err)
    if err.strip():
        out = out + ("\n" if out and not out.endswith("\n") else "") + "[stderr] " + err.strip() + "\n"
    return stdout.channel.recv_exit_status(), out


def recortar(texto, maximo):
    lineas = texto.rstrip().splitlines()
    if len(lineas) > maximo:
        return "\n".join(lineas[:maximo]) + "\n[... %d lineas mas]" % (len(lineas) - maximo)
    return "\n".join(lineas)


def cmd_check(args):
    reglas = guardia.cargar_reglas()
    for cmd in args:
        try:
            guardia.comprobar(cmd, reglas)
            print("OK        " + cmd)
        except guardia.Bloqueado as e:
            print("BLOQUEADO " + cmd + "   <- " + str(e))


def cmd_run(args):
    nas = args.pop(0)
    sudo = "--sudo" in args
    maximo = 60
    if "--max" in args:
        i = args.index("--max")
        maximo = int(args[i + 1])
        del args[i:i + 2]
    args = [a for a in args if a != "--sudo"]
    env = leer_env()
    reglas = guardia.cargar_reglas()
    cli, via = conectar(env, nas)
    print("[%s por %s%s]" % (nas, via, ", sudo" if sudo else ""))
    for cmd in args:
        print("\n$ " + cmd)
        try:
            guardia.comprobar(cmd, reglas)
        except guardia.Bloqueado as e:
            print("[BLOQUEADO por la guardia] %s" % e)
            continue
        rc, out = ejecutar(cli, cmd, env["QNAP_PASSWORD"] if sudo else None)
        if out.strip():
            print(recortar(out, maximo))
        print("[rc=%d]" % rc)
    cli.close()


def cmd_sql(args):
    nas = args.pop(0)
    sudo = "--sudo" in args
    args = [a for a in args if a != "--sudo"]
    db, consulta = args
    if not SQL_OK.match(consulta) or ";" in consulta:
        print("[BLOQUEADO] solo SELECT o PRAGMA de consulta, sin punto y coma")
        return
    guardia.comprobar("cat " + db)
    env = leer_env()
    cli, via = conectar(env, nas)
    # el primer python3 que exista: el de Virtualization Station o el del sistema
    # con VS desactivado no existe /QVS, pero su python3 sigue en la carpeta del paquete
    cmd = ("for p in /QVS/usr/bin/python3 /share/*/.qpkg/QKVM/usr/bin/python3 "
           "/usr/local/bin/python3 /usr/bin/python3; do "
           "if [ -x $p ]; then q=${p%%/usr/bin/python3}; "
           "LD_LIBRARY_PATH=$q/usr/lib:$q/usr/lib64:$q/lib $p -c %s %s %s; exit $?; fi; done; "
           "echo '[sin python3 en el NAS]'; exit 127") % (
        shlex.quote(SQL_SCRIPT), shlex.quote(db), shlex.quote(consulta))
    rc, out = ejecutar(cli, cmd, env["QNAP_PASSWORD"] if sudo else None)
    print(recortar(out, 310))
    print("[rc=%d]" % rc)
    cli.close()


def cmd_bateria(args):
    nas, ruta = args
    with open(ruta, encoding="utf-8") as f:
        catalogo = json.load(f)
    pata = os.path.splitext(os.path.basename(ruta))[0]
    destino = os.path.join(AQUI, "resultados", nas, pata)
    os.makedirs(destino, exist_ok=True)
    env = leer_env()
    reglas = guardia.cargar_reglas()
    cli, via = conectar(env, nas)
    print("[%s por %s] %d comandos -> %s" % (nas, via, len(catalogo["comandos"]), destino))
    print("%-28s %8s %8s %8s %8s  %s" % ("id", "rc", "bytes", "rc_sudo", "bytes", "veredicto"))
    for c in catalogo["comandos"]:
        try:
            guardia.comprobar(c["cmd"], reglas)
        except guardia.Bloqueado as e:
            print("%-28s BLOQUEADO: %s" % (c["id"], e))
            continue
        fila = []
        for sufijo, clave in (("", None), (".sudo", env["QNAP_PASSWORD"])):
            rc, out = ejecutar(cli, c["cmd"], clave)
            with open(os.path.join(destino, c["id"] + sufijo + ".txt"), "w", encoding="utf-8") as f:
                f.write("$ %s\n[rc=%d]\n%s" % (c["cmd"], rc, out))
            fila.append((rc, len(out.strip()), out))
        (rc1, n1, o1), (rc2, n2, o2) = fila
        if rc1 == 0 and n1 and o1 == o2:
            veredicto = "sin sudo"
        elif rc1 == 0 and n1 and "[stderr]" not in o1:
            veredicto = "sin sudo (difiere de sudo)"
        elif rc2 == 0 and n2:
            veredicto = "requiere sudo"
        else:
            veredicto = "FALLA"
        print("%-28s %8d %8d %8d %8d  %s" % (c["id"], rc1, n1, rc2, n2, veredicto))
    cli.close()


def cmd_alta(args):
    nas = args[0]
    env = leer_env()
    with open(CLAVE + ".pub", encoding="utf-8") as f:
        pub = f.read().strip()
    cli, via = conectar(env, nas, con_clave=False)
    q = shlex.quote(pub)
    rc, out = ejecutar(cli, (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        "{ grep -qF %s ~/.ssh/authorized_keys 2>/dev/null || echo %s >> ~/.ssh/authorized_keys; } && "
        "chmod 600 ~/.ssh/authorized_keys && ls -ld ~ ~/.ssh ~/.ssh/authorized_keys") % (q, q))
    print(out.rstrip())
    print("[instalacion rc=%d, entrando por %s]" % (rc, via))
    cli.close()
    cli, via = conectar(env, nas)
    rc, out = ejecutar(cli, "id")
    print("[reentrada por %s] %s" % (via, out.strip()))
    cli.close()


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    ordenes = {"check": cmd_check, "run": cmd_run, "sql": cmd_sql, "bateria": cmd_bateria, "alta": cmd_alta}
    if orden not in ordenes:
        print(__doc__)
        sys.exit(2)
    ordenes[orden](sys.argv[2:])
