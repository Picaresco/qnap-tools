# -*- coding: utf-8 -*-
"""Las 10 herramientas de virtualizacion contra el NAS de laboratorio. Solo con
QNAP_TOOLS_PRUEBA_REAL=1.

El alta se hace con instalar_clave=False: la prueba no escribe nada en el NAS. Ninguna
herramienta arranca, para ni cambia nada: solo lee lo que dicen libvirt y docker.
"""
import real
from qnap_tools import servidor
from qnap_tools.flota import servidor as flota_srv
from qnap_tools.virtualizacion import servidor as virt_srv

pytestmark = real.solo_real


def test_las_diez_herramientas_responden_con_datos(tmp_path):
    env = real.leer_env()
    entorno = {"QNAP_TOOLS_USER": env["QNAP_USER"], "QNAP_TOOLS_PASSWORD": env["QNAP_PASSWORD"],
               "QNAP_TOOLS_DATA": str(tmp_path)}
    ctx = servidor.Contexto(entorno)
    nas = real.nas_de_laboratorio()
    alta = flota_srv.Herramientas(ctx).nas_alta("lab", nas.host, nas.port, instalar_clave=False)
    assert alta["ok"] is True, alta
    h = virt_srv.Herramientas(ctx)

    def datos(resultado):
        (r,) = resultado
        assert r["ok"] is True, r
        return r["datos"]

    try:
        resumen = datos(h.virtualizacion_resumen("lab"))
        assert resumen["sistema"] in ("hero", "qts") and "errores" not in resumen, resumen.get("errores")
        assert resumen["nas"]["hilos"] >= 1 and resumen["nas"]["memoria"]["total"] > 2 ** 30
        maquinas, contenedores = resumen["maquinas_virtuales"], resumen["contenedores"]
        # el NAS de laboratorio tiene los dos paquetes activos y con su servicio en marcha
        assert maquinas["activo"] and maquinas["servicio"] and maquinas["total"] >= 1
        assert contenedores["activo"] and contenedores["servicio"] and contenedores["version"]
        assert sum(maquinas["por_estado"].values()) == maquinas["total"]

        lista = datos(h.vm_lista("lab"))["vms"]
        assert lista["total"] == maquinas["total"] and not lista["truncado"]
        assert all(v["nombre"] and v["uuid"] and v["vcpus"] >= 1 and v["memoria"] > 0 for v in lista["filas"])
        en_marcha = [v for v in lista["filas"] if v["estado"] == "en marcha"]
        assert len(en_marcha) == maquinas["por_estado"].get("en marcha", 0)

        primera = (en_marcha or lista["filas"])[0]
        detalle = datos(h.vm_detalle("lab", primera["nombre"]))
        assert "errores" not in detalle, detalle.get("errores")
        vm = detalle["vm"]
        assert vm["uuid"] == primera["uuid"] and vm["discos"] and vm["consola"]
        assert datos(h.vm_detalle("lab", primera["uuid"]))["vm"]["nombre"] == primera["nombre"]
        if en_marcha:
            assert all(isinstance(i["direcciones"], list) for i in vm["interfaces"])
        (malo,) = h.vm_detalle("lab", "no-existe; reboot")
        assert malo["ok"] is False and "no hay ninguna maquina virtual" in malo["error"]

        uso = datos(h.vm_uso("lab"))
        assert "errores" not in uso, uso.get("errores")
        assert len(uso["vms"]) == len(en_marcha)
        if en_marcha:
            assert 4.0 <= uso["segundos"] <= 8.0
            assert all(v["nombre"] and 0 <= v["cpu_pct"] <= 100 for v in uso["vms"])

        instantaneas = datos(h.vm_snapshots("lab"))
        assert "errores" not in instantaneas, instantaneas.get("errores")
        assert instantaneas["vms"]["total"] == maquinas["total"]
        for v in instantaneas["vms"]["filas"]:
            assert v["instantaneas"] is not None and v["discos"] is not None and v["libvirt"] is not None
            # cada disco, con su cadena leida: tantas capas como instantaneas, mas la base
            assert all(d["capas"] >= 1 and d["ocupa"] > 0 for d in v["discos"]), v

        ct = datos(h.contenedores_lista("lab"))
        assert "errores" not in ct, ct.get("errores")
        assert ct["contenedores"]["total"] == contenedores["total"]
        assert sum(ct["por_estado"].values()) == contenedores["total"]

        medido = datos(h.contenedores_uso("lab"))
        assert medido["contenedores"]["total"] == ct["por_estado"].get("running", 0)

        redes = datos(h.contenedores_redes("lab"))["redes"]
        assert {"bridge", "host", "none"} <= {r["red"] for r in redes["filas"]}

        if ct["contenedores"]["filas"]:
            nombre = ct["contenedores"]["filas"][0]["nombre"]
            uno = datos(h.contenedor_detalle("lab", nombre))["contenedor"]
            assert uno["nombre"] == nombre and uno["imagen"] and uno["estado"]
            registro = datos(h.contenedor_logs("lab", nombre, 5))
            assert registro["contenedor"] == nombre and len(registro["lineas"]) <= 5
        (malo,) = h.contenedor_detalle("lab", "no-existe")
        assert malo["ok"] is False and "no hay ningun contenedor" in malo["error"]
    finally:
        ctx.flota.cerrar()
