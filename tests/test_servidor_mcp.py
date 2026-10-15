# -*- coding: utf-8 -*-
"""Lo comun a los cinco servidores MCP: como se registran las herramientas (marca de solo
lectura, que no bloqueen el servidor) y lo que el paquete declara que necesita."""
import ast
import asyncio
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any

from qnap_tools import config, servidor
from qnap_tools.discos import servidor as discos_srv
from qnap_tools.flota import servidor as flota_srv
from qnap_tools.logs import servidor as logs_srv
from qnap_tools.redes import servidor as redes_srv
from qnap_tools.virtualizacion import servidor as virt_srv

RAIZ = Path(__file__).parent.parent
DE_CONSULTA = (redes_srv, discos_srv, virt_srv, logs_srv)
# lo que escribe algo, en este ordenador o en el NAS, y si puede quitar o pisar lo que habia
ESCRIBEN = {"nas_alta": False, "nas_enrolar": False, "inventario_exportar": False,
            "nas_baja": True, "inventario_importar": True}


def herramientas(modulo):
    return {t.name: t for t in asyncio.run(modulo.construir({}).list_tools())}


def test_las_herramientas_de_consulta_se_declaran_de_solo_lectura():
    for modulo in DE_CONSULTA:
        for nombre, t in herramientas(modulo).items():
            assert t.annotations is not None and t.annotations.readOnlyHint is True, nombre


def test_en_la_flota_solo_lista_y_comprobar_son_de_solo_lectura():
    flota = herramientas(flota_srv)
    assert {n for n, t in flota.items() if t.annotations.readOnlyHint} == {"nas_lista", "nas_comprobar"}
    for nombre, destructiva in ESCRIBEN.items():
        a = flota[nombre].annotations
        assert a.readOnlyHint is False and a.destructiveHint is destructiva, nombre


class Lentas:
    """Dos herramientas que se esperan una a otra: solo terminan bien si corren a la vez."""

    def __init__(self, espera_s=5):
        self.senal = threading.Event()
        self.espera_s = espera_s

    def espera(self, nas: str) -> dict[str, Any]:
        """Espera a que la otra herramienta de la senal."""
        return {"llego": self.senal.wait(self.espera_s)}

    def avisa(self, nas: str) -> dict[str, Any]:
        """Da la senal."""
        self.senal.set()
        return {"hecho": True}


def test_una_herramienta_lenta_no_bloquea_al_servidor():
    mcp, _ = servidor.crear("prueba", "instrucciones", {})
    servidor.registrar(mcp, Lentas(), ("espera", "avisa"))

    async def las_dos():
        inicio = time.monotonic()
        espera = asyncio.create_task(mcp.call_tool("espera", {"nas": "x"}))
        await asyncio.sleep(0.2)
        await mcp.call_tool("avisa", {"nas": "x"})
        resultado = await espera
        return resultado, time.monotonic() - inicio
    resultado, segundos = asyncio.run(las_dos())
    assert '"llego": true' in str(resultado) and segundos < 4


def test_con_un_candado_las_herramientas_van_de_una_en_una():
    mcp, _ = servidor.crear("prueba", "instrucciones", {})
    lentas = Lentas(espera_s=0.5)
    servidor.registrar(mcp, lentas, ("espera", "avisa"), candado=threading.Lock())

    async def las_dos():
        espera = asyncio.create_task(mcp.call_tool("espera", {"nas": "x"}))
        await asyncio.sleep(0.1)
        await mcp.call_tool("avisa", {"nas": "x"})
        return await espera
    # 'avisa' no puede entrar hasta que 'espera' termine: espera sin recibir la senal
    assert '"llego": false' in str(asyncio.run(las_dos()))


def test_el_registro_conserva_nombre_descripcion_y_parametros():
    mcp, _ = servidor.crear("prueba", "instrucciones", {})
    servidor.registrar(mcp, Lentas(), ("espera",))
    (t,) = asyncio.run(mcp.list_tools())
    assert (t.name, t.description) == ("espera", "Espera a que la otra herramienta de la senal.")
    assert t.inputSchema["required"] == ["nas"]


def test_dos_consultas_a_la_vez_al_arrancar_comparten_una_sola_flota(monkeypatch):
    real = config.cargar

    def lenta(entorno):
        time.sleep(0.3)
        return real(entorno)
    monkeypatch.setattr(config, "cargar", lenta)
    ctx = servidor.Contexto({"QNAP_TOOLS_USER": "u", "QNAP_TOOLS_PASSWORD": "p", "QNAP_TOOLS_DATA": "."})
    flotas = []
    hilos = [threading.Thread(target=lambda: flotas.append(ctx.flota)) for _ in range(2)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(flotas) == 2 and flotas[0] is flotas[1]


def test_el_paquete_declara_todo_lo_que_importa():
    declaradas = {d.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip().lower()
                  for d in tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
                  ["project"]["dependencies"]}
    importadas = set()
    for fichero in (RAIZ / "src" / "qnap_tools").rglob("*.py"):
        for nodo in ast.walk(ast.parse(fichero.read_text(encoding="utf-8"))):
            if isinstance(nodo, ast.Import):
                importadas |= {a.name.split(".")[0] for a in nodo.names}
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0:
                importadas.add(nodo.module.split(".")[0])
    terceros = importadas - set(sys.stdlib_module_names) - {"qnap_tools"}
    assert terceros <= declaradas, terceros - declaradas


def test_al_salir_el_proceso_se_cierra_la_flota(monkeypatch):
    registrados = []
    monkeypatch.setattr(servidor.atexit, "register", lambda f, *a: registrados.append(f))
    _, ctx = servidor.crear("prueba", "instrucciones", {"QNAP_TOOLS_USER": "u",
                                                       "QNAP_TOOLS_PASSWORD": "p", "QNAP_TOOLS_DATA": "."})
    assert registrados == [ctx.cerrar]


def test_cerrar_el_contexto_cierra_las_conexiones_y_sin_flota_no_hace_nada():
    ctx = servidor.Contexto({"QNAP_TOOLS_USER": "u", "QNAP_TOOLS_PASSWORD": "p", "QNAP_TOOLS_DATA": "."})
    ctx.cerrar()                                   # aun no hay flota: no la crea ni falla
    assert ctx._flota is None
    cerrada = []
    ctx.flota.cerrar = lambda: cerrada.append(True)
    ctx.cerrar()
    assert cerrada == [True]
