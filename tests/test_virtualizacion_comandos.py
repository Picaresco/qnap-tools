# -*- coding: utf-8 -*-
"""Coherencia de las ordenes de la pata de virtualizacion: todas son de solo lectura."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pruebas"))
import guardia  # noqa: E402  (la guardia de solo lectura del laboratorio)

from qnap_tools.comandos import Comando, ParametroInvalido  # noqa: E402
from qnap_tools.virtualizacion import comandos as vc  # noqa: E402

EJEMPLOS = {"uuid": "12345678-9abc-4def-8123-456789abcdef", "nombre": "web-1", "entero": "50",
            "ruta": "/share/ruta1/vm1/disco1.img"}
SECRETOS = re.compile(
    r"shadow|smbpasswd|ssh_host|\.pem|id_rsa|id_ed25519|authorized_keys|qvpn/|openvpn|"
    r"ipsec\.(conf|secrets)|privatekey|security-info|qvs\.db|ctstation|\.sqlite|passwd", re.I)
# lo que el diseno deja fuera aunque exista en el NAS
VETADO = re.compile(
    r"\blxc\b|\bcurl\b|\bwget\b|sqlite|screenshot|qemu-agent|guestinfo|--source agent|"
    r"\bdu |\bfind |ls -[A-Za-z]*R|\.Config\.Env|\.Config\.Cmd|\.Args|\.Path\b|\{\{ *json *\. *\}\}")
DE_VM = {"ANFITRION", "VM_ESTADISTICAS", "VM_XML", "VM_IP", "VM_USO", "VM_IMAGENES", "VM_SNAP_LIBVIRT",
         "VM_SNAP_VS", "VM_GUARDADAS", "DISCO_INFO", "DISCO_CHECK", "VM_DEFINICION_FICHERO"}
DE_CONTENEDORES = {"CT_INFO", "CT_LISTA", "CT_COMPOSE", "CT_DETALLE", "CT_STATS", "CT_LOGS",
                   "CT_REDES", "CT_INTERNOS", "CT_LXD"}
CON_SUDO = {"CT_LXD"}          # las carpetas de LXD solo las lee root
DOCKER = "$(getcfg container-station Install_Path -f /etc/config/qpkg.conf)/bin/docker"
INTERNO = " -H unix:///var/run/system-docker.sock"
SUBORDENES_DOCKER = {"info", "ps", "inspect", "stats", "logs", "network ls", "network inspect", "compose ls"}
VIRSH = "LD_LIBRARY_PATH=/QVS/usr/lib:/QVS/usr/lib64:/QVS/lib /QVS/usr/bin/virsh -r -c qemu:///system"
SUBORDENES_VIRSH = {"uri", "list", "domstats", "dumpxml", "domifaddr", "domblklist", "snapshot-list"}


def todos():
    return {nombre: valor for nombre, valor in vars(vc).items() if isinstance(valor, Comando)}


def test_estan_todas_las_ordenes_previstas_y_ninguna_mas():
    assert set(todos()) == DE_VM | DE_CONTENEDORES


def test_todas_valen_para_los_dos_sistemas():
    # Virtualization Station y Container Station son los mismos en QTS y en QuTS hero
    assert {c.sistema for c in todos().values()} == {"ambos"}


def test_los_identificadores_son_unicos():
    ids = [c.id for c in todos().values()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_cada_orden_pasa_la_guardia_de_solo_lectura_del_laboratorio(nombre):
    comando = todos()[nombre]
    texto = comando.render({p: EJEMPLOS[tipo] for p, tipo in comando.params.items()})
    guardia.comprobar(texto)          # lanza guardia.Bloqueado si algo no esta permitido


def test_la_guardia_del_laboratorio_sigue_bloqueando_escrituras():
    # si esto dejara de fallar, la prueba anterior no demostraria nada
    libvirt = "LD_LIBRARY_PATH=/QVS/usr/lib /QVS/usr/bin/virsh"
    for texto in (libvirt + " -r -c qemu:///system destroy x", libvirt + " -c qemu:///system list --all",
                  libvirt + " -r list --all", libvirt + " -r -c qemu:///system dumpxml x --security-info",
                  "/QVS/usr/bin/qemu-img resize /share/x.img 1G", "/QVS/usr/bin/qemu-img info /share/x.img",
                  "docker rm x", "docker exec x sh", "docker logs -f --tail 5 x", "docker logs x",
                  "docker stats", "docker network rm x", "docker compose down", "docker system prune",
                  "echo x | while read -r m; do rm \"$m\"; done", "echo x | while read m n; do true; done"):
        with pytest.raises(guardia.Bloqueado):
            guardia.comprobar(texto)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ninguna_orden_toca_secretos(nombre):
    assert not SECRETOS.search(todos()[nombre].plantilla)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_ninguna_orden_usa_lo_que_el_diseno_deja_fuera(nombre):
    assert not VETADO.search(todos()[nombre].plantilla)


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_virsh_va_siempre_en_solo_lectura_y_contra_el_libvirt_del_sistema(nombre):
    plantilla = todos()[nombre].plantilla
    # sin -c, un usuario que no es root arranca un libvirt propio (escribe en su carpeta) y
    # devuelve una lista vacia; -r hace que libvirt rechace cualquier escritura
    assert plantilla.count("virsh") == plantilla.count(VIRSH)
    subordenes = set(re.findall(re.escape(VIRSH) + r" ([a-z-]+)", plantilla))
    assert subordenes <= SUBORDENES_VIRSH
    assert plantilla.count(VIRSH) == len(re.findall(re.escape(VIRSH) + r" [a-z-]+", plantilla))


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_el_xml_de_una_vm_nunca_sale_entero(nombre):
    # de dumpxml solo salen lineas elegidas con grep; los metadatos de VS no se piden
    plantilla = todos()[nombre].plantilla
    # o va directo a grep, o se guarda en $x (para dejar una marca si virsh falla) y lo unico que
    # se hace con $x es pasarlo a grep
    guardado = plantilla.count("x=$(%s dumpxml $d)" % VIRSH)
    assert plantilla.count("dumpxml $d") == plantilla.count("dumpxml $d | grep ") + guardado
    assert plantilla.count("$x") == plantilla.count('"$x" | grep ') == guardado
    assert "qvs:graphics" not in plantilla and "qvs:vm" not in plantilla


@pytest.mark.parametrize("nombre", sorted(todos()))
def test_qemu_img_solo_describe_la_imagen_y_sin_bloquearla(nombre):
    plantilla = todos()[nombre].plantilla
    # info describe y check cuenta errores, los dos con -U; check nunca con -r (repara y escribe)
    assert plantilla.count("qemu-img") == plantilla.count("qemu-img info -U ") + plantilla.count(
        "qemu-img check -U --output=json ")
    for uso in re.findall(r"qemu-img [^;|)]*", plantilla):
        assert " -r" not in uso and "--repair" not in uso, uso
    # --backing-chain abriria la base que diga cada imagen, tambien una direccion de red
    assert "--backing-chain" not in plantilla


def test_la_comprobacion_de_una_imagen_solo_lee_y_se_da_tiempo_para_las_grandes():
    assert vc.DISCO_CHECK.sudo is False and vc.DISCO_CHECK.params == {"ruta": "ruta"}
    assert vc.DISCO_CHECK.timeout == 120 and vc.DISCO_INFO.sudo is False
    assert vc.DISCO_CHECK.plantilla.count("check -U --output=json") == 1


def test_la_guardia_deja_pasar_check_con_u_y_rechaza_repararlo():
    qemu = "LD_LIBRARY_PATH=/QVS/usr/lib /QVS/usr/bin/qemu-img "
    guardia.comprobar(qemu + "check -U --output=json /share/x.img")
    guardia.comprobar(qemu + "check -U /share/x.img")
    # -r y --repair REPARAN la imagen: escriben en ella
    for texto in ("check -r all -U --output=json /share/x.img", "check -U -r leaks /share/x.img",
                  "check -U --output=json -r all /share/x.img", "check --repair all -U /share/x.img",
                  "check -U --repair=leaks /share/x.img", "check -rU all /share/x.img",
                  "check -U -r /share/x.img", "check /share/x.img", "check --output=json /share/x.img",
                  "check -U -f raw /share/x.img", "check -U -T none /share/x.img",
                  "check -U --image-opts /share/x.img", "check -U /share/x.img /share/y.img"):
        with pytest.raises(guardia.Bloqueado):
            guardia.comprobar(qemu + texto)
    for texto in ("info /share/x.img", "commit /share/x.img", "resize /share/x.img 1G", "convert a b", "amend a",
                  "snapshot -c x /share/x.img", "bitmap --add /share/x.img b"):
        with pytest.raises(guardia.Bloqueado):
            guardia.comprobar(qemu + texto)


def test_la_regla_de_check_dice_por_que_no_admite_reparar():
    reglas = [r for r in guardia.cargar_reglas()["qemu-img"] if r.get("sub") == ["check"]]
    assert len(reglas) == 1
    regla = reglas[0]
    assert regla["requiere"] == ["-U"] and set(regla["solo_flags"]) == {"-U", "--output=json"}
    assert "-r" in regla["nota"] and "ESCRIBEN" in regla["nota"]


def test_las_ordenes_de_ruta_solo_leen_lo_que_cuelga_de_share():
    for c in (vc.DISCO_INFO, vc.DISCO_CHECK, vc.VM_DEFINICION_FICHERO):
        assert c.params == {"ruta": "ruta"} and c.sudo is False and "readlink -f {ruta}" in c.plantilla, c.id
        assert '"${f#/share/}" != "$f"' in c.plantilla and "==rechazada" in c.plantilla, c.id


@pytest.mark.parametrize("valor", ["x.img", "../etc/passwd", "/share/../etc", "/share/a/./b", "", "/share/a\nb",
                                   "/" + "a" * 513])
def test_la_ruta_se_valida_antes_de_componer_la_orden(valor):
    for c in (vc.DISCO_INFO, vc.DISCO_CHECK, vc.VM_DEFINICION_FICHERO):
        with pytest.raises(ParametroInvalido):
            c.render({"ruta": valor})


def test_una_ruta_con_espacios_o_comillas_viaja_entrecomillada():
    orden = vc.DISCO_CHECK.render({"ruta": "/share/Mis VMs/it's.img"})
    assert orden.startswith("f=$(readlink -f '/share/Mis VMs/it'\"'\"'s.img');")
    guardia.comprobar(orden)


def test_la_definicion_de_un_fichero_no_pide_la_consola_entera_ni_los_metadatos_de_la_consola():
    plantilla = vc.VM_DEFINICION_FICHERO.plantilla
    # la consola solo por atributos pedidos por su nombre (nunca passwd); ni el elemento ni los metadatos de VS
    assert not any("graphics" in e or e == "qvs:vm" for e in vc.ELEMENTOS_DEFINICION)
    assert "passwd" not in plantilla and "password" not in plantilla.lower() and "cat " not in plantilla
    assert "grep -E '<graphics ' \"$f\" | grep -o -E \"(type|port|autoport|listen|keymap)='[^']*'\"" in plantilla
    # se comprueba que es un .xml y una definicion de libvirt antes de leerlo
    assert '"${f%.xml}" != "$f"' in plantilla and "grep -q '^<domain '" in plantilla


def test_las_rutas_sacadas_de_una_vm_no_se_recorren_con_un_for():
    # la carpeta de una VM lleva su nombre, que puede tener espacios: un 'for x in $(...)' la
    # partiria (y la VM saldria sin instantaneas o sin disco); 'while read' lee la linea entera
    for comando in (vc.VM_IMAGENES, vc.VM_SNAP_VS):
        # el unico otro 'for' es el contador de capas de la cadena: numeros, no rutas
        contador = "for i in %s;" % " ".join(str(i) for i in range(1, vc.MAX_CAPAS_IMAGEN + 1))
        plantilla = comando.plantilla.replace(contador, "")
        assert plantilla.count("for ") == 1 and "for d in $(" in plantilla
        assert comando.plantilla.count("| while read -r ") == 1
    assert "[ -d \"$m\" ] || echo '!! " in vc.VM_SNAP_VS.plantilla


def test_solo_estas_ordenes_van_con_sudo():
    assert {n for n, c in todos().items() if c.sudo} == CON_SUDO


@pytest.mark.parametrize("valor", ["x; reboot", "-a", "$(id)", "12345678", "", "12345678-9abc-4def-8123-456789abcdef x"])
def test_la_vm_se_valida_antes_de_componer_la_orden(valor):
    with pytest.raises(ParametroInvalido):
        vc.VM_IP.render({"uuid": valor})


def test_la_vm_entra_entrecomillada():
    uuid = "12345678-9abc-4def-8123-456789abcdef"
    assert vc.VM_IP.render({"uuid": uuid}).endswith("domifaddr %s --source arp" % uuid)


def test_las_ordenes_con_bucle_dicen_a_que_libvirt_hablan():
    # si la conexion falla, la lista de VMs sale vacia y el bucle no da ningun error: la
    # primera linea (uri=) permite al parser distinguir "no hay VMs" de "no hubo respuesta"
    for nombre, c in todos().items():
        if "list --all --uuid" in c.plantilla or nombre == "VM_ESTADISTICAS":
            assert c.plantilla.startswith("echo uri=$(%s uri); " % VIRSH), nombre


def test_la_medida_de_uso_es_corta_y_solo_de_las_vm_en_marcha():
    assert vc.VM_USO.plantilla.count("sleep 5;") == 1 and vc.VM_USO.plantilla.count("--list-running") == 2
    assert vc.VM_USO.timeout <= 40


# --- contenedores -------------------------------------------------------------------------------

@pytest.mark.parametrize("nombre", sorted(todos()))
def test_docker_solo_se_usa_para_consultar_y_su_ruta_sale_de_la_configuracion_del_paquete(nombre):
    plantilla = todos()[nombre].plantilla
    # la carpeta de Container Station cambia de un NAS a otro: nunca se fija
    assert plantilla.count("/bin/docker") == plantilla.count(DOCKER)
    usos = re.findall(re.escape(DOCKER) + r"((?: -H [^ ]+)?) ([a-z]+(?: (?:ls|inspect))?)", plantilla)
    assert len(usos) == plantilla.count(DOCKER)
    for servidor, suborden in usos:
        assert servidor in ("", INTERNO) and suborden in SUBORDENES_DOCKER, suborden
    # y nunca como orden suelta, sin su ruta
    assert not re.search(r"(^|[;|&(] *)(system-)?docker ", plantilla)


def test_la_lista_de_contenedores_no_pide_tamanos():
    # con el campo Size, docker ps no termina en 40 s en un NAS con 45 contenedores, y
    # docker system df tampoco en 60 s: ninguna orden pide a docker que mida el disco
    for c in todos().values():
        assert ".Size" not in c.plantilla and "system df" not in c.plantilla
    assert " ps -a --no-trunc --format " in vc.CT_LISTA.plantilla


def test_el_detalle_de_un_contenedor_pide_campos_concretos():
    plantilla = vc.CT_DETALLE.plantilla
    assert " inspect --format '" in plantilla and plantilla.endswith("' {contenedor}")
    # ni variables de entorno, ni orden de arranque, ni las etiquetas enteras
    for vetado in (".Config.Env", ".Config.Cmd", ".Config.Entrypoint", ".Args", ".Path", "json .Config.Labels}",
                   "json .Config}", "json .HostConfig}", "json .}"):
        assert vetado not in plantilla, vetado
    assert plantilla.count("index .Config.Labels \"com.docker.compose.") == 3


def test_los_registros_se_piden_acotados_y_sin_seguirlos():
    plantilla = vc.CT_LOGS.plantilla
    # docker entre parentesis con su codigo de salida al final: asi se distingue un fallo de
    # docker de lo que haya escrito el programa del contenedor, empiece como empiece
    assert plantilla.startswith("(" + DOCKER + " logs --tail {lineas} {contenedor} 2>&1; ")
    assert "; rc=$?; echo; echo ==rc $rc) | cut -c1-" in plantilla
    opciones = plantilla.split(" logs ", 1)[1]
    assert " -f" not in opciones and "--follow" not in opciones and "--since" not in opciones
    assert vc.CT_LOGS.params == {"lineas": "entero", "contenedor": "nombre"}


def test_el_uso_de_los_contenedores_es_una_sola_muestra():
    assert " stats --no-stream --format " in vc.CT_STATS.plantilla


@pytest.mark.parametrize("valor", ["x; reboot", "-f", "$(id)", "a b", "", "../x", "a/b", "x\ny"])
def test_el_contenedor_se_valida_antes_de_componer_la_orden(valor):
    with pytest.raises(ParametroInvalido):
        vc.CT_DETALLE.render({"contenedor": valor})
    with pytest.raises(ParametroInvalido):
        vc.CT_LOGS.render({"contenedor": valor, "lineas": 5})


@pytest.mark.parametrize("valor", ["abc", "-5", "5; x", "", "5 5"])
def test_el_numero_de_lineas_se_valida_antes_de_componer_la_orden(valor):
    with pytest.raises(ParametroInvalido):
        vc.CT_LOGS.render({"contenedor": "web-1", "lineas": valor})


def test_lxd_solo_se_mira_por_sus_carpetas():
    # el cliente lxc crea ~/.config/lxc y un certificado la primera vez: no se ejecuta
    assert "lxc " not in vc.CT_LXD.plantilla and "ls " in vc.CT_LXD.plantilla


def test_la_captura_da_valores_validos_a_todas_las_ordenes_con_parametros():
    # pruebas/captura.py y pruebas/efectos.py abortan si falta el valor de los parametros de una orden
    import captura
    datos = Path(__file__).parent / "datos" / "virtualizacion"
    leidas = {n: (datos / (n.lower() + "_hero.txt")).read_text(encoding="utf-8")
              for n in ("VM_XML", "VM_IMAGENES", "CT_LISTA")}
    valores = captura.valores_reales("virtualizacion", leidas.__getitem__, "hero")
    con_parametros = {n: c for n, c in vars(vc).items() if isinstance(c, Comando) and c.params}
    assert set(con_parametros) == {"VM_IP", "CT_DETALLE", "CT_LOGS", "DISCO_INFO", "DISCO_CHECK",
                                   "VM_DEFINICION_FICHERO"}
    for nombre, comando in con_parametros.items():
        assert valores.get(nombre), nombre
        guardia.comprobar(comando.render(valores[nombre]))
    # un disco que cuelga de /share y la carpeta de su VM (donde VS guarda los metadatos)
    assert valores["DISCO_INFO"] == valores["DISCO_CHECK"] == {"ruta": "/share/ruta1/vm1/ruta10.1790544225"}
    assert valores["VM_DEFINICION_FICHERO"] == {"ruta": "/share/ruta1/vm1"}
    # un NAS sin discos en /share no tiene con que probarlas
    sin = captura.valores_reales("virtualizacion", dict(leidas, VM_IMAGENES="").__getitem__, "hero")
    assert sin["DISCO_INFO"] is None and sin["VM_DEFINICION_FICHERO"] is None
