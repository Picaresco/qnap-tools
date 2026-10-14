# -*- coding: utf-8 -*-
"""El anonimizador del laboratorio: de el depende que los datos de prueba versionados no
lleven nada real. Todos los valores de estas pruebas son inventados."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pruebas"))
import anonimiza  # noqa: E402


def test_los_numeros_de_serie_se_sustituyen_de_forma_coherente():
    a = anonimiza.Anonimizador()
    texto = ("serial_no = WD-ABC1234567\n"
             "Serial Number:      S4EWNX0N998877\n"
             "\tSerial Number:\tWD-ABC1234567\n"
             "/dev/nvme0n1     S4EWNX0N998877       Samsung SSD 970 EVO Plus 1TB\n")
    assert a.aplicar(texto) == (
        "serial_no = SERIE0001\n"
        "Serial Number:      SERIE0002\n"
        "\tSerial Number:\tSERIE0001\n"
        "/dev/nvme0n1     SERIE0002       Samsung SSD 970 EVO Plus 1TB\n")


def test_un_numero_de_serie_ya_visto_se_sustituye_tambien_fuera_de_su_campo():
    a = anonimiza.Anonimizador()
    assert a.aplicar("serial_no = ZX81QWERTY\nDisk 3: ZX81QWERTY (ok)\n") == (
        "serial_no = SERIE0001\nDisk 3: SERIE0001 (ok)\n")


def test_wwn_e_iqn_se_sustituyen():
    a = anonimiza.Anonimizador()
    texto = ("wwn = 0x5000c500a1b2c3d4\nnaa.5000c500a1b2c3d4 naa.600140512345678901234567890abcde\n"
             "iqn.2004-04.com.qnap:ts-999:iscsi.contabilidad.a1b2c3\n"
             "initiatorIQN = iqn.1991-05.com.microsoft:servidor-real\n")
    salida = a.aplicar(texto)
    assert "c500a1b2" not in salida and "contabilidad" not in salida and "servidor-real" not in salida
    assert salida.splitlines()[0] == "wwn = 0x5000000000000001"
    assert salida.splitlines()[1] == "naa.5000000000000001 naa.5000000000000002"
    assert salida.splitlines()[2] == "iqn.2004-04.com.example:destino-1"
    assert salida.splitlines()[3] == "initiatorIQN = iqn.2004-04.com.example:destino-2"


def test_las_palabras_se_sustituyen_tambien_dentro_de_otras():
    # nombres de equipo: aparecen pegados a prefijos y dominios
    a = anonimiza.Anonimizador({"NASREAL": "NAS-EJEMPLO"})
    assert a.aplicar("hcnasreal.dominio.test NASREAL") == "hcNAS-EJEMPLO.dominio.test NAS-EJEMPLO"


def test_los_nombres_solo_se_sustituyen_enteros_y_el_mas_largo_gana():
    # nombres de carpeta y de usuario: cortos, no deben tocar otras palabras
    a = anonimiza.Anonimizador(nombres={"ana": "usuario1", "Datos": "carpeta1", "DatosVentas": "carpeta2"})
    assert a.aplicar("valid users = ana,mariana,@Datos\npath = /share/CACHEDEV1_DATA/DatosVentas\n[Datos]\n") == (
        "valid users = usuario1,mariana,@carpeta1\npath = /share/CACHEDEV1_DATA/carpeta2\n[carpeta1]\n")


def test_aplicar_dos_veces_da_lo_mismo():
    a = anonimiza.Anonimizador({"NASREAL": "NAS-EJEMPLO"}, nombres={"Datos": "carpeta1"})
    texto = ("serial_no = WD-ABC1234567\nwwn = 0x5000c500a1b2c3d4\niqn.2004-04.com.qnap:ts-999:x.y\n"
             "192.168.50.7 00:de:ad:be:ef:01 NASREAL /share/Datos\n")
    una = a.aplicar(texto)
    assert a.aplicar(una) == una
    assert anonimiza.Anonimizador({"NASREAL": "NAS-EJEMPLO"}, nombres={"Datos": "carpeta1"}).aplicar(una) == una


def test_revisar_detecta_lo_que_aun_parece_real():
    sucio = ("serial_no = WD-ABC1234567\nwwn = 0x5000c500a1b2c3d4\niqn.2004-04.com.qnap:ts-999:x\n"
             "path = /share/Datos\n")
    dudas = anonimiza.revisar(sucio, nombres=["Datos"])
    assert len(dudas) == 4
    limpio = anonimiza.Anonimizador(nombres={"Datos": "carpeta1"}).aplicar(sucio)
    assert anonimiza.revisar(limpio, nombres=["Datos"]) == []


def test_lo_que_ya_hacia_sigue_igual():
    a = anonimiza.Anonimizador()
    assert a.aplicar("192.168.50.7 00:de:ad:be:ef:01 127.0.0.1 fe80::1234:5678:9abc:def0") == (
        "192.0.2.1 00:11:22:33:44:00 127.0.0.1 fe80::200:5eff:fe00:5301")


def test_el_identificador_de_disco_de_los_nombres_de_zfs_se_sustituye():
    # QuTS hero nombra cada miembro de un pool con el WWN o el numero de serie del disco
    a = anonimiza.Anonimizador()
    texto = ("serial_no = S4EWNX0N998877\n"
             "    qzfs/enc_0/disk_0x3_5000ABCDEF123456_3  ONLINE       0     0     0\n"
             "    qzfs/enc_23/disk_0x170001_S4EWNX0N998877_6      -      -      -\n"
             "    qzfs/enc_0/disk_0x3_5000ABCDEF123456_2  ONLINE\n")
    salida = a.aplicar(texto)
    assert salida == ("serial_no = SERIE0001\n"
                      "    qzfs/enc_0/disk_0x3_SERIE0002_3  ONLINE       0     0     0\n"
                      "    qzfs/enc_23/disk_0x170001_SERIE0001_6      -      -      -\n"
                      "    qzfs/enc_0/disk_0x3_SERIE0002_2  ONLINE\n")
    assert a.aplicar(salida) == salida
    assert anonimiza.revisar(salida) == []
    assert anonimiza.revisar(texto) == ["disco 5000ABCDEF123456", "disco S4EWNX0N998877", "serie S4EWNX0N998877"]


def test_el_guid_de_un_pool_se_sustituye():
    a = anonimiza.Anonimizador()
    salida = a.aplicar("guid = 4774096989271448021\nzpool1\tguid\t4774096989271448021\n")
    assert "4774096989271448021" not in salida
    assert salida == "guid = 1000000000000000001\nzpool1\tguid\t1000000000000000001\n"
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []


def test_los_comentarios_de_las_carpetas_se_sustituyen_salvo_los_de_fabrica():
    a = anonimiza.Anonimizador()
    texto = ("[Public]\ncomment = System default share\n[Otra]\n\tcomment = Facturas de Fulano 2026\n"
             "[Mas]\ncomment = \n[Y]\ncomment = Facturas de Fulano 2026\n")
    salida = a.aplicar(texto)
    assert salida == ("[Public]\ncomment = System default share\n[Otra]\n\tcomment = comentario de ejemplo 1\n"
                      "[Mas]\ncomment = \n[Y]\ncomment = comentario de ejemplo 1\n")
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []
    assert anonimiza.revisar(texto) == ["comentario Facturas de Fulano 2026"]


def test_el_identificador_de_una_exportacion_nfs_se_sustituye():
    a = anonimiza.Anonimizador()
    salida = a.aplicar('"/share/X" 192.168.5.5(rw,fsid=8cc1d6fe00c84ffc9184cfa7b84fa39f) \n')
    assert salida == '"/share/X" 192.0.2.1(rw,fsid=00000000000000000000000000000001) \n'
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []


def test_un_nombre_no_se_sustituye_dentro_de_un_identificador_con_guiones_bajos():
    # un usuario "NAS" o una carpeta "Backup" no deben tocar NAS_HOST ni un atributo SMART
    a = anonimiza.Anonimizador(nombres={"NAS": "usuario1", "Backup": "carpeta1"})
    texto = 'NAS_HOST  235,Power_Fail_Backup_Health  valid users = "NAS",@"x"  /share/Backup/a\n'
    assert a.aplicar(texto) == (
        'NAS_HOST  235,Power_Fail_Backup_Health  valid users = "usuario1",@"x"  /share/carpeta1/a\n')
    assert anonimiza.revisar("NAS_HOST Power_Fail_Backup_Health\n", nombres=["NAS", "Backup"]) == []
    assert anonimiza.revisar('"NAS"\n', nombres=["NAS", "Backup"]) == ["nombre NAS"]


def test_los_uuid_se_sustituyen():
    # identificadores de montajes remotos, de maquinas virtuales, etc.
    a = anonimiza.Anonimizador()
    texto = "x -> external/.nd/0/01a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d\nuuid 9A8B7C6D-b65c-20b3-35e5-0123456789ab\n"
    salida = a.aplicar(texto)
    assert salida == ("x -> external/.nd/0/00000000-0000-0000-0000-000000000001\n"
                      "uuid 00000000-0000-0000-0000-000000000002\n")
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []
    assert len(anonimiza.revisar(texto)) == 2


def test_los_identificadores_de_capa_de_docker_se_sustituyen():
    # las capas montadas de los contenedores salen en df con su identificador de 64 cifras
    a = anonimiza.Anonimizador()
    capa, otra = "ab12" * 16, "cd34" * 16
    texto = ("overlay 10 5 5 50% /share/X/overlay2/" + capa + "/merged\n"
             "overlay 10 5 5 50% /share/X/overlay2/" + otra + "/merged\n"
             "overlay 10 5 5 50% /share/Y/" + capa + "\n")
    salida = a.aplicar(texto)
    una, dos = "0" * 52 + "000000000001", "0" * 52 + "000000000002"
    assert salida == ("overlay 10 5 5 50% /share/X/overlay2/" + una + "/merged\n"
                      "overlay 10 5 5 50% /share/X/overlay2/" + dos + "/merged\n"
                      "overlay 10 5 5 50% /share/Y/" + una + "\n")
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []
    assert anonimiza.revisar(texto) == ["capa " + capa, "capa " + otra]


def test_la_descripcion_de_una_vm_se_sustituye():
    # texto libre que escribe quien administra el NAS; puede llevar nombres, fechas e IP
    a = anonimiza.Anonimizador()
    texto = ("  <description>Servidor de ficheros - clon del 25/09 (lab 10.1.2.3)</description>\n"
             "  <description>Otra cosa</description>\n"
             "  <description>Servidor de ficheros - clon del 25/09 (lab 10.1.2.3)</description>\n"
             "  <description></description>\n")
    salida = a.aplicar(texto)
    assert salida == ("  <description>descripcion de ejemplo 1</description>\n"
                      "  <description>descripcion de ejemplo 2</description>\n"
                      "  <description>descripcion de ejemplo 1</description>\n"
                      "  <description></description>\n")
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []
    assert "descripcion Otra cosa" in anonimiza.revisar(texto)


def test_las_rutas_de_share_se_sustituyen_componente_a_componente_si_se_pide():
    # discos de VM, montajes de contenedor, ficheros compose: carpetas y ficheros del usuario
    a = anonimiza.Anonimizador(nombres={"Contable": "vm1"}, rutas=True)
    texto = ("<source file='/share/Maquinas/Contable/Disco_Contable.1790000000'/>\n"
             "block.0.path=/share/Maquinas/Contable/Disco_Contable.img\n"
             "raiz=/share/ZFS2_DATA/.qpkg/container-station/docker\n"
             "bind:/share/Apps/web/conf.d->/etc/nginx/conf.d /share/Apps/web/compose.yaml\n"
             "/share/CACHEDEV1_DATA/Apps/lib/docker/overlay2/" + "ab12" * 16 + "/merged\n")
    salida = a.aplicar(texto)
    assert salida == (
        "<source file='/share/ruta1/vm1/ruta2.1790000000'/>\n"
        "block.0.path=/share/ruta1/vm1/ruta2.img\n"
        "raiz=/share/ZFS2_DATA/.qpkg/container-station/docker\n"
        "bind:/share/ruta3/ruta4/ruta5.d->/etc/nginx/conf.d /share/ruta3/ruta4/ruta6.yaml\n"
        "/share/CACHEDEV1_DATA/ruta3/lib/docker/overlay2/" + "0" * 63 + "1/merged\n")
    assert a.aplicar(salida) == salida


def test_sin_pedirlo_las_rutas_de_share_no_se_tocan():
    assert anonimiza.Anonimizador().aplicar("/share/Public/informe.pdf\n") == "/share/Public/informe.pdf\n"


def test_el_nombre_suelto_de_la_imagen_base_sigue_a_su_ruta():
    # qemu-img da el nombre del fichero base tal cual y, entre parentesis, su ruta
    a = anonimiza.Anonimizador(rutas=True)
    texto = "backing file: Disco_Contable.img (actual path: /share/Maquinas/Contable/Disco_Contable.img)\n"
    assert a.aplicar(texto) == "backing file: ruta3.img (actual path: /share/ruta1/ruta2/ruta3.img)\n"


def test_el_nombre_de_la_imagen_base_en_json_sigue_a_su_ruta():
    # qemu-img --output=json: "backing-filename" es el nombre suelto del fichero base
    a = anonimiza.Anonimizador(rutas=True)
    texto = ('"full-backing-filename": "/share/Maquinas/Contable/Disco_Contable.img",\n'
             '"backing-filename": "Disco_Contable.img",\n')
    salida = a.aplicar(texto)
    assert salida == ('"full-backing-filename": "/share/ruta1/ruta2/ruta3.img",\n'
                      '"backing-filename": "ruta3.img",\n')
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []
    assert anonimiza.revisar(texto) == ["imagen base Disco_Contable.img"]


def test_de_un_fichero_con_varios_puntos_solo_se_conserva_la_ultima_extension():
    # visto en un NAS real: "<vm>.<dominio>_00.<epoch>" dejaba el nombre del dominio a la vista
    a = anonimiza.Anonimizador(rutas=True)
    salida = a.aplicar("/share/Maquinas/Servidor.Empresa_00.1744416004 /share/Maquinas/copia.tar.gz "
                       "/share/Maquinas/Servidor.Empresa_00.1715862105_1\n")
    assert salida == "/share/ruta1/ruta2.1744416004 /share/ruta1/ruta3.gz /share/ruta1/ruta2.1715862105_1\n"
    assert a.aplicar(salida) == salida


def test_revisar_las_rutas_detecta_lo_que_no_es_del_sistema_ni_de_ejemplo():
    limpio = ("/share/ruta1/vm1/ruta2.1790000000 /share/ZFS2_DATA/.qpkg/container-station/docker "
              "/share/CACHEDEV1_DATA/carpeta3/ruta4.yaml\n")
    assert anonimiza.revisar(limpio, rutas=True) == []
    sucio = "/share/ruta1/ruta7.Empresa_00.1744416004 /share/Maquinas/vm1/ruta2.img\n"
    assert anonimiza.revisar(sucio, rutas=True) == ["ruta Maquinas", "ruta ruta7.Empresa_00.1744416004"]
    assert anonimiza.revisar(sucio) == []          # sin pedirlo, las rutas no se miran


def test_el_servicio_compose_de_un_contenedor_se_sustituye():
    # el nombre que el usuario da a cada servicio en su fichero compose
    a = anonimiza.Anonimizador()
    salida = a.aplicar('proyecto="p"\nservicio="base-de-datos"\nservicio=""\nservicio="base-de-datos"\n')
    assert salida == 'proyecto="p"\nservicio="servicio1"\nservicio=""\nservicio="servicio1"\n'
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []
    assert anonimiza.revisar('servicio="web"\n') == ["servicio web"]


def test_el_nombre_de_un_volumen_de_docker_sigue_a_su_carpeta():
    # un volumen con nombre sale como "Name" y como carpeta de su ruta
    a = anonimiza.Anonimizador(rutas=True)
    texto = ('[{"Name":"datos_de_la_tienda","Source":"/share/CACHEDEV1_DATA/Apps/lib/docker/volumes/'
             'datos_de_la_tienda/_data"},{"Name":"proyecto7"},{"Name":"' + "ab12" * 16 + '"}]\n')
    salida = a.aplicar(texto)
    assert salida == ('[{"Name":"ruta2","Source":"/share/CACHEDEV1_DATA/ruta1/lib/docker/volumes/ruta2/_data"},'
                      '{"Name":"proyecto7"},{"Name":"' + "0" * 63 + '1"}]\n')
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida, rutas=True) == []
    assert "nombre datos_de_la_tienda" in anonimiza.revisar(texto, rutas=True)


def test_el_destino_de_un_montaje_dentro_del_contenedor_se_sustituye():
    # la ruta de dentro del contenedor delata el programa que corre en el
    a = anonimiza.Anonimizador(rutas=True)
    texto = ('montajes=[{"Destination":"/var/lib/programa","RW":true},{"Destination":"/arranca-programa.sh"},'
             '{"Destination":"/var/lib/programa","Type":"volume"}]\n')
    salida = a.aplicar(texto)
    assert salida == ('montajes=[{"Destination":"/destino1","RW":true},{"Destination":"/destino2"},'
                      '{"Destination":"/destino1","Type":"volume"}]\n')
    assert a.aplicar(salida) == salida
    assert anonimiza.revisar(salida, rutas=True) == []
    assert anonimiza.revisar(texto, rutas=True) == ["destino /arranca-programa.sh", "destino /var/lib/programa"]
    # sin pedir rutas no se toca: en redes y discos no hay montajes de contenedor
    assert anonimiza.Anonimizador().aplicar(texto) == texto


def test_los_nombres_de_red_y_de_interfaz_de_docker_se_sustituyen():
    # el puente de una red de Docker lleva el identificador de la red; el veth, uno al azar
    a = anonimiza.Anonimizador()
    texto = ("5: br-0123456789ab: <UP>\n7: veth1a2b3c4@if6: <UP> master br-0123456789ab\n"
             "br-fedcba987654 veth1a2b3c4 vethfffffff\n")
    salida = a.aplicar(texto)
    assert salida == ("5: br-000000000001: <UP>\n7: veth0000001@if6: <UP> master br-000000000001\n"
                      "br-000000000002 veth0000001 veth0000002\n")
    assert a.aplicar(salida) == salida and anonimiza.revisar(salida) == []
    assert anonimiza.revisar(texto) == ["puente br-0123456789ab", "puente br-fedcba987654",
                                        "veth veth1a2b3c4", "veth vethfffffff"]
    # lo que no es un identificador (menos de 12 o de 7 cifras hexadecimales) no se toca
    assert a.aplicar("br-lan br0 veth0 vethernet\n") == "br-lan br0 veth0 vethernet\n"


def test_los_textos_entre_comillas_de_un_registro_se_sustituyen_si_se_pide():
    # la descripcion de un evento cita entre comillas usuarios, maquinas, carpetas, ficheros
    a = anonimiza.Anonimizador(comillas=True)
    texto = ('[Users] Failed to log in via user account "pepe".\n'
             '[VS] Started virtual machine "Servidor de pruebas".\n'
             '[Users] User "pepe" logged in.\n[x] valor "" vacio.\n')
    salida = a.aplicar(texto)
    assert salida == ('[Users] Failed to log in via user account "texto1".\n'
                      '[VS] Started virtual machine "texto2".\n'
                      '[Users] User "texto1" logged in.\n[x] valor "" vacio.\n')
    assert a.aplicar(salida) == salida
    assert anonimiza.revisar(salida, comillas=True) == []
    assert anonimiza.revisar(texto, comillas=True) == ["entre comillas Servidor de pruebas", "entre comillas pepe"]
    # sin pedirlo no se toca: en las demas patas las comillas son de JSON y de configuracion
    assert anonimiza.Anonimizador().aplicar(texto) == texto and anonimiza.revisar(texto) == []


REGISTRO_A_MANO = (
    "event_id,event_type,event_date,event_time,event_user,event_ip,event_comp,event_desc,event_msgid,\n"
    "9101,  2,2026-01-02,04:05:06,pepe,192.168.1.20,PC-PEPE,[Users] pepe entro desde PC-PEPE.,19,\n"
    "9102,  0,2026-01-02,04:05:07,---,---,nas-casa,[App] algo,1,\n"
    "conn_id,conn_type,conn_date,conn_time,conn_user,conn_ip,conn_comp,conn_res,conn_serv,\n"
    "9103,0,2026-01-02,04:05:08,pepe,192.168.1.20,---,---,7,\n"
    "id,severity,server,action,serviceName,facility,time,endtime,user,ip,client,desc,msgCode,\n"
    "9104,  6,  0,  0,System,  0,1767326709,1767326709,maria,192.168.1.21,PC-MARIA,[x] y,  0,\n"
    "Done. Return value is 0\n")


def test_los_usuarios_y_equipos_de_las_filas_de_un_registro_se_sustituyen():
    # el usuario y el equipo van en columnas fijas de cada fila, y se repiten en el texto
    a = anonimiza.Anonimizador(comillas=True)
    salida = a.aplicar(REGISTRO_A_MANO)
    lineas = salida.splitlines()
    assert lineas[1] == "9101,  2,2026-01-02,04:05:06,usuario1,192.0.2.1,equipo1,[Users] usuario1 entro desde equipo1.,19,"
    assert lineas[2] == "9102,  0,2026-01-02,04:05:07,---,---,equipo2,[App] algo,1,"
    assert lineas[4] == "9103,0,2026-01-02,04:05:08,usuario1,192.0.2.1,---,---,7,"
    assert lineas[6] == "9104,  6,  0,  0,System,  0,1767326709,1767326709,usuario2,192.0.2.2,equipo3,[x] y,  0,"
    assert a.aplicar(salida) == salida
    assert anonimiza.revisar(salida, comillas=True) == []
    assert anonimiza.revisar(REGISTRO_A_MANO, comillas=True) == [
        "equipo PC-MARIA", "equipo PC-PEPE", "equipo nas-casa", "ip 192.168.1.20", "ip 192.168.1.21",
        "usuario maria", "usuario pepe"]


def test_el_recurso_de_un_acceso_pierde_los_nombres_de_carpeta_y_fichero():
    texto = ("conn_id,conn_type,conn_date,conn_time,conn_user,conn_ip,conn_comp,conn_res,conn_serv,\n"
             "9001,0,2026-01-02,03:04:05,pepe,192.168.1.20,PC-PEPE,Fotos/pepe/Informe.doc,1,\n"
             "9002,0,2026-01-02,03:04:06,pepe,192.168.1.20,PC-PEPE,---,1,\n"
             "Done. Return value is 0\n")
    a = anonimiza.Anonimizador(nombres={"Fotos": "carpeta1"}, comillas=True)
    salida = a.aplicar(texto)
    lineas = salida.splitlines()
    assert lineas[1] == "9001,0,2026-01-02,03:04:05,usuario1,192.0.2.1,equipo1,carpeta1/usuario1/ruta1.doc,1,"
    assert lineas[2] == "9002,0,2026-01-02,03:04:06,usuario1,192.0.2.1,equipo1,---,1,"
    assert a.aplicar(salida) == salida
    assert anonimiza.revisar(salida, comillas=True) == []
    a_medias = salida.replace("ruta1.doc", "Informe.doc")
    assert anonimiza.revisar(a_medias, comillas=True) == ["recurso Informe.doc"]
