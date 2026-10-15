# -*- coding: utf-8 -*-
import asyncio
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import paramiko
import pytest

import falsos
from qnap_tools import deteccion, servidor, transporte
from qnap_tools import inventario as inv
from qnap_tools.flota import servidor as flota_srv
from qnap_tools.inventario import Nas
from qnap_tools.transporte import Conexion

DATOS = Path(__file__).parent / "datos"
HERO = (DATOS / "deteccion_hero.txt").read_text(encoding="utf-8")
DET = deteccion.DETECCION.plantilla
ID_ADMIN = "uid=1002(usuario) gid=100(everyone) groups=0(administrators),100(everyone)\n"
ID_NORMAL = "uid=1002(usuario) gid=100(everyone) groups=100(everyone)\n"
INSTALAR = re.compile(r"^mkdir -p ~/\.ssh")
HOST = "192.0.2.10"


def nas_simulado(acepta_la_clave_tras_instalar=True, **extra):
    """Un QNAP recien salido de la caja: host sin fijar y sin nuestra clave."""
    extra.setdefault("host_fijado", False)
    mundo = falsos.Mundo(acepta_clave=False, **extra)

    def instala(orden, sudo):
        if acepta_la_clave_tras_instalar:
            mundo.acepta_clave = True
        return ""
    mundo.respuestas.update({"id": ID_ADMIN, "id -u": "0\n", DET: HERO, INSTALAR: instala})
    return mundo


def montar(tmp_path, mundos, entorno=None):
    """Herramientas de flota sobre NAS simulados (un Mundo por host)."""
    if entorno is None:
        entorno = {"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto",
                   "QNAP_TOOLS_DATA": str(tmp_path)}

    def fabrica(nas, cfg):
        return Conexion(nas, cfg, fabrica=mundos[nas.host].cliente)
    ctx = servidor.Contexto(entorno, fabrica_conexion=fabrica)
    return flota_srv.Herramientas(ctx), ctx


def guardado(ctx):
    return inv.cargar(ctx.cfg.inventario)


def instalaciones(mundo):
    return [o for o, _ in mundo.ordenes if INSTALAR.search(o)]


# --- nas_alta ------------------------------------------------------------------------

def test_alta_guarda_el_nas_e_informa(tmp_path):
    mundo = nas_simulado()
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is True and r["nas"] == "casa"
    assert r["acceso"] == "clave" and r["sudo_root"] is True
    assert r["huella_host"] == "ssh-ed25519 SHA256:huella-de-AAAAfijada"
    assert r["perfil"]["sistema"] == "hero" and r["perfil"]["firmware"] == "6.0.2"
    assert r["avisos"] == []
    assert guardado(ctx) == {"casa": Nas("casa", HOST)}


def test_alta_entra_primero_por_contrasena_y_fija_la_clave_de_host(tmp_path):
    mundo = nas_simulado()
    h, _ = montar(tmp_path, {HOST: mundo})
    h.nas_alta("casa", HOST)
    assert mundo.intentos[0] == ("contrasena", "usuario")
    assert mundo.fijaciones == 1


def test_alta_envia_la_orden_exacta_de_instalacion_despues_de_identificar_el_nas(tmp_path):
    mundo = nas_simulado()
    h, ctx = montar(tmp_path, {HOST: mundo})
    h.nas_alta("casa", HOST)
    publica = (ctx.cfg.datos / "id_ed25519.pub").read_text(encoding="utf-8").strip()
    ordenes = [o for o, _ in mundo.ordenes]
    instalar = flota_srv.orden_instalar_clave(publica)
    assert (instalar, False) in mundo.ordenes                  # sin sudo: es el home del usuario
    assert ordenes.index("id") < ordenes.index(DET) < ordenes.index(instalar)
    assert instalar.count(publica) == 2 and "authorized_keys" in instalar


def test_alta_con_puerto_propio(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado()})
    assert h.nas_alta("casa", HOST, 223)["ok"] is True
    assert guardado(ctx)["casa"].port == 223


def test_alta_sin_instalar_clave_guarda_acceso_por_contrasena(tmp_path):
    mundo = nas_simulado()
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST, instalar_clave=False)
    assert r["ok"] is True and r["acceso"] == "contrasena"
    assert instalaciones(mundo) == []
    assert guardado(ctx)["casa"].auth == "contrasena"
    assert not ctx.cfg.clave.exists()                          # ni siquiera se genera el par


def test_alta_en_un_nas_que_no_acepta_claves_cae_a_contrasena_y_avisa(tmp_path):
    mundo = nas_simulado(acepta_la_clave_tras_instalar=False)
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is True and r["acceso"] == "contrasena"
    assert len(r["avisos"]) == 1 and "clave" in r["avisos"][0]
    assert guardado(ctx)["casa"].auth == "contrasena"


def test_alta_si_la_instalacion_de_la_clave_falla_cae_a_contrasena_y_avisa(tmp_path):
    mundo = nas_simulado()
    mundo.respuestas[INSTALAR] = (1, "", "mkdir: can't create directory '/share/homes/usuario/.ssh'\n")
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is True and r["acceso"] == "contrasena"
    assert "can't create directory" in r["avisos"][0]
    assert guardado(ctx)["casa"].auth == "contrasena"


def test_alta_con_sudo_que_no_da_root_se_guarda_con_aviso(tmp_path):
    mundo = nas_simulado()
    mundo.respuestas["id -u"] = (1, "", "usuario is not in the sudoers file.\n")
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is True and r["sudo_root"] is False
    assert any("sudo" in a for a in r["avisos"])
    assert "casa" in guardado(ctx)


@pytest.mark.parametrize("nombre,host,port", [
    ("Mal Nombre", HOST, 22), ("todos", HOST, 22), ("casa", "a b", 22), ("casa", "$(x)", 22),
    ("casa", HOST, 0), ("casa", HOST, 70000),
])
def test_alta_con_datos_invalidos_no_llega_a_conectar(tmp_path, nombre, host, port):
    mundo = nas_simulado()
    h, ctx = montar(tmp_path, {HOST: mundo, "a b": mundo, "$(x)": mundo})
    r = h.nas_alta(nombre, host, port)
    assert r["ok"] is False and "error" in r
    assert mundo.clientes == []
    assert not ctx.cfg.inventario.exists()


def test_alta_de_un_nombre_que_ya_existe_no_llega_a_conectar(tmp_path):
    mundo = nas_simulado()
    h, ctx = montar(tmp_path, {HOST: mundo})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", "192.0.2.99")})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is False and "ya existe" in r["error"]
    assert mundo.clientes == []
    assert guardado(ctx) == {"casa": Nas("casa", "192.0.2.99")}


def test_alta_con_el_nas_inalcanzable_no_guarda_nada(tmp_path):
    mundo = nas_simulado(error_conexion=ConnectionRefusedError(10061, "refused"))
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is False and HOST in r["error"]
    assert not ctx.cfg.inventario.exists()


def test_alta_con_la_contrasena_rechazada_no_guarda_nada(tmp_path):
    mundo = nas_simulado(acepta_contrasena=False)
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is False and "rechazo" in r["error"] and "secreto" not in r["error"]
    assert not ctx.cfg.inventario.exists()


def test_alta_con_un_usuario_que_no_es_administrador_no_guarda_ni_escribe_en_el_nas(tmp_path):
    mundo = nas_simulado()
    mundo.respuestas["id"] = ID_NORMAL
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is False and "administrators" in r["error"]
    assert instalaciones(mundo) == []
    assert not ctx.cfg.inventario.exists()


def test_alta_de_algo_que_no_es_un_qnap_no_guarda_ni_escribe_en_el(tmp_path):
    mundo = nas_simulado()
    mundo.respuestas[DET] = (0, "sistema=\nfirmware=\n", "")
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is False and "identificar" in r["error"]
    assert instalaciones(mundo) == []
    assert not ctx.cfg.inventario.exists()


def test_alta_con_la_clave_de_host_cambiada_se_rechaza(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado(host_cambiado=True)})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is False and "clave de host" in r["error"]
    assert not ctx.cfg.inventario.exists()


def test_sin_credencial_configurada_cada_herramienta_lo_dice(tmp_path):
    h, _ = montar(tmp_path, {}, entorno={"QNAP_TOOLS_DATA": str(tmp_path)})
    for r in (h.nas_alta("casa", HOST), h.nas_lista(), h.nas_baja("casa"),
              h.inventario_exportar(str(tmp_path / "x.toml")),
              h.inventario_importar(str(tmp_path / "x.toml"))):
        assert r["ok"] is False and "QNAP_TOOLS_USER" in r["error"]
    for r in (h.nas_comprobar("todos"), h.nas_enrolar()):
        assert len(r) == 1 and r[0]["ok"] is False and "QNAP_TOOLS_USER" in r[0]["error"]


# --- nas_lista, nas_comprobar, nas_baja --------------------------------------------------

def test_lista_vacia_y_con_entradas(tmp_path):
    h, ctx = montar(tmp_path, {})
    assert h.nas_lista() == {"ok": True, "inventario": str(ctx.cfg.inventario), "nas": []}
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST),
                                     "otro": Nas("otro", "192.0.2.20", 223, user="pepe", auth="contrasena")})
    assert h.nas_lista()["nas"] == [
        {"nombre": "casa", "host": HOST, "port": 22, "usuario": "usuario", "auth": "auto"},
        {"nombre": "otro", "host": "192.0.2.20", "port": 223, "usuario": "pepe", "auth": "contrasena"},
    ]


def test_comprobar_dice_acceso_sudo_y_sistema_de_cada_nas(tmp_path):
    bien = nas_simulado(host_fijado=True)
    bien.acepta_clave = True
    caido = nas_simulado(host_fijado=True, error_conexion=ConnectionRefusedError(10061, "refused"))
    h, ctx = montar(tmp_path, {HOST: bien, "192.0.2.20": caido})
    falsos.crear_clave(ctx.cfg.clave)
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST), "otro": Nas("otro", "192.0.2.20")})
    r = h.nas_comprobar("todos")
    assert r[0]["nas"] == "casa" and r[0]["ok"] is True
    assert r[0]["datos"]["acceso"] == "clave" and r[0]["datos"]["sudo_root"] is True
    assert r[0]["datos"]["sistema"] == "hero" and r[0]["datos"]["modelo"] == "TS-X85"
    assert r[0]["datos"]["paquetes"] == ["QKVM", "container-station"]
    assert r[1]["nas"] == "otro" and r[1]["ok"] is False


def test_comprobar_un_nas_sin_sudo_lo_marca_sin_fallar(tmp_path):
    mundo = nas_simulado(host_fijado=True)
    mundo.respuestas["id -u"] = (1, "", "usuario is not in the sudoers file.\n")
    h, ctx = montar(tmp_path, {HOST: mundo})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    r = h.nas_comprobar("casa")
    assert r[0]["ok"] is True and r[0]["datos"]["sudo_root"] is False
    assert r[0]["datos"]["acceso"] == "contrasena"


def test_baja_quita_la_entrada_y_no_toca_el_nas(tmp_path):
    mundo = nas_simulado()
    h, ctx = montar(tmp_path, {HOST: mundo})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST), "otro": Nas("otro", "192.0.2.20")})
    r = h.nas_baja("casa")
    assert r["ok"] is True and "no se ha tocado" in r["nota"]
    assert list(guardado(ctx)) == ["otro"]
    assert mundo.clientes == []


def test_baja_de_un_nombre_inexistente_lista_los_validos(tmp_path):
    h, ctx = montar(tmp_path, {})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    r = h.nas_baja("nope")
    assert r["ok"] is False and "casa" in r["error"]
    assert list(guardado(ctx)) == ["casa"]


def test_baja_olvida_la_clave_de_host_para_poder_volver_a_darlo_de_alta(tmp_path):
    h, ctx = montar(tmp_path, {})
    falsos.crear_clave(tmp_path / "otra")
    clave = paramiko.PKey.from_path(str(tmp_path / "otra"))
    hosts = paramiko.HostKeys()
    for nombre in (HOST, "[192.0.2.20]:223"):
        hosts.add(nombre, clave.get_name(), clave)
    hosts.save(str(ctx.cfg.known_hosts))
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST), "otro": Nas("otro", "192.0.2.20", 223)})
    h.nas_baja("otro")
    despues = paramiko.HostKeys(str(ctx.cfg.known_hosts))
    assert despues.lookup("[192.0.2.20]:223") is None
    assert despues.lookup(HOST) is not None


def test_baja_conserva_la_clave_de_host_si_otra_entrada_usa_el_mismo_equipo(tmp_path):
    h, ctx = montar(tmp_path, {})
    falsos.crear_clave(tmp_path / "otra")
    clave = paramiko.PKey.from_path(str(tmp_path / "otra"))
    hosts = paramiko.HostKeys()
    hosts.add(HOST, clave.get_name(), clave)
    hosts.save(str(ctx.cfg.known_hosts))
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST), "alias": Nas("alias", HOST)})
    h.nas_baja("alias")
    assert paramiko.HostKeys(str(ctx.cfg.known_hosts)).lookup(HOST) is not None


# --- nas_enrolar ---------------------------------------------------------------------------

def test_enrolar_fija_el_host_en_todos_e_instala_la_clave_donde_toca(tmp_path):
    con_clave, solo_contrasena = nas_simulado(), nas_simulado()
    h, ctx = montar(tmp_path, {HOST: con_clave, "192.0.2.20": solo_contrasena})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST),
                                     "viejo": Nas("viejo", "192.0.2.20", auth="contrasena")})
    r = h.nas_enrolar()
    assert [x["nas"] for x in r] == ["casa", "viejo"] and all(x["ok"] for x in r)
    assert r[0]["datos"] == {"acceso": "clave", "clave_instalada": True,
                             "huella_host": "ssh-ed25519 SHA256:huella-de-AAAAfijada"}
    assert r[1]["datos"]["acceso"] == "contrasena" and r[1]["datos"]["clave_instalada"] is False
    assert con_clave.fijaciones == 1 and solo_contrasena.fijaciones == 1
    assert len(instalaciones(con_clave)) == 1 and instalaciones(solo_contrasena) == []


def test_enrolar_con_un_nas_caido_sigue_con_los_demas(tmp_path):
    caido = nas_simulado(error_conexion=ConnectionRefusedError(10061, "refused"))
    h, ctx = montar(tmp_path, {HOST: nas_simulado(), "192.0.2.20": caido})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST), "otro": Nas("otro", "192.0.2.20")})
    r = h.nas_enrolar()
    assert r[0]["ok"] is True and r[1]["ok"] is False


def test_enrolar_si_el_nas_no_acepta_la_clave_lo_dice(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado(acepta_la_clave_tras_instalar=False)})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    r = h.nas_enrolar()
    assert r[0]["ok"] is True and r[0]["datos"]["acceso"] == "contrasena"
    assert "aviso" in r[0]["datos"]


def test_enrolar_con_inventario_vacio_lo_dice(tmp_path):
    h, _ = montar(tmp_path, {})
    r = h.nas_enrolar()
    assert len(r) == 1 and r[0]["ok"] is False and "vacio" in r[0]["error"]


def test_enrolar_varios_a_la_vez_no_pierde_ninguna_clave_de_host(tmp_path):
    # enrolar conecta con los NAS en paralelo; cada conexion guarda known_hosts entero
    mundos = {"192.0.2.%d" % i: nas_simulado(retardo_fijar=0.3) for i in (10, 20, 30)}
    h, ctx = montar(tmp_path, mundos)
    inv.guardar(ctx.cfg.inventario, {"n%d" % i: Nas("n%d" % i, host) for i, host in enumerate(mundos)})
    assert all(x["ok"] for x in h.nas_enrolar())
    fijados = paramiko.HostKeys(str(ctx.cfg.known_hosts))
    assert all(fijados.lookup(host) is not None for host in mundos)


def test_dos_altas_a_la_vez_por_el_servidor_quedan_las_dos(tmp_path):
    mundos = {"192.0.2.10": nas_simulado(retardo_fijar=0.3), "192.0.2.20": nas_simulado(retardo_fijar=0.3)}

    def fabrica(nas, cfg):
        return Conexion(nas, cfg, fabrica=mundos[nas.host].cliente)
    entorno = {"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto", "QNAP_TOOLS_DATA": str(tmp_path)}
    mcp = flota_srv.construir(entorno, fabrica_conexion=fabrica)

    async def las_dos():
        return await asyncio.gather(*(mcp.call_tool("nas_alta", {"nombre": "n%d" % i, "host": host})
                                      for i, host in enumerate(mundos)))
    asyncio.run(las_dos())
    assert set(inv.cargar(tmp_path / "inventario.toml")) == {"n0", "n1"}
    fijados = paramiko.HostKeys(str(tmp_path / "known_hosts"))
    assert all(fijados.lookup(host) is not None for host in mundos)


def test_dos_bajas_a_la_vez_por_el_servidor_no_se_pisan(tmp_path, monkeypatch):
    # cada baja lee el inventario, quita su NAS y lo guarda: a la vez, la segunda pisaria a la primera
    entorno = {"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto", "QNAP_TOOLS_DATA": str(tmp_path)}
    inv.guardar(tmp_path / "inventario.toml", {"a": Nas("a", HOST), "b": Nas("b", "192.0.2.20")})
    real = inv.guardar

    def lento(ruta, nas):
        time.sleep(0.3)
        real(ruta, nas)
    monkeypatch.setattr(inv, "guardar", lento)
    mcp = flota_srv.construir(entorno)

    async def las_dos():
        return await asyncio.gather(mcp.call_tool("nas_baja", {"nombre": "a"}),
                                    mcp.call_tool("nas_baja", {"nombre": "b"}))
    asyncio.run(las_dos())
    assert inv.cargar(tmp_path / "inventario.toml") == {}


# --- exportar e importar ------------------------------------------------------------------------

def test_exportar_e_importar_ida_y_vuelta(tmp_path):
    h, ctx = montar(tmp_path / "a", {})
    originales = {"casa": Nas("casa", HOST), "otro": Nas("otro", "192.0.2.20", 223, auth="contrasena")}
    inv.guardar(ctx.cfg.inventario, originales)
    copia = tmp_path / "copia.toml"
    r = h.inventario_exportar(str(copia))
    assert r["ok"] is True and r["total"] == 2 and Path(r["ruta"]) == copia
    h2, ctx2 = montar(tmp_path / "b", {})
    r = h2.inventario_importar(str(copia))
    assert r["ok"] is True and r["anadidos"] == ["casa", "otro"]
    assert guardado(ctx2) == originales


def test_exportar_no_pisa_un_fichero_existente(tmp_path):
    h, ctx = montar(tmp_path, {})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    destino = tmp_path / "importante.toml"
    destino.write_text("no me pises", encoding="utf-8")
    r = h.inventario_exportar(str(destino))
    assert r["ok"] is False and "existe" in r["error"]
    assert destino.read_text(encoding="utf-8") == "no me pises"


def test_exportar_exige_extension_toml(tmp_path):
    h, ctx = montar(tmp_path, {})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    r = h.inventario_exportar(str(tmp_path / "copia.txt"))
    assert r["ok"] is False and ".toml" in r["error"]
    assert not (tmp_path / "copia.txt").exists()


def test_importar_no_pisa_una_entrada_distinta_salvo_que_se_pida(tmp_path):
    h, ctx = montar(tmp_path, {})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST), "igual": Nas("igual", "192.0.2.30")})
    origen = tmp_path / "origen.toml"
    inv.guardar(origen, {"casa": Nas("casa", "192.0.2.77"), "igual": Nas("igual", "192.0.2.30"),
                         "nuevo": Nas("nuevo", "192.0.2.40")})
    r = h.inventario_importar(str(origen))
    assert r["anadidos"] == ["nuevo"] and r["sin_cambios"] == ["igual"]
    assert r["conflictos"] == ["casa"] and r["sustituidos"] == []
    assert guardado(ctx)["casa"].host == HOST
    r = h.inventario_importar(str(origen), sobrescribir=True)
    assert r["sustituidos"] == ["casa"] and r["conflictos"] == []
    assert guardado(ctx)["casa"].host == "192.0.2.77"


def test_importar_un_fichero_que_no_existe_o_no_vale_es_error(tmp_path):
    h, ctx = montar(tmp_path, {})
    assert h.inventario_importar(str(tmp_path / "no-existe.toml"))["ok"] is False
    malo = tmp_path / "malo.toml"
    malo.write_text('[nas.casa]\nhost = "a b"\n', encoding="utf-8")
    r = h.inventario_importar(str(malo))
    assert r["ok"] is False and "host" in r["error"]
    assert not ctx.cfg.inventario.exists()


# --- registro en el servidor MCP ------------------------------------------------------------------

def test_el_servidor_publica_las_siete_herramientas_con_descripcion(tmp_path):
    mcp = flota_srv.construir({"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto",
                               "QNAP_TOOLS_DATA": str(tmp_path)})
    herramientas = asyncio.run(mcp.list_tools())
    assert sorted(t.name for t in herramientas) == [
        "inventario_exportar", "inventario_importar", "nas_alta", "nas_baja",
        "nas_comprobar", "nas_enrolar", "nas_lista"]
    assert all(t.description and len(t.description) > 20 for t in herramientas)


def test_el_servidor_arranca_aunque_falte_la_credencial():
    mcp = flota_srv.construir({})
    assert len(asyncio.run(mcp.list_tools())) == 7


# --- clave de host tras un alta fallida ---------------------------------------------------

def hosts_fijados(ctx):
    ruta = ctx.cfg.known_hosts
    return sorted(paramiko.HostKeys(str(ruta)).keys()) if ruta.exists() else []


def test_alta_correcta_deja_fijada_la_clave_de_host(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado()})
    assert h.nas_alta("casa", HOST)["ok"] is True
    assert hosts_fijados(ctx) == [HOST]


@pytest.mark.parametrize("fallo", ["contrasena", "no_administrador", "no_qnap"])
def test_alta_fallida_no_deja_fijada_la_clave_de_host(tmp_path, fallo):
    mundo = nas_simulado(acepta_contrasena=(fallo != "contrasena"))
    if fallo == "no_administrador":
        mundo.respuestas["id"] = ID_NORMAL
    if fallo == "no_qnap":
        mundo.respuestas[DET] = (0, "sistema=\nfirmware=\n", "")
    h, ctx = montar(tmp_path, {HOST: mundo})
    assert h.nas_alta("casa", HOST)["ok"] is False
    assert mundo.fijaciones == 1            # la clave se guardo al conectar, antes de fallar
    assert hosts_fijados(ctx) == []         # y no queda huerfana: nas_baja no podria quitarla


def test_alta_fallida_conserva_una_clave_de_host_que_ya_estaba_fijada(tmp_path):
    # el mismo equipo ya se dio de alta antes: su clave no es de este intento
    mundo = nas_simulado(host_fijado=True, acepta_contrasena=False)
    h, ctx = montar(tmp_path, {HOST: mundo})
    hosts = paramiko.HostKeys()
    hosts.add(HOST, falsos.clave_de_host().get_name(), falsos.clave_de_host())
    hosts.save(str(ctx.cfg.known_hosts))
    assert h.nas_alta("otra", HOST)["ok"] is False
    assert hosts_fijados(ctx) == [HOST]


# --- la unica escritura en el NAS: la orden que instala la clave ---------------------------

PUBLICA = "ssh-ed25519 " + "A" * 68 + " qnap-tools@pc"
AJENA = b"ssh-rsa AAAAclaveDeOtroOrdenador otro@equipo"
SH = shutil.which("sh")


@pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar la orden de instalacion")
@pytest.mark.parametrize("previo, esperado", [
    (None, PUBLICA.encode() + b"\n"),
    (b"", PUBLICA.encode() + b"\n"),
    (AJENA + b"\n", AJENA + b"\n" + PUBLICA.encode() + b"\n"),
    (AJENA, AJENA + b"\n" + PUBLICA.encode() + b"\n"),               # sin salto de linea final
    (PUBLICA.encode() + b"\n", PUBLICA.encode() + b"\n"),             # ya instalada: no se duplica
    (AJENA + b"\n" + PUBLICA.encode(), AJENA + b"\n" + PUBLICA.encode()),
], ids=["sin-fichero", "vacio", "con-otra-clave", "otra-clave-sin-salto-final", "ya-instalada",
        "ya-instalada-sin-salto-final"])
def test_la_orden_de_instalar_la_clave_no_estropea_lo_que_ya_habia(tmp_path, previo, esperado):
    ssh = tmp_path / ".ssh"
    if previo is not None:
        ssh.mkdir()
        (ssh / "authorized_keys").write_bytes(previo)
    orden = flota_srv.orden_instalar_clave(PUBLICA)
    r = subprocess.run([SH, "-c", orden], env=dict(os.environ, HOME=str(tmp_path)), capture_output=True)
    assert r.returncode == 0, r.stderr
    assert (ssh / "authorized_keys").read_bytes() == esperado


# --- nas_comprobar: con que se entra de verdad -------------------------------------------------

def test_comprobar_avisa_si_un_nas_con_clave_entra_por_contrasena(tmp_path):
    mundo = nas_simulado(host_fijado=True)          # no acepta la clave (la perdio al rehacer el usuario)
    h, ctx = montar(tmp_path, {HOST: mundo})
    falsos.crear_clave(ctx.cfg.clave)
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})              # auth auto
    datos = h.nas_comprobar("casa")[0]["datos"]
    assert datos["acceso"] == "contrasena"
    assert len(datos["avisos"]) == 1 and "nas_enrolar" in datos["avisos"][0]


def test_comprobar_no_avisa_si_el_nas_es_solo_contrasena(tmp_path):
    mundo = nas_simulado(host_fijado=True)
    h, ctx = montar(tmp_path, {HOST: mundo})
    falsos.crear_clave(ctx.cfg.clave)
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST, auth="contrasena")})
    assert h.nas_comprobar("casa")[0]["datos"]["avisos"] == []


def test_comprobar_informa_del_acceso_con_el_que_se_ha_hecho_el_trabajo(tmp_path):
    mundo = nas_simulado(host_fijado=True)
    mundo.acepta_clave = True
    h, ctx = montar(tmp_path, {HOST: mundo})
    falsos.crear_clave(ctx.cfg.clave)
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    assert h.nas_comprobar("casa")[0]["datos"]["acceso"] == "clave"
    mundo.cortar()                      # la conexion cacheada murio ...
    mundo.acepta_clave = False          # ... y el NAS ya no admite la clave
    datos = h.nas_comprobar("casa")[0]["datos"]
    assert datos["acceso"] == "contrasena" and len(datos["avisos"]) == 1


# --- nas_alta: la prueba de la clave -------------------------------------------------------------

def nas_con_corte_tras_instalar(error):
    """La clave se instala bien y la conexion de PRUEBA siguiente falla por la red."""
    mundo = nas_simulado()

    def instala(orden, sudo):
        mundo.acepta_clave = True
        mundo.error_conexion = error
        return ""
    mundo.respuestas[INSTALAR] = instala
    return mundo


def test_alta_con_un_corte_al_probar_la_clave_deja_auto_y_no_acusa_al_nas(tmp_path):
    mundo = nas_con_corte_tras_instalar(paramiko.SSHException("Error reading SSH protocol banner"))
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is True and r["acceso"] == "contrasena"
    assert "no se pudo comprobar" in r["avisos"][0] and "no acepta" not in r["avisos"][0]
    assert "siguiente conexion" in r["avisos"][0]
    assert guardado(ctx)["casa"].auth == "auto"


def test_alta_con_la_clave_de_host_cambiada_al_probar_la_clave_es_error(tmp_path):
    mundo = nas_simulado()

    def instala(orden, sudo):
        mundo.acepta_clave = True
        mundo.host_cambiado = True
        return ""
    mundo.respuestas[INSTALAR] = instala
    h, ctx = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is False and "clave de host" in r["error"]
    assert guardado(ctx) == {}


def test_enrolar_con_un_corte_al_probar_la_clave_no_dice_que_el_nas_la_rechace(tmp_path):
    mundo = nas_con_corte_tras_instalar(OSError("timed out"))
    h, ctx = montar(tmp_path, {HOST: mundo})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    d = h.nas_enrolar()[0]["datos"]
    assert d["clave_instalada"] is True and d["acceso"] == "contrasena"
    assert "no se pudo comprobar" in d["aviso"] and "cada conexion" in d["aviso"]
    assert guardado(ctx)["casa"].auth == "auto"


def test_enrolar_con_la_clave_rechazada_deja_el_inventario_y_avisa_de_lo_que_pasara(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado(acepta_la_clave_tras_instalar=False)})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    d = h.nas_enrolar()[0]["datos"]
    assert "cada conexion" in d["aviso"]
    assert guardado(ctx)["casa"].auth == "auto"


# --- nas_enrolar de un solo NAS --------------------------------------------------------------------

def test_enrolar_un_nas_concreto_no_toca_los_demas(tmp_path):
    a, b = nas_simulado(), nas_simulado()
    h, ctx = montar(tmp_path, {HOST: a, "192.0.2.20": b})
    inv.guardar(ctx.cfg.inventario, {"a": Nas("a", HOST), "b": Nas("b", "192.0.2.20")})
    r = h.nas_enrolar("b")
    assert [x["nas"] for x in r] == ["b"] and r[0]["ok"] is True
    assert a.clientes == [] and len(instalaciones(b)) == 1


def test_enrolar_un_nombre_que_no_existe_lista_los_validos(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado()})
    inv.guardar(ctx.cfg.inventario, {"casa": Nas("casa", HOST)})
    r = h.nas_enrolar("nope")
    assert r[0]["ok"] is False and "casa" in r[0]["error"]


# --- nas_alta: equipo repetido, datos saneados, limpieza que falla ---------------------------------------

def test_alta_del_mismo_equipo_con_otro_nombre_no_llega_a_conectar(tmp_path):
    mundo = nas_simulado()
    h, ctx = montar(tmp_path, {HOST: mundo})
    assert h.nas_alta("a", HOST)["ok"] is True
    conexiones = mundo.conexiones
    r = h.nas_alta("b", HOST)
    assert r["ok"] is False and "ya esta en el inventario como a" in r["error"]
    assert mundo.conexiones == conexiones and list(guardado(ctx)) == ["a"]


def test_alta_del_mismo_host_en_otro_puerto_es_otro_equipo(tmp_path):
    mundo = nas_simulado()
    h, ctx = montar(tmp_path, {HOST: mundo})
    assert h.nas_alta("a", HOST)["ok"] is True
    assert h.nas_alta("b", HOST, port=2222)["ok"] is True


def test_alta_no_devuelve_la_contrasena_ni_en_el_perfil(tmp_path):
    mundo = nas_simulado()
    mundo.respuestas[DET] = HERO.replace("nombre=NAS-EJEMPLO", "nombre=secreto")
    h, _ = montar(tmp_path, {HOST: mundo})
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is True and r["perfil"]["nombre"] == "***"
    assert "secreto" not in str(r)


def test_alta_fallida_cuyo_olvido_de_la_huella_falla_conserva_el_error(tmp_path, monkeypatch):
    mundo = nas_simulado()
    mundo.respuestas["id"] = ID_NORMAL
    h, ctx = montar(tmp_path, {HOST: mundo})

    def falla(cfg, nas):
        raise PermissionError(13, "known_hosts en uso")
    monkeypatch.setattr(transporte, "olvidar_host", falla)
    r = h.nas_alta("casa", HOST)
    assert r["ok"] is False
    assert "administrators" in r["error"]                       # el error de verdad no se pierde
    assert "known_hosts" in r["error"]                         # y se dice que la huella quedo


# --- la huella de host y el inventario -------------------------------------------------------------------

def test_baja_cuyo_olvido_de_la_huella_falla_deja_el_nas_para_repetirla(tmp_path, monkeypatch):
    h, ctx = montar(tmp_path, {HOST: nas_simulado()})
    assert h.nas_alta("casa", HOST)["ok"] is True
    real = transporte.olvidar_host

    def falla(cfg, nas):
        raise PermissionError(13, "known_hosts en uso")
    monkeypatch.setattr(transporte, "olvidar_host", falla)
    r = h.nas_baja("casa")
    assert r["ok"] is False and "PermissionError" in r["error"]
    assert "casa" in guardado(ctx)                              # sigue dado de alta
    monkeypatch.setattr(transporte, "olvidar_host", real)
    assert h.nas_baja("casa")["ok"] is True                     # y repetirla funciona
    assert hosts_fijados(ctx) == [] and guardado(ctx) == {}


def importado(tmp_path, entradas):
    fichero = tmp_path / "importar.toml"
    inv.guardar(fichero, entradas)
    return str(fichero)


def test_importar_con_sobrescribir_y_otro_host_olvida_la_huella_del_viejo(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado()})
    assert h.nas_alta("casa", HOST)["ok"] is True
    r = h.inventario_importar(importado(tmp_path, {"casa": Nas("casa", "192.0.2.77")}), sobrescribir=True)
    assert r["sustituidos"] == ["casa"]
    assert hosts_fijados(ctx) == []


def test_importar_con_otro_host_conserva_la_huella_si_otro_nas_usa_el_viejo(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado()})
    assert h.nas_alta("casa", HOST)["ok"] is True
    inv.guardar(ctx.cfg.inventario, dict(guardado(ctx), alias=Nas("alias", HOST)))
    h.inventario_importar(importado(tmp_path, {"casa": Nas("casa", "192.0.2.77")}), sobrescribir=True)
    assert hosts_fijados(ctx) == [HOST]


def test_importar_sin_cambiar_el_host_no_toca_la_huella(tmp_path):
    h, ctx = montar(tmp_path, {HOST: nas_simulado()})
    assert h.nas_alta("casa", HOST)["ok"] is True
    h.inventario_importar(importado(tmp_path, {"casa": Nas("casa", HOST, auth="contrasena")}),
                          sobrescribir=True)
    assert hosts_fijados(ctx) == [HOST]
    assert guardado(ctx)["casa"].auth == "contrasena"
