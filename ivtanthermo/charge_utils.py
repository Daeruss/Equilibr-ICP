import json
import re

from .models import SubstanceCharge


def parse_charge_from_label(label: str) -> int:
    if label == "e(-g)":
        return -1

    suffix_match = re.search(r"\(([^)]*)\)$", label)
    if not suffix_match:
        return 0
    suffix = suffix_match.group(1)

    explicit_match = re.fullmatch(r"([+-])g;([+-]?\d+)", suffix)
    if explicit_match:
        return int(explicit_match.group(2))

    simple_match = re.fullmatch(r"([+-])(\d*)g", suffix)
    if simple_match:
        sign = 1 if simple_match.group(1) == "+" else -1
        magnitude = int(simple_match.group(2) or "1")
        return sign * magnitude

    return 0


def build_substance_charge_map(substances) -> dict[int, int]:
    substance_list = list(substances)
    if not substance_list:
        return {}

    substance_ids = [substance.id for substance in substance_list]
    stored_map = {
        row.substance_id: row.charge
        for row in SubstanceCharge.objects.filter(substance_id__in=substance_ids)
    }

    charge_map: dict[int, int] = {}
    for substance in substance_list:
        charge_map[substance.id] = stored_map.get(substance.id, parse_charge_from_label(substance.label))
    return charge_map


def coerce_float_array(value) -> list[float]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = json.loads(value)
    return [float(item) for item in value]
