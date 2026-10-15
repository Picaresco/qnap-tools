# -*- coding: utf-8 -*-
"""Las 9 herramientas de redes contra el NAS de laboratorio. Solo con QNAP_TOOLS_PRUEBA_REAL=1.

El alta se hace con instalar_clave=False: la prueba no escribe nada en el NAS. El diagnostico
va contra la puerta de enlace del propio NAS.
"""
import real
from qnap_tools import servidor
from qnap_tools.flota import servidor as flota_srv
from qnap_tools.redes import servidor as redes_srv

pytestmark = real.solo_real


def test_las_nueve_herramientas_responden_con_datos(tmp_path):
    env = real.leer_env()
    entorno = {"QNAP_TOOLS_USER": env["QNAP_USER"], "QNAP_TOOLS_PASSWORD": env["QNAP_PASSWORD"],
               "QNAP_TOOLS_DATA": str(tmp_path)}
    ctx = servidor.Contexto(entorno)
    nas = real.nas_de_laboratorio()
    alta = flota_srv.Herramientas(ctx).nas_alta("lab", nas.host, nas.port, instalar_clave=False)
    assert alta["ok"] is True, alta
    h = redes_srv.Herramientas(ctx)

    def datos(resultado):
        (r,) = resultado
        assert r["ok"] is True, r
        return r["datos"]

    try:
        resumen = datos(h.red_resumen("lab"))
        fisicas = [i for i in resumen["interfaces"]["filas"] if i["tipo"] == "fisica"]
        assert fisicas and fisicas[0]["velocidad_mbps"] >= 100
        assert any(i["ipv4"] for i in resumen["interfaces"]["filas"])
        pasarela = resumen["puerta_enlace"][0]["via"]
        assert resumen["dns"]["servidores"]

        todas = datos(h.red_interfaces("lab"))
        assert todas["interfaces"]["total"] >= resumen["interfaces"]["total"]
        assert "error" not in todas["agregaciones"] and isinstance(todas["agregaciones"]["filas"], list)
        assert "error" not in todas["vlan"] and isinstance(todas["vlan"]["filas"], list)

        una = datos(h.red_interfaces("lab", interfaz=fisicas[0]["interfaz"]))
        assert una["enlace"]["enlace"] is True and una["controlador"]["driver"]
        assert una["contadores_error"]["contadores"] > 0

        puentes = datos(h.red_conmutadores("lab"))["puentes"]
        assert puentes["total"] >= 1

        rutas = datos(h.red_rutas("lab"))
        assert rutas["rutas"]["total"] >= 1 and rutas["reglas"]["total"] >= 3
        assert "error" not in rutas["estaticas"] and isinstance(rutas["estaticas"]["filas"], list)

        servicios = datos(h.red_servicios("lab"))
        assert servicios["configurados"]["ssh"]["activo"] is True
        ssh = [e for e in servicios["en_escucha"]["filas"] if e["proceso"] == "sshd"]
        assert ssh and ssh[0]["puerto"] == nas.port and ssh[0]["pids"]

        assert datos(h.red_dhcp_dns("lab"))["dns"]["servidores"]

        cortafuegos = datos(h.red_cortafuegos("lab"))
        assert {t["tabla"] for t in cortafuegos["iptables"]} >= {"filter"}
        assert cortafuegos["bloqueo_ip"]["activo"] in (True, False)
        assert "error" not in cortafuegos["qufirewall"] and "cortafuegos" in cortafuegos["qufirewall"]

        remoto = datos(h.red_acceso_remoto("lab"))
        assert remoto["upnp"]["activo"] in (True, False, None)
        assert remoto["ddns"]["proveedores_disponibles"] >= 1

        ping = datos(h.red_diagnostico("lab", pasarela))
        assert ping["recibidos"] >= 1 and ping["media_ms"] is not None
        traza = datos(h.red_diagnostico("lab", pasarela, prueba="traceroute"))
        assert traza["alcanzado"] is True and len(traza["saltos"]) == 1
        resuelto = datos(h.red_diagnostico("lab", "www.qnap.com", prueba="dns"))
        assert resuelto["resuelto"] is True

        rechazo = h.red_diagnostico("lab", pasarela + "; id")[0]
        assert rechazo["ok"] is False
    finally:
        ctx.flota.cerrar()
