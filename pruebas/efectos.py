# -*- coding: utf-8 -*-
"""Prueba de efectos secundarios: que ficheros del NAS cambian al ejecutar cada comando.

Uso: python efectos.py <nas> [--sin id1,id2] [--salida NOMBRE] <catalogo.json> [...]
     python efectos.py <nas> [--salida NOMBRE] --producto <pata>     (redes, discos...)

Con un catalogo, cada comando se prueba sin sudo y con sudo. Con --producto se prueban las
ordenes del propio plugin (qnap_tools/<pata>/comandos.py) con parametros reales del NAS y
solo como el plugin las lanza: con sudo las marcadas, sin el las demas.

Entre comando y comando se lista (ls -lAR, con sudo) el contenido de las carpetas de sistema
y se compara tamano y fecha de cada fichero, y que carpetas hay. Lo que cambia tambien sin
hacer nada (ruido de fondo: logs, estado del sistema) se descarta con una fase de control; los
comandos senalados se repiten dos veces mas, alternando con controles, y solo se da por
confirmado lo que se repite.

Repetir no sirve para un efecto que solo ocurre la primera vez (un cliente que crea su carpeta
de configuracion): por eso el informe senala aparte lo que aparecio junto a una orden, no
existia al empezar la prueba y sigue ahi al acabarla ("nuevos_que_siguen"). Aun asi, lo que un
usuario ya dejo creado en una ejecucion anterior a la prueba no se puede ver.
Todo pasa por la guardia. Informe en resultados/<nas>/efectos.json.
"""
import json
import os
import shlex
import sys
import time

import guardia
import ro

VIGILADAS = "/tmp /etc /var /root /mnt/HDA_ROOT /mnt/sync /share/homes/%s"
LISTAR = None  # se completa en main() con el usuario del .env
LISTAR_EXT = "ls -lAR --full-time /mnt/ext 2>/dev/null"


def foto(cli, clave, cmd=None):
    cmd = cmd or LISTAR
    guardia.comprobar(cmd)
    return leer_listado(ro.ejecutar(cli, cmd, clave, timeout=90)[1])


def leer_listado(salida):
    """{ruta: (tamano, fecha)} de un 'ls -lAR --full-time'; cada carpeta, como 'ruta/'."""
    datos = {}
    carpeta = ""
    for linea in salida.splitlines():
        if linea.endswith(":") and linea.startswith("/"):
            carpeta = linea[:-1]
            datos[carpeta + "/"] = ("carpeta", "")
            continue
        p = linea.split(None, 8)
        if len(p) < 9 or p[0][0] not in "-dlsbcp":
            continue
        if p[0][0] in "dl":
            continue
        datos[carpeta + "/" + p[8]] = (p[4], p[5] + " " + p[6])
    return datos


def cambios(a, b):
    fuera = set()
    for k in b:
        if k not in a or a[k] != b[k]:
            fuera.add(k)
    for k in a:
        if k not in b:
            fuera.add(k + " (borrado)")
    return fuera


def nuevos_que_siguen(vistos, inicial, final):
    """De lo que cambio junto a una orden, lo que no existia al empezar la prueba y sigue al
    acabarla: lo que deja un efecto de primera vez, que al repetir la orden ya no se repite."""
    return sorted(k for k in vistos if k in final and k not in inicial)


def lanzar(cli, cmd, clave):
    try:
        guardia.comprobar(cmd)
    except guardia.Bloqueado as e:
        return None, str(e)
    rc, out = ro.ejecutar(cli, cmd, clave, timeout=45)
    return rc, out


def comandos_del_producto(pata, cli, clave):
    """[(ident, orden, (sudo,))] con las ordenes de una pata del plugin validas para el
    sistema de este NAS, tal como el plugin las lanza."""
    import captura
    from qnap_tools.deteccion import detectar
    from qnap_tools.transporte import Resultado

    class Via:
        destino = "laboratorio"

        def ejecutar(self, orden, sudo=False, timeout=20):
            guardia.comprobar(orden)
            rc, salida = ro.ejecutar(cli, orden, clave if sudo else None, timeout=timeout)
            return Resultado(rc, salida, "", rc == -1)

    sistema = detectar(Via()).sistema
    ordenes = captura.ordenes(pata, sistema)
    porNombre = dict(ordenes)

    def leer(nombre):
        comando = porNombre[nombre]
        return Via().ejecutar(comando.render(), comando.sudo, 45).salida
    valores = captura.valores_reales(pata, leer, sistema)
    lista = []
    for nombre, comando in ordenes:
        if nombre in valores and valores[nombre] is None:
            print("  %s: sin parametro disponible en este NAS, no se prueba" % nombre)
            continue
        if comando.params and nombre not in valores:
            raise SystemExit("falta en captura.py el valor de los parametros de %s" % nombre)
        lista.append(("%s/%s" % (pata, comando.id), comando.render(valores.get(nombre)), (comando.sudo,)))
    print("sistema %s: %d ordenes de %s" % (sistema, len(lista), pata))
    return lista


def main():
    nas = sys.argv[1]
    comandos = []
    args = sys.argv[2:]
    # --sin id1,id2 excluye comandos; --salida NOMBRE cambia el nombre del informe
    excluidos, salida, producto = set(), "efectos", None
    while args and args[0] in ("--sin", "--salida", "--producto"):
        if args[0] == "--sin":
            excluidos = set(args[1].split(","))
        elif args[0] == "--producto":
            producto = args[1]
        else:
            salida = args[1]
        args = args[2:]
    for ruta in args:
        pata = os.path.splitext(os.path.basename(ruta))[0]
        with open(ruta, encoding="utf-8") as f:
            cat = json.load(f)
        for c in cat["comandos"]:
            if c["id"] not in excluidos:
                comandos.append((pata + "/" + c["id"], c["cmd"], (False, True)))
        for i, s in enumerate(cat.get("sql", [])):
            if isinstance(s, dict) and s.get("db") and s.get("consulta"):
                comandos.append((pata + "/sql_%d" % i, ("SQL", s["db"], s["consulta"]), (False, True)))
    env = ro.leer_env()
    clave = env["QNAP_PASSWORD"]
    global LISTAR
    LISTAR = "ls -lAR --full-time %s 2>/dev/null" % (VIGILADAS % env["QNAP_USER"])
    cli, via = ro.conectar(env, nas)
    if producto:
        comandos.extend(comandos_del_producto(producto, cli, clave))
    print("[%s por %s] %d comandos" % (nas, via, len(comandos)), flush=True)

    ext_antes = foto(cli, clave, LISTAR_EXT)

    # fase de control: ruido de fondo y efecto del propio arnes (sesion y sudo)
    ruido = set()
    inicial = previa = foto(cli, clave)
    for i in range(8):
        ro.ejecutar(cli, "true", clave if i % 2 else None)
        time.sleep(4)
        ahora = foto(cli, clave)
        ruido |= cambios(previa, ahora)
        previa = ahora
    print("ruido de fondo: %d ficheros" % len(ruido), flush=True)

    def ejecutar_uno(cmd, con_sudo):
        if isinstance(cmd, tuple):
            texto = ("for p in /QVS/usr/bin/python3; do LD_LIBRARY_PATH=/QVS/usr/lib:/QVS/usr/lib64:/QVS/lib "
                     "$p -c %s %s %s; done") % (shlex.quote(ro.SQL_SCRIPT), shlex.quote(cmd[1]), shlex.quote(cmd[2]))
            return ro.ejecutar(cli, texto, clave if con_sudo else None, timeout=45)
        return lanzar(cli, cmd, clave if con_sudo else None)

    candidatos = {}
    bloqueados = []
    for n, (ident, cmd, modos) in enumerate(comandos):
        for con_sudo in modos:
            rc, out = ejecutar_uno(cmd, con_sudo)
            if rc is None:
                if not con_sudo:
                    bloqueados.append((ident, out))
                continue
            ahora = foto(cli, clave)
            dif = cambios(previa, ahora)
            previa = ahora
            nuevos = dif - ruido
            if nuevos:
                candidatos[(ident, con_sudo)] = (cmd, nuevos)
        if n % 20 == 19:
            print("  %d/%d, candidatos hasta ahora: %d" % (n + 1, len(comandos), len(candidatos)), flush=True)

    # fase de confirmacion: repetir cada candidato dos veces, con un control antes de cada una
    confirmados = {}
    for (ident, con_sudo), (cmd, vistos) in candidatos.items():
        comunes = set(vistos)
        for _ in range(2):
            time.sleep(3)
            ahora = foto(cli, clave)
            control = cambios(previa, ahora)
            previa = ahora
            ruido |= control
            ejecutar_uno(cmd, con_sudo)
            ahora = foto(cli, clave)
            dif = cambios(previa, ahora)
            previa = ahora
            comunes &= dif
        comunes -= ruido
        if comunes:
            confirmados["%s%s" % (ident, " (sudo)" if con_sudo else "")] = {
                "cmd": cmd if isinstance(cmd, str) else "SQL " + cmd[2], "ficheros": sorted(comunes)}

    final = foto(cli, clave)
    siguen = {}
    for (ident, con_sudo), (_, vistos) in candidatos.items():
        suyos = [k for k in nuevos_que_siguen(vistos, inicial, final) if k not in ruido]
        if suyos:
            siguen["%s%s" % (ident, " (sudo)" if con_sudo else "")] = suyos
    ext_despues = foto(cli, clave, LISTAR_EXT)
    cli.close()

    informe = {
        "nas": nas,
        "comandos": len(comandos),
        "bloqueados_por_la_guardia": bloqueados,
        "ruido_de_fondo": sorted(ruido),
        "candidatos_no_confirmados": sorted(
            "%s%s" % (i, " (sudo)" if s else "") for (i, s) in candidatos
            if "%s%s" % (i, " (sudo)" if s else "") not in confirmados),
        "confirmados": confirmados,
        # aparecio junto a la orden, no existia al empezar y sigue ahi: posible efecto de primera vez
        "nuevos_que_siguen": siguen,
        # lo que cambio junto a cada candidato la primera vez (para saber que se descarto)
        "ficheros_de_los_candidatos": {
            "%s%s" % (i, " (sudo)" if s else ""): sorted(vistos) for (i, s), (_, vistos) in candidatos.items()},
        "cambios_en_mnt_ext_durante_toda_la_prueba": sorted(cambios(ext_antes, ext_despues)),
    }
    destino = os.path.join(ro.AQUI, "resultados", nas, salida + ".json")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=1, ensure_ascii=True)
    print("\ncomandos: %d | bloqueados: %d | candidatos: %d | CONFIRMADOS: %d | nuevos que siguen: %d" % (
        len(comandos), len(bloqueados), len(candidatos), len(confirmados), len(siguen)))
    for ident, d in confirmados.items():
        print("\n%s\n  $ %s" % (ident, d["cmd"][:160]))
        for fich in d["ficheros"][:12]:
            print("    " + fich)
    print("\ncambios en /mnt/ext en toda la prueba: %d" % len(informe["cambios_en_mnt_ext_durante_toda_la_prueba"]))
    for fich in informe["cambios_en_mnt_ext_durante_toda_la_prueba"][:15]:
        print("    " + fich)
    print("informe: " + destino)


if __name__ == "__main__":
    main()
