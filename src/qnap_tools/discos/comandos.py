# -*- coding: utf-8 -*-
"""Ordenes de la pata de discos y carpetas. Todas de solo lectura.

Salen de la exploracion hecha contra NAS reales (pruebas/catalogo/discos*.json). Cada orden
declara para que sistema vale: "ambos", "hero" (QuTS hero, ZFS) o "qts" (QTS, md y LVM).
De los ficheros de configuracion se leen campos concretos, nunca el fichero entero.

Un disco se identifica por cabina y bahia, los dos numeros que usa el propio NAS en sus
ficheros (enclosure_<cabina>.conf, smart_<cabina>_<bahia>.info): la cabina 0 es el NAS.
"""
from ..comandos import Comando, no_vacia, rc_cero

# --- discos fisicos ---------------------------------------------------------------------------

# Siempre sin sudo: como root no termina en 40 s en un NAS con muchos discos.
DISCOS_LISTA = Comando("discos_lista", "qcli_storage -d", timeout=30)
DISCOS_REPARTO = Comando("discos_reparto", "qcli_storage -p", timeout=30)

# Ni los WWN ni las pruebas de velocidad que el NAS guarda en el mismo fichero. El ultimo
# fichero puede no tener discos (grep termina con 1): se valida la salida, no el codigo.
CAMPOS_DISCO = ("port_id", "pd_sys_name", "type", "vendor", "model", "serial_no", "revision",
                "capacity", "sector_size", "rotation_speed", "status")
DISCOS_DETALLE = Comando(
    "discos_detalle",
    "for f in /etc/enclosure_*.conf; do echo \"== $f\"; grep -E '^\\[PhysicalDisk|^(%s) =' $f; done"
    % "|".join(CAMPOS_DISCO),
    valida=no_vacia)

# Veredicto SMART del propio NAS para las bahias de la cabina principal. getsysinfo no termina
# sus respuestas en salto de linea (de ahi un echo por valor) y sin privilegios responde
# "0 C" y "--" con codigo 0: siempre con sudo, y el parser comprueba esos centinelas.
MAX_BAHIAS = 32
DISCOS_SALUD = Comando(
    "discos_salud",
    "n=$(getsysinfo hdnum); for b in %s; do [ $b -le $n ] && echo \"== $b\""
    " && echo modelo=$(getsysinfo hdmodel $b) && echo temperatura=$(getsysinfo hdtmp $b)"
    " && echo smart=$(getsysinfo hdsmart $b) && echo estado=$(getsysinfo hdstatus $b); done;"
    " [ -n \"$n\" ]" % " ".join(str(b) for b in range(1, MAX_BAHIAS + 1)),
    sudo=True, timeout=40)

# --- SMART ------------------------------------------------------------------------------------

# Los ficheros que el NAS refresca cada pocos minutos con los atributos de cada disco (tambien
# de los NVMe y de las cabinas de expansion). La carpeta solo la lee root.
SMART_TODOS = Comando(
    "smart_todos",
    "for f in /tmp/smart/smart_*.info; do [ -e $f ] && echo \"== $f\" && cat $f; done;"
    " ls /tmp/smart/ >/dev/null",
    sudo=True, timeout=30)
SMART_ATRIBUTOS = Comando("smart_atributos", "cat /tmp/smart/smart_{cabina}_{bahia}.info",
                          {"cabina": "bahia", "bahia": "bahia"}, sudo=True)
# Avisos por valor que el usuario haya configurado en el NAS. Sin fichero no hay ninguno.
SMART_UMBRALES = Comando(
    "smart_umbrales",
    "[ ! -e /tmp/smart_warning.conf ] || grep -E '^\\[|^(policy|enable|value) =' /tmp/smart_warning.conf",
    valida=rc_cero)

# Desgaste de cada SSD segun el NAS. Un NAS sin SSD no tiene ficheros, o ni la carpeta.
SSD_VIDA = Comando(
    "ssd_vida",
    "for f in /tmp/disk/disk_*.info; do [ -e $f ] && echo \"== $f\" && grep -E '^SSD_LIFE_USED' $f; done;"
    " [ ! -d /tmp/disk ] || ls /tmp/disk/ >/dev/null",
    valida=rc_cero)

# --- rendimiento ------------------------------------------------------------------------------

# Dos lecturas de los contadores del kernel, cada una con su reloj (/proc/uptime) para saber
# el intervalo real. Solo discos enteros: en QuTS hero el fichero trae un zd por volumen.
_LECTURA = "cat /proc/uptime; grep -E ' (sd[a-z]+|nvme[0-9]+n[0-9]+) ' /proc/diskstats"
DISKSTATS = Comando("diskstats", "%s; sleep 5; echo ==5s; %s" % (_LECTURA, _LECTURA), timeout=25)

# --- QuTS hero: pools, datasets, instantaneas y LUN ---------------------------------------------

# -H -p: sin cabecera, separado por tabuladores y con los tamanos en bytes. El ZFS de QNAP no
# tiene la propiedad de fragmentacion.
POOLS = Comando("pools", "zpool list -H -p -o name,size,alloc,free,cap,dedup,health", sistema="hero")
POOLS_ESTADO = Comando("pools_estado", "zpool status -v", sistema="hero", timeout=30)
DATASETS = Comando(
    "datasets",
    "zfs list -H -p -t filesystem,volume -o name,type,used,avail,refer,quota,refquota,compressratio,mountpoint,"
    "compression,dedup,encryption,keystatus",
    sistema="hero", timeout=30)
# Todas, de la mas antigua a la mas reciente: el recorte y su cuenta los pone el servidor. Sin
# tuberia, para que el codigo de salida sea el de zfs. Un NAS sin instantaneas no devuelve nada.
SNAPSHOTS_HERO = Comando("zfs_snapshots", "zfs list -H -p -t snapshot -o name,used,refer,creation -s creation",
                         sistema="hero", timeout=60, valida=rc_cero)
# Lo que liberaria borrar todas las instantaneas de cada dataset. La suma del "used" de cada
# instantanea se queda corta: lo que comparten dos instantaneas no cuenta en ninguna.
SNAPSHOTS_RETENIDO_HERO = Comando("zfs_retenido", "zfs list -H -p -t filesystem,volume -o name,usedbysnapshots",
                                  sistema="hero", timeout=30)
# Todo menos "description", que es texto libre.
CAMPOS_PROG_HERO = ("source_lv_id", "retention", "expiremin", "keepAmount", "hourAmount", "dayAmount",
                    "weekAmount", "monthAmount", "normalAmount", "Schedule", "MonthDay", "WeekDay",
                    "Dueday", "Frequency", "OnHour", "OnMinute", "OffHour", "OffMinute", "smart", "vital",
                    "immutable", "snapshot_type", "schedule_status", "ScheduleTime", "lastRetentionTime")
_PROG_HERO = "/etc/config/qsnapshot/zsnapshotSchedule.conf"
SNAPSHOTS_PROG_HERO = Comando(
    "zfs_snapshots_prog",
    "[ ! -s %s ] || grep -E '^\\[|^(%s) =' %s" % (_PROG_HERO, "|".join(CAMPOS_PROG_HERO), _PROG_HERO),
    sistema="hero", valida=rc_cero)
# De los dos JSON de iSCSI (una clave por linea), solo estas claves: ni CHAP ni nada que no se
# haya visto. grep -o saca la clave y su valor, no la linea: si el fichero viniera en una sola
# linea no saldria nada (y la orden fallaria) en vez de salir entero. Ningun NAS de pruebas
# tenia destinos ni LUN: sin validar.
CLAVES_ISCSI_HERO = ("lun", "portal", "target", "initiator", "service_enable", "service_port",
                     "iqn_prefix", "initiator_id", "name", "alias", "[0-9]+")
LUNS_HERO = Comando(
    "zfs_iscsi",
    "for f in /etc/config/hero_zfs_lun.json /etc/config/hero_iscsi_scst.json; do"
    " [ ! -s $f ] || echo \"== $f\"; [ ! -s $f ] ||"
    " grep -o -E '^[[:space:]]*\"(%s)\":(\"[^\"]*\"|[a-z0-9.-]+|[{][}]?)' $f; done"
    % "|".join(CLAVES_ISCSI_HERO),
    sistema="hero", valida=rc_cero, no_probado=True)


# --- QTS: grupos md, volumenes, pools ligeros, instantaneas e iSCSI -----------------------------

def _campos_de(fichero, campos, secciones="^\\["):
    """Orden que saca de un .conf sus cabeceras de seccion y solo estos campos. Sin fichero (o
    vacio) no devuelve nada; si existe y no se puede leer, falla."""
    return "[ ! -s %s ] || grep -E '%s|^(%s) ?=' %s" % (fichero, secciones, "|".join(campos), fichero)


MDSTAT = Comando("mdstat", "cat /proc/mdstat", sistema="qts")
# Un echo por valor: segun el nivel faltan ficheros (un raid0 no tiene sync_action) y cat
# los saltaria, descolocando los demas. Un valor vacio es "no lo dice", no un cero.
MD_SYS = Comando(
    "md_sys",
    "for d in /sys/block/md*/md; do echo \"== $d\"; echo nivel=$(cat $d/level 2>/dev/null);"
    " echo estado=$(cat $d/array_state 2>/dev/null); echo accion=$(cat $d/sync_action 2>/dev/null);"
    " echo degradado=$(cat $d/degraded 2>/dev/null);"
    " echo discrepancias=$(cat $d/mismatch_cnt 2>/dev/null); done",
    sistema="qts")
# Los grupos que QTS considera suyos (los demas md son del sistema) y sus miembros por bahia.
# grep -o: de "data_0 = 1, <WWN>" solo sale "data_0 = 1".
RAID_CONF = Comando(
    "raid_conf",
    "[ ! -s /etc/config/raid.conf ] || grep -o -E '^\\[[A-Za-z0-9_]+\\]|^(id|deviceName|raidLevel) = .*"
    "|^(data|spare)_[0-9]+ = [0-9A-Fa-f]+|^globalSpare[0-9]+ = [0-9A-Fa-f]+' /etc/config/raid.conf",
    sistema="qts", valida=rc_cero)
VOLUMENES_CONF = Comando(
    "volumenes_conf",
    _campos_de("/etc/volume.conf", ("volId", "volName", "raidId", "raidName", "encryption", "ssdCache",
                                    "unclean", "mappingName", "readOnly", "status", "volType", "internal"),
               secciones="^\\[VOL"),
    sistema="qts", valida=rc_cero)
LVM_CONF = Comando(
    "lvm_conf",
    _campos_de("/etc/config/qlvm.conf", ("poolId", "tpId", "poolName", "threshold", "overThreshold",
                                         "snapshot_reserved", "memberId", "memberName", "tpName", "tpSize",
                                         "metaSize", "lvId", "lvName", "lvSize", "volName")),
    sistema="qts", valida=rc_cero)
# status, nunca table: table ensena la clave de los volumenes cifrados.
DM_ESTADO = Comando("dm_estado", "dmsetup status", sudo=True, sistema="qts")
SNAPSHOTS_QTS = Comando(
    "lvm_snapshots",
    _campos_de("/etc/config/qsnapshot/snapshot.conf", ("Count", "snapshotId", "name", "size", "expiremin",
                                                       "time", "vital", "snapshot_type", "replicated")),
    sistema="qts", timeout=30, valida=rc_cero)
CAMPOS_PROG_QTS = ("source_lv_id", "retention", "expiremin", "keepAmount", "hourAmount", "dayAmount",
                   "weekAmount", "monthAmount", "normalAmount", "Schedule", "MonthDay", "WeekDay", "Hour",
                   "Minute", "smart", "vital", "snapshot_type", "status", "schedule_status", "ScheduleTime",
                   "lastRetentionTime")
SNAPSHOTS_PROG_QTS = Comando(
    "lvm_snapshots_prog", _campos_de("/etc/config/qsnapshot/snapshotSchedule.conf", CAMPOS_PROG_QTS),
    sistema="qts", valida=rc_cero)
# Servicio, iniciadores y, de destinos y LUN, nombre y estado. Las claves CHAP y la seccion de
# claves de iniciador no estan en la lista. Ningun NAS de pruebas tenia destinos ni LUN: los
# nombres de sus campos no se han podido comprobar.
ISCSI_QTS = Comando(
    "lvm_iscsi",
    _campos_de("/etc/config/iscsi_trgt.conf", ("bServiceEnable", "servicePort", "targetIQNPrefix",
                                               "initiatorIQN", "initiatorAlias", "targetIndex", "targetName",
                                               "targetIQN", "targetAlias", "bTargetEnable", "targetStatus",
                                               "LUNIndex", "LUNName", "LUNCapacity", "LUNStatus", "bLUNEnable")),
    sistema="qts", valida=rc_cero, no_probado=True)


# --- carpetas compartidas y ocupacion (los dos sistemas) ----------------------------------------

# Solo los montajes de volumen (/share/<X>_DATA), una linea cada uno y en KiB. Con ellos como
# argumentos df no consulta los demas montajes: una carpeta remota caida lo dejaria colgado, y
# el df de QNAP (BusyBox) no tiene -l. Las carpetas de /share que no son un montaje salen como
# el tmpfs de /share y el parser las descarta. Sin ningun volumen df termina con 1 y solo da la
# cabecera: se valida la salida, y el parser exige esa cabecera.
OCUPACION = Comando("ocupacion", "df -P -k /share/*_DATA", timeout=25, valida=no_vacia)
# De smb.conf, las secciones y solo los campos de cada carpeta: quien entra y como. Sin este
# fichero no hay "ninguna carpeta": es un fallo de lectura.
CAMPOS_SMB = ("path", "comment", "valid users", "invalid users", "read list", "write list", "browsable",
              "browseable", "guest ok", "recycle bin")
CARPETAS_SMB = Comando(
    "carpetas_smb",
    "grep -E '^\\[|^[[:space:]]*(%s) *=' /etc/config/smb.conf" % "|".join(CAMPOS_SMB))
# El uso de cada carpeta que el propio NAS calcula y guarda (no se recorre nada).
CARPETAS_USO = Comando(
    "carpetas_uso",
    "[ ! -s /etc/config/volumeStatus.conf ] || grep -E"
    " '^\\[|^(Used Size|Directory Count|File Count|Latest Update Time) *=' /etc/config/volumeStatus.conf",
    valida=rc_cero)
# Vacio o inexistente si no hay nada exportado por NFS. No lleva secretos.
CARPETAS_NFS = Comando("carpetas_nfs", "[ ! -s /etc/exports ] || cat /etc/exports", valida=rc_cero)
# Solo el primer nivel: cada carpeta compartida es un enlace a su volumen.
CARPETAS_ENLACES = Comando("carpetas_enlaces", "ls -l /share/")
