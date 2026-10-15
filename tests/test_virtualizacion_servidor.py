# -*- coding: utf-8 -*-
"""Las 12 herramientas de qnap-virtualizacion sobre NAS simulados que responden con salidas
reales anonimizadas (un QuTS hero y un QTS con Virtualization Station y Container Station).
Los registros de un contenedor y las direcciones de una VM se escriben aqui a mano."""
import asyncio
import json
import re
import shlex
from pathlib import Path

import pytest

import falsos
from qnap_tools import inventario as inv
from qnap_tools import servidor
from qnap_tools.comandos import Comando
from qnap_tools.deteccion import DETECCION
from qnap_tools.inventario import Nas
from qnap_tools.transporte import Conexion
from qnap_tools.virtualizacion import comandos as vc
from qnap_tools.virtualizacion import parsers as p
from qnap_tools.virtualizacion import servidor as virt_srv

DATOS = Path(__file__).parent / "datos"
ENTORNO = {"QNAP_TOOLS_USER": "usuario", "QNAP_TOOLS_PASSWORD": "secreto"}
ORDENES = {nombre: c for nombre, c in vars(vc).items() if isinstance(c, Comando)}
LLAMADAS = {"virtualizacion_resumen": (), "vm_lista": (), "vm_detalle": ("vm1",), "vm_uso": (),
            "vm_snapshots": (), "contenedores_lista": (), "contenedor_detalle": ("contenedor1",),
            "contenedores_uso": (), "contenedor_logs": ("contenedor1",), "contenedores_redes": (),
            "disco_info": ("/Vms/carpeta/disco1.img",), "vm_definicion_fichero": ("/Vms/carpeta",)}
DE_VM = ("vm_lista", "vm_detalle", "vm_uso", "vm_snapshots")
DE_FICHEROS = ("disco_info", "vm_definicion_fichero")
DE_CONTENEDORES = ("contenedores_lista", "contenedor_detalle", "contenedores_uso", "contenedor_logs",
                   "contenedores_redes")
# un valor valido de cada tipo de parametro y la expresion que casa con cualquier otro
CENTINELAS = {"uuid": ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "[0-9a-f-]{36}"), "entero": ("987654", "[0-9]+"),
              "nombre": ("zzNOMBREzz", "[A-Za-z0-9_.-]+"), "ruta": ("/share/zzRUTAzz", "/share/[^\x00-\x1f]+")}
GIB = 1024 ** 3
VM1_HERO = "00000000-0000-0000-0000-000000000006"
VM3_HERO = "00000000-0000-0000-0000-000000000004"           # apagada, con tres instantaneas
SIN_SOCKETS = "\n".join(linea for linea in (DATOS / "virtualizacion" / "anfitrion_hero.txt").read_text(
    encoding="utf-8").splitlines() if not linea.startswith("socket=")) + "\n"
DOCKER_CAIDO = (1, "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                       "Is the docker daemon running?\n")
RC_BIEN = "\n==rc 0\n"               # lo que la orden del registro anade: el codigo de salida de docker


def dato(nombre):
    return (DATOS / "virtualizacion" / (nombre + ".txt")).read_text(encoding="utf-8")


def patron(comando):
    """Expresion regular de la orden de un Comando con parametros: un grupo por parametro."""
    texto = re.escape(comando.render({n: CENTINELAS[t][0] for n, t in comando.params.items()}))
    for nombre, tipo in comando.params.items():
        texto = texto.replace(re.escape(CENTINELAS[tipo][0]), "(?P<%s>%s)" % (nombre, CENTINELAS[tipo][1]))
    return re.compile("^" + texto + "$")


P_IP, P_DETALLE, P_LOGS = patron(vc.VM_IP), patron(vc.CT_DETALLE), patron(vc.CT_LOGS)
P_INFO, P_CHECK, P_DEFINICION = patron(vc.DISCO_INFO), patron(vc.DISCO_CHECK), patron(vc.VM_DEFINICION_FICHERO)
CON_PARAMETROS = ((P_IP, vc.VM_IP), (P_DETALLE, vc.CT_DETALLE), (P_LOGS, vc.CT_LOGS), (P_INFO, vc.DISCO_INFO),
                  (P_CHECK, vc.DISCO_CHECK), (P_DEFINICION, vc.VM_DEFINICION_FICHERO))


def deteccion(sistema, vs=True, cs=True):
    """Lo que responde el NAS al identificarse, con los paquetes que se pidan activos."""
    base = (DATOS / ("deteccion_%s.txt" % sistema)).read_text(encoding="utf-8")
    lineas = [linea for linea in base.splitlines() if not linea.startswith("paquete.")]
    for paquete, activo in (("QKVM", vs), ("container-station", cs)):
        lineas += ["paquete.%s.enable=%s" % (paquete, "TRUE" if activo else "FALSE"),
                   "paquete.%s.ruta=/share/DATOS/.qpkg/%s" % (paquete, paquete)]
    return "\n".join(lineas) + "\n"


def registro(orden, sudo):
    """Tantas lineas de registro como pida la orden."""
    lineas = int(P_LOGS.match(orden).group("lineas"))
    return "".join("linea %d del registro\n" % i for i in range(1, lineas + 1)) + RC_BIEN


def nas_simulado(sistema, vs=True, cs=True, **extra):
    """Un NAS simulado: responde a cada orden de los paquetes que tiene con su salida real."""
    respuestas = {DETECCION.render(): deteccion(sistema, vs, cs)}
    for nombre, comando in ORDENES.items():
        suya = (vs or cs) if nombre == "ANFITRION" else (vs if nombre.startswith("VM_") else cs)
        if suya and not comando.params:
            respuestas[comando.render()] = dato("%s_%s" % (comando.id, sistema))
    if vs:
        respuestas[P_IP] = dato("vm_ip_" + sistema)
        respuestas[P_INFO] = dato("disco_info_" + sistema)
        respuestas[P_CHECK] = dato("disco_check_" + sistema)
        respuestas[P_DEFINICION] = dato("vm_definicion_fichero_" + sistema)
    if cs:
        respuestas[P_DETALLE] = lambda orden, sudo: dato("ct_detalle_" + sistema).replace(
            'nombre="/contenedor1"', 'nombre="/%s"' % P_DETALLE.match(orden).group("contenedor"))
        respuestas[P_LOGS] = registro
    return falsos.Mundo(respuestas, **extra)


def montar(tmp_path, mundos, entorno=None):
    """Herramientas de virtualizacion sobre NAS simulados: un Mundo por nombre de NAS."""
    entorno = dict(ENTORNO if entorno is None else entorno, QNAP_TOOLS_DATA=str(tmp_path))

    def fabrica(nas, cfg):
        return Conexion(nas, cfg, fabrica=mundos[nas.nombre].cliente)
    ctx = servidor.Contexto(entorno, fabrica_conexion=fabrica)
    nas = {n: Nas(n, "192.0.2.%d" % (i + 10)) for i, n in enumerate(sorted(mundos))}
    inv.guardar(Path(tmp_path) / "inventario.toml", nas)
    return virt_srv.Herramientas(ctx)


def uno(tmp_path, sistema="hero", cambios=None, **paquetes):
    """Un solo NAS simulado; 'cambios' sustituye la respuesta a algunas ordenes (por su
    texto, o por su patron si llevan parametros)."""
    mundo = nas_simulado(sistema, **paquetes)
    for clave, respuesta in (cambios or {}).items():
        assert clave in mundo.respuestas, clave
        mundo.respuestas[clave] = respuesta
    return montar(tmp_path, {sistema: mundo}), mundo


def datos(resultado):
    (r,) = resultado
    assert r["ok"] is True, r
    return r["datos"]


def fallo(resultado):
    (r,) = resultado
    assert r["ok"] is False, r
    return r["error"]


def por(lista, clave, valor):
    (x,) = [x for x in lista if x[clave] == valor]
    return x


def algun(avisos, *trozos):
    return any(all(t in a for t in trozos) for a in avisos)


def todas_las_llamadas(h, nas):
    return {nombre: getattr(h, nombre)(nas, *extra) for nombre, extra in LLAMADAS.items()}


def lanzadas(mundo, trozo):
    return [orden for orden, _ in mundo.ordenes if trozo in orden]


def estadisticas_con(sistema, uuid, **cambios):
    """Las estadisticas reales con otros valores en los campos de una VM."""
    antes, marca, resto = dato("vm_estadisticas_" + sistema).partition("Domain: '%s'\n" % uuid)
    suya, salto, despues = resto.partition("\n\n")
    assert marca
    for campo, valor in cambios.items():
        campo = campo.replace("_", ".")
        suya, n = re.subn(r"(?m)^(\s*%s)=.*$" % re.escape(campo), lambda m: "%s=%s" % (m.group(1), valor), suya)
        assert n == 1, campo
    return antes + marca + suya + salto + despues


def lista_con(sistema, nombre, **cambios):
    """La lista real de contenedores con otro estado o detalle en uno de ellos."""
    columnas = {"estado": 2, "detalle": 3}
    lineas = dato("ct_lista_" + sistema).splitlines()
    (i,) = [i for i, linea in enumerate(lineas) if linea.split("\t")[0] == nombre]
    campos = lineas[i].split("\t")
    for clave, valor in cambios.items():
        campos[columnas[clave]] = valor
    lineas[i] = "\t".join(campos)
    return "\n".join(lineas) + "\n"


# --- lo que vale para todas ---------------------------------------------------------------------

def test_cada_herramienta_responde_en_los_dos_sistemas_por_una_sola_conexion(tmp_path):
    mundos = {"hero": nas_simulado("hero"), "qts": nas_simulado("qts")}
    h = montar(tmp_path, mundos)
    assert sorted(LLAMADAS) == sorted(virt_srv.HERRAMIENTAS)
    for nombre, r in todas_las_llamadas(h, "todos").items():
        assert [(e["nas"], e["ok"]) for e in r] == [("hero", True), ("qts", True)], (nombre, r)
        if nombre != "virtualizacion_resumen":
            assert all(e["datos"]["activo"] is True and "errores" not in e["datos"] for e in r), (nombre, r)
    assert [m.conexiones for m in mundos.values()] == [1, 1]


def test_el_servidor_solo_lanza_ordenes_definidas_y_con_sudo_solo_las_marcadas(tmp_path):
    mundos = {"hero": nas_simulado("hero"), "qts": nas_simulado("qts")}
    todas_las_llamadas(montar(tmp_path, mundos), "todos")
    definidas = {c.render(): c.sudo for c in ORDENES.values() if not c.params}
    definidas[DETECCION.render()] = False
    con_sudo = set()
    for mundo in mundos.values():
        for orden, sudo in mundo.ordenes:
            if orden in definidas:
                assert definidas[orden] is sudo, orden
            else:
                (comando,) = [c for patron_, c in CON_PARAMETROS if patron_.match(orden)]
                assert comando.sudo is sudo, orden
            if sudo:
                con_sudo.add(orden)
    assert con_sudo == {vc.CT_LXD.render()}


def test_no_hay_ninguna_orden_de_la_pata_que_no_use_alguna_herramienta(tmp_path):
    mundos = {"hero": nas_simulado("hero"), "qts": nas_simulado("qts")}
    todas_las_llamadas(montar(tmp_path, mundos), "todos")
    for sistema, mundo in mundos.items():
        vistas = {orden for orden, _ in mundo.ordenes}
        sin_uso = [nombre for nombre, c in ORDENES.items() if not c.params and c.render() not in vistas]
        sin_uso += [c.id for patron_, c in CON_PARAMETROS if not any(patron_.match(o) for o in vistas)]
        assert sin_uso == [], sistema


def test_el_servidor_registra_las_doce_herramientas_con_descripcion(tmp_path):
    mcp = virt_srv.construir(dict(ENTORNO, QNAP_TOOLS_DATA=str(tmp_path)))
    herramientas = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert sorted(herramientas) == [
        "contenedor_detalle", "contenedor_logs", "contenedores_lista", "contenedores_redes", "contenedores_uso",
        "disco_info", "virtualizacion_resumen", "vm_definicion_fichero", "vm_detalle", "vm_lista", "vm_snapshots",
        "vm_uso"]
    assert all(t.description and len(t.description) > 40 for t in herramientas.values())
    assert all("nas" in t.inputSchema["required"] for t in herramientas.values())
    assert herramientas["vm_detalle"].inputSchema["required"] == ["nas", "vm"]
    assert herramientas["contenedor_detalle"].inputSchema["required"] == ["nas", "contenedor"]
    registros = herramientas["contenedor_logs"].inputSchema
    assert set(registros["properties"]) == {"nas", "contenedor", "lineas"}
    assert registros["required"] == ["nas", "contenedor"] and registros["properties"]["lineas"]["default"] == 50


def test_el_servidor_arranca_aunque_falte_la_credencial():
    assert len(asyncio.run(virt_srv.construir({}).list_tools())) == 12


def test_un_nas_desconocido_y_la_falta_de_credencial_se_dicen_en_el_error(tmp_path):
    h, _ = uno(tmp_path)
    assert "otro" in fallo(h.vm_lista("otro"))
    sin = montar(tmp_path, {"hero": nas_simulado("hero")}, entorno={})
    assert "contrasena" in fallo(sin.contenedores_lista("hero")).lower()


def test_la_contrasena_no_sale_en_un_error(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.CT_LISTA.plantilla: (1, "", "fallo raro con secreto dentro\n")})
    error = fallo(h.contenedores_lista("hero"))
    assert "secreto" not in error and "***" in error


# --- sin el paquete, o con su servicio parado ---------------------------------------------------

def test_sin_los_dos_paquetes_ninguna_herramienta_lanza_nada(tmp_path):
    h, mundo = uno(tmp_path, "qts", vs=False, cs=False)
    for nombre, r in todas_las_llamadas(h, "qts").items():
        d = datos(r)
        if nombre == "virtualizacion_resumen":
            assert d["maquinas_virtuales"]["activo"] is False and d["contenedores"]["activo"] is False
            assert "Virtualization Station" in d["maquinas_virtuales"]["motivo"]
            assert "Container Station" in d["contenedores"]["motivo"]
            assert d["avisos"] == [] and "errores" not in d
        else:
            assert d["activo"] is False and "Station" in d["motivo"], nombre
            assert set(d) == {"activo", "motivo"}, nombre
    assert set(mundo.ordenes) == {(DETECCION.render(), False)}


def test_el_nas_de_pruebas_sin_paquetes_responde_que_no_estan_activos(tmp_path):
    # la deteccion capturada de QTS es la de un NAS con VS desactivada y sin Container Station
    mundo = falsos.Mundo({DETECCION.render(): (DATOS / "deteccion_qts.txt").read_text(encoding="utf-8")})
    h = montar(tmp_path, {"qts": mundo})
    assert datos(h.vm_lista("qts"))["activo"] is False
    assert datos(h.contenedores_lista("qts"))["activo"] is False


def test_sin_virtualization_station_no_se_lanza_virsh_y_los_contenedores_siguen(tmp_path):
    h, mundo = uno(tmp_path, vs=False)
    respuestas = todas_las_llamadas(h, "hero")
    for nombre in DE_VM + DE_FICHEROS:
        assert datos(respuestas[nombre])["activo"] is False, nombre
    for nombre in DE_CONTENEDORES:
        assert datos(respuestas[nombre])["activo"] is True, nombre
    resumen = datos(respuestas["virtualizacion_resumen"])
    assert resumen["maquinas_virtuales"]["activo"] is False and resumen["contenedores"]["total"] == 6
    assert lanzadas(mundo, "virsh") == [] and lanzadas(mundo, "qemu-img") == []


def test_sin_container_station_no_se_lanza_docker_y_las_vms_siguen(tmp_path):
    h, mundo = uno(tmp_path, cs=False)
    respuestas = todas_las_llamadas(h, "hero")
    for nombre in DE_CONTENEDORES:
        assert datos(respuestas[nombre])["activo"] is False, nombre
    for nombre in DE_VM + DE_FICHEROS:
        assert datos(respuestas[nombre])["activo"] is True, nombre
    resumen = datos(respuestas["virtualizacion_resumen"])
    assert resumen["contenedores"]["activo"] is False and resumen["maquinas_virtuales"]["total"] == 6
    assert lanzadas(mundo, "/bin/docker") == [] and lanzadas(mundo, "/var/lib/lxd") == []


def test_un_paquete_con_la_ruta_mal_lo_dice_en_el_motivo(tmp_path):
    h, _ = uno(tmp_path, cambios={DETECCION.plantilla: deteccion("hero").replace("/share/DATOS/.qpkg/QKVM", "/share/a b/QKVM")})
    motivo = datos(h.vm_lista("hero"))["motivo"]
    assert "QKVM" in motivo and "ruta" in motivo


def test_un_paquete_activado_despues_de_conectar_se_ve_sin_reiniciar(tmp_path):
    h, mundo = uno(tmp_path, cs=False)
    assert datos(h.contenedores_lista("hero"))["activo"] is False
    assert datos(h.virtualizacion_resumen("hero"))["contenedores"]["activo"] is False
    mundo.respuestas.update(nas_simulado("hero").respuestas)        # se instala Container Station
    assert datos(h.contenedores_lista("hero"))["contenedores"]["total"] == 6
    assert datos(h.virtualizacion_resumen("hero"))["contenedores"]["total"] == 6
    assert mundo.conexiones == 1


def test_un_paquete_desactivado_despues_de_conectar_no_sale_como_servicio_parado(tmp_path):
    h, mundo = uno(tmp_path)
    assert datos(h.vm_lista("hero"))["activo"] is True
    # se desactiva Virtualization Station: deja de estar su socket y cambia qpkg.conf
    mundo.respuestas[DETECCION.render()] = deteccion("hero", vs=False)
    mundo.respuestas[vc.ANFITRION.render()] = dato("anfitrion_hero").replace(
        "socket=/QVS/var/run/libvirt/libvirt-sock-ro\n", "")
    d = datos(h.vm_lista("hero"))
    assert d["activo"] is False and "Virtualization Station" in d["motivo"]
    resumen = datos(h.virtualizacion_resumen("hero"))
    assert resumen["maquinas_virtuales"]["activo"] is False and resumen["avisos"] == []
    assert resumen["contenedores"]["total"] == 6


def test_el_paquete_activo_con_el_servicio_parado_es_un_error_y_no_una_lista_vacia(tmp_path):
    h, mundo = uno(tmp_path, cambios={vc.ANFITRION.plantilla: SIN_SOCKETS})
    for nombre in DE_VM:
        error = fallo(getattr(h, nombre)("hero", *LLAMADAS[nombre]))
        assert "Virtualization Station" in error and "servicio" in error, nombre
    for nombre in DE_CONTENEDORES:
        error = fallo(getattr(h, nombre)("hero", *LLAMADAS[nombre]))
        assert "Container Station" in error and "servicio" in error, nombre
    assert lanzadas(mundo, "virsh") == [] and lanzadas(mundo, "/bin/docker") == []


def test_el_resumen_avisa_del_servicio_parado_sin_fallar(tmp_path):
    h, mundo = uno(tmp_path, cambios={vc.ANFITRION.plantilla: SIN_SOCKETS})
    d = datos(h.virtualizacion_resumen("hero"))
    assert d["maquinas_virtuales"] == {"activo": True, "servicio": False}
    assert d["contenedores"] == {"activo": True, "servicio": False}
    assert algun(d["avisos"], "Virtualization Station", "servicio") and algun(d["avisos"], "Container Station", "servicio")
    assert d["nas"]["hilos"] == 4
    assert lanzadas(mundo, "virsh") == [] and lanzadas(mundo, "/bin/docker") == []


# --- el resumen ---------------------------------------------------------------------------------

def test_el_resumen_de_hero_cuenta_maquinas_y_contenedores(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.virtualizacion_resumen("hero"))
    assert d["sistema"] == "hero" and "errores" not in d and d["avisos"] == []
    assert d["nas"] == {"hilos": 4, "cpu": "Intel(R) Xeon(R) CPU D-1602 @ 2.50GHz", "virtualizacion": "vmx",
                        "carga": [2.17, 1.29, 1.2], "memoria": p.anfitrion(dato("anfitrion_hero"))["memoria"]}
    assert d["maquinas_virtuales"] == {
        "activo": True, "servicio": True, "total": 6, "por_estado": {"en marcha": 2, "apagada": 4},
        "vcpus_en_marcha": 4, "memoria_en_marcha": 8 * GIB}
    assert d["contenedores"] == {
        "activo": True, "servicio": True, "version": "27.1.2-qnap12", "total": 6, "por_estado": {"exited": 6},
        "imagenes": 5, "internos": [], "lxd": {"contenedores": [], "maquinas": []}}


def test_el_resumen_de_qts_avisa_del_contenedor_que_no_esta_sano(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.virtualizacion_resumen("qts"))
    assert d["maquinas_virtuales"]["por_estado"] == {"en marcha": 3, "apagada": 6}
    assert d["maquinas_virtuales"]["memoria_en_marcha"] == 20 * GIB
    assert d["contenedores"]["total"] == 45 and d["contenedores"]["por_estado"] == {"running": 34, "exited": 11}
    assert d["contenedores"]["internos"] == [{"nombre": "qcal", "imagen": "qcal:1.1", "estado": "running"}]
    (aviso,) = d["avisos"]
    enfermo = por(datos(h.contenedores_lista("qts"))["contenedores"]["filas"], "salud", "unhealthy")
    assert enfermo["nombre"] in aviso and "unhealthy" in aviso


@pytest.mark.parametrize("cambios, trozos", [
    ({"estado": "restarting", "detalle": "Restarting (1) 5 seconds ago"}, ("contenedor2", "restarting")),
    ({"estado": "dead", "detalle": "Dead"}, ("contenedor2", "dead")),
    ({"estado": "paused", "detalle": "Up 2 hours (Paused)"}, ("contenedor2", "paused")),
    ({"estado": "running", "detalle": "Up 2 hours (unhealthy)"}, ("contenedor2", "unhealthy")),
    ({"estado": "algo-nuevo", "detalle": "Up"}, ("contenedor2", "algo-nuevo"))])
def test_un_contenedor_reiniciandose_muerto_o_no_sano_sale_en_los_avisos(tmp_path, cambios, trozos):
    h, _ = uno(tmp_path, cambios={vc.CT_LISTA.plantilla: lista_con("hero", "contenedor2", **cambios)})
    assert algun(datos(h.virtualizacion_resumen("hero"))["avisos"], *trozos)


def test_muchos_contenedores_con_aviso_no_llenan_la_respuesta(tmp_path):
    filas = "".join("c%d\timagen:1\trestarting\tRestarting (1) 1 second ago\t\tbridge\t2026-10-01 00:00:00 +0200 CEST\t\n"
                    % i for i in range(300))
    h, _ = uno(tmp_path, cambios={vc.CT_LISTA.plantilla: filas})
    avisos = datos(h.virtualizacion_resumen("hero"))["avisos"]
    assert len(avisos) <= virt_srv.MAX_AVISOS + 1 and algun(avisos, "300")


@pytest.mark.parametrize("motivo, trozos", [(3, ("vm1", "caida")), (6, ("vm1", "arrancar"))])
def test_una_vm_apagada_por_una_caida_o_un_fallo_al_arrancar_avisa_y_sigue_apagada(tmp_path, motivo, trozos):
    # libvirt: shut off con motivo 3 (crashed) o 6 (failed); no visto aun en un NAS
    h, _ = uno(tmp_path, cambios={vc.VM_ESTADISTICAS.plantilla: estadisticas_con(
        "hero", VM1_HERO, state_state=5, state_reason=motivo)})
    d = datos(h.virtualizacion_resumen("hero"))
    assert algun(d["avisos"], *trozos)
    assert d["maquinas_virtuales"]["por_estado"] == {"en marcha": 1, "apagada": 5}
    assert por(datos(h.vm_lista("hero"))["vms"]["filas"], "nombre", "vm1")["estado"] == "apagada"


@pytest.mark.parametrize("motivo", [0, 1, 2, 4])
def test_una_vm_apagada_por_otro_motivo_no_avisa(tmp_path, motivo):
    h, _ = uno(tmp_path, cambios={vc.VM_ESTADISTICAS.plantilla: estadisticas_con(
        "hero", VM1_HERO, state_state=5, state_reason=motivo)})
    assert datos(h.virtualizacion_resumen("hero"))["avisos"] == []


@pytest.mark.parametrize("codigo, estado", [(3, "en pausa"), (2, "bloqueada"), (6, "caida"), (9, "estado 9")])
def test_una_vm_en_pausa_bloqueada_o_caida_sale_en_los_avisos(tmp_path, codigo, estado):
    h, _ = uno(tmp_path, cambios={vc.VM_ESTADISTICAS.plantilla: estadisticas_con("hero", VM1_HERO, state_state=codigo)})
    d = datos(h.virtualizacion_resumen("hero"))
    assert algun(d["avisos"], "vm1", estado) and d["maquinas_virtuales"]["por_estado"][estado] == 1


def test_una_vm_suspendida_sale_como_tal_y_en_los_avisos(tmp_path):
    # como una VM del NAS de laboratorio tras suspenderla desde Virtualization Station
    h, _ = uno(tmp_path, cambios={vc.VM_ESTADISTICAS.plantilla: estadisticas_con(
        "hero", VM1_HERO, state_state=5, state_reason=5)})
    d = datos(h.virtualizacion_resumen("hero"))
    assert d["maquinas_virtuales"]["por_estado"] == {"en marcha": 1, "apagada": 4, "suspendida": 1}
    assert d["maquinas_virtuales"]["vcpus_en_marcha"] == 2           # no corre: no cuenta
    assert algun(d["avisos"], "vm1", "suspendida", "disco")
    assert por(datos(h.vm_lista("hero"))["vms"]["filas"], "nombre", "vm1")["estado"] == "suspendida"


def con_memoria_guardada(sistema, uuid, linea="guardada 3252802928 1792011004"):
    marca = "== %s\n" % uuid
    texto = dato("vm_guardadas_" + sistema)
    assert marca in texto
    return texto.replace(marca, marca + linea + "\n")


def test_una_vm_suspendida_antes_de_reiniciar_el_nas_sigue_saliendo_suspendida(tmp_path):
    # como dos VMs del NAS de laboratorio (2026-10-14): VS las suspendio al reiniciar y,
    # ya arrancado, libvirt solo dice "apagada" (motivo 0); queda su memoria en <uuid>.state
    h, _ = uno(tmp_path, cambios={
        vc.VM_ESTADISTICAS.plantilla: estadisticas_con("hero", VM1_HERO, state_state=5, state_reason=0),
        vc.VM_GUARDADAS.plantilla: con_memoria_guardada("hero", VM1_HERO)})
    d = datos(h.virtualizacion_resumen("hero"))
    assert d["maquinas_virtuales"]["por_estado"] == {"en marcha": 1, "apagada": 4, "suspendida": 1}
    assert algun(d["avisos"], "vm1", "suspendida", "disco", "3.0 GiB", "2026-10-14T20:50:04Z")
    assert por(datos(h.vm_lista("hero"))["vms"]["filas"], "nombre", "vm1")["estado"] == "suspendida"
    detalle = datos(h.vm_detalle("hero", "vm1"))["vm"]
    assert detalle["estado"] == "suspendida"
    assert detalle["memoria_guardada"] == {"bytes": 3252802928, "fecha": "2026-10-14T20:50:04Z"}


def test_la_memoria_guardada_solo_cuenta_con_la_vm_apagada(tmp_path):
    # en marcha manda libvirt, aunque quedara un fichero de una suspension anterior
    h, _ = uno(tmp_path, cambios={vc.VM_GUARDADAS.plantilla: con_memoria_guardada("hero", VM1_HERO)})
    d = datos(h.virtualizacion_resumen("hero"))
    assert d["maquinas_virtuales"]["por_estado"] == {"en marcha": 2, "apagada": 4}
    assert not algun(d["avisos"], "suspendida")


def test_sin_poder_leer_la_memoria_guardada_las_vms_salen_con_lo_que_dice_libvirt_y_se_dice(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.VM_GUARDADAS.plantilla: (1, "", "error: failed to connect\n")})
    d = datos(h.virtualizacion_resumen("hero"))
    assert d["maquinas_virtuales"]["por_estado"] == {"en marcha": 2, "apagada": 4}
    assert "memoria_guardada" in d["errores"]
    filas = datos(h.vm_lista("hero"))
    assert "memoria_guardada" in filas["errores"] and len(filas["vms"]["filas"]) == 6


def test_el_resumen_avisa_si_las_vms_en_marcha_tienen_mas_memoria_que_el_nas(tmp_path):
    poca = dato("anfitrion_hero").replace("MemTotal:       32771296 kB", "MemTotal:        6291456 kB")
    h, _ = uno(tmp_path, cambios={vc.ANFITRION.plantilla: poca})
    assert algun(datos(h.virtualizacion_resumen("hero"))["avisos"], "memoria", "8.0 GiB", "6.0 GiB")


def test_el_resumen_dice_lo_que_no_ha_podido_mirar(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.CT_LXD.plantilla: (1, "", "ls: permiso denegado\n"), vc.VM_XML.plantilla: (1, "", "error\n")})
    d = datos(h.virtualizacion_resumen("hero"))
    assert set(d["errores"]) == {"lxd", "maquinas_virtuales"}
    assert d["contenedores"]["lxd"] is None and d["contenedores"]["total"] == 6
    assert d["maquinas_virtuales"] == {"activo": True, "servicio": True, "total": None, "por_estado": None,
                                       "vcpus_en_marcha": None, "memoria_en_marcha": None}


def test_el_resumen_no_da_por_buenos_cero_contenedores_si_docker_no_responde(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.CT_LISTA.plantilla: DOCKER_CAIDO})
    d = datos(h.virtualizacion_resumen("hero"))
    assert "contenedores" in d["errores"] and d["contenedores"]["total"] is None
    assert d["maquinas_virtuales"]["total"] == 6


def test_sin_docker_interno_no_se_le_pregunta(tmp_path):
    sin_interno = dato("anfitrion_hero").replace("socket=/var/run/system-docker.sock\n", "")
    h, mundo = uno(tmp_path, cambios={vc.ANFITRION.plantilla: sin_interno})
    d = datos(h.virtualizacion_resumen("hero"))
    assert d["contenedores"]["internos"] is None and "errores" not in d
    assert lanzadas(mundo, "system-docker.sock ps") == []


def test_las_instancias_de_lxd_se_cuentan_en_el_resumen(tmp_path):
    lxd = "== /var/lib/lxd/containers\nubuntu-lab\n== /var/lib/lxd/virtual-machines\n"
    h, _ = uno(tmp_path, cambios={vc.CT_LXD.plantilla: lxd})
    assert datos(h.virtualizacion_resumen("hero"))["contenedores"]["lxd"] == {"contenedores": ["ubuntu-lab"], "maquinas": []}


# --- maquinas virtuales -------------------------------------------------------------------------

def test_vm_lista_da_cada_vm_con_su_estado_y_sus_discos(tmp_path):
    h, _ = uno(tmp_path)
    vms = datos(h.vm_lista("hero"))["vms"]
    assert vms["total"] == 6 and vms["truncado"] is False
    assert por(vms["filas"], "nombre", "vm2") == {
        "nombre": "vm2", "uuid": "00000000-0000-0000-0000-000000000002", "estado": "en marcha", "vcpus": 2,
        "memoria": 4 * GIB, "sistema": "win2012r2", "arranque_automatico": {"modo": "off", "retraso_s": 60},
        # tres discos; la unidad de CD no cuenta
        "discos": 3, "capacidad": 107374182400 + 1099511627776 + 1623497637888}
    assert por(vms["filas"], "nombre", "vm3")["estado"] == "apagada"


def test_vm_lista_en_qts_da_las_nueve(tmp_path):
    h, _ = uno(tmp_path, "qts")
    filas = datos(h.vm_lista("qts"))["vms"]["filas"]
    assert [v["nombre"] for v in filas] == ["vm%d" % i for i in range(1, 10)]
    assert por(filas, "nombre", "vm9")["arranque_automatico"]["modo"] == "quo"
    assert [v["nombre"] for v in filas if v["estado"] == "en marcha"] == ["vm1", "vm2", "vm3"]


@pytest.mark.parametrize("respuesta", ["", "uri=\n", "uri=qemu:///session\n", "error: failed to connect\n"])
def test_un_libvirt_que_no_es_el_del_sistema_es_un_error_y_no_cero_maquinas(tmp_path, respuesta):
    for comando in (vc.VM_ESTADISTICAS, vc.VM_XML):
        h, _ = uno(tmp_path, cambios={comando.plantilla: respuesta})
        fallo(h.vm_lista("hero"))
        assert "maquinas_virtuales" in datos(h.virtualizacion_resumen("hero"))["errores"]


def test_si_una_consulta_ve_maquinas_y_la_otra_ninguna_es_un_error(tmp_path):
    vacia = "uri=qemu:///system\n"
    for comando in (vc.VM_ESTADISTICAS, vc.VM_XML):
        h, _ = uno(tmp_path, cambios={comando.plantilla: vacia})
        assert "mismas" in fallo(h.vm_lista("hero"))
    h, _ = uno(tmp_path, cambios={vc.VM_ESTADISTICAS.plantilla: vacia, vc.VM_XML.plantilla: vacia})
    assert datos(h.vm_lista("hero"))["vms"] == {"filas": [], "total": 0, "truncado": False}
    assert datos(h.virtualizacion_resumen("hero"))["maquinas_virtuales"]["total"] == 0


def xml_con_vm1_ilegible():
    real = dato("vm_xml_hero")
    marca = "== %s\n" % VM1_HERO
    assert real.count(marca) == 1
    return real.replace(marca, marca + "  <memory unit='MiB'>4096</memory>\n")


def test_una_vm_con_una_definicion_que_no_se_entiende_no_tumba_a_las_demas(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.VM_XML.plantilla: xml_con_vm1_ilegible()})
    vms = datos(h.vm_lista("hero"))["vms"]["filas"]
    assert len(vms) == 6
    rara = por(vms, "uuid", VM1_HERO)
    assert rara["nombre"] == "vm1" and rara["estado"] == "en marcha" and "definicion" in rara["error"]
    assert rara["discos"] is None and rara["capacidad"] is None
    # lo que si sabe libvirt de ella sigue saliendo
    assert rara["vcpus"] == 2 and rara["memoria"] == 4 * GIB
    assert "error" not in por(vms, "nombre", "vm2")
    d = datos(h.virtualizacion_resumen("hero"))
    assert d["maquinas_virtuales"]["total"] == 6 and d["maquinas_virtuales"]["vcpus_en_marcha"] == 4
    assert algun(d["avisos"], "vm1", "definicion")
    assert datos(h.vm_detalle("hero", "vm2"))["vm"]["nombre"] == "vm2"
    detalle = datos(h.vm_detalle("hero", "vm1"))["vm"]
    assert detalle["error"] and detalle["discos"] is None and detalle["interfaces"] is None
    assert detalle["estado"] == "en marcha"
    instantaneas = datos(h.vm_snapshots("hero"))["vms"]["filas"]
    assert len(instantaneas) == 6 and "definicion" in por(instantaneas, "uuid", VM1_HERO)["error"]
    assert "error" not in por(instantaneas, "nombre", "vm2")


def test_vm_detalle_vale_por_nombre_o_por_uuid(tmp_path):
    h, _ = uno(tmp_path)
    por_nombre = datos(h.vm_detalle("hero", "vm1"))
    assert por_nombre == datos(h.vm_detalle("hero", VM1_HERO)) == datos(h.vm_detalle("hero", "VM1"))
    vm = por_nombre["vm"]
    assert (vm["nombre"], vm["uuid"], vm["estado"]) == ("vm1", VM1_HERO, "en marcha")
    assert vm["descripcion"] == "descripcion de ejemplo 1" and vm["sistema"] == "win2012r2"
    assert (vm["firmware"], vm["maquina"], vm["arranque"]) == ("bios", "pc-i440fx-7.0", ["cdrom", "hd"])
    assert (vm["vcpus"], vm["memoria"], vm["memoria_actual"]) == (2, 4 * GIB, 4 * GIB)
    assert vm["consola"] == {"tipo": "vnc", "puerto": 5900, "escucha": "127.0.0.1"}
    assert vm["discos"] == [
        {"dispositivo": "hda", "bus": "ide", "clase": "disk", "formato": "qcow2",
         "fichero": "/share/ruta1/vm1/ruta10.1790544225", "capas": 2, "capacidad": 268435456000,
         "ocupa_capa_activa": 785244672},
        {"dispositivo": "hdb", "bus": "ide", "clase": "cdrom", "formato": "raw", "fichero": "/QVS/guest_tools.iso",
         "capas": 1, "capacidad": 132255744, "ocupa_capa_activa": 129872384}]


def test_vm_detalle_pone_a_cada_interfaz_las_direcciones_que_el_nas_conoce(tmp_path):
    tabla = (" Name       MAC address          Protocol     Address\n" + "-" * 79 + "\n"
             " vnet0      00:11:22:33:44:00    ipv4         192.0.2.77/24\n")
    h, mundo = uno(tmp_path, cambios={P_IP: tabla})
    (interfaz,) = datos(h.vm_detalle("hero", "vm1"))["vm"]["interfaces"]
    assert interfaz == {"tipo": "bridge", "mac": "00:11:22:33:44:00", "conmutador": "qvs2", "interfaz": "vnet0",
                        "modelo": "e1000", "direcciones": ["192.0.2.77"]}
    assert lanzadas(mundo, "domifaddr") == [vc.VM_IP.render({"uuid": VM1_HERO})]


def test_a_una_vm_apagada_no_se_le_piden_direcciones(tmp_path):
    h, mundo = uno(tmp_path)
    vm = datos(h.vm_detalle("hero", "vm3"))["vm"]
    assert vm["estado"] == "apagada" and [i["direcciones"] for i in vm["interfaces"]] == [None]
    assert vm["consola"]["puerto"] is None and lanzadas(mundo, "domifaddr") == []
    assert por(vm["discos"], "dispositivo", "hda")["capas"] == 4


def test_sin_tabla_de_direcciones_la_vm_sale_con_el_error_en_su_sitio(tmp_path):
    h, _ = uno(tmp_path, cambios={P_IP: (1, "", "error: Domain not found\n")})
    d = datos(h.vm_detalle("hero", "vm1"))
    assert "direcciones" in d["errores"] and d["vm"]["interfaces"][0]["direcciones"] is None
    assert d["vm"]["nombre"] == "vm1"


@pytest.mark.parametrize("vm", ["", "   ", None, 5, True, 2.5, ["vm1"], "a" * 300, "vm1\nvm2", "vm\x00"])
def test_vm_detalle_rechaza_un_valor_que_no_es_un_nombre_sin_conectar(tmp_path, vm):
    h, mundo = uno(tmp_path)
    assert "vm" in fallo(h.vm_detalle("hero", vm))
    assert mundo.conexiones == 0


@pytest.mark.parametrize("vm", ["x; reboot", "-f", "$(id)", "vm1 --security-info", "no-existe",
                                "00000000-0000-0000-0000-0000000000ff"])
def test_vm_detalle_dice_que_vms_hay_si_la_pedida_no_existe_y_no_lanza_nada_con_ese_valor(tmp_path, vm):
    h, mundo = uno(tmp_path)
    error = fallo(h.vm_detalle("hero", vm))
    assert "vm1, vm2, vm3, vm4, vm5, vm6" in error
    # el valor pedido solo se compara: al NAS no va nada que lo lleve
    assert {orden for orden, _ in mundo.ordenes} == {
        c.render() for c in (DETECCION, vc.ANFITRION, vc.VM_ESTADISTICAS, vc.VM_XML, vc.VM_GUARDADAS)}


def test_vm_detalle_con_un_nombre_repetido_pide_el_uuid(tmp_path):
    repetido = dato("vm_xml_hero").replace("<qvs:name>vm2</qvs:name>", "<qvs:name>vm1</qvs:name>")
    h, _ = uno(tmp_path, cambios={vc.VM_XML.plantilla: repetido})
    error = fallo(h.vm_detalle("hero", "vm1"))
    assert VM1_HERO in error and "00000000-0000-0000-0000-000000000002" in error
    assert datos(h.vm_detalle("hero", VM1_HERO))["vm"]["uuid"] == VM1_HERO


def test_vm_uso_da_las_vms_en_marcha_por_consumo_y_con_su_nombre(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.vm_uso("qts"))
    assert d["segundos"] == 5.02
    assert [(v["nombre"], v["cpu_nucleos"], v["cpu_pct"]) for v in d["vms"]] == [
        ("vm3", 0.3, 7.5), ("vm2", 0.1, 2.5), ("vm1", 0.07, 1.8)]
    vm = d["vms"][0]
    assert vm["vcpus"] == 4 and vm["memoria"] == 10 * GIB and vm["discos"] and vm["red"]


def test_vm_uso_sin_vms_en_marcha_responde_bien_y_vacio(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.VM_USO.plantilla: "uri=qemu:///system\n100.00 200.00\n==rc 0\n==5s\n"
                                                         "uri=qemu:///system\n105.00 210.00\n==rc 0\n"})
    assert datos(h.vm_uso("hero")) == {"activo": True, "segundos": 5.0, "vms": []}


def test_vm_uso_sin_poder_leer_los_nombres_da_las_cifras_con_el_uuid(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.VM_XML.plantilla: (1, "", "error\n")})
    d = datos(h.vm_uso("hero"))
    assert "nombres" in d["errores"] and len(d["vms"]) == 2
    assert all(v["nombre"] is None and v["uuid"] for v in d["vms"])


def test_vm_uso_sin_respuesta_de_libvirt_en_la_primera_lectura_es_un_error(tmp_path):
    # la primera lectura sin libvirt: antes salia "ninguna VM en marcha" con ok
    real = dato("vm_uso_hero")
    antes, marca, despues = real.partition("==5s")
    sin_libvirt = "uri=\n" + antes.split("\n", 1)[1].split("Domain:", 1)[0] + "==rc 1\n" + marca + despues
    h, _ = uno(tmp_path, cambios={vc.VM_USO.render(): sin_libvirt})
    assert "libvirt" in fallo(h.vm_uso("hero"))


def test_vm_uso_con_la_primera_lectura_de_domstats_fallida_es_un_error(tmp_path):
    # libvirt responde a uri pero domstats falla: antes salia "ninguna VM en marcha" con ok
    real = dato("vm_uso_hero")
    antes, marca, despues = real.partition("==5s")
    fallida = antes.split("Domain:", 1)[0] + "==rc 1\n" + marca + despues
    h, _ = uno(tmp_path, cambios={vc.VM_USO.render(): fallida})
    assert "domstats" in fallo(h.vm_uso("hero"))


def test_vm_uso_que_no_termina_es_un_error(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.VM_USO.plantilla: (1, "", "error: failed to connect to the hypervisor\n")})
    fallo(h.vm_uso("hero"))


def test_vm_snapshots_da_las_instantaneas_de_vs_y_la_cadena_de_cada_disco(tmp_path):
    h, _ = uno(tmp_path)
    d = datos(h.vm_snapshots("hero"))
    assert "errores" not in d and d["vms"]["total"] == 6
    vm = por(d["vms"]["filas"], "uuid", VM3_HERO)
    assert (vm["nombre"], vm["tipo"], vm["libvirt"]) == ("vm3", "external", [])
    # de la mas reciente a la mas antigua
    assert vm["instantaneas"] == {"total": 3, "truncado": False, "filas": [
        {"id": 1790199623, "creada": "2026-09-23T21:40:23Z", "con_memoria": False},
        {"id": 1715887104, "creada": "2024-05-16T19:18:24Z", "con_memoria": False},
        {"id": 1715862105, "creada": "2024-05-16T12:21:45Z", "con_memoria": False}]}
    (disco,) = vm["discos"]
    assert disco["fichero"] == "/share/ruta1/vm3/vm3.1790199623" and disco["capas"] == 4
    assert disco["ocupa"] == 952418816 + 76116836864 + 2490585600 + 115389985280
    assert [(c["fichero"].rsplit("/", 1)[1], c["ocupa"], c["desde"]) for c in disco["cadena"]] == [
        ("vm3.1790199623", 952418816, "2026-09-23T21:40:23Z"),
        ("vm3.1715887104", 76116836864, "2024-05-16T19:18:24Z"),
        ("vm3.1715862105_1", 2490585600, "2024-05-16T12:21:45Z"),
        ("vm3.img", 115389985280, None)]
    assert all(c["formato"] == "qcow2" and c["virtual"] == 322122547200 for c in disco["cadena"])
    assert disco["base_sin_leer"] is None and disco["cortada"] is False


def test_vm_snapshots_en_qts_distingue_las_tomadas_con_la_vm_en_marcha(tmp_path):
    h, _ = uno(tmp_path, "qts")
    vms = datos(h.vm_snapshots("qts"))["vms"]["filas"]
    assert por(vms, "nombre", "vm2")["instantaneas"]["filas"] == [
        {"id": 1790104406, "creada": "2026-09-22T19:13:26Z", "con_memoria": True}]
    sin = por(vms, "nombre", "vm1")
    assert sin["instantaneas"] == {"filas": [], "total": 0, "truncado": False}
    assert [d["capas"] for d in sin["discos"]] == [1]
    assert [d["capas"] for d in por(vms, "nombre", "vm5")["discos"]] == [3, 3]


def test_vm_snapshots_sin_poder_leer_las_imagenes_da_el_resto_y_lo_dice(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.VM_IMAGENES.plantilla: (1, "", "error\n"), vc.VM_SNAP_LIBVIRT.plantilla: (1, "", "error\n")})
    d = datos(h.vm_snapshots("hero"))
    assert set(d["errores"]) == {"imagenes", "libvirt"}
    vm = por(d["vms"]["filas"], "uuid", VM3_HERO)
    assert vm["discos"] is None and vm["libvirt"] is None and vm["instantaneas"]["total"] == 3


def test_un_disco_cuya_imagen_no_se_pudo_leer_sale_sin_cadena(tmp_path):
    marca = "-- /share/ruta1/vm1/ruta10.1790544225\n"
    antes, _, resto = dato("vm_imagenes_hero").partition(marca)
    cuerpo, sep, despues = resto.partition("== ")
    h, _ = uno(tmp_path, cambios={vc.VM_IMAGENES.plantilla: antes + marca + sep + despues})
    (disco,) = por(datos(h.vm_snapshots("hero"))["vms"]["filas"], "uuid", VM1_HERO)["discos"]
    assert disco == {"fichero": "/share/ruta1/vm1/ruta10.1790544225", "capas": None, "ocupa": None, "cadena": None,
                     "base_sin_leer": None, "cortada": False}


def test_una_base_remota_no_se_sigue_y_el_disco_lo_dice(tmp_path):
    # escrito a mano sobre la captura: la base de la imagen de vm1 pasa a ser una direccion de red
    real = dato("vm_imagenes_hero")
    base = '"full-backing-filename": "/share/ruta1/vm1/ruta10.img"'
    assert real.count(base) == 1
    marca = "-- /share/ruta1/vm1/ruta10.1790544225\n"
    antes, _, resto = real.partition(marca)
    capa, sep, despues = resto.partition("\n{")             # solo la primera capa: la base no se lee
    texto = antes + marca + capa.replace(base, '"full-backing-filename": "nbd://192.0.2.9/x"') + "\n"
    texto += despues[despues.index("== "):]
    h, _ = uno(tmp_path, cambios={vc.VM_IMAGENES.plantilla: texto})
    (disco,) = por(datos(h.vm_snapshots("hero"))["vms"]["filas"], "uuid", VM1_HERO)["discos"]
    assert disco["capas"] == 1 and disco["base_sin_leer"] == "nbd://192.0.2.9/x"


def test_una_vm_sin_carpeta_de_metadatos_sale_sin_instantaneas_conocidas_y_se_dice(tmp_path):
    marca = "== %s\n" % VM1_HERO
    texto = dato("vm_snap_vs_hero").replace(marca, marca + "!! sin carpeta de metadatos\n")
    h, _ = uno(tmp_path, cambios={vc.VM_SNAP_VS.plantilla: texto})
    d = datos(h.vm_snapshots("hero"))
    vm = por(d["vms"]["filas"], "uuid", VM1_HERO)
    assert vm["instantaneas"] is None and vm["discos"] is not None
    assert "1 " in d["errores"]["instantaneas"] and "metadatos" in d["errores"]["instantaneas"]
    assert por(d["vms"]["filas"], "uuid", VM3_HERO)["instantaneas"]["total"] == 3


def test_una_vm_cuyo_dumpxml_fallo_sale_sin_instantaneas_conocidas_y_se_dice(tmp_path):
    marca = "== %s\n" % VM1_HERO
    texto = dato("vm_snap_vs_hero").replace(marca, marca + "!! dumpxml fallo\n")
    h, _ = uno(tmp_path, cambios={vc.VM_SNAP_VS.plantilla: texto})
    d = datos(h.vm_snapshots("hero"))
    assert por(d["vms"]["filas"], "uuid", VM1_HERO)["instantaneas"] is None
    assert "1 " in d["errores"]["instantaneas"]


def test_si_el_dumpxml_de_una_vm_fallo_la_memoria_guardada_se_dice_en_errores(tmp_path):
    marca = "== %s\n" % VM1_HERO
    texto = dato("vm_guardadas_hero").replace(marca, marca + "!! dumpxml fallo\n")
    h, _ = uno(tmp_path, cambios={vc.VM_GUARDADAS.plantilla: texto})
    d = datos(h.virtualizacion_resumen("hero"))
    assert "memoria_guardada" in d["errores"] and "dumpxml" in d["errores"]["memoria_guardada"]


def test_muchas_instantaneas_de_una_vm_llegan_recortadas_con_su_cuenta(tmp_path):
    muchas = "uri=qemu:///system\n== %s\n%s" % (VM3_HERO, "".join("%d.xml\n" % (1700000000 + i) for i in range(120)))
    resto = "".join("== %s\n" % v["uuid"] for v in p.vm_xml(dato("vm_xml_hero")) if v["uuid"] != VM3_HERO)
    h, _ = uno(tmp_path, cambios={vc.VM_SNAP_VS.plantilla: muchas + resto})
    instantaneas = por(datos(h.vm_snapshots("hero"))["vms"]["filas"], "uuid", VM3_HERO)["instantaneas"]
    assert instantaneas["total"] == 120 and instantaneas["truncado"] is True
    assert len(instantaneas["filas"]) == virt_srv.MAX_INSTANTANEAS and instantaneas["filas"][0]["id"] == 1700000119


# --- contenedores -------------------------------------------------------------------------------

def test_contenedores_lista_da_contenedores_y_aplicaciones(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.contenedores_lista("qts"))
    assert d["por_estado"] == {"running": 34, "exited": 11}
    assert d["contenedores"]["total"] == 45 and d["contenedores"]["truncado"] is False
    assert d["contenedores"]["filas"][0] == {
        "nombre": "contenedor1", "imagen": "imagen1:latest", "estado": "running", "detalle": "Up 16 hours (healthy)",
        "salud": "healthy", "salida": None,
        "puertos": [{"anfitrion": "0.0.0.0", "puerto": "5100", "interno": "3000", "protocolo": "tcp"}],
        "redes": ["red1"], "creado": "2026-10-13 11:28:17 +0200 CEST", "proyecto": "proyecto1"}
    assert d["aplicaciones"]["total"] == 28
    assert set(d["aplicaciones"]["filas"][0]) == {"proyecto", "estado", "ficheros"}


def test_contenedores_lista_sin_poder_leer_las_aplicaciones_da_la_lista_y_lo_dice(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.CT_COMPOSE.plantilla: (1, "", "docker: 'compose' is not a docker command.\n")})
    d = datos(h.contenedores_lista("hero"))
    assert "aplicaciones" in d["errores"] and d["aplicaciones"] is None and d["contenedores"]["total"] == 6


def test_un_nas_sin_contenedores_responde_bien_y_vacio(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.CT_LISTA.plantilla: "", vc.CT_COMPOSE.plantilla: "[]\n"})
    d = datos(h.contenedores_lista("hero"))
    assert d["contenedores"] == {"filas": [], "total": 0, "truncado": False} and d["por_estado"] == {}
    assert d["aplicaciones"] == {"filas": [], "total": 0, "truncado": False}


@pytest.mark.parametrize("herramienta", ["contenedores_lista", "contenedores_uso", "contenedores_redes"])
def test_que_docker_no_responda_es_un_error_y_no_una_lista_vacia(tmp_path, herramienta):
    cambios = {c.plantilla: DOCKER_CAIDO for c in (vc.CT_LISTA, vc.CT_STATS, vc.CT_REDES)}
    h, _ = uno(tmp_path, cambios=cambios)
    assert "Cannot connect" in fallo(getattr(h, herramienta)("hero"))


def test_trescientos_contenedores_llegan_recortados_con_su_cuenta(tmp_path):
    filas = "".join("c%d\timagen:1\trunning\tUp 2 hours\t\tbridge\t2026-10-01 00:00:00 +0200 CEST\t\n" % i
                    for i in range(300))
    uso = "".join("c%d\t%d.00%%\t1MiB / 1GiB\t0.10%%\t1kB / 1kB\t0B / 0B\t3\n" % (i, i % 50) for i in range(300))
    h, _ = uno(tmp_path, cambios={vc.CT_LISTA.plantilla: filas, vc.CT_STATS.plantilla: uso})
    lista = datos(h.contenedores_lista("hero"))
    assert lista["contenedores"]["total"] == 300 and lista["contenedores"]["truncado"] is True
    assert len(lista["contenedores"]["filas"]) == virt_srv.MAX_CONTENEDORES and lista["por_estado"] == {"running": 300}
    medido = datos(h.contenedores_uso("hero"))
    assert medido["contenedores"]["total"] == 300 and len(medido["contenedores"]["filas"]) == virt_srv.MAX_CONTENEDORES
    assert datos(h.virtualizacion_resumen("hero"))["contenedores"]["total"] == 300
    # y aun asi se encuentra uno que no cabe en la lista recortada
    assert datos(h.contenedor_detalle("hero", "c299"))["contenedor"]["nombre"] == "c299"


def test_contenedor_detalle_da_estado_redes_puertos_y_montajes(tmp_path):
    h, mundo = uno(tmp_path, "qts")
    c = datos(h.contenedor_detalle("qts", "contenedor1"))["contenedor"]
    assert (c["nombre"], c["imagen"], c["estado"], c["salud"]) == ("contenedor1", "imagen1:latest", "running", "healthy")
    assert c["detalle"] == "Up 16 hours (healthy)" and c["reinicio"] == "unless-stopped" and c["salida"] == 0
    assert c["redes"] == [{"red": "red1", "direccion": "192.0.2.1", "prefijo": 22, "puerta": "192.0.2.2",
                           "mac": "00:11:22:33:44:00"}]
    assert c["puertos"] == {"total": 1, "truncado": False, "filas": [
        {"interno": "3000/tcp", "anfitrion": "0.0.0.0", "puerto": "5100"}]}
    assert c["montajes"]["total"] == 1 and c["montajes"]["filas"][0]["destino"] == "/destino1"
    assert c["proyecto"] == "proyecto1"
    assert lanzadas(mundo, " inspect ") == [vc.CT_DETALLE.render({"contenedor": "contenedor1"})]


def test_un_contenedor_con_miles_de_puertos_o_cientos_de_montajes_llega_acotado_con_su_cuenta(tmp_path):
    puertos = json.dumps({"%d/udp" % i: [{"HostIp": "0.0.0.0", "HostPort": str(i)}] for i in range(40000, 42000)})
    montajes = json.dumps([{"Type": "bind", "Source": "/share/x/%d" % i, "Destination": "/d/%d" % i, "RW": True}
                           for i in range(300)])

    def detalle(orden, sudo):
        lineas = [("puertos=" + puertos) if linea.startswith("puertos=") else
                  ("montajes=" + montajes) if linea.startswith("montajes=") else linea
                  for linea in dato("ct_detalle_hero").splitlines()]
        return "\n".join(lineas) + "\n"
    h, _ = uno(tmp_path, cambios={P_DETALLE: detalle})
    respuesta = h.contenedor_detalle("hero", "contenedor1")
    c = datos(respuesta)["contenedor"]
    assert c["puertos"]["total"] == 2000 and c["puertos"]["truncado"] is True
    assert len(c["puertos"]["filas"]) == virt_srv.MAX_PUERTOS
    assert c["montajes"]["total"] == 300 and len(c["montajes"]["filas"]) == virt_srv.MAX_MONTAJES
    assert len(json.dumps(respuesta)) < 30000


@pytest.mark.parametrize("contenedor", ["x; reboot", "-f", "$(id)", "a b", "", "../x", "a/b", None, 5, True, "x\ny"])
def test_un_nombre_de_contenedor_no_valido_se_rechaza_sin_conectar(tmp_path, contenedor):
    h, mundo = uno(tmp_path)
    assert "contenedor" in fallo(h.contenedor_detalle("hero", contenedor))
    assert "contenedor" in fallo(h.contenedor_logs("hero", contenedor))
    assert mundo.conexiones == 0


def test_un_contenedor_que_no_existe_dice_cuales_hay_y_no_se_consulta(tmp_path):
    h, mundo = uno(tmp_path)
    for error in (fallo(h.contenedor_detalle("hero", "no-existe")), fallo(h.contenedor_logs("hero", "no-existe"))):
        assert "no-existe" in error and "contenedor1, contenedor2, contenedor3" in error
    assert lanzadas(mundo, " inspect ") == [] and lanzadas(mundo, " logs ") == []


def test_la_lista_de_contenedores_que_hay_va_acotada_en_el_error(tmp_path):
    filas = "".join("c%d\timagen:1\trunning\tUp 2 hours\t\tbridge\t2026-10-01 00:00:00 +0200 CEST\t\n" % i
                    for i in range(300))
    h, _ = uno(tmp_path, cambios={vc.CT_LISTA.plantilla: filas})
    error = fallo(h.contenedor_detalle("hero", "no-existe"))
    assert len(error) < 1500 and "300" in error


def test_contenedores_uso_ordena_por_cpu_y_suma(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.contenedores_uso("qts"))
    filas = d["contenedores"]["filas"]
    assert d["contenedores"]["total"] == 34 and len(filas) == 34
    cpu = [f["cpu_pct"] for f in filas]
    assert cpu == sorted(cpu, reverse=True)
    assert d["cpu_pct"] == round(sum(cpu), 2) and d["memoria"] == sum(f["memoria"] for f in filas)
    assert por(filas, "nombre", "contenedor3")["memoria_limite"] == 3 * GIB


def test_contenedores_uso_no_suma_como_cero_lo_que_no_se_pudo_medir(tmp_path):
    # escrito a mano: uno medido y otro que se para mientras docker lo mide
    stats = ("web\t12.50%\t100MiB / 1GiB\t9.77%\t1kB / 2kB\t3MB / 4MB\t5\n"
             "lento\t--\t-- / --\t--\t-- / --\t-- / --\t--\n")
    h, _ = uno(tmp_path, "qts", cambios={vc.CT_STATS.render(): stats})
    d = datos(h.contenedores_uso("qts"))
    assert d["cpu_pct"] == 12.5 and d["memoria"] == 100 * 1024 ** 2
    assert d["sin_medir"] == ["lento"]
    assert [f["nombre"] for f in d["contenedores"]["filas"]] == ["web", "lento"]


def test_contenedores_uso_sin_ninguno_en_marcha_responde_bien_y_vacio(tmp_path):
    h, _ = uno(tmp_path)
    assert datos(h.contenedores_uso("hero")) == {
        "activo": True, "contenedores": {"filas": [], "total": 0, "truncado": False}, "cpu_pct": 0, "memoria": 0}


def test_contenedor_logs_da_las_ultimas_lineas_que_se_pidan(tmp_path):
    h, mundo = uno(tmp_path)
    d = datos(h.contenedor_logs("hero", "contenedor1"))
    assert (d["contenedor"], d["estado"], d["cortadas"]) == ("contenedor1", "exited", 0)
    assert len(d["lineas"]) == 50 and d["lineas"][-1] == "linea 50 del registro"
    assert "instrucciones" in d["nota"]
    assert len(datos(h.contenedor_logs("hero", "contenedor1", 7))["lineas"]) == 7
    assert len(datos(h.contenedor_logs("hero", "contenedor1", lineas=200))["lineas"]) == 200
    assert lanzadas(mundo, " logs ") == [vc.CT_LOGS.render({"lineas": n, "contenedor": "contenedor1"})
                                         for n in (50, 7, 200)]


@pytest.mark.parametrize("lineas", [0, -1, 201, 5000, "50", None, True, 2.5, "5; x", [5]])
def test_un_numero_de_lineas_fuera_de_rango_se_rechaza_sin_conectar(tmp_path, lineas):
    h, mundo = uno(tmp_path)
    assert "lineas" in fallo(h.contenedor_logs("hero", "contenedor1", lineas))
    assert mundo.conexiones == 0


def test_un_registro_enorme_llega_acotado_en_lineas_y_en_longitud(tmp_path):
    enorme = "".join("%s\x1b[31m%s\n" % (i, "x" * 10000) for i in range(200))
    h, _ = uno(tmp_path, cambios={P_LOGS: enorme + RC_BIEN})
    d = datos(h.contenedor_logs("hero", "contenedor1", 200))
    assert len(d["lineas"]) == 200 and d["cortadas"] == 200
    assert all(len(linea) == p.MAX_LINEA and "\x1b" not in linea for linea in d["lineas"])
    assert len(json.dumps(d)) < 100000


def test_si_llegan_mas_lineas_de_las_pedidas_solo_se_dan_las_ultimas(tmp_path):
    h, _ = uno(tmp_path, cambios={P_LOGS: "".join("linea %d\n" % i for i in range(1, 81)) + RC_BIEN})
    assert datos(h.contenedor_logs("hero", "contenedor1", 5))["lineas"] == ["linea %d" % i for i in range(76, 81)]


def test_un_contenedor_que_no_ha_escrito_nada_responde_bien_y_vacio(tmp_path):
    h, _ = uno(tmp_path, cambios={P_LOGS: RC_BIEN})
    assert datos(h.contenedor_logs("hero", "contenedor1"))["lineas"] == []


@pytest.mark.parametrize("salida", ["", "linea 1\nlinea 2\n"])
def test_un_registro_que_llega_sin_su_marca_final_es_un_error(tmp_path, salida):
    h, _ = uno(tmp_path, cambios={P_LOGS: salida})
    fallo(h.contenedor_logs("hero", "contenedor1"))


def test_un_error_de_docker_al_pedir_el_registro_no_pasa_por_registro(tmp_path):
    sin_lectura = "Error response from daemon: configured logging driver does not support reading\n"
    h, _ = uno(tmp_path, cambios={P_LOGS: sin_lectura + "\n==rc 1\n"})
    assert "does not support reading" in fallo(h.contenedor_logs("hero", "contenedor1"))


def test_un_registro_que_empieza_por_un_error_del_programa_se_devuelve(tmp_path):
    del_programa = "Error: connect ECONNREFUSED 192.0.2.1:5432\n    at TCPConnectWrap.afterConnect\nreintentando\n"
    h, _ = uno(tmp_path, cambios={P_LOGS: del_programa + RC_BIEN})
    assert len(datos(h.contenedor_logs("hero", "contenedor1"))["lineas"]) == 3


@pytest.mark.parametrize("linea", ["Error: boom", "Error response from daemon: lo dice el programa",
                                   "Cannot connect to the Docker daemon at unix:///x.sock"])
def test_un_registro_de_una_sola_linea_que_parece_un_error_de_docker_se_devuelve(tmp_path, linea):
    h, _ = uno(tmp_path, cambios={P_LOGS: linea + RC_BIEN})
    assert datos(h.contenedor_logs("hero", "contenedor1"))["lineas"] == [linea]


def test_contenedores_redes_da_subredes_y_contenedores_conectados(tmp_path):
    h, _ = uno(tmp_path, "qts")
    redes = datos(h.contenedores_redes("qts"))["redes"]
    assert redes["total"] == 35 and redes["truncado"] is False
    assert por(redes["filas"], "red", "red7") == {
        "red": "red7", "driver": "bridge", "ambito": "local", "interna": False,
        "subredes": [{"subred": "192.0.2.3/22", "puerta": "192.0.2.4"}],
        "contenedores": {"total": 3, "truncado": False, "filas": [
            {"nombre": "contenedor9", "direccion": "192.0.2.5"}, {"nombre": "contenedor25", "direccion": "192.0.2.6"},
            {"nombre": "proyecto7", "direccion": "192.0.2.7"}]}}


def test_una_red_con_muchos_contenedores_llega_acotada_con_su_cuenta(tmp_path):
    conectados = " ".join("c%d=192.0.2.%d/24" % (i, i % 250) for i in range(400))
    red = "grande\tbridge\tlocal\tfalse\t[{\"Subnet\":\"192.0.2.0/24\",\"Gateway\":\"192.0.2.1\"}]\t%s \n" % conectados
    h, _ = uno(tmp_path, cambios={vc.CT_REDES.plantilla: red})
    contenedores = datos(h.contenedores_redes("hero"))["redes"]["filas"][0]["contenedores"]
    assert contenedores["total"] == 400 and contenedores["truncado"] is True
    assert len(contenedores["filas"]) == virt_srv.MAX_CONECTADOS


# --- disco_info y vm_definicion_fichero: lo que se lee por una ruta ------------------------------

def check_con(**campos):
    """La salida de qemu-img check de la imagen de hero con otros valores (y su codigo de salida)."""
    base = {"image-end-offset": 4390912, "total-clusters": 2097152, "check-errors": 0, "allocated-clusters": 66,
            "filename": "/share/ruta1/vm1/disco1.1790544225", "format": "qcow2"}
    rc = campos.pop("rc", 0)
    base.update(campos)
    return "==fichero /share/ruta1/vm1/disco1.1790544225\n==check\n%s\n==rc %d\n" % (json.dumps(base, indent=4), rc)


def test_disco_info_da_las_capas_y_la_comprobacion_y_avisa_de_la_base_sucia(tmp_path):
    h, mundo = uno(tmp_path)
    d = datos(h.disco_info("hero", "/Vms/carpeta/disco1.img"))
    assert d["pedida"] == "/share/Vms/carpeta/disco1.img" and d["fichero"].endswith("disco1.1790544225")
    assert [c["fichero"].rsplit("/", 1)[1] for c in d["capas"]] == ["disco1.1790544225", "disco1.img"]
    assert [c["dirty"] for c in d["capas"]] == [False, True] and d["capas"][1]["lazy_refcounts"] is True
    assert d["capas"][0]["base"] == d["capas"][1]["fichero"] and d["capas"][1]["base"] is None
    assert d["comprobacion"]["soportado"] is True and d["comprobacion"]["corrupciones"] == 0
    assert "errores" not in d and d["cadena_cortada"] is False and d["base_sin_leer"] is None
    assert len(d["avisos"]) == 1 and algun(d["avisos"], "disco1.img", "dirty", "lazy-refcounts", "escribe")
    assert "nunca repara" in d["nota"] and "falsos" in d["nota"]
    lanzado = lanzadas(mundo, "qemu-img")
    assert len(lanzado) == 2 and all(" -U" in orden for orden in lanzado)
    assert not any("--repair" in orden or " -r " in orden for orden in lanzado)


def test_disco_info_de_una_imagen_limpia_con_instantaneas_internas_no_avisa(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.disco_info("qts", "Vms/otra/disco2.img"))
    assert d["pedida"] == "/share/Vms/otra/disco2.img" and d["avisos"] == []
    (capa,) = d["capas"]
    assert capa["instantaneas_total"] == 2 and [i["nombre"] for i in capa["instantaneas"]] == [
        "instantanea1", "instantanea2"]


def test_disco_info_avisa_de_corrupciones_fugas_y_errores_de_la_comprobacion(tmp_path):
    h, _ = uno(tmp_path, cambios={P_CHECK: check_con(**{"check-errors": 2, "corruptions": 3, "leaks": 7, "rc": 2})})
    d = datos(h.disco_info("hero", "/Vms/carpeta/disco1.img"))
    assert d["comprobacion"]["corrupciones"] == 3 and d["comprobacion"]["fugas"] == 7
    assert algun(d["avisos"], "3 corrupciones") and algun(d["avisos"], "7 fugas") and algun(d["avisos"], "2 errores")


CUENTA_PENDIENTE = "ERROR cluster N refcount=0 reference=1"
COPIED_PENDIENTE = "ERROR OFLAG_COPIED data cluster: l2_entry=N refcount=0"


def check_con_lineas(tipos, **campos):
    """check_con con las cuentas por tipo de linea que da la orden ({tipo: lineas})."""
    texto = check_con(**campos)
    cola = "".join("==tipo %d %s\n" % (n, t) for t, n in tipos.items())
    return texto.replace("\n==rc ", "\n" + cola + "==rc ")


def pedida_sin_cerrar(dirty=True, lazy=True):
    """disco_info de hero con la capa pedida (la primera) sin cerrar limpia y con lazy-refcounts."""
    texto = dato("disco_info_hero")
    texto = texto.replace('"lazy-refcounts": false', '"lazy-refcounts": %s' % ("true" if lazy else "false"), 1)
    return texto.replace('"dirty-flag": false', '"dirty-flag": %s' % ("true" if dirty else "false"), 1)


def test_las_cuentas_pendientes_de_una_imagen_sin_cerrar_no_se_dan_por_corrupciones(tmp_path):
    """dirty + lazy-refcounts y solo clusters en uso con refcount=0: son las cuentas que QEMU no llego a escribir
    (las rehace al abrir la imagen), no datos danados; el aviso no puede decir 'corrupciones' a secas."""
    check = check_con_lineas({CUENTA_PENDIENTE: 3, COPIED_PENDIENTE: 3}, corruptions=6, rc=2)
    h, _ = uno(tmp_path, cambios={P_INFO: pedida_sin_cerrar(), P_CHECK: check})
    d = datos(h.disco_info("hero", "/Vms/carpeta/disco1.img"))
    assert d["comprobacion"]["corrupciones"] == 6
    assert not algun(d["avisos"], "6 corrupciones")
    assert algun(d["avisos"], "disco1.1790544225", "6", "cuentas de referencia", "lazy-refcounts", "no se cerro")


@pytest.mark.parametrize("info, tipos, corrupciones", [
    (pedida_sin_cerrar(), {CUENTA_PENDIENTE: 3, COPIED_PENDIENTE: 3, "ERROR cluster N refcount=2 reference=1": 1}, 7),
    (pedida_sin_cerrar(dirty=False), {CUENTA_PENDIENTE: 3, COPIED_PENDIENTE: 3}, 6),       # se cerro limpia
    (pedida_sin_cerrar(lazy=False), {CUENTA_PENDIENTE: 3, COPIED_PENDIENTE: 3}, 6),        # sin lazy-refcounts
    (pedida_sin_cerrar(), {CUENTA_PENDIENTE: 3, COPIED_PENDIENTE: 3}, 9),                  # hay mas de las que se ven
    (pedida_sin_cerrar().replace('"corrupt": false', '"corrupt": true', 1), {CUENTA_PENDIENTE: 6}, 6),
])
def test_si_no_son_solo_cuentas_pendientes_se_avisa_de_corrupciones(tmp_path, info, tipos, corrupciones):
    check = check_con_lineas(tipos, corruptions=corrupciones, rc=2)
    h, _ = uno(tmp_path, cambios={P_INFO: info, P_CHECK: check})
    d = datos(h.disco_info("hero", "/Vms/carpeta/disco1.img"))
    assert algun(d["avisos"], "%d corrupciones" % corrupciones)
    assert not algun(d["avisos"], "cuentas de referencia")


def test_una_imagen_marcada_como_corrupta_avisa(tmp_path):
    corrupta = dato("disco_info_qts").replace('"corrupt": false', '"corrupt": true')
    h, _ = uno(tmp_path, "qts", cambios={P_INFO: corrupta})
    assert algun(datos(h.disco_info("qts", "/Vms/otra/disco2.img"))["avisos"], "corrupta")


def test_si_la_comprobacion_falla_la_informacion_sale_igual_y_el_error_va_aparte(tmp_path):
    h, _ = uno(tmp_path, cambios={P_CHECK: (1, "", "qemu-img: se ha ido\n")})
    d = datos(h.disco_info("hero", "/Vms/carpeta/disco1.img"))
    assert d["comprobacion"] is None and "comprobacion" in d["errores"]
    assert len(d["capas"]) == 2 and algun(d["avisos"], "dirty")


def test_una_comprobacion_que_el_formato_no_admite_no_es_un_aviso(tmp_path):
    sin = ("==fichero /share/ruta1/vm1/disco1.1790544225\n==check\n"
           "qemu-img: This image format does not support checks\n==rc 63\n")
    h, _ = uno(tmp_path, cambios={P_CHECK: sin})
    d = datos(h.disco_info("hero", "/Vms/carpeta/disco1.img"))
    assert d["comprobacion"]["soportado"] is False and "errores" not in d
    assert not algun(d["avisos"], "comprobacion")


@pytest.mark.parametrize("ruta", ["", "   ", None, 5, True, ["/Vms/x"], "/Vms/../etc/passwd", "/Vms/./x",
                                  "/Vms/x\ny", "/Vms/x\x00", "/" + "a" * 600])
def test_disco_info_y_la_definicion_rechazan_una_ruta_que_no_vale_sin_conectar(tmp_path, ruta):
    h, mundo = uno(tmp_path)
    assert "ruta" in fallo(h.disco_info("hero", ruta))
    assert "ruta" in fallo(h.vm_definicion_fichero("hero", ruta))
    assert mundo.conexiones == 0


def test_una_ruta_con_espacios_o_caracteres_raros_va_citada_y_no_se_interpreta():
    ruta = "/share/Vms/mi carpeta/a'b; reboot $(id).img"
    for orden in (vc.DISCO_INFO, vc.DISCO_CHECK, vc.VM_DEFINICION_FICHERO):
        assert shlex.quote(ruta) in orden.render({"ruta": ruta}), orden.id


@pytest.mark.parametrize("herramienta", ["disco_info", "vm_definicion_fichero"])
def test_una_ruta_que_el_nas_rechaza_es_un_error_y_no_un_dato_vacio(tmp_path, herramienta):
    rechazada = "==rechazada /share/Vms/x\n"
    h, _ = uno(tmp_path, cambios={P_INFO: rechazada, P_CHECK: rechazada, P_DEFINICION: rechazada})
    assert "share" in fallo(getattr(h, herramienta)("hero", "/Vms/x")).lower()


def test_disco_info_sigue_leyendo_con_el_servicio_parado(tmp_path):
    h, mundo = uno(tmp_path, cambios={vc.ANFITRION.plantilla: SIN_SOCKETS})
    d = datos(h.disco_info("hero", "/Vms/carpeta/disco1.img"))
    assert d["activo"] is True and len(d["capas"]) == 2
    assert lanzadas(mundo, "virsh") == []


def test_la_definicion_de_una_vm_registrada_dice_cual(tmp_path):
    h, mundo = uno(tmp_path)
    d = datos(h.vm_definicion_fichero("hero", "/Vms/carpeta"))
    assert d["registrada"] is True and d["registrada_como"] == "vm1" and "errores" not in d
    assert d["uuid"] == VM1_HERO and d["nombre"] == "vm1" and d["pedida"] == "/share/Vms/carpeta"
    assert d["graficos"] == {"tipo": "vnc", "puerto": None, "autopuerto": True, "escucha": "127.0.0.1",
                             "teclado": "es"}
    assert d["discos"][0]["fichero"].endswith("disco1.1790544225") and d["discos"][0]["bases"] == [
        "/share/ruta1/vm1/disco1.img"]
    assert d["nics"][0]["conmutador"] == "qvs2"
    assert lanzadas(mundo, "qemu-img") == []


def test_la_definicion_de_una_vm_que_no_esta_registrada_lo_dice(tmp_path):
    h, _ = uno(tmp_path, "qts")
    d = datos(h.vm_definicion_fichero("qts", "/Vms/otra/vm2"))
    assert d["registrada"] is False and d["registrada_como"] is None and "errores" not in d
    assert d["uuid"] == "00000000-0000-0000-0000-000000000099" and d["nombre"] == "maquina-ejemplo2"


def test_si_no_se_pueden_leer_las_registradas_la_definicion_sale_sin_saber_si_lo_esta(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.VM_XML.plantilla: (1, "", "error\n")})
    d = datos(h.vm_definicion_fichero("hero", "/Vms/carpeta"))
    assert d["registrada"] is None and d["registrada_como"] is None and "registrada" in d["errores"]
    assert d["nombre"] == "vm1"


def test_con_el_servicio_parado_la_definicion_sale_y_la_registrada_queda_sin_saber(tmp_path):
    h, _ = uno(tmp_path, cambios={vc.ANFITRION.plantilla: SIN_SOCKETS})
    d = datos(h.vm_definicion_fichero("hero", "/Vms/carpeta"))
    assert d["registrada"] is None and "registrada" in d["errores"] and d["nombre"] == "vm1"


def test_la_contrasena_de_la_consola_no_sale_aunque_el_nas_la_devuelva(tmp_path):
    con = dato("vm_definicion_fichero_hero").replace(
        "==graficos\n", "==graficos\npasswd='clave-vnc-123'\ntype='vnc' passwd='clave-vnc-123'\n")
    assert con.count("clave-vnc-123") == 2
    h, _ = uno(tmp_path, cambios={P_DEFINICION: con})
    texto = json.dumps(h.vm_definicion_fichero("hero", "/Vms/carpeta"))
    assert '"ok": true' in texto and "clave-vnc-123" not in texto and "passwd" not in texto


def test_la_orden_de_la_definicion_no_trae_el_xml_entero():
    # solo se piden elementos concretos y de la consola, atributo a atributo: nunca la linea entera
    plantilla = vc.VM_DEFINICION_FICHERO.plantilla
    assert "passwd" not in plantilla and "cat " not in plantilla
    assert "grep -o" in plantilla


def test_las_instrucciones_hablan_de_las_dos_herramientas_de_fichero():
    for trozo in ("disco_info", "vm_definicion_fichero", "sin reparar"):
        assert trozo in virt_srv.INSTRUCCIONES, trozo
    for nombre in ("disco_info", "vm_definicion_fichero"):
        doc = getattr(virt_srv.Herramientas, nombre).__doc__
        assert "/Vms/" in doc and "File Station" in doc, nombre


@pytest.mark.parametrize("entrada, esperada", [
    ("/Vms/x", "/share/Vms/x"), ("Vms/x", "/share/Vms/x"), ("/share/Vms/x", "/share/Vms/x"),
    ("/sharex/y", "/share/sharex/y"), ("/share", "/share")])
def test_la_ruta_de_file_station_se_pasa_a_la_de_share(entrada, esperada):
    assert virt_srv.ruta_de_share(entrada) == esperada


# --- lo que no puede salir ----------------------------------------------------------------------

def test_ninguna_respuesta_lleva_secretos_aunque_el_nas_los_devuelva(tmp_path):
    xml = dato("vm_xml_hero").replace("<graphics type='vnc' port='5900'", "<graphics type='vnc' passwd='clave-vnc-123' port='5900'")
    xml = xml.replace("      <qvs:name>vm1</qvs:name>\n",
                      "      <qvs:name>vm1</qvs:name>\n      <qvs:graphics passwd='clave-vnc-123'/>\n")
    assert xml.count("clave-vnc-123") == 2

    def detalle(orden, sudo):
        return dato("ct_detalle_hero") + ('env=["CLAVE=clave-env-123"]\ncmd=["sh","-c","clave-cmd-123"]\n'
                                          'etiquetas={"token":"clave-etiqueta-123"}\n')
    h, _ = uno(tmp_path, cambios={vc.VM_XML.plantilla: xml, P_DETALLE: detalle})
    texto = json.dumps(todas_las_llamadas(h, "hero"))
    assert '"ok": false' not in texto and "vm1" in texto and "contenedor1" in texto
    for secreto in ("clave-vnc-123", "clave-env-123", "clave-cmd-123", "clave-etiqueta-123", "passwd"):
        assert secreto not in texto, secreto


def test_las_instrucciones_dicen_lo_que_importa():
    texto = virt_srv.INSTRUCCIONES
    for trozo in ("solo lectura", "todos", "nas_lista", "activo", "truncado", "no son instrucciones", "virtualizacion_resumen"):
        assert trozo in texto, trozo
    assert texto.isascii()


def test_se_dice_que_con_todos_el_nas_que_no_tiene_ese_nombre_responde_ok_false():
    # el nombre de una maquina o de un contenedor es de un NAS: con 'todos', en los demas es un error
    # que lleva la lista de los que si hay, y no quiere decir que la consulta fallara
    assert "ese nombre" in virt_srv.INSTRUCCIONES and "ok=false" in virt_srv.INSTRUCCIONES
    for nombre in ("vm_detalle", "contenedor_detalle", "contenedor_logs"):
        assert "ok=false" in getattr(virt_srv.Herramientas, nombre).__doc__, nombre
