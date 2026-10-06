"""Reglas canónicas de alerta para los tenants de control interno (spec 011 §4.7).

Las reglas viven en archivos YAML estáticos (internal_rules/<slug>.yaml) que se
copian al contenedor verbatim (rol 'backend': copy del arbol -> /opt/anomalia,
Dockerfile COPY . .). Al no pasar por Jinja, las anotaciones con {{ $labels.* }}
llegan intactas a vmalert.

La BD es la fuente de verdad de las reglas, pero para un tenant interno el PUT
esta bloqueado a nivel de API; el unico origen admisible es este modulo, por lo
que las reglas son inmutables por construccion (cualquier cambio es un commit).
"""
import logging
from pathlib import Path

import yaml

logger = logging.getLogger("anomalia.internal_rules")

_RULES_DIR = Path(__file__).parent / "internal_rules"

INTERNAL_RULES: dict[str, str] = {}
for _path in sorted(_RULES_DIR.glob("*.yaml")):
    _slug = _path.stem
    _content = _path.read_text(encoding="utf-8")
    try:
        yaml.safe_load(_content)
    except yaml.YAMLError as exc:  # pragma: no cover - fail fast en arranque
        raise ValueError(f"Reglas internas inválidas para el tenant '{_slug}': {exc}") from exc
    INTERNAL_RULES[_slug] = _content

logger.info("Reglas internas cargadas: %s", ", ".join(sorted(INTERNAL_RULES)))
