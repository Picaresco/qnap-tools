# -*- coding: utf-8 -*-
"""Arranca un servidor MCP por stdio y hace el saludo a mano: initialize + tools/list.

Uso: python mcp_handshake.py <ejecutable> [--llamar HERRAMIENTA JSON_ARGS]

Las variables de entorno del servidor (QNAP_TOOLS_USER, etc.) se heredan de quien lo lanza.
Sirve para comprobar que un servidor arranca y publica sus herramientas sin Claude Code.
"""
import json
import queue
import subprocess
import sys
import threading


def main():
    args = sys.argv[1:]
    llamar = None
    if "--llamar" in args:
        i = args.index("--llamar")
        llamar = (args[i + 1], json.loads(args[i + 2]))
        del args[i:i + 3]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8")
    lineas = queue.Queue()
    threading.Thread(target=lambda: [lineas.put(l) for l in proc.stdout], daemon=True).start()

    def enviar(mensaje):
        proc.stdin.write(json.dumps(mensaje) + "\n")
        proc.stdin.flush()

    def recibir(ident, espera=60):
        while True:
            try:
                linea = lineas.get(timeout=espera)
            except queue.Empty:
                proc.kill()
                print("SIN RESPUESTA en %d s; stderr: %s" % (espera, proc.stderr.read()[-800:]))
                sys.exit(1)
            mensaje = json.loads(linea)
            if mensaje.get("id") == ident:
                return mensaje

    enviar({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "mcp_handshake", "version": "0"}}})
    inicio = recibir(1)["result"]
    print("servidor: %s %s | protocolo %s" % (
        inicio["serverInfo"]["name"], inicio["serverInfo"].get("version", ""), inicio["protocolVersion"]))
    print("instrucciones: %s..." % (inicio.get("instructions") or "")[:110])
    enviar({"jsonrpc": "2.0", "method": "notifications/initialized"})
    enviar({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    herramientas = recibir(2)["result"]["tools"]
    print("herramientas (%d):" % len(herramientas))
    for h in herramientas:
        parametros = ", ".join(sorted(h["inputSchema"].get("properties", {})))
        print("  %-22s (%s) %s" % (h["name"], parametros, " ".join(h.get("description", "").split())[:70]))
    if llamar:
        enviar({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": llamar[0], "arguments": llamar[1]}})
        respuesta = recibir(3, espera=120)
        resultado = respuesta.get("result", respuesta)
        print("llamada %s -> isError=%s" % (llamar[0], resultado.get("isError")))
        for bloque in resultado.get("content", []):
            print(bloque.get("text", bloque)[:3000])
    proc.stdin.close()
    proc.wait(timeout=10)
    print("salida del proceso: %d" % proc.returncode)


if __name__ == "__main__":
    main()
