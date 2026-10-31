"""Comprobaciones independientes del agente: el precio que dice y el análisis que hizo para llegar a él.

``answers.py`` ya decide si una redacción de Grok está respaldada; este módulo lo vuelve a mirar por otro camino
para que un error en esa barrera no pase como acierto en la evaluación:

- **Oráculo de precios:** cada cifra en pesos de la respuesta debe aparecer en lo que devolvieron las herramientas
  en ese turno (precio, subtotal, total, o un monto escrito en la información de la tienda). Va siempre.
- **Códigos internos:** la respuesta nunca muestra un SKU que pasó por las herramientas (en la línea base del
  31-10, tres casos aprobados decían «Para CEM-050 hay 3 bulto disponibles»). Va siempre.
- **Análisis:** un caso puede exigir cómo entendió Grok el mensaje, no solo el resultado:
  ``forbidden_tools`` (herramientas que no debía ejecutar, como ``registrar_pedido`` ante un fiado),
  ``forbidden_skus`` (lo que no debía elegir, como un huevo suelto cuando pidieron la cubeta) y
  ``expected_search`` (campos que alguna búsqueda debía llevar: ``{"product": "queso"}``).
- **Paráfrasis:** casos con el mismo ``grupo`` dicen lo mismo con otras palabras; el reporte mide si el agente
  llegó al mismo estado y a los mismos productos en todos.
"""

import re

from asistendero.tienda.vocabulario import normalize_text

# «$13.800», «$ 1.100», «$249.000»: punto de miles como en la respuesta del agente.
PESOS = re.compile(r"\$\s?(\d{1,3}(?:\.\d{3})+|\d+)")


def _amounts_in(value: object, found: set[int]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        found.add(value)
    elif isinstance(value, str):
        found.update(int(amount.replace(".", "")) for amount in PESOS.findall(value))
    elif isinstance(value, dict):
        for item in value.values():
            _amounts_in(item, found)
    elif isinstance(value, list):
        for item in value:
            _amounts_in(item, found)


def backed_amounts(tool_calls: list[dict]) -> set[int]:
    """Montos que las herramientas ejecutadas devolvieron en este turno."""
    found: set[int] = set()
    for call in tool_calls:
        if call.get("executed"):
            _amounts_in((call.get("response") or {}).get("data"), found)
    return found


def unbacked_prices(reply: str, tool_calls: list[dict]) -> list[str]:
    backed = backed_amounts(tool_calls)
    return [f"${amount}" for amount in dict.fromkeys(PESOS.findall(reply)) if int(amount.replace(".", "")) not in backed]


def _skus_in(value: object, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "sku" and isinstance(item, str):
                found.add(item)
            else:
                _skus_in(item, found)
    elif isinstance(value, list):
        for item in value:
            _skus_in(item, found)


def leaked_codes(reply: str, tool_calls: list[dict]) -> list[str]:
    """SKU que las herramientas usaron o devolvieron y que la respuesta deja ver al cliente."""
    seen: set[str] = set()
    for call in tool_calls:
        _skus_in(call.get("arguments"), seen)
        _skus_in((call.get("response") or {}).get("data"), seen)
    return sorted(sku for sku in seen if re.search(rf"(?<![A-Z0-9-]){re.escape(sku)}(?![A-Z0-9-])", reply))


def _search_items(tool_calls: list[dict]) -> list[dict]:
    return [item for call in tool_calls if call.get("executed") and call["requested_tool"] == "buscar_productos"
            for item in (call.get("arguments") or {}).get("items", [])]


def _fits(item: dict, wanted: dict) -> bool:
    return all(normalize_text(str(value)) in normalize_text(str(item.get(field) or "")) for field, value in wanted.items())


def analysis_reasons(check: dict, tool_calls: list[dict], selected_skus: list[str]) -> list[str]:
    """Motivos por los que el camino del agente no fue el esperado, aunque el estado final lo sea."""
    executed = {call["requested_tool"] for call in tool_calls if call.get("executed")}
    reasons = [f"ejecutó {name}" for name in check.get("forbidden_tools", []) if name in executed]
    reasons += [f"eligió {sku}" for sku in check.get("forbidden_skus", []) if sku in selected_skus]
    items = _search_items(tool_calls)
    reasons += [f"ninguna búsqueda con {wanted}" for wanted in check.get("expected_search", [])
                if not any(_fits(item, wanted) for item in items)]
    return reasons


def paraphrase_groups(records: list[dict]) -> dict[str, dict]:
    """Por grupo de paráfrasis: estados y productos de cada caso y si el agente respondió igual a todos."""
    groups: dict[str, list[dict]] = {}
    for record in records:
        if record.get("grupo"):
            groups.setdefault(record["grupo"], []).append(record)
    summary = {}
    for name, members in sorted(groups.items()):
        outcomes = {(str(member["actual_status"]), tuple(sorted(member.get("selected_skus") or []))) for member in members}
        summary[name] = {"cases": [member["id"] for member in members], "consistent": len(outcomes) == 1,
                         "outcomes": sorted(" · ".join(filter(None, (status, ", ".join(skus)))) for status, skus in outcomes)}
    return summary
