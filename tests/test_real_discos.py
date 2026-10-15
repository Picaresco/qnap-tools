# -*- coding: utf-8 -*-
"""Las 13 herramientas de discos contra el NAS de laboratorio. Solo con QNAP_TOOLS_PRUEBA_REAL=1.

El alta se hace con instalar_clave=False: la prueba no escribe nada en el NAS. Ninguna
herramienta lanza pruebas sobre los discos: solo lee lo que el NAS ya tiene.
"""
import real
from qnap_tools import servidor
from qnap_tools.discos import servidor as discos_srv
from qnap_tools.flota import servidor as flota_srv

pytestmark = real.solo_real


def test_las_nueve_herramientas_responden_con_datos(tmp_path):
    env = real.leer_env()
    entorno = {"QNAP_TOOLS_USER": env["QNAP_USER"], "QNAP_TOOLS_PASSWORD": env["QNAP_PASSWORD"],
               "QNAP_TOOLS_DATA": str(tmp_path)}
    ctx = servidor.Contexto(entorno)
    nas = real.nas_de_laboratorio()
    alta = flota_srv.Herramientas(ctx).nas_alta("lab", nas.host, nas.port, instalar_clave=False)
    assert alta["ok"] is True, alta
    h = discos_srv.Herramientas(ctx)

    def datos(resultado):
        (r,) = resultado
        assert r["ok"] is True, r
        return r["datos"]

    try:
        resumen = datos(h.almacenamiento_resumen("lab"))
        assert resumen["sistema"] in ("hero", "qts") and "errores" not in resumen, resumen.get("errores")
        assert resumen["discos"]["total"] >= 1 and resumen["volumenes"]
        assert all(0 <= v["ocupacion_pct"] <= 100 and v["bytes"] > 0 for v in resumen["volumenes"])
        hero = resumen["sistema"] == "hero"
        if hero:
            assert any(not x["interno"] and x["salud"] == "ONLINE" for x in resumen["pools"])
        else:
            assert resumen["grupos"] and all(g["degradado"] is False for g in resumen["grupos"])

        fisicos = datos(h.discos_fisicos("lab"))
        assert "errores" not in fisicos, fisicos.get("errores")
        filas = fisicos["discos"]["filas"]
        assert len(filas) == resumen["discos"]["total"]
        # con sudo funcionando, todos tienen temperatura creible y los de la cabina 0, veredicto
        assert all(d["temperatura"] is not None and 10 <= d["temperatura"] <= 75 for d in filas), filas
        assert all(d["smart"] for d in filas if d["cabina"] == 0)
        assert all(d["serie"] and d["bytes"] > 10 ** 9 and d["puerto"] for d in filas)
        assert any(d["grupo"] for d in filas)

        primero = filas[0]
        smart = datos(h.disco_smart("lab", primero["bahia"], cabina=primero["cabina"]))
        assert smart["atributos"] and smart["temperatura"] == primero["temperatura"]
        assert smart["disco"]["serie"] == primero["serie"]
        assert "error" not in smart["avisos_configurados"]
        for d in filas:
            if d["bus"] == "nvme":
                nvme = datos(h.disco_smart("lab", d["bahia"], cabina=d["cabina"]))
                assert nvme["clase"] == "nvme" and nvme["nvme"]["horas"] > 0 and nvme["sectores"] is None
                break
        (malo,) = h.disco_smart("lab", 999)
        assert malo["ok"] is False and "no hay disco" in malo["error"]

        raid = datos(h.raid_estado("lab"))
        assert raid["sistema"] == resumen["sistema"]
        if hero:
            assert all(x["dispositivos"] for x in raid["pools"])
            assert any(x["cabina"] is not None for pool in raid["pools"] for x in pool["dispositivos"])
        else:
            assert any(not g["sistema"] and g["miembros"] for g in raid["grupos"])

        volumenes = datos(h.volumenes("lab"))
        assert "errores" not in volumenes, volumenes.get("errores")
        assert volumenes["volumenes"]["total"] >= 1
        assert all(v["bytes"] and v["usado"] is not None for v in volumenes["volumenes"]["filas"])
        # la ocupacion de cada volumen es la que da df en el resumen (un punto de margen: se leen
        # en dos momentos)
        segun_df = {v["volumen"]: v["ocupacion_pct"] for v in resumen["volumenes"]}
        assert all(abs(v["ocupacion_pct"] - segun_df[v["volumen"]]) <= 1
                   for v in volumenes["volumenes"]["filas"] if v["ocupacion_pct"] is not None)

        instantaneas = datos(h.snapshots("lab"))
        assert instantaneas["total"] >= instantaneas["recientes"]["total"] >= 0
        assert "programaciones" in instantaneas["programacion"]

        carpetas = datos(h.carpetas_compartidas("lab"))
        assert "errores" not in carpetas, carpetas.get("errores")
        assert carpetas["carpetas"]["total"] >= 1
        assert all(c["ruta"] and (c["volumen"] or c["ruta"] == "%H") for c in carpetas["carpetas"]["filas"])
        assert any(c["uso"] for c in carpetas["carpetas"]["filas"])

        iscsi = datos(h.iscsi("lab"))
        assert "no_probado" not in iscsi and "errores" not in iscsi

        rendimiento = datos(h.rendimiento_discos("lab"))
        assert 4.0 <= rendimiento["segundos"] <= 8.0
        conocidos = [d for d in rendimiento["discos"] if d["cabina"] is not None]
        assert len(conocidos) >= len(filas)
        assert all(d["ocupacion_pct"] is not None and 0 <= d["ocupacion_pct"] <= 100 for d in conocidos)
    finally:
        ctx.flota.cerrar()


def test_las_herramientas_de_rutas_tareas_y_externos_responden(tmp_path):
    env = real.leer_env()
    entorno = {"QNAP_TOOLS_USER": env["QNAP_USER"], "QNAP_TOOLS_PASSWORD": env["QNAP_PASSWORD"],
               "QNAP_TOOLS_DATA": str(tmp_path)}
    ctx = servidor.Contexto(entorno)
    nas = real.nas_de_laboratorio()
    alta = flota_srv.Herramientas(ctx).nas_alta("lab", nas.host, nas.port, instalar_clave=False)
    assert alta["ok"] is True, alta
    h = discos_srv.Herramientas(ctx)

    def datos(resultado):
        (r,) = resultado
        assert r["ok"] is True, r
        return r["datos"]

    try:
        # Public existe en QTS y en QuTS hero; con y sin barra, y bajo /share, es lo mismo
        ocupa = datos(h.ruta_ocupacion("lab", "Public"))
        assert ocupa["ruta"] == "/share/Public" and ocupa["ruta_real"].startswith("/share/")
        assert ocupa["bytes"] >= 0 and ocupa["ficheros"] >= 0 and ocupa["carpetas"] >= 0
        assert ocupa["es_fichero"] is False and ocupa["bytes_en_disco"] >= 0
        assert datos(h.ruta_ocupacion("lab", "/share/Public"))["ruta_real"] == ocupa["ruta_real"]
        (fuera,) = h.ruta_ocupacion("lab", "/share/../etc")
        assert fuera["ok"] is False

        lista = datos(h.ruta_listar("lab", "/Public", limite=5))
        assert lista["es_carpeta"] is True and lista["entradas"]["total"] >= len(lista["entradas"]["filas"])
        assert all(e["tipo"] in ("fichero", "carpeta", "enlace", "otro") and e["permisos"] and e["fecha"]
                   for e in lista["entradas"]["filas"])

        # una carpeta comparada consigo misma: todo coincide
        igual = datos(h.ruta_comparar("lab", "Public", "/share/Public"))
        assert igual["iguales"] is True and igual["coinciden"] == igual["origen"]["ficheros"]

        tareas = datos(h.tareas_file_station("lab"))
        assert isinstance(tareas, dict)

        fisicos = datos(h.discos_fisicos("lab"))
        for e in fisicos["externos"]:
            assert "montaje" in e and "sistema_ficheros" in e
            if e["montaje"]:
                assert e["montaje"].startswith("/share/external/") and e["bytes_montaje"] > 0
        carpetas = datos(h.carpetas_compartidas("lab"))
        assert all(c["externo"] in (True, False) for c in carpetas["carpetas"]["filas"])
    finally:
        ctx.flota.cerrar()
