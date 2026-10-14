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
