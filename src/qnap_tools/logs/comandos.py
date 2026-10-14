# -*- coding: utf-8 -*-
"""Ordenes de la pata de registros y avisos. Todas de solo lectura.

Salen de la exploracion hecha contra NAS reales (pruebas/catalogo/logs*.json).

Los tres registros del NAS (eventos, accesos y avisos del escritorio) son bases SQLite que se
leen con sus propias utilidades en modo consulta: SIEMPRE con -q -v (sin -v no dicen nada) y
NUNCA con sudo (con sudo, log_tool altera la base de eventos). Toda consulta va acotada en
filas: nunca se vuelca un registro entero. Una consulta que no encuentra nada no imprime ni la
cabecera; lo que dice que la utilidad respondio es su linea final "Done. Return value is 0".

Ademas: mensajes del kernel, sensores y cabinas, estado del sistema y configuracion de alertas.
"""
import re

from ..comandos import Comando, estricta, rc_cero, todas

# Con -s 13 la utilidad ordena de la fila mas reciente a la mas antigua y con -s 12 al reves;
# -l 0 -o N da las N primeras de ese orden.
RECIENTES = "-s 13 -l 0 -o {limite}"
# una fila de una utilidad empieza por su numero; la linea final dice que respondio
FILA_O_FIN = "'^ *[0-9]+,|^Done. Return value is 0$'"

# --- eventos del sistema (event.log) -------------------------------------------------------------

# Los ultimos eventos de una gravedad (0 todas, 1 informacion, 2 avisos, 3 errores) entre dos
# fechas (las dos incluidas). El intervalo va siempre: sin filtro se piden fechas extremas.
EVT_LISTA = Comando(
    "evt_lista", "log_tool -q -v -e {gravedad} -d {desde} -g {hasta} " + RECIENTES,
    {"gravedad": "entero", "desde": "fecha", "hasta": "fecha", "limite": "entero"},
    timeout=40, valida=rc_cero)

# Lo mismo, solo los que llevan un texto en su descripcion.
EVT_PALABRA = Comando(
    "evt_palabra", "log_tool -q -v -e {gravedad} -d {desde} -g {hasta} -k {texto} " + RECIENTES,
    {"gravedad": "entero", "desde": "fecha", "hasta": "fecha", "texto": "palabra", "limite": "entero"},
    timeout=40, valida=rc_cero)

# Cuantos eventos hay de cada gravedad (contando la linea final, que dice que respondio), y el
# mas antiguo y el mas reciente de los que se guardan.
EVT_RECUENTO = Comando(
    "evt_recuento",
    "for e in 1 2 3; do echo ==gravedad $e $(log_tool -q -v -e $e | grep -c -E %s); done; "
    "echo ==primero; log_tool -q -v -s 12 -l 0 -o 1; echo ==ultimo; log_tool -q -v -s 13 -l 0 -o 1"
    % FILA_O_FIN,
    timeout=90, valida=rc_cero)

# --- accesos (conn.log) ----------------------------------------------------------------------------

# Los ultimos accesos de un tipo (0 todos, 2 avisos: sobre todo intentos fallidos, 3 errores).
# El registro de accesos no se recorre entero: en un NAS con mucha actividad tiene millones de
# filas y la utilidad, sin intervalo, no devuelve ninguna.
CONN_LISTA = Comando(
    "conn_lista", "conn_log_tool -q -v -e {tipo} " + RECIENTES,
    {"tipo": "entero", "limite": "entero"}, timeout=40, valida=rc_cero)

# El acceso mas antiguo y el mas reciente de los que se guardan.
CONN_EXTREMOS = Comando(
    "conn_extremos",
    "echo ==primero; conn_log_tool -q -v -s 12 -l 0 -o 1; echo ==ultimo; conn_log_tool -q -v -s 13 -l 0 -o 1",
    timeout=40, valida=rc_cero)

# --- avisos del escritorio (notice.log, el centro de avisos de la web) -----------------------------

# Los ultimos avisos. Su hora va en segundos desde 1970 y se da en UTC: el desfase de hoy no
# vale para un aviso de antes del cambio de hora.
NOTICE_LISTA = Comando("notice_lista", "notice_log_tool -q -v " + RECIENTES, {"limite": "entero"},
                       timeout=40, valida=rc_cero)

# Cuantos avisos hay de cada gravedad y origen (el registro tiene tope: 10 000 filas), con la
# linea final de la utilidad.
NOTICE_RESUMEN = Comando(
    "notice_resumen",
    "notice_log_tool -q -v | cut -d, -f2,6 | grep -E '^ *[0-9]|^Done' | sort | uniq -c",
    timeout=40, valida=rc_cero)


# --- kernel ----------------------------------------------------------------------------------------

# El NAS guarda los mensajes del kernel en /etc/logs/kmsg, una linea por mensaje:
# "2026-10-13 17:14:03 +02:00 <3> [   86.792967] texto". El nivel va entre < y >; como una
# plantilla no puede llevar ">", los patrones usan un punto en su lugar.
NIVEL_O_MAS_GRAVE = "' <[0-{nivel}]. '"

# Cuantas lineas hay, desde cuando y cuantas de cada nivel.
KMSG_NIVELES = Comando(
    "kmsg_niveles",
    "echo ==lineas $(wc -l /etc/logs/kmsg); echo ==primera; head -n 1 /etc/logs/kmsg | cut -c1-26; "
    "echo ==niveles; cut -d' ' -f4 /etc/logs/kmsg | grep -E '^.[0-7].$' | sort | uniq -c",
    timeout=30, valida=rc_cero)

# Las ultimas lineas de un nivel o mas graves, con su cuenta.
KMSG_LINEAS = Comando(
    "kmsg_lineas",
    "echo ==lineas $(grep -c -E %s /etc/logs/kmsg); grep -E %s /etc/logs/kmsg | tail -n {lineas} | cut -c1-300"
    % (NIVEL_O_MAS_GRAVE, NIVEL_O_MAS_GRAVE),
    {"nivel": "nivel", "lineas": "entero"}, timeout=30, valida=rc_cero)

# La cola del registro del kernel en vivo (desde el ultimo arranque), con su cuenta.
DMESG = Comando("dmesg", "echo ==lineas $(dmesg | wc -l); dmesg | tail -n {lineas} | cut -c1-300",
                {"lineas": "entero"}, timeout=30, valida=rc_cero)

# --- hardware --------------------------------------------------------------------------------------

TEMPERATURA = re.compile(r"=[1-9][0-9]* C")


def con_temperatura(rc, salida):
    """getsysinfo sin root devuelve vacio, "0 C" o "--" con codigo 0: sin ninguna temperatura
    de verdad, la lectura no vale."""
    if not TEMPERATURA.search(salida):
        return "getsysinfo no dio ninguna temperatura (sin privilegios de root?)"
    return None


# Temperatura de CPU y del sistema y vueltas de cada ventilador (solo con sudo).
SENSORES = Comando(
    "sensores",
    "echo cpu=$(getsysinfo cputmp); echo sistema=$(getsysinfo systmp); echo ventiladores=$(getsysinfo sysfannum); "
    "seq 1 $(getsysinfo sysfannum) | while read -r i; do echo ventilador$i=$(getsysinfo sysfan $i); done",
    sudo=True, timeout=30, valida=todas(rc_cero, con_temperatura))

# Las cabinas: el NAS (0), las ranuras de cache, la de arranque, la USB y las de expansion.
CHASIS = Comando("chasis", "hal_app --se_enum", timeout=30, valida=estricta)

# Cuantas fuentes de alimentacion tiene el modelo y si son redundantes (no hay consulta de su
# estado en vivo).
FUENTES = Comando(
    "fuentes",
    "echo fuentes=$(getcfg Enclosure_0 max_psu_num -f /etc/hal.conf); "
    "echo redundante=$(grep -c -i -E '^REDUNDANT_POWER_INFO *= *yes' /etc/model.conf)",
    timeout=20, valida=rc_cero)

# El SAI configurado y si el servicio que lo vigila responde (y con que SAI).
SAI = Comando(
    "sai",
    "echo activo=$(getcfg UPS Enable); echo modelo=$(getcfg UPS 'UPS Type'); echo red=$(getcfg UPS 'AC Power'); "
    "echo bateria=$(getcfg UPS 'Battery Power'); echo apagar_en=$(getcfg UPS 'Shutdown System In'); "
    "echo ==upsc; upsc -l 2>&1; echo ==rc $?",
    timeout=20, valida=rc_cero)

# --- sistema ---------------------------------------------------------------------------------------

# Tiempo encendido (segundos), carga, hilos de CPU y memoria.
CARGA = Comando(
    "carga",
    "echo ==encendido; cat /proc/uptime; echo ==carga; cat /proc/loadavg; "
    "echo ==hilos $(grep -c '^processor' /proc/cpuinfo); echo ==memoria; "
    "grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo",
    timeout=20, valida=rc_cero)

# El firmware instalado (el uLinux.conf de fabrica dice el de verdad) y la comprobacion de
# actualizaciones.
FABRICA = "-f /etc/default_config/uLinux.conf"
FIRMWARE = Comando(
    "firmware",
    "echo version=$(getcfg System Version %s); echo compilacion=$(getcfg System 'Build Number' %s); "
    "echo comprobado=$(getcfg System 'Latest Check Live Update'); "
    "echo actualizado=$(getcfg System 'Latest Live Update'); echo comprobar=$(getcfg System 'Enable Live Update')"
    % (FABRICA, FABRICA),
    timeout=20, valida=rc_cero)

# La politica de actualizacion automatica del firmware, clave a clave. "leido" dice que
# uLinux.conf se pudo leer: sin el, todo vacio no distinguiria "sin configurar" de "no se pudo".
CLAVES_AUTO = (("importantes", "Enable Important"), ("recomendadas", "Enable Recommended"),
               ("ultimas", "Enable Latest"), ("version", "version"), ("modo", "action_mode"),
               ("modo_v3", "v3_action_mode"), ("programa", "type"), ("hora", "h"), ("minuto", "m"),
               ("dia_semana", "week_day"), ("dia", "d"))
FIRMWARE_AUTO = Comando(
    "firmware_auto",
    "echo leido=$(getcfg System Version); "
    + "; ".join("echo %s=$(getcfg 'Auto Firmware Update' '%s')" % c for c in CLAVES_AUTO),
    timeout=20, valida=rc_cero)

# Las aplicaciones de registro y seguridad, con su version y si estan activas. "==paquetes"
# dice cuantos paquetes conoce qpkg.conf: con 0, no se pudo leer.
APPS_DE_REGISTRO = ("QuLog", "NotificationCenter", "MalwareRemover", "SecurityCounselor", "QuFirewall",
                    "ResourceMonitor")
APPS = Comando(
    "apps",
    "echo ==paquetes $(grep -c '^\\[' /etc/config/qpkg.conf); for q in %s; do "
    "echo $q $(getcfg $q Version -f /etc/config/qpkg.conf) $(getcfg $q Enable -f /etc/config/qpkg.conf); done"
    % " ".join(APPS_DE_REGISTRO),
    timeout=20, valida=rc_cero)

# Los motores de registro en marcha (con la cabecera de ps, que dice que ps respondio).
MOTORES_DE_REGISTRO = ("rsyslogd", "qLogEngined", "qNoticeEngined", "qulogd", "qulogdb", "ncdb")
MOTORES = Comando(
    "motores",
    "ps | grep -E '^ *PID |[r]syslogd|[q]LogEngined|[q]NoticeEngined|[q]ulogd|[n]cdb' | cut -c1-110",
    timeout=20, valida=rc_cero)

# Los ficheros de /etc/logs con su tamano y su fecha: los volcados del kernel que guarda pstore
# tras un cuelgue (pstore_N_AAAAMMDDhhmm.log) y el registro de procesos matados al apagar.
VOLCADOS = Comando(
    "volcados",
    "stat -c '%s %Y %n' /etc/logs/*; [ ! -e /etc/logs/.force_kill_in_shutdown.log ] "
    "|| stat -c '%s %Y %n' /etc/logs/.force_kill_in_shutdown.log",
    timeout=20, valida=rc_cero)

# --- alertas ---------------------------------------------------------------------------------------

# Nivel de alerta, zumbador y aviso de espacio libre. De la seccion de alertas solo se lee el
# nivel: el resto son destinatarios y credenciales de notificacion.
ALERTAS = Comando(
    "alertas",
    "echo nivel=$(getcfg Alert 'Alert Level'); echo zumbador=$(getcfg Misc 'Buzzer Warning Enable'); "
    "echo aviso_espacio=$(getcfg Misc 'Disk Free Size Alert Enable'); "
    "echo espacio_minimo=$(getcfg Misc 'Disk Free Size Alert')",
    timeout=20, valida=rc_cero)

# El servidor syslog del NAS (recibe registros de otros equipos), si esta configurado.
SYSLOG = Comando("syslog", "[ ! -e /etc/config/syslog_server.conf ] || cat /etc/config/syslog_server.conf",
                 timeout=20, valida=rc_cero)
