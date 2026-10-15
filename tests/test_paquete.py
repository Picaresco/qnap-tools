# -*- coding: utf-8 -*-
import re
import tomllib
from pathlib import Path


def test_el_minimo_de_mcp_es_el_que_tiene_toolannotations():
    # ToolAnnotations y add_tool(annotations=) aparecen en mcp 1.7.0 (no estan en 1.6.0)
    proyecto = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    (mcp,) = [d for d in proyecto["project"]["dependencies"] if d.startswith("mcp")]
    minimo = re.search(r">=\s*([0-9]+)\.([0-9]+)", mcp)
    assert minimo and (int(minimo.group(1)), int(minimo.group(2))) >= (1, 7), mcp
