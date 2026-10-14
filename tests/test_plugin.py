# -*- coding: utf-8 -*-
"""El manifiesto del plugin y el paquete tienen que decir lo mismo."""
import json
import tomllib
from pathlib import Path

import qnap_tools

RAIZ = Path(__file__).resolve().parent.parent
PLUGIN = json.loads((RAIZ / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
PAQUETE = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))


def test_la_version_del_plugin_es_la_del_paquete():
    assert PLUGIN["version"] == qnap_tools.__version__


def test_cada_servidor_del_plugin_lanza_un_ejecutable_del_paquete_y_no_falta_ninguno():
    lanzados = {nombre: servidor["args"][-1] for nombre, servidor in PLUGIN["mcpServers"].items()}
    assert lanzados == {"qnap-flota": "qnap-tools-flota", "qnap-redes": "qnap-tools-redes",
                        "qnap-discos": "qnap-tools-discos", "qnap-virtualizacion": "qnap-tools-virtualizacion",
                        "qnap-logs": "qnap-tools-logs"}
    assert set(lanzados.values()) == set(PAQUETE["project"]["scripts"])


def test_los_servidores_se_lanzan_desde_pypi_con_la_version_exacta_del_plugin():
    # sin version fija uvx resolveria contra PyPI en cada arranque (leccion 25); con la carpeta
    # del plugin (CLAUDE_PLUGIN_ROOT) cada usuario construiria el paquete en su equipo
    for nombre, servidor in PLUGIN["mcpServers"].items():
        assert servidor["command"] == "uvx", nombre
        assert servidor["args"][:2] == ["--from", "qnap-tools==%s" % qnap_tools.__version__], nombre


def test_el_paquete_enlaza_al_repositorio_publico():
    urls = PAQUETE["project"]["urls"]
    assert urls["Repository"] == "https://github.com/Picaresco/qnap-tools"


def test_todos_los_servidores_reciben_la_credencial_y_la_carpeta_de_datos():
    for nombre, servidor in PLUGIN["mcpServers"].items():
        assert servidor["env"] == {"QNAP_TOOLS_USER": "${user_config.ssh_user}",
                                   "QNAP_TOOLS_PASSWORD": "${user_config.ssh_password}",
                                   "QNAP_TOOLS_DATA": "${CLAUDE_PLUGIN_DATA}"}, nombre
