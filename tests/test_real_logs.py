# -*- coding: utf-8 -*-
"""Las 8 herramientas de registros contra el NAS de laboratorio. Solo con
QNAP_TOOLS_PRUEBA_REAL=1.

El alta se hace con instalar_clave=False: la prueba no escribe nada en el NAS. Las utilidades de
registro van en modo consulta y sin sudo: no cambian ningun registro (los accesos de la propia
prueba si quedan anotados en el registro de accesos, como cualquier inicio de sesion).
"""
import real
from qnap_tools import servidor
from qnap_tools.flota import servidor as flota_srv
from qnap_tools.logs import servidor as logs_srv

pytestmark = real.solo_real


def test_las_ocho_herramientas_responden_con_datos(tmp_path):
    env = real.leer_env()
    entorno = {"QNAP_TOOLS_USER": env["QNAP_USER"], "QNAP_TOOLS_PASSWORD": env["QNAP_PASSWORD"],
               "QNAP_TOOLS_DATA": str(tmp_path)}
    ctx = servidor.Contexto(entorno)
    nas = real.nas_de_laboratorio()
    alta = flota_srv.Herramientas(ctx).nas_alta("lab", nas.host, nas.port, instalar_clave=False)
    assert alta["ok"] is True, alta
    h = logs_srv.Herramientas(ctx)

    def datos(resultado):
        (r,) = resultado
        assert r["ok"] is True, r
        assert "errores" not in r["datos"], r["datos"].get("errores")
        return r["datos"]

    try:
        eventos = datos(h.eventos("lab", limite=5))["eventos"]
        assert len(eventos) == 5 and eventos[0]["id"] > eventos[-1]["id"]
        resumen = datos(h.eventos_resumen("lab"))
        assert resumen["total"] >= 5 and resumen["desde"] <= resumen["hasta"]
        if resumen["por_gravedad"]["error"]:
            assert resumen["ultimos_errores"] == datos(h.eventos("lab", gravedad="error", limite=10))["eventos"]
        assert datos(h.eventos("lab", desde="2099-01-01"))["eventos"] == []

        accesos = datos(h.accesos("lab", limite=5))
        # la propia prueba acaba de iniciar sesion por SSH
        assert accesos["accesos"] and accesos["se_conserva"]["filas"] >= 1
        assert any(a["servicio"] == "SSH (7)" for a in accesos["accesos"])

        avisos = datos(h.avisos("lab", limite=5))
        assert avisos["recuento"]["total"] >= len(avisos["ultimos"])

        kernel = datos(h.kernel("lab", nivel=7, lineas=5))
        assert kernel["guardados"]["lineas"] >= kernel["ultimos"]["total"] and len(kernel["en_vivo"]["lineas"]) == 5

        hardware = datos(h.salud_hardware("lab"))
        assert hardware["temperaturas"]["cpu_c"] > 0 and hardware["cabinas"][0]["cabina"] == 0

        sistema = datos(h.sistema_estado("lab"))
        assert sistema["encendido_s"] > 0 and sistema["firmware"]["version"] and sistema["motores"]["qLogEngined"] >= 1

        alertas = datos(h.alertas_config("lab"))
        assert alertas["alertas"]["nivel"] is not None
    finally:
        ctx.flota.cerrar()
