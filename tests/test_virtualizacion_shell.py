# -*- coding: utf-8 -*-
"""Las ordenes que recorren rutas sacadas de la definicion de una VM, ejecutadas en un shell
de verdad con un virsh y un qemu-img de pega: una carpeta con espacios en el nombre (las VMs
de Virtualization Station se guardan en una carpeta con su nombre) no puede partir la ruta.

Necesita un sh en el PATH (en Windows, el de Git); si no lo hay, se saltan."""
import json
import os
import shutil
import subprocess

import pytest

from qnap_tools.virtualizacion import comandos as vc
from qnap_tools.virtualizacion import parsers as p

SH = shutil.which("sh")
pytestmark = pytest.mark.skipif(SH is None, reason="hace falta un sh para ejecutar las ordenes")
UUID = "00000000-0000-0000-0000-00000000000a"
# virsh de pega: responde a las cuatro subordenes que usan estas ordenes ($1 a $3 son las
# opciones -r -c qemu:///system, que el shell le pasa tal cual)
VIRSH_DE_PEGA = """\
shift 3
case "$1" in
  uri) echo qemu:///system ;;
  list) cat "$PEGA/lista" ;;
  dumpxml) cat "$PEGA/$2.xml" ;;
  domblklist) cat "$PEGA/$3.blk" ;;
esac
"""


QEMU_DE_PEGA = """\
for a in "$@"; do ultimo="$a"; done
echo "$*" >> "$PEGA/llamadas"
nombre=$(basename "$ultimo")
[ ! -e "$PEGA/img/$nombre" ] || cat "$PEGA/img/$nombre"
"""


def posix(ruta):
    return str(ruta).replace("\\", "/")


def lanzar(comando, tmp_path, xml="", discos="", qemu=None):
    """La salida de la orden en un sh real, con virsh y qemu-img sustituidos por dobles."""
    pega = tmp_path / "pega"
    pega.mkdir(exist_ok=True)
    (pega / "virsh.sh").write_text(VIRSH_DE_PEGA, encoding="utf-8", newline="\n")
    (pega / "lista").write_text(UUID + "\n", encoding="utf-8", newline="\n")
    (pega / (UUID + ".xml")).write_text(xml, encoding="utf-8", newline="\n")
    (pega / (UUID + ".blk")).write_text(discos, encoding="utf-8", newline="\n")
    texto = comando.render()
    assert vc.VIRSH in texto
    texto = texto.replace(vc.VIRSH, "sh %s/virsh.sh -r -c qemu:///system" % posix(pega))
    if qemu is None:
        # qemu-img de pega: dice con que argumentos lo llaman, uno por linea entre corchetes
        texto = texto.replace(vc.QEMU_IMG, "printf '[\"%s\"]\\n'")
    else:
        (pega / "qemu.sh").write_text(qemu, encoding="utf-8", newline="\n")
        texto = texto.replace(vc.QEMU_IMG, "sh %s/qemu.sh" % posix(pega))
    r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                       env={"PEGA": posix(pega), "PATH": os.environ["PATH"]}, timeout=60)
    return r.returncode, r.stdout


def test_las_instantaneas_de_una_vm_guardada_en_una_carpeta_con_espacios_se_leen(tmp_path):
    meta = tmp_path / "Mis VMs" / "Windows 10 de pruebas" / ".meta"
    (meta / "snapshot").mkdir(parents=True)
    for nombre in ("1790544225.xml", "1790544225.state", "1715862105.xml"):
        (meta / "snapshot" / nombre).write_text("", encoding="utf-8")
    xml = "<domain>\n  <metadata>\n    <qvs:meta_path>%s</qvs:meta_path>\n  </metadata>\n</domain>\n" % posix(meta)
    rc, salida = lanzar(vc.VM_SNAP_VS, tmp_path, xml=xml)
    assert rc == 0
    (vm,) = p.vm_snap_vs(salida)
    assert [(i["id"], i["con_memoria"]) for i in vm["instantaneas"]] == [(1715862105, False), (1790544225, True)]


def test_una_vm_sin_instantaneas_tiene_su_carpeta_y_ninguna_instantanea(tmp_path):
    meta = tmp_path / "vm" / ".meta"
    meta.mkdir(parents=True)
    xml = "    <qvs:meta_path>%s</qvs:meta_path>\n" % posix(meta)
    rc, salida = lanzar(vc.VM_SNAP_VS, tmp_path, xml=xml)
    assert rc == 0 and p.vm_snap_vs(salida) == [{"uuid": UUID, "instantaneas": []}]


def test_una_carpeta_de_metadatos_que_no_existe_no_pasa_por_cero_instantaneas(tmp_path):
    xml = "    <qvs:meta_path>%s</qvs:meta_path>\n" % posix(tmp_path / "no existe" / ".meta")
    rc, salida = lanzar(vc.VM_SNAP_VS, tmp_path, xml=xml)
    assert rc == 0 and p.vm_snap_vs(salida) == [{"uuid": UUID, "instantaneas": None}]


def test_la_memoria_guardada_de_una_vm_en_una_carpeta_con_espacios_se_lee(tmp_path):
    meta = tmp_path / "Mis VMs" / "Windows 10 de pruebas" / ".meta"
    (meta / "snapshot").mkdir(parents=True)
    (meta / (UUID + ".state")).write_bytes(b"x" * 1234)
    # la memoria de una instantanea no es la de la suspension
    (meta / "snapshot" / "1790544225.state").write_bytes(b"x")
    xml = "    <qvs:meta_path>%s</qvs:meta_path>\n" % posix(meta)
    rc, salida = lanzar(vc.VM_GUARDADAS, tmp_path, xml=xml)
    assert rc == 0
    assert p.vm_guardadas(salida)[UUID]["bytes"] == 1234


@pytest.mark.parametrize("con_carpeta", [True, False])
def test_sin_memoria_guardada_o_sin_carpeta_la_vm_no_tiene_memoria_guardada(tmp_path, con_carpeta):
    meta = tmp_path / "vm" / ".meta"
    if con_carpeta:
        meta.mkdir(parents=True)
    xml = "    <qvs:meta_path>%s</qvs:meta_path>\n" % posix(meta)
    rc, salida = lanzar(vc.VM_GUARDADAS, tmp_path, xml=xml)
    assert rc == 0 and p.vm_guardadas(salida) == {UUID: None}
    assert ("!! sin carpeta" in salida) is not con_carpeta


def test_un_dumpxml_que_falla_deja_su_marca_y_no_pasa_por_cero_instantaneas_ni_por_no_suspendida(
        tmp_path, monkeypatch):
    # virsh de pega cuyo dumpxml falla: la orden acaba bien, pero la VM no puede salir como si
    # no tuviera instantaneas ni memoria guardada
    roto = VIRSH_DE_PEGA.replace('dumpxml) cat "$PEGA/$2.xml" ;;', 'dumpxml) echo "error: fallo" 1>&2; exit 1 ;;')
    assert roto != VIRSH_DE_PEGA
    monkeypatch.setitem(globals(), "VIRSH_DE_PEGA", roto)
    for comando in (vc.VM_SNAP_VS, vc.VM_GUARDADAS):
        rc, salida = lanzar(comando, tmp_path)
        assert rc == 0 and "!! dumpxml fallo" in salida, comando.id
    assert p.vm_snap_vs(lanzar(vc.VM_SNAP_VS, tmp_path)[1]) == [{"uuid": UUID, "instantaneas": None}]
    with pytest.raises(ValueError):
        p.vm_guardadas(lanzar(vc.VM_GUARDADAS, tmp_path)[1])


def test_la_cadena_se_recorre_capa_a_capa_y_no_sigue_una_base_remota(tmp_path):
    discos = (" Type   Device   Target   Source\n" + "-" * 48 + "\n"
              " file   disk     vda      /share/Mis VMs/vm/disco 1.img.1790544225\n")
    img = tmp_path / "pega" / "img"
    img.mkdir(parents=True)
    capas = {
        "disco 1.img.1790544225": {"filename": "/share/Mis VMs/vm/disco 1.img.1790544225", "format": "qcow2",
                                   "actual-size": 4, "backing-filename": "disco 1.img",
                                   "full-backing-filename": "/share/Mis VMs/vm/disco 1.img"},
        "disco 1.img": {"filename": "/share/Mis VMs/vm/disco 1.img", "format": "qcow2", "actual-size": 8,
                        "backing-filename": "nbd://192.0.2.9:10809/x", "full-backing-filename": "nbd://192.0.2.9:10809/x"},
        "x": {"filename": "nbd://192.0.2.9:10809/x", "format": "raw", "actual-size": 1}}
    for nombre, capa in capas.items():
        (img / nombre).write_text(json.dumps(capa, indent=4) + "\n", encoding="utf-8", newline="\n")
    rc, salida = lanzar(vc.VM_IMAGENES, tmp_path, discos=discos, qemu=QEMU_DE_PEGA)
    assert rc == 0
    llamadas = (tmp_path / "pega" / "llamadas").read_text(encoding="utf-8").splitlines()
    assert [ll.rsplit("json ", 1)[1] for ll in llamadas] == [
        "/share/Mis VMs/vm/disco 1.img.1790544225", "/share/Mis VMs/vm/disco 1.img"]
    assert not any("--backing-chain" in ll for ll in llamadas)
    (vm,) = p.vm_imagenes(salida)
    (disco,) = vm["discos"]
    assert [c["ocupa"] for c in disco["cadena"]] == [4, 8]
    assert disco["base_sin_leer"] == "nbd://192.0.2.9:10809/x"


def test_una_base_fuera_de_las_carpetas_compartidas_no_se_abre(tmp_path):
    # una imagen que apunta a un dispositivo o a un fichero del sistema: qemu-img no lo abre
    discos = (" Type   Device   Target   Source\n" + "-" * 48 + "\n"
              " file   disk     vda      /share/vm/capa.img\n")
    img = tmp_path / "pega" / "img"
    img.mkdir(parents=True)
    (img / "capa.img").write_text(json.dumps({"filename": "/share/vm/capa.img", "format": "qcow2",
                                              "full-backing-filename": "/dev/sda"}) + "\n",
                                  encoding="utf-8", newline="\n")
    rc, salida = lanzar(vc.VM_IMAGENES, tmp_path, discos=discos, qemu=QEMU_DE_PEGA)
    assert rc == 0
    llamadas = (tmp_path / "pega" / "llamadas").read_text(encoding="utf-8").splitlines()
    assert [ll.rsplit("json ", 1)[1] for ll in llamadas] == ["/share/vm/capa.img"]
    (vm,) = p.vm_imagenes(salida)
    assert vm["discos"][0]["base_sin_leer"] == "/dev/sda"


def test_una_cadena_sin_fin_se_corta_y_se_dice(tmp_path):
    discos = (" Type   Device   Target   Source\n" + "-" * 48 + "\n"
              " file   disk     vda      /share/vm/bucle.img\n")
    img = tmp_path / "pega" / "img"
    img.mkdir(parents=True)
    # una imagen que se tiene a si misma por base: la orden no da vueltas sin fin
    (img / "bucle.img").write_text(json.dumps({"filename": "/share/vm/bucle.img", "format": "qcow2",
                                               "full-backing-filename": "/share/vm/bucle.img"}) + "\n",
                                   encoding="utf-8", newline="\n")
    rc, salida = lanzar(vc.VM_IMAGENES, tmp_path, discos=discos, qemu=QEMU_DE_PEGA)
    assert rc == 0
    (vm,) = p.vm_imagenes(salida)
    (disco,) = vm["discos"]
    assert disco["cortada"] is True and len(disco["cadena"]) == vc.MAX_CAPAS_IMAGEN


def test_la_imagen_de_un_disco_en_una_carpeta_con_espacios_se_pide_entera(tmp_path):
    discos = (" Type   Device   Target   Source\n"
              "------------------------------------------------\n"
              " file   disk     vda      /share/Mis VMs/Windows 10 de pruebas/disco 1.img   \n"
              " file   disk     vdb      /share/Vms/vm/datos.img\n"
              " file   cdrom    hda      /QVS/guest_tools.iso\n"
              " file   cdrom    hdb      -\n\n")
    rc, salida = lanzar(vc.VM_IMAGENES, tmp_path, discos=discos)
    lineas = salida.splitlines()
    assert lineas[:2] == ["uri=qemu:///system", "== " + UUID]
    assert [linea for linea in lineas if linea.startswith("-- ")] == [
        "-- /share/Mis VMs/Windows 10 de pruebas/disco 1.img", "-- /share/Vms/vm/datos.img"]
    # la ruta llega a qemu-img como un solo argumento, el ultimo
    assert '["/share/Mis VMs/Windows 10 de pruebas/disco 1.img"]' in lineas
    assert '["/share/Vms/vm/datos.img"]' in lineas

# --- las ordenes que leen por una ruta de la carpeta compartida ----------------------------------
# /share no existe en este PC: las ordenes se ejecutan con "/share/" cambiado por una carpeta
# temporal (la misma en la ruta pedida, en la comprobacion de que cuelga de ella y en el filtro de
# las bases), de modo que lo que se prueba es la plantilla de verdad.

QEMU_FICHERO_DE_PEGA = """\
for a in "$@"; do ultimo="$a"; done
echo "$*" >> "$PEGA/llamadas"
nombre=$(basename "$ultimo")
if [ "$1" = check ]; then [ ! -e "$PEGA/chk/$nombre.err" ] || cat "$PEGA/chk/$nombre.err" >&2
  cat "$PEGA/chk/$nombre"; exit $(cat "$PEGA/chk/rc"); fi
[ ! -e "$PEGA/img/$nombre" ] || cat "$PEGA/img/$nombre"
"""
XML_VM = """\
<domain type='kvm'>
  <name>{uuid}</name>
  <uuid>{uuid}</uuid>
  <description>prueba</description>
  <metadata>
    <qvs:vm xmlns:qvs="http://example.invalid/qvs">
      <qvs:name>maquina de pruebas</qvs:name>
      <qvs:meta_path>{meta}</qvs:meta_path>
      <qvs:os type="linux" arch="x86"/>
    </qvs:vm>
  </metadata>
  <memory unit='KiB'>2097152</memory>
  <currentMemory unit='KiB'>2097152</currentMemory>
  <vcpu placement='static'>2</vcpu>
  <os>
    <type arch='x86_64' machine='pc-i440fx-7.0'>hvm</type>
  </os>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' cache='writeback'/>
      <source file='{disco}'/>
      <target dev='hda' bus='ide'/>
    </disk>
    <graphics type='vnc' port='5901' autoport='no' listen='0.0.0.0' passwd='clave-vnc-123' keymap='es'>
      <listen type='address' address='0.0.0.0'/>
    </graphics>
  </devices>
</domain>
"""
UUID_FICHERO = "12345678-9abc-4def-8123-456789abcdef"


class Share:
    """Una carpeta compartida de pega: tmp/share, con su ruta canonica tal como la ve el sh."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.carpeta = tmp_path / "share"
        self.carpeta.mkdir(exist_ok=True)
        r = subprocess.run([SH, "-c", 'readlink -f "%s"' % posix(self.carpeta)], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        self.real = r.stdout.strip()
        assert self.real, r.stderr
        self.raiz = self.real.rsplit("/", 1)[0]       # la carpeta que contiene a share

    def ruta(self, relativa):
        """La ruta pedida al comando (/share/...) y la que el sh vera de verdad."""
        return "/share/" + relativa, self.real + "/" + relativa

    def fichero(self, relativa, texto="x"):
        destino = self.carpeta / relativa
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8", newline="\n")
        return destino

    def lanzar(self, comando, relativa, qemu=None, fuera=False):
        """La salida de la orden pedida con /share/<relativa> (o con una ruta fuera de la compartida)."""
        pega = self.tmp / "pega"
        pega.mkdir(exist_ok=True)
        pedida = "/fuera/" + relativa if fuera else self.ruta(relativa)[0]
        texto = comando.render({"ruta": pedida}).replace("/share/", self.real + "/").replace(
            "/fuera/", self.raiz + "/")
        if qemu is not None:
            (pega / "qemu.sh").write_text(qemu, encoding="utf-8", newline="\n")
            texto = texto.replace(vc.QEMU_IMG, "sh %s/qemu.sh" % posix(pega))
        r = subprocess.run([SH, "-c", texto], capture_output=True, text=True, encoding="utf-8",
                           env={"PEGA": posix(pega), "PATH": os.environ["PATH"]}, timeout=60)
        return r.returncode, r.stdout

    def imagen(self, nombre, **campos):
        """La respuesta de qemu-img info para una imagen (sus rutas ya con la carpeta de verdad)."""
        img = self.tmp / "pega" / "img"
        img.mkdir(parents=True, exist_ok=True)
        capa = {"filename": self.ruta(nombre)[1], "format": "qcow2", "virtual-size": 1024, "actual-size": 8}
        capa.update(campos)
        (img / nombre.rsplit("/", 1)[-1]).write_text(json.dumps(capa, indent=4) + "\n", encoding="utf-8", newline="\n")

    def comprobacion(self, nombre, rc, salida, errores=""):
        """Lo que da qemu-img check de esa imagen: 'salida' por stdout, 'errores' por stderr."""
        chk = self.tmp / "pega" / "chk"
        chk.mkdir(parents=True, exist_ok=True)
        (chk / nombre.rsplit("/", 1)[-1]).write_text(salida, encoding="utf-8", newline="\n")
        if errores:
            (chk / (nombre.rsplit("/", 1)[-1] + ".err")).write_text(errores, encoding="utf-8", newline="\n")
        (chk / "rc").write_text(str(rc), encoding="utf-8", newline="\n")

    def llamadas(self):
        return (self.tmp / "pega" / "llamadas").read_text(encoding="utf-8").splitlines()


def test_disco_info_recorre_la_cadena_de_una_carpeta_con_espacios_capa_a_capa(tmp_path):
    s = Share(tmp_path)
    capa, base = "Mis VMs/vm/disco 1.img.1790544225", "Mis VMs/vm/disco 1.img"
    s.fichero(capa), s.fichero(base)
    s.imagen(capa, **{"full-backing-filename": s.ruta(base)[1], "backing-filename": "disco 1.img",
                      "dirty-flag": False})
    s.imagen(base, **{"dirty-flag": True})
    rc, salida = s.lanzar(vc.DISCO_INFO, capa, qemu=QEMU_FICHERO_DE_PEGA)
    assert rc == 0
    info = p.disco_info(salida.replace(s.real, "/share"))
    assert [c["fichero"] for c in info["capas"]] == ["/share/" + capa, "/share/" + base]
    assert [c["dirty"] for c in info["capas"]] == [False, True] and info["cortada"] is False
    llamadas = s.llamadas()
    assert [ll.rsplit("json ", 1)[1] for ll in llamadas] == [s.ruta(capa)[1], s.ruta(base)[1]]
    assert all(ll.startswith("info -U --output=json ") for ll in llamadas)
    assert not any("--backing-chain" in ll for ll in llamadas)


def test_disco_info_no_sigue_una_base_fuera_de_la_carpeta_compartida(tmp_path):
    s = Share(tmp_path)
    s.fichero("vm/capa.img")
    s.imagen("vm/capa.img", **{"full-backing-filename": "nbd://192.0.2.9:10809/x"})
    rc, salida = s.lanzar(vc.DISCO_INFO, "vm/capa.img", qemu=QEMU_FICHERO_DE_PEGA)
    assert rc == 0 and len(s.llamadas()) == 1
    info = p.disco_info(salida.replace(s.real, "/share"))
    assert info["base_sin_leer"] == "nbd://192.0.2.9:10809/x" and len(info["capas"]) == 1


def test_disco_info_con_una_cadena_sin_fin_se_corta_y_lo_dice(tmp_path):
    s = Share(tmp_path)
    s.fichero("vm/bucle.img")
    s.imagen("vm/bucle.img", **{"full-backing-filename": s.ruta("vm/bucle.img")[1]})
    rc, salida = s.lanzar(vc.DISCO_INFO, "vm/bucle.img", qemu=QEMU_FICHERO_DE_PEGA)
    assert rc == 0
    info = p.disco_info(salida.replace(s.real, "/share"))
    assert info["cortada"] is True and len(info["capas"]) == vc.MAX_CAPAS_IMAGEN


@pytest.mark.parametrize("comando", [vc.DISCO_INFO, vc.DISCO_CHECK])
def test_una_ruta_fuera_de_la_carpeta_compartida_o_que_no_existe_no_llega_a_qemu(tmp_path, comando):
    s = Share(tmp_path)
    (tmp_path / "otra").mkdir()
    (tmp_path / "otra" / "disco.img").write_text("x", encoding="utf-8")
    (s.carpeta / "vm" / "carpeta.img").mkdir(parents=True)      # una carpeta con nombre de imagen no vale
    for relativa, fuera in (("otra/disco.img", True), ("vm/no existe.img", False), ("vm/carpeta.img", False)):
        rc, salida = s.lanzar(comando, relativa, qemu=QEMU_FICHERO_DE_PEGA, fuera=fuera)
        assert rc == 0 and salida.strip() == "==rechazada", relativa
        with pytest.raises(ValueError):
            (p.disco_info if comando is vc.DISCO_INFO else p.disco_check)(salida)
    assert not (tmp_path / "pega" / "llamadas").exists()


def test_la_comprobacion_da_el_codigo_de_salida_y_nunca_repara(tmp_path):
    s = Share(tmp_path)
    s.fichero("vm/disco.img")
    fichero = s.ruta("vm/disco.img")[1]
    salida_qemu = json.dumps({"image-end-offset": 4096, "total-clusters": 16, "check-errors": 0, "corruptions": 2,
                              "filename": fichero, "format": "qcow2"}, indent=4) + "\n"
    s.comprobacion("disco.img", 2, salida_qemu)
    rc, salida = s.lanzar(vc.DISCO_CHECK, "vm/disco.img", qemu=QEMU_FICHERO_DE_PEGA)
    assert rc == 0 and salida.rstrip().endswith("==rc 2")
    comprobacion = p.disco_check(salida.replace(s.real, "/share"))
    assert comprobacion["corrupciones"] == 2 and comprobacion["codigo_de_salida"] == 2
    (llamada,) = s.llamadas()
    assert llamada.startswith("check -U --output=json ") and " -r" not in llamada and "--repair" not in llamada


def test_la_comprobacion_acota_en_el_nas_las_lineas_de_qemu_y_las_cuenta_por_tipo(tmp_path):
    """Como la imagen sin cerrar del USB: una linea por cluster. Por la conexion solo viajan 20 y la cuenta
    de cada tipo (con los numeros cambiados por N, salvo los valores de refcount y reference), y el codigo de
    salida sigue siendo el de qemu-img aunque pase por awk."""
    s = Share(tmp_path)
    s.fichero("vm/disco.img")
    fichero = s.ruta("vm/disco.img")[1]
    errores = "".join("ERROR cluster %d refcount=0 reference=1\n" % (5000 + i) for i in range(3000))
    errores += "".join("ERROR OFLAG_COPIED data cluster: l2_entry=80000000%08x refcount=0\n" % (0x50000 + i * 0x10000)
                       for i in range(3000))
    errores += "Leaked cluster 77 refcount=1 reference=0\nLeaked cluster 78 refcount=1 reference=0\n"
    salida_qemu = json.dumps({"image-end-offset": 4096, "total-clusters": 16, "check-errors": 0, "corruptions": 6000,
                              "leaks": 2, "filename": fichero, "format": "qcow2"}, indent=4) + "\n"
    s.comprobacion("disco.img", 3, salida_qemu, errores)
    rc, salida = s.lanzar(vc.DISCO_CHECK, "vm/disco.img", qemu=QEMU_FICHERO_DE_PEGA)
    assert rc == 0 and salida.rstrip().endswith("==rc 3") and len(salida) < 4000
    c = p.disco_check(salida.replace(s.real, "/share"))
    a = c["avisos_de_qemu"]
    assert a["total"] == 6002 and a["truncado"] is True and len(a["filas"]) == 20
    assert a["filas"][0] == "ERROR cluster 5000 refcount=0 reference=1"
    assert a["por_tipo"]["filas"] == [
        {"tipo": "ERROR OFLAG_COPIED data cluster: l2_entry=N refcount=0", "lineas": 3000},
        {"tipo": "ERROR cluster N refcount=0 reference=1", "lineas": 3000},
        {"tipo": "Leaked cluster N refcount=1 reference=0", "lineas": 2}]
    assert (c["corrupciones"], c["fugas"], c["codigo_de_salida"]) == (6000, 2, 3)


def test_la_comprobacion_no_da_mas_de_cincuenta_y_un_tipos_de_linea(tmp_path):
    s = Share(tmp_path)
    s.fichero("vm/disco.img")
    errores = "".join("mensaje raro %s\n" % "".join(chr(97 + int(d)) for d in str(i)) for i in range(200))
    s.comprobacion("disco.img", 1, "", errores)
    rc, salida = s.lanzar(vc.DISCO_CHECK, "vm/disco.img", qemu=QEMU_FICHERO_DE_PEGA)
    assert rc == 0 and salida.count("==tipo ") == 51 and salida.count("==linea ") == 20
    assert "==tipo 150 (otros tipos)" in salida and salida.rstrip().endswith("==rc 1")


def escribe_vm(s, carpeta="Mis VMs/maquina 1", xml=None):
    """Una VM de VS en una carpeta con espacios: <carpeta>/.<uuid>.meta/<uuid>.xml. Devuelve el .xml."""
    meta = "%s/.%s.meta" % (carpeta, UUID_FICHERO)
    texto = xml if xml is not None else XML_VM.format(
        uuid=UUID_FICHERO, meta=s.ruta(meta)[1], disco=s.ruta(carpeta + "/disco 1.img")[1])
    s.fichero("%s/%s.xml" % (meta, UUID_FICHERO), texto)
    return "%s/%s.xml" % (meta, UUID_FICHERO)


@pytest.mark.parametrize("que", ["el_xml", "la_carpeta_de_metadatos", "la_carpeta_de_la_vm"])
def test_la_definicion_se_lee_desde_el_xml_su_carpeta_de_metadatos_o_la_de_la_vm(tmp_path, que):
    s = Share(tmp_path)
    xml = escribe_vm(s)
    relativa = {"el_xml": xml, "la_carpeta_de_metadatos": xml.rsplit("/", 1)[0],
                "la_carpeta_de_la_vm": "Mis VMs/maquina 1"}[que]
    rc, salida = s.lanzar(vc.VM_DEFINICION_FICHERO, relativa)
    assert rc == 0
    vm = p.vm_definicion_fichero(salida.replace(s.real, "/share"))
    assert vm["uuid"] == UUID_FICHERO and vm["nombre"] == "maquina de pruebas" and vm["vcpus"] == 2
    assert vm["fichero"] == "/share/" + xml
    assert vm["discos"][0]["fichero"] == "/share/Mis VMs/maquina 1/disco 1.img"
    assert vm["graficos"] == {"tipo": "vnc", "puerto": 5901, "autopuerto": False, "escucha": "0.0.0.0",
                              "teclado": "es"}


def test_la_contrasena_de_la_consola_no_sale_del_nas_ni_con_el_xml_real(tmp_path):
    s = Share(tmp_path)
    xml = escribe_vm(s)
    rc, salida = s.lanzar(vc.VM_DEFINICION_FICHERO, xml)
    assert rc == 0 and "clave-vnc-123" not in salida and "passwd" not in salida
    # un XML en una sola linea no deja pasar la contrasena: la lectura da un error, no el dato
    una_linea = "".join(linea.strip() for linea in (tmp_path / "share" / xml).read_text(encoding="utf-8").splitlines())
    assert "passwd=" in una_linea
    (tmp_path / "share" / xml).write_text(una_linea + "\n", encoding="utf-8", newline="\n")
    rc, salida = s.lanzar(vc.VM_DEFINICION_FICHERO, xml)
    assert "clave-vnc-123" not in salida and "passwd" not in salida
    with pytest.raises(ValueError):
        p.vm_definicion_fichero(salida.replace(s.real, "/share"))


def test_un_xml_que_no_es_una_definicion_o_una_ruta_que_no_vale_no_se_lee(tmp_path):
    s = Share(tmp_path)
    s.fichero("vm/notas.xml", "<notas>\n  <name>esto no es una VM</name>\n</notas>\n")
    s.fichero("vm/texto.txt", "<domain type='kvm'>\n</domain>\n")
    rc, salida = s.lanzar(vc.VM_DEFINICION_FICHERO, "vm/notas.xml")
    assert rc == 0 and salida.strip() == "==no_es_vm" and "esto no es" not in salida
    for relativa, fuera in (("vm/texto.txt", False), ("vm/no existe.xml", False), ("vacia", False)):
        rc, salida = s.lanzar(vc.VM_DEFINICION_FICHERO, relativa, fuera=fuera)
        assert rc == 0 and salida.strip() == "==rechazada", relativa
    (tmp_path / "otra").mkdir()
    (tmp_path / "otra" / "vm.xml").write_text("<domain type='kvm'>\n</domain>\n", encoding="utf-8")
    rc, salida = s.lanzar(vc.VM_DEFINICION_FICHERO, "otra/vm.xml", fuera=True)
    assert rc == 0 and salida.strip() == "==rechazada"
    for texto in ("==no_es_vm\n", "==rechazada\n"):
        with pytest.raises(ValueError):
            p.vm_definicion_fichero(texto)
