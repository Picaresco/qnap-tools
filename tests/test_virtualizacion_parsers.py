# -*- coding: utf-8 -*-
"""Parsers de la pata de virtualizacion sobre salidas reales anonimizadas: *_hero.txt de un
QuTS hero de laboratorio y *_qts.txt de un QTS de pruebas. Lo escrito a mano se indica."""
from pathlib import Path

import pytest

from qnap_tools.virtualizacion import parsers as p

DATOS = Path(__file__).parent / "datos" / "virtualizacion"
URI = "uri=qemu:///system\n"
VM1 = "00000000-0000-0000-0000-000000000006"          # en marcha en el NAS de laboratorio
VM2 = "00000000-0000-0000-0000-000000000002"


def dato(nombre):
    return (DATOS / (nombre + ".txt")).read_text(encoding="utf-8")


def por(lista, clave, valor):
    (x,) = [x for x in lista if x[clave] == valor]
    return x


# ==== anfitrion =================================================================================

def test_el_anfitrion_da_cpu_memoria_en_bytes_y_servicios_en_marcha():
    a = p.anfitrion(dato("anfitrion_hero"))
    assert a == {
        "hilos": 4, "cpu": "Intel(R) Xeon(R) CPU D-1602 @ 2.50GHz", "virtualizacion": "vmx",
        "carga": [2.17, 1.29, 1.2],
        "memoria": {"total": 32771296 * 1024, "libre": 6922004 * 1024, "disponible": 7742808 * 1024,
                    "intercambio": 63736824 * 1024, "intercambio_libre": 63736824 * 1024},
        "libvirt": True, "docker": True, "docker_interno": True}


def test_sin_sockets_los_servicios_estan_parados():
    # escrito a mano: un NAS con los paquetes instalados y los servicios sin arrancar
    a = p.anfitrion("hilos=2\nmodel name\t: CPU de ejemplo\nvirt=\ncarga=0.10 0.20 0.30 1/200 999\n"
                    "MemTotal:        8000000 kB\nMemFree:         1000000 kB\nSwapTotal:             0 kB\n"
                    "SwapFree:              0 kB\n")
    assert (a["libvirt"], a["docker"], a["docker_interno"], a["virtualizacion"]) == (False, False, False, None)
    assert a["memoria"]["disponible"] is None and a["memoria"]["libre"] == 1000000 * 1024


@pytest.mark.parametrize("texto", ["", "hilos=4\n", "hilos=cuatro\nMemTotal: 1 kB\n", "MemTotal: 100 kB\n"])
def test_el_anfitrion_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.anfitrion(texto)


# ==== estadisticas (domstats) ===================================================================

def test_las_estadisticas_dan_estado_memoria_discos_y_red_de_cada_vm():
    vms = p.vm_estadisticas(dato("vm_estadisticas_hero"))
    assert len(vms) == 6 and sorted(v["estado"] for v in vms) == ["apagada"] * 4 + ["en marcha"] * 2
    en_marcha = por(vms, "uuid", VM2)
    assert (en_marcha["estado"], en_marcha["estado_codigo"], en_marcha["cpu_ns"], en_marcha["vcpus"]) == (
        "en marcha", 1, 5544684426202, 2)
    assert (en_marcha["memoria"], en_marcha["memoria_residente"]) == (4194304 * 1024, 4251948 * 1024)
    assert en_marcha["red"] == [{"interfaz": "vnet1", "rx_bytes": 2251152, "tx_bytes": 1478799,
                                 "rx_errores": 0, "tx_errores": 0, "rx_descartados": 0, "tx_descartados": 0}]
    assert len(en_marcha["discos"]) == 4
    assert en_marcha["discos"][0] == {
        "dispositivo": "hda", "fichero": "/share/ruta1/vm2/ruta4.1790572518", "capacidad": 107374182400,
        "asignado": 569835520, "en_disco": 259170816}


def test_una_vm_apagada_no_tiene_cpu_ni_red_pero_si_discos():
    apagada = por(p.vm_estadisticas(dato("vm_estadisticas_hero")), "uuid", "00000000-0000-0000-0000-000000000001")
    assert (apagada["estado"], apagada["cpu_ns"], apagada["memoria_residente"], apagada["red"]) == (
        "apagada", None, None, [])
    assert [d["dispositivo"] for d in apagada["discos"]][0] == "vda" and len(apagada["discos"]) == 3
    assert apagada["memoria"] == 4194304 * 1024


def test_las_estadisticas_de_qts_tienen_el_mismo_formato():
    vms = p.vm_estadisticas(dato("vm_estadisticas_qts"))
    assert len(vms) == 9 and sum(1 for v in vms if v["estado"] == "en marcha") == 3
    assert all(v["memoria"] > 0 and v["discos"] for v in vms)


def test_un_estado_que_no_se_conoce_se_da_con_su_codigo():
    # escrito a mano: libvirt puede anadir estados
    (vm,) = p.vm_estadisticas(URI + "Domain: '%s'\n  state.state=3\n  state.reason=1\n  balloon.current=1024\n" % VM1)
    assert (vm["estado"], vm["estado_codigo"]) == ("en pausa", 3)
    (vm,) = p.vm_estadisticas(URI + "Domain: '%s'\n  state.state=42\n" % VM1)
    assert (vm["estado"], vm["estado_codigo"], vm["memoria"]) == ("estado 42", 42, None)


def test_una_vm_suspendida_por_virtualization_station_no_sale_como_apagada():
    # visto en el NAS de laboratorio (2026-10-14): la "suspension" de VS guarda la memoria en disco
    # y libvirt da la VM por apagada (5) con el motivo 5, "guardada"; una apagada normal, motivo 0
    (vm,) = p.vm_estadisticas(URI + "Domain: '%s'\n  state.state=5\n  state.reason=5\n" % VM1)
    assert (vm["estado"], vm["estado_codigo"]) == ("suspendida", 5)
    (vm,) = p.vm_estadisticas(URI + "Domain: '%s'\n  state.state=5\n  state.reason=0\n" % VM1)
    assert vm["estado"] == "apagada"


def test_un_invitado_dormido_en_memoria_no_se_confunde_con_una_suspendida():
    # escrito a mano: el estado 7 de libvirt es el invitado en reposo (S3), no la suspension de VS
    (vm,) = p.vm_estadisticas(URI + "Domain: '%s'\n  state.state=7\n  state.reason=0\n" % VM1)
    assert (vm["estado"], vm["estado_codigo"]) == ("en reposo", 7)


def test_sin_vms_la_lista_esta_vacia_pero_sin_respuesta_de_libvirt_es_un_error():
    assert p.vm_estadisticas(URI) == []
    # sin la conexion al libvirt del sistema la orden no dice a quien pregunto: no es "no hay"
    for texto in ("", "uri=\n", "uri=qemu:///session\n", "Domain: '%s'\n  state.state=1\n" % VM1):
        with pytest.raises(ValueError):
            p.vm_estadisticas(texto)


@pytest.mark.parametrize("cuerpo", ["  state.state=1\n", "Domain: 'x'\n  state.state=uno\n",
                                    "Domain: 'x'\n  sin igual\n", "Domain: 'x'\n"])
def test_las_estadisticas_no_se_inventan(cuerpo):
    with pytest.raises(ValueError):
        p.vm_estadisticas(URI + cuerpo)


# ==== definicion (dumpxml filtrado) =============================================================

def test_la_definicion_da_nombre_recursos_discos_red_y_consola():
    vms = p.vm_xml(dato("vm_xml_hero"))
    assert [v["nombre"] for v in vms] == ["vm1", "vm2", "vm3", "vm4", "vm5", "vm6"]
    assert por(vms, "uuid", VM1) == {
        "uuid": VM1, "nombre": "vm1", "descripcion": "descripcion de ejemplo 1", "sistema": "win2012r2",
        "arquitectura": "x86", "arranque_automatico": {"modo": "off", "retraso_s": 60},
        "instantaneas": "external", "memoria": 4194304 * 1024, "memoria_actual": 4194304 * 1024, "vcpus": 2,
        "maquina": "pc-i440fx-7.0", "firmware": "bios", "tpm": None, "arranque": ["cdrom", "hd"],
        "discos": [
            {"dispositivo": "hda", "bus": "ide", "clase": "disk", "formato": "qcow2",
             "fichero": "/share/ruta1/vm1/ruta10.1790544225", "bases": ["/share/ruta1/vm1/ruta10.img"]},
            {"dispositivo": "hdb", "bus": "ide", "clase": "cdrom", "formato": "raw",
             "fichero": "/QVS/guest_tools.iso", "bases": []}],
        "interfaces": [{"tipo": "bridge", "mac": "00:11:22:33:44:00", "conmutador": "qvs2",
                        "interfaz": "vnet0", "modelo": "e1000"}],
        "consola": {"tipo": "vnc", "puerto": 5900, "escucha": "127.0.0.1"}, "dispositivos_pasados": 0}


def test_una_vm_con_uefi_y_tpm_y_una_apagada_sin_puerto_de_consola():
    uefi = por(p.vm_xml(dato("vm_xml_qts")), "nombre", "vm4")
    assert (uefi["firmware"], uefi["tpm"], uefi["sistema"], uefi["vcpus"], uefi["memoria"]) == (
        "uefi", "tpm-tis", "win11", 4, 8388608 * 1024)
    assert uefi["descripcion"] is None and uefi["consola"] == {"tipo": "vnc", "puerto": None, "escucha": "127.0.0.1"}
    # apagada: sin interfaz del anfitrion y sin la cadena de imagenes base
    assert all(i["interfaz"] is None for i in uefi["interfaces"])


def test_el_arranque_automatico_puede_ser_el_estado_anterior():
    vms = p.vm_xml(dato("vm_xml_qts"))
    assert len(vms) == 9
    assert por(vms, "nombre", "vm9")["arranque_automatico"] == {"modo": "quo", "retraso_s": 60}
    assert por(vms, "nombre", "vm1")["arranque_automatico"] == {"modo": "off", "retraso_s": 0}


def test_los_discos_de_qts_con_virtio_y_sata_y_un_cd_sin_disco():
    vms = p.vm_xml(dato("vm_xml_qts")) + p.vm_xml(dato("vm_xml_hero"))
    buses = {d["bus"] for v in vms for d in v["discos"]}
    assert buses == {"ide", "virtio", "sata"}
    vacios = [d for v in vms for d in v["discos"] if d["clase"] == "cdrom" and d["fichero"] is None]
    assert vacios and all(d["bases"] == [] for d in vacios)


VM_A_MANO = (
    URI + "== %s\n"
    "  <description>%s</description>\n"
    "      <qvs:name>%s</qvs:name>\n"
    "  <memory unit='KiB'>1048576</memory>\n"
    "  <vcpu placement='static'>1</vcpu>\n"
    "    <type arch='x86_64' machine='q35'>hvm</type>\n"
    "    <hostdev mode='subsystem' type='usb' managed='yes'>\n"
    "    </hostdev>\n"
    "    <interface type='network'>\n"
    "      <mac address='52:54:00:00:00:01'/>\n"
    "      <source network='default'/>\n"
    "      <model type='virtio'/>\n"
    "    </interface>\n"
    "    <graphics type='vnc' port='5900' autoport='yes' listen='0.0.0.0' passwd='secreto'>\n")


def test_el_texto_que_escribe_un_tercero_llega_acotado_y_la_contrasena_de_la_consola_nunca():
    # escrito a mano: con --security-info (que no se usa) libvirt daria passwd en <graphics>
    (vm,) = p.vm_xml(VM_A_MANO % (VM1, "d" * 900 + "\x07", "n" * 900))
    assert len(vm["descripcion"]) == p.MAX_DESCRIPCION and len(vm["nombre"]) == p.MAX_NOMBRE
    assert "\x07" not in vm["descripcion"]
    assert vm["consola"] == {"tipo": "vnc", "puerto": 5900, "escucha": "0.0.0.0"}
    assert "secreto" not in repr(vm)
    assert vm["dispositivos_pasados"] == 1 and vm["firmware"] == "bios" and vm["sistema"] is None
    assert vm["interfaces"] == [{"tipo": "network", "mac": "52:54:00:00:00:01", "conmutador": "default",
                                 "interfaz": None, "modelo": "virtio"}]


def test_sin_vms_no_hay_definiciones_y_sin_libvirt_es_un_error():
    assert p.vm_xml(URI) == []
    for texto in ("", "uri=\n", "== %s\n  <memory unit='KiB'>1</memory>\n" % VM1):
        with pytest.raises(ValueError):
            p.vm_xml(texto)


@pytest.mark.parametrize("cuerpo", [
    "  <memory unit='KiB'>1</memory>\n",                                    # sin VM a la que colgarlo
    "== no-es-un-uuid\n  <memory unit='KiB'>1</memory>\n"])
def test_la_definicion_no_se_inventa(cuerpo):
    with pytest.raises(ValueError):
        p.vm_xml(URI + cuerpo)


@pytest.mark.parametrize("cuerpo", [
    "",                                                                     # una VM sin ningun dato
    "  <memory unit='MiB'>1024</memory>\n  <vcpu>1</vcpu>\n",               # unidad no prevista
    "  <memory unit='KiB'>mucha</memory>\n",
    "  <qvs:name>vm rara</qvs:name>\n  algo que no es un elemento\n"])
def test_una_definicion_que_no_se_entiende_deja_esa_vm_con_su_error_y_sin_inventar(cuerpo):
    vm, otra = p.vm_xml(URI + "== %s\n" % VM1 + cuerpo + "== %s\n  <memory unit='KiB'>1024</memory>\n"
                        "  <vcpu>1</vcpu>\n" % VM2)
    assert vm["uuid"] == VM1 and vm["error"] and "definicion" in vm["error"]
    assert all(vm[c] is None for c in ("memoria", "vcpus", "discos", "interfaces", "firmware", "arranque"))
    assert (otra["uuid"], otra["memoria"], otra["vcpus"]) == (VM2, 1024 * 1024, 1) and "error" not in otra


def test_una_vm_ilegible_conserva_su_nombre_si_se_ve():
    (vm,) = p.vm_xml(URI + "== %s\n  <qvs:name>vm rara</qvs:name>\n  <memory unit='KiB'>mucha</memory>\n" % VM1)
    assert vm["nombre"] == "vm rara" and vm["error"]


# ==== direcciones ===============================================================================

IP_VISTA = (" Name       MAC address          Protocol     Address\n"
            "-------------------------------------------------------------------------------\n"
            " vnet1      52:54:00:00:00:02    ipv4         192.0.2.13/0\n")


def test_las_direcciones_de_una_vm_salen_de_la_tabla_arp():
    # la linea de datos es la que se vio en el NAS de laboratorio, con la direccion cambiada
    assert p.vm_ip(IP_VISTA) == [{"interfaz": "vnet1", "mac": "52:54:00:00:00:02", "protocolo": "ipv4",
                                  "direccion": "192.0.2.13"}]
    assert p.vm_ip(dato("vm_ip_hero")) == [] and p.vm_ip(dato("vm_ip_qts")) == []


@pytest.mark.parametrize("texto", ["", "error: Domain is not running\n", IP_VISTA + " vnet1 sin-mac\n"])
def test_las_direcciones_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.vm_ip(texto)


# ==== uso (dos lecturas) ========================================================================

def lecturas(antes, despues, t0="100.00 1.00", t1="105.00 2.00", uri0=URI, uri1=URI, rc0="==rc 0\n",
             rc1="==rc 0\n"):
    """Lo que da la orden: cada lectura dice antes a que libvirt habla y despues como termino domstats."""
    return "%s%s\n%s%s==5s\n%s%s\n%s%s" % (uri0, t0, antes, rc0, uri1, t1, despues, rc1)


def lectura(cpu, rx, tx, rd, wr, rd_reqs=0, wr_reqs=0, vcpus=2):
    return ("Domain: '%s'\n  cpu.time=%d\n  balloon.current=2097152\n  balloon.rss=1048576\n  vcpu.current=%d\n"
            "  net.count=1\n  net.0.name=vnet0\n  net.0.rx.bytes=%d\n  net.0.tx.bytes=%d\n"
            "  block.count=1\n  block.0.name=vda\n  block.0.rd.reqs=%d\n  block.0.rd.bytes=%d\n"
            "  block.0.wr.reqs=%d\n  block.0.wr.bytes=%d\n" % (VM1, cpu, vcpus, rx, tx, rd_reqs, rd, wr_reqs, wr))


def test_el_uso_sale_de_la_diferencia_entre_las_dos_lecturas():
    # 5 s; 5e9 ns de CPU = un nucleo entero; con 2 vCPU, la mitad de lo que puede usar
    r = p.vm_uso(lecturas(lectura(10 ** 12, 1000, 2000, 0, 0), lectura(10 ** 12 + 5 * 10 ** 9, 6000, 2000, 5242880, 1048576, 50, 10)))
    assert r["segundos"] == 5.0
    assert r["vms"] == [{
        "uuid": VM1, "vcpus": 2, "cpu_nucleos": 1.0, "cpu_pct": 50.0, "memoria": 2097152 * 1024,
        "memoria_residente": 1048576 * 1024,
        "discos": [{"dispositivo": "vda", "lectura_bytes_s": 1048576.0, "escritura_bytes_s": 209715.2,
                    "lecturas_s": 10.0, "escrituras_s": 2.0}],
        "red": [{"interfaz": "vnet0", "rx_bytes_s": 1000.0, "tx_bytes_s": 0.0}]}]


def test_un_contador_que_retrocede_no_da_una_cifra_negativa():
    # la VM se reinicio entre las dos lecturas: sus contadores vuelven a empezar
    r = p.vm_uso(lecturas(lectura(10 ** 12, 9000, 9000, 9000, 9000), lectura(10 ** 9, 10, 10, 10, 10)))
    (vm,) = r["vms"]
    assert vm["cpu_nucleos"] is None and vm["cpu_pct"] is None
    assert vm["red"][0] == {"interfaz": "vnet0", "rx_bytes_s": None, "tx_bytes_s": None}
    assert vm["discos"][0]["lectura_bytes_s"] is None


def test_una_vm_que_solo_sale_en_una_lectura_no_se_mide():
    r = p.vm_uso(lecturas(lectura(1, 1, 1, 1, 1), ""))
    assert r["vms"] == [] and r["segundos"] == 5.0
    assert p.vm_uso(lecturas("", "")) == {"segundos": 5.0, "vms": []}


def test_el_uso_real_mide_las_vm_en_marcha():
    for sistema, en_marcha in (("hero", 2), ("qts", 3)):
        r = p.vm_uso(dato("vm_uso_" + sistema))
        assert 4.5 <= r["segundos"] <= 6.5 and len(r["vms"]) == en_marcha
        for vm in r["vms"]:
            assert 0 <= vm["cpu_pct"] <= 100 and vm["vcpus"] >= 1 and vm["memoria"] > 0
            assert vm["discos"] and all(d["lectura_bytes_s"] >= 0 for d in vm["discos"])
            assert vm["red"] and all(n["rx_bytes_s"] >= 0 for n in vm["red"])


@pytest.mark.parametrize("texto", [
    "", "100.00 1.00\n", lecturas("", "", t1="100.00 2.00"), lecturas("", "", t1="99.00 2.00"),
    lecturas("  cpu.time=1\n", ""), "sin reloj\n==5s\n105.00 1.00\n",
    # sin respuesta del libvirt del sistema en una de las lecturas: no es "ninguna VM en marcha"
    lecturas("", lectura(1, 1, 1, 1, 1), uri0="uri=\n"), lecturas(lectura(1, 1, 1, 1, 1), "", uri1="uri=\n"),
    lecturas("", "", uri0="", uri1=""),
    # domstats fallo en una lectura (libvirt respondio a uri): sin dominios no es "ninguna en marcha"
    lecturas("", lectura(1, 1, 1, 1, 1), rc0="==rc 1\n"), lecturas(lectura(1, 1, 1, 1, 1), "", rc1="==rc 1\n"),
    lecturas("", "", rc0="", rc1="")])
def test_el_uso_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.vm_uso(texto)


# ==== cadena de imagenes ========================================================================

def test_la_cadena_de_imagenes_da_cada_capa_con_su_tamano():
    vms = p.vm_imagenes(dato("vm_imagenes_hero"))
    assert len(vms) == 6
    (disco,) = por(vms, "uuid", VM1)["discos"]
    assert disco["fichero"] == "/share/ruta1/vm1/ruta10.1790544225" and len(disco["cadena"]) == 2
    capa, base = disco["cadena"]
    assert (capa["fichero"], capa["formato"], capa["virtual"], capa["base"]) == (
        "/share/ruta1/vm1/ruta10.1790544225", "qcow2", 268435456000, "/share/ruta1/vm1/ruta10.img")
    assert capa["ocupa"] > 0 and (base["fichero"], base["base"]) == ("/share/ruta1/vm1/ruta10.img", None)
    # una VM con tres instantaneas: cuatro capas
    assert [len(d["cadena"]) for d in por(vms, "uuid", "00000000-0000-0000-0000-000000000004")["discos"]] == [4]


def test_la_cadena_de_imagenes_de_qts():
    vms = p.vm_imagenes(dato("vm_imagenes_qts"))
    assert len(vms) == 9 and sum(len(v["discos"]) for v in vms) == 10
    assert sorted(len(d["cadena"]) for v in vms for d in v["discos"]) == [1, 1, 2, 2, 3, 3, 3, 3, 3, 4]


def test_un_disco_cuya_imagen_no_se_puede_leer_queda_sin_cadena_y_no_tumba_a_los_demas():
    # escrito a mano: qemu-img escribe su error por la salida de errores y aqui no llega nada
    vms = p.vm_imagenes(URI + "== %s\n-- /share/x/roto.img\n-- /share/x/bien.img\n"
                        '{"virtual-size": 10, "filename": "/share/x/bien.img", "format": "raw", "actual-size": 4}\n'
                        "== %s\n" % (VM1, VM2))
    assert vms == [
        {"uuid": VM1, "discos": [
            {"fichero": "/share/x/roto.img", "cadena": None, "base_sin_leer": None, "cortada": False},
            {"fichero": "/share/x/bien.img", "cadena": [
                {"fichero": "/share/x/bien.img", "formato": "raw", "virtual": 10, "ocupa": 4, "base": None}],
             "base_sin_leer": None, "cortada": False}]},
        {"uuid": VM2, "discos": []}]


CAPA = '{"filename": "%s", "format": "qcow2", "virtual-size": 10, "actual-size": 4%s}\n'


def test_una_imagen_base_que_no_es_un_fichero_local_no_se_sigue_y_se_dice():
    # escrito a mano: la orden solo sigue las bases que son una ruta local; la ultima capa leida
    # apunta a otra cosa y ahi se queda
    base = ', "backing-filename": "nbd://192.0.2.9/x", "full-backing-filename": "nbd://192.0.2.9/x"'
    (vm,) = p.vm_imagenes(URI + "== %s\n-- /share/x/capa.img\n" % VM1
                          + CAPA % ("/share/x/capa.img", ', "full-backing-filename": "/share/x/base.img"')
                          + CAPA % ("/share/x/base.img", base))
    (disco,) = vm["discos"]
    assert [c["fichero"] for c in disco["cadena"]] == ["/share/x/capa.img", "/share/x/base.img"]
    assert disco["base_sin_leer"] == "nbd://192.0.2.9/x" and disco["cortada"] is False


def test_una_cadena_mas_larga_de_lo_que_se_recorre_se_marca_cortada():
    (vm,) = p.vm_imagenes(URI + "== %s\n-- /share/x/capa.img\n" % VM1
                          + CAPA % ("/share/x/capa.img", ', "full-backing-filename": "/share/x/base.img"')
                          + "!! cadena cortada\n")
    (disco,) = vm["discos"]
    assert disco["cortada"] is True and disco["base_sin_leer"] == "/share/x/base.img"


@pytest.mark.parametrize("texto", ["", "uri=\n", URI + "-- /share/x.img\n{}\n",
                                   URI + "== %s\n-- /share/x.img\n{\"filename\": 3}\n" % VM1,
                                   URI + "== %s\n-- /share/x.img\n{no es json\n" % VM1,
                                   # el formato de --backing-chain (una lista) ya no es el de la orden
                                   URI + "== %s\n-- /share/x.img\n[{\"filename\": \"/share/x.img\"}]\n" % VM1,
                                   URI + "== %s\n!! cadena cortada\n" % VM1])
def test_la_cadena_de_imagenes_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.vm_imagenes(texto)


# ==== instantaneas ==============================================================================

def test_las_instantaneas_de_vs_salen_de_los_ficheros_de_cada_vm():
    vms = p.vm_snap_vs(dato("vm_snap_vs_hero"))
    assert len(vms) == 6
    assert por(vms, "uuid", VM1)["instantaneas"] == [
        {"id": 1790544225, "creada": "2026-09-27T21:23:45Z", "con_memoria": False}]
    assert [s["id"] for s in por(vms, "uuid", "00000000-0000-0000-0000-000000000004")["instantaneas"]] == [
        1715862105, 1715887104, 1790199623]
    assert por(vms, "uuid", VM2)["instantaneas"] == []


def test_una_instantanea_con_la_vm_en_marcha_guarda_tambien_su_memoria():
    vms = p.vm_snap_vs(dato("vm_snap_vs_qts"))
    con_memoria = [s for v in vms for s in v["instantaneas"] if s["con_memoria"]]
    assert len(con_memoria) == 4 and sum(len(v["instantaneas"]) for v in vms) == 13


def test_las_instantaneas_de_libvirt_suelen_estar_vacias():
    assert all(v["instantaneas"] == [] for v in p.vm_snap_libvirt(dato("vm_snap_libvirt_hero")))
    con = [v for v in p.vm_snap_libvirt(dato("vm_snap_libvirt_qts")) if v["instantaneas"]]
    assert len(con) == 1
    assert con[0]["instantaneas"] == [{"nombre": "1790104406", "creada": "2026-09-22 21:13:26 +0200",
                                       "estado": "running", "padre": None}]


@pytest.mark.parametrize("parser", [p.vm_snap_vs, p.vm_snap_libvirt])
@pytest.mark.parametrize("texto", ["", "uri=\n", URI + "1790544225.xml\n", URI + "== no-es-uuid\n"])
def test_las_instantaneas_no_se_inventan(parser, texto):
    with pytest.raises(ValueError):
        parser(texto)


def test_un_fichero_que_no_es_de_instantanea_no_cuenta():
    # escrito a mano
    (vm,) = p.vm_snap_vs(URI + "== %s\n1790544225.xml\nnotas.txt\n1790544225.state\n" % VM1)
    assert vm["instantaneas"] == [{"id": 1790544225, "creada": "2026-09-27T21:23:45Z", "con_memoria": True}]


# ================================================================================================
# contenedores (Container Station)
# ================================================================================================

ERRORES_DE_DOCKER = [
    "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?\n",
    "Error response from daemon: No such container: x\n",
    "permission denied while trying to connect to the Docker daemon socket\n"]


def test_el_resumen_de_docker_da_version_y_cuentas():
    assert p.ct_info(dato("ct_info_qts")) == {
        "version": "27.1.2-qnap8", "driver": "overlay2",
        "raiz": "/share/CACHEDEV3_DATA/ruta1/container-station-data/lib/docker", "contenedores": 45,
        "en_marcha": 34, "en_pausa": 0, "parados": 11, "imagenes": 137, "cpus": 8, "memoria": 33557118976}
    assert p.ct_info(dato("ct_info_hero"))["en_marcha"] == 0


@pytest.mark.parametrize("texto", ["", "version=27\n", "version=27\ncontenedores=muchos\n"] + ERRORES_DE_DOCKER)
def test_el_resumen_de_docker_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.ct_info(texto)


# --- lista --------------------------------------------------------------------------------------

def test_la_lista_da_imagen_estado_salud_puertos_redes_y_proyecto():
    lista = p.ct_lista(dato("ct_lista_qts"))
    assert len(lista) == 45 and sum(1 for c in lista if c["estado"] == "running") == 34
    assert por(lista, "nombre", "contenedor1") == {
        "nombre": "contenedor1", "imagen": "imagen1:latest", "estado": "running",
        "detalle": "Up 16 hours (healthy)", "salud": "healthy", "salida": None,
        "puertos": [{"anfitrion": "0.0.0.0", "puerto": "5100", "interno": "3000", "protocolo": "tcp"}],
        "redes": ["red1"], "creado": "2026-10-13 11:28:17 +0200 CEST", "proyecto": "proyecto1"}
    assert sum(1 for c in lista if c["salud"] == "unhealthy") == 1
    assert sum(1 for c in lista if c["salud"] is None and c["estado"] == "running") == 6


def test_un_contenedor_parado_da_su_codigo_de_salida():
    lista = p.ct_lista(dato("ct_lista_hero"))
    assert len(lista) == 6 and {c["estado"] for c in lista} == {"exited"}
    assert sorted(c["salida"] for c in lista) == [0, 0, 0, 0, 0, 137]
    assert por(lista, "nombre", "contenedor2")["redes"] == ["red1", "red2"]
    assert all(c["puertos"] == [] and c["proyecto"] == "proyecto1" for c in lista)


def test_los_puertos_expuestos_sin_publicar_y_los_rangos():
    # escrito a mano con las formas que da docker ps
    linea = ("web\tnginx:1\trunning\tUp 2 hours (health: starting)\t80/tcp, 0.0.0.0:8443->443/tcp, "
             ":::8443->443/tcp, 0.0.0.0:9000-9002->9000-9002/udp\tbridge\t2026-10-13 11:28:17 +0200 CEST\t\n")
    (c,) = p.ct_lista(linea)
    assert c["puertos"] == [
        {"anfitrion": None, "puerto": None, "interno": "80", "protocolo": "tcp"},
        {"anfitrion": "0.0.0.0", "puerto": "8443", "interno": "443", "protocolo": "tcp"},
        {"anfitrion": "::", "puerto": "8443", "interno": "443", "protocolo": "tcp"},
        {"anfitrion": "0.0.0.0", "puerto": "9000-9002", "interno": "9000-9002", "protocolo": "udp"}]
    assert (c["salud"], c["proyecto"], c["salida"]) == ("starting", None, None)


def test_un_contenedor_enlazado_con_link_sale_con_su_nombre():
    # visto en el NAS de laboratorio (2026-10-14): si otro contenedor lo enlaza con --link, docker ps
    # da en Names tambien el alias del enlace ("otro/alias"); el nombre es el que no lleva barra
    linea = ("prueba-base,prueba-enlace/base\tredis:7-alpine\trunning\tUp 8 seconds (unhealthy)\t6379/tcp\t"
             "bridge\t2026-10-14 21:47:01 +0200 CEST\t\n")
    (c,) = p.ct_lista(linea)
    assert c["nombre"] == "prueba-base"
    (c,) = p.ct_lista(linea.replace("prueba-base,prueba-enlace/base", "prueba-enlace/base,prueba-base"))
    assert c["nombre"] == "prueba-base"


def test_la_lista_de_contenedores_llega_con_el_texto_acotado():
    # escrito a mano: el nombre de imagen lo escribe quien crea el contenedor
    (c,) = p.ct_lista("web\t%s\tcreated\tCreated\t\t\t2026-10-13 11:28:17 +0200 CEST\t\n" % ("i" * 900))
    assert len(c["imagen"]) == p.MAX_NOMBRE and c["redes"] == [] and c["estado"] == "created"


def test_sin_contenedores_la_lista_esta_vacia():
    assert p.ct_lista("") == []


@pytest.mark.parametrize("texto", ["web\tnginx\trunning\n", "una linea sin tabuladores\n"] + ERRORES_DE_DOCKER)
def test_la_lista_de_contenedores_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.ct_lista(texto)


def test_las_aplicaciones_compose_dan_estado_y_ficheros():
    assert p.ct_compose(dato("ct_compose_hero")) == [
        {"proyecto": "proyecto1", "estado": "exited(6)", "ficheros": ["/share/ruta1/proyecto1/ruta2.yaml"]}]
    assert len(p.ct_compose(dato("ct_compose_qts"))) >= 10
    assert p.ct_compose("[]\n") == []


@pytest.mark.parametrize("texto", ["", "{}\n", "[{\"Status\": \"x\"}]\n", "NAME STATUS CONFIG FILES\n"] + ERRORES_DE_DOCKER)
def test_las_aplicaciones_compose_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.ct_compose(texto)


# --- detalle ------------------------------------------------------------------------------------

def test_el_detalle_de_un_contenedor_en_marcha():
    assert p.ct_detalle(dato("ct_detalle_qts")) == {
        "nombre": "contenedor1", "imagen": "imagen1:latest", "creado": "2026-10-13T09:28:17.663683158Z",
        "estado": "running", "salida": 0, "sin_memoria": False, "error": None,
        "inicio": "2026-10-13T09:28:33.159896152Z", "fin": None, "reinicios": 0, "salud": "healthy",
        "reinicio": "unless-stopped", "memoria_limite": None, "cpus_limite": None, "privilegiado": False,
        "modo_red": "red1",
        "redes": [{"red": "red1", "direccion": "192.0.2.1", "prefijo": 22, "puerta": "192.0.2.2",
                   "mac": "00:11:22:33:44:00"}],
        "puertos": [{"interno": "3000/tcp", "anfitrion": "0.0.0.0", "puerto": "5100"}],
        "montajes": [{"tipo": "volume", "volumen": "ruta2", "destino": "/destino1", "escritura": True,
                      "origen": "/share/CACHEDEV3_DATA/ruta1/container-station-data/lib/docker/volumes/ruta2/_data"}],
        "proyecto": "proyecto1", "servicio": "servicio1", "compose": "/share/ruta1/proyecto1/ruta3.yml"}


def test_el_detalle_de_un_contenedor_parado_en_la_red_del_anfitrion():
    d = p.ct_detalle(dato("ct_detalle_hero"))
    assert (d["estado"], d["salida"], d["salud"], d["fin"]) == ("exited", 0, None, "2026-09-27T21:59:06.524049095Z")
    assert d["redes"] == [{"red": "host", "direccion": None, "prefijo": None, "puerta": None, "mac": None}]
    assert d["puertos"] == [] and len(d["montajes"]) == 2
    assert d["montajes"][0] == {"tipo": "bind", "volumen": None, "destino": "/destino1", "escritura": False,
                                "origen": "/share/ruta1/proyecto1/ruta2/ruta3.sh"}


def test_los_elementos_de_numa_y_de_cpu_en_caliente_no_son_la_memoria_ni_las_vcpu_de_la_vm():
    # escrito a mano con el formato de libvirt: con el mismo nombre que la memoria y las vCPU
    # de la VM hay otros elementos (ajuste NUMA, modulos de memoria, vCPU que se anaden en
    # caliente). Una sola VM que los tenga no puede dejar sin leer todas las demas
    extra = ("    <memory mode='strict' nodeset='0'/>\n    <memory model='dimm'>\n"
             "    <vcpu id='0' enabled='yes' hotpluggable='no' order='1'/>\n"
             "    <vcpu id='1' enabled='no' hotpluggable='yes'/>\n")
    marca = "  <currentMemory unit='KiB'>4194304</currentMemory>\n"
    texto = dato("vm_xml_hero")
    assert texto.count(marca) == 6
    assert p.vm_xml(texto.replace(marca, marca + extra)) == p.vm_xml(texto)


DETALLE_A_MANO = (
    'nombre="/web"\nimagen="nginx:1"\ncreado="2026-10-01T10:00:00Z"\nestado="restarting"\nsalida=1\n'
    'sin_memoria=true\nerror="%s"\ninicio="2026-10-01T10:00:00Z"\nfin="2026-10-01T10:00:05Z"\nreinicios=37\n'
    'salud="unhealthy"\nreinicio="always"\nmemoria=536870912\nnanocpus=1500000000\nprivilegiado=true\n'
    'modo_red="bridge"\nredes=bridge=172.17.0.2/16 172.17.0.1 02:42:ac:11:00:02;otra=/0  ;\n'
    'puertos={"80/tcp":[{"HostIp":"0.0.0.0","HostPort":"8080"},{"HostIp":"::","HostPort":"8080"}],"443/tcp":null}\n'
    'montajes=[]\nproyecto=""\nservicio=""\ncompose=""\n')


def test_el_detalle_da_limites_reinicios_y_errores():
    # escrito a mano con el formato de la orden: un contenedor que no para de reiniciarse
    d = p.ct_detalle(DETALLE_A_MANO % ("e" * 900))
    assert (d["estado"], d["salida"], d["sin_memoria"], d["reinicios"], d["salud"]) == (
        "restarting", 1, True, 37, "unhealthy")
    assert (d["memoria_limite"], d["cpus_limite"], d["privilegiado"]) == (536870912, 1.5, True)
    assert len(d["error"]) == p.MAX_DESCRIPCION
    assert d["redes"] == [
        {"red": "bridge", "direccion": "172.17.0.2", "prefijo": 16, "puerta": "172.17.0.1", "mac": "02:42:ac:11:00:02"},
        {"red": "otra", "direccion": None, "prefijo": None, "puerta": None, "mac": None}]
    assert d["puertos"] == [{"interno": "80/tcp", "anfitrion": "0.0.0.0", "puerto": "8080"},
                            {"interno": "80/tcp", "anfitrion": "::", "puerto": "8080"},
                            {"interno": "443/tcp", "anfitrion": None, "puerto": None}]
    assert (d["proyecto"], d["servicio"], d["compose"]) == (None, None, None)


def test_el_detalle_solo_devuelve_los_campos_previstos():
    # aunque el NAS devolviera variables de entorno o la orden de arranque, no pasan
    d = p.ct_detalle(DETALLE_A_MANO % "" + 'env=["CLAVE=secreta"]\norden=["sh","-c","mysql -psecreta"]\n')
    assert "secreta" not in repr(d) and "env" not in d and "orden" not in d


@pytest.mark.parametrize("texto", ["", 'nombre="/web"\n', DETALLE_A_MANO.replace("salida=1", "salida=uno") % "",
                                   DETALLE_A_MANO.replace("montajes=[]", "montajes={") % ""] + ERRORES_DE_DOCKER)
def test_el_detalle_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.ct_detalle(texto)


# --- uso ----------------------------------------------------------------------------------------

def test_el_uso_da_porcentajes_como_numero_y_tamanos_en_bytes():
    uso = p.ct_stats(dato("ct_stats_qts"))
    assert len(uso) == 34
    assert por(uso, "nombre", "contenedor1") == {
        "nombre": "contenedor1", "cpu_pct": 0.0, "memoria": 71586284, "memoria_limite": 33554432000,
        "memoria_pct": 0.21, "red_recibido": 25900000, "red_enviado": 28700000, "disco_leido": 19100000000,
        "disco_escrito": 56100000, "procesos": 11}
    limitado = por(uso, "nombre", "contenedor3")
    assert (limitado["cpu_pct"], limitado["memoria_limite"], limitado["memoria_pct"]) == (0.1, 3 * 1024 ** 3, 1.05)
    assert p.ct_stats(dato("ct_stats_hero")) == []            # ninguno en marcha


def test_las_unidades_de_docker_decimales_y_binarias():
    # escrito a mano: docker da la memoria en multiplos de 1024 y la red y el disco en multiplos de 1000
    (u,) = p.ct_stats("web\t150.25%\t512KiB / 1.5TiB\t0.00%\t0B / 1.2kB\t3TB / 0B\t1\n")
    assert (u["cpu_pct"], u["memoria"], u["memoria_limite"]) == (150.25, 512 * 1024, int(1.5 * 1024 ** 4))
    assert (u["red_recibido"], u["red_enviado"], u["disco_leido"], u["disco_escrito"]) == (0, 1200, 3 * 10 ** 12, 0)


def test_un_contenedor_sin_cifras_las_da_sin_valor():
    # escrito a mano: lo que da docker stats de un contenedor que se para mientras lo mide
    (u,) = p.ct_stats("web\t--\t-- / --\t--\t-- / --\t-- / --\t--\n")
    assert u == {"nombre": "web", "cpu_pct": None, "memoria": None, "memoria_limite": None, "memoria_pct": None,
                 "red_recibido": None, "red_enviado": None, "disco_leido": None, "disco_escrito": None,
                 "procesos": None}


def test_una_memoria_de_cero_sobre_cero_es_que_no_se_midio():
    # escrito a mano: lo que da docker stats de un contenedor que aun arranca o ya se ha parado
    (u,) = p.ct_stats("web\t0.00%\t0B / 0B\t0.00%\t0B / 0B\t0B / 0B\t0\n")
    # no es un contenedor parado a cero: no se midio, y nada de esa fila es una cifra
    assert u == {"nombre": "web", "cpu_pct": None, "memoria": None, "memoria_limite": None, "memoria_pct": None,
                 "red_recibido": None, "red_enviado": None, "disco_leido": None, "disco_escrito": None,
                 "procesos": None}


@pytest.mark.parametrize("texto", ["web\t1%\n", "web\tmucho\t1MiB / 2MiB\t1%\t0B / 0B\t0B / 0B\t1\n",
                                   "web\t1%\t1 litro / 2MiB\t1%\t0B / 0B\t0B / 0B\t1\n"] + ERRORES_DE_DOCKER)
def test_el_uso_de_los_contenedores_no_se_inventa(texto):
    with pytest.raises(ValueError):
        p.ct_stats(texto)


# --- registros ----------------------------------------------------------------------------------

REGISTRO = ("2026-10-13T09:00:00Z arranque correcto\n"
            "\x1b[32mINFO\x1b[0m peticion atendida\tGET /\n"
            "\n"
            "%s\n" % ("x" * 500))


BIEN = "\n==rc 0\n"                  # lo que la orden anade al final: el codigo de salida de docker


def test_los_registros_llegan_sin_caracteres_de_control_y_con_lineas_acotadas():
    # escrito a mano: los registros reales de un contenedor no se guardan como datos de prueba
    lineas = p.ct_logs(REGISTRO + BIEN)
    assert lineas[:2] == ["2026-10-13T09:00:00Z arranque correcto", " [32mINFO [0m peticion atendida GET /"]
    assert len(lineas) == 3 and len(lineas[2]) == p.MAX_LINEA
    assert p.ct_logs(BIEN) == []


@pytest.mark.parametrize("texto", ERRORES_DE_DOCKER + ["Error: No such container: web\n"])
def test_un_error_de_docker_no_pasa_por_registro_del_contenedor(texto):
    with pytest.raises(ValueError) as e:
        p.ct_logs(texto + "\n==rc 1\n")
    assert texto.strip()[:40] in str(e.value)


def test_docker_que_falla_sin_decir_nada_tambien_es_un_error():
    with pytest.raises(ValueError) as e:
        p.ct_logs("\n==rc 125\n")
    assert "125" in str(e.value)


@pytest.mark.parametrize("texto", ["", "una linea\n", REGISTRO, "==rc\n", "==rc x\n", "==rc 0 y algo mas\n"])
def test_un_registro_sin_su_marca_final_no_se_da_por_bueno(texto):
    # sin la marca no se sabe si docker respondio o si la salida llego cortada
    with pytest.raises(ValueError):
        p.ct_logs(texto)


@pytest.mark.parametrize("texto, lineas", [
    ("Error: boom\n", ["Error: boom"]),
    ("Error response from daemon: algo que registra el propio programa\n",
     ["Error response from daemon: algo que registra el propio programa"]),
    ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n",
     ["Cannot connect to the Docker daemon at unix:///var/run/docker.sock"]),
    ("Error: connect ECONNREFUSED 192.0.2.1:5432\n    at TCPConnectWrap.afterConnect\nreintentando\n",
     ["Error: connect ECONNREFUSED 192.0.2.1:5432", "    at TCPConnectWrap.afterConnect", "reintentando"]),
    ("==rc 1\notra\n", ["==rc 1", "otra"]),
    ("ultima linea sin salto", ["ultima linea sin salto"])])
def test_lo_que_escribe_el_programa_es_registro_aunque_parezca_un_error_de_docker(texto, lineas):
    # con docker terminando bien (==rc 0), todo lo anterior a la marca lo ha escrito el contenedor
    assert p.ct_logs(texto + BIEN) == lineas


# --- redes --------------------------------------------------------------------------------------

def test_las_redes_dan_driver_subred_y_contenedores_conectados():
    redes = p.ct_redes(dato("ct_redes_qts"))
    assert len(redes) == 35 and sorted({r["driver"] for r in redes}) == ["bridge", "host", "null", "qnet"]
    assert por(redes, "red", "red7") == {
        "red": "red7", "driver": "bridge", "ambito": "local", "interna": False,
        "subredes": [{"subred": "192.0.2.3/22", "puerta": "192.0.2.4"}],
        "contenedores": [{"nombre": "contenedor9", "direccion": "192.0.2.5"},
                         {"nombre": "contenedor25", "direccion": "192.0.2.6"},
                         {"nombre": "proyecto7", "direccion": "192.0.2.7"}]}
    assert por(redes, "red", "host")["subredes"] == []


def test_las_redes_de_un_nas_sin_contenedores_en_marcha():
    redes = p.ct_redes(dato("ct_redes_hero"))
    assert [r["red"] for r in redes] == ["bridge", "host", "red1", "red2", "none"]
    assert all(r["contenedores"] == [] for r in redes)


@pytest.mark.parametrize("texto", ["", "bridge\tbridge\tlocal\n", "bridge\tbridge\tlocal\tfalse\t{no json\t\n",
                                   "bridge\tbridge\tlocal\tfalse\tnull\tweb sin direccion \n"] + ERRORES_DE_DOCKER)
def test_las_redes_no_se_inventan(texto):
    with pytest.raises(ValueError):
        p.ct_redes(texto)


# --- lo que no es Docker ------------------------------------------------------------------------

def test_los_contenedores_internos_de_container_station():
    assert p.ct_internos(dato("ct_internos_qts")) == [{"nombre": "qcal", "imagen": "qcal:1.1", "estado": "running"}]
    assert p.ct_internos(dato("ct_internos_hero")) == []
    for texto in ["qcal\tqcal:1.1\n"] + ERRORES_DE_DOCKER:
        with pytest.raises(ValueError):
            p.ct_internos(texto)


def test_las_instancias_de_lxd_salen_de_sus_carpetas():
    assert p.ct_lxd(dato("ct_lxd_qts")) == {"contenedores": [], "maquinas": []}
    # escrito a mano: un NAS con instancias y otro que no tiene LXD
    assert p.ct_lxd("== /var/lib/lxd/containers\nubuntu-1\notro\n== /var/lib/lxd/virtual-machines\nvm-lxd\n") == {
        "contenedores": ["ubuntu-1", "otro"], "maquinas": ["vm-lxd"]}
    for texto in ("", "ubuntu-1\n", "== /var/lib/lxd/containers\n"):
        with pytest.raises(ValueError):
            p.ct_lxd(texto)
