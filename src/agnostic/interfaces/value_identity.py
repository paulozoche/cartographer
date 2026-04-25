from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any


def cell_value_identity_token(value: Any) -> str:
    if value is None:
        return "__none__"
    if isinstance(value, str) and value == "":
        return "__empty__"
    return str(value)


def stable_value_id(value: Any) -> str:
    if value is None:
        payload = "none:"
    elif isinstance(value, str) and value == "":
        payload = "empty:"
    else:
        payload = f"value:{str(value)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"vid_{digest[:24]}"


def resolve_selected_value_impact(
    *,
    selected_value_id: str,
    selected_value: str,
    active_recorte: dict[str, Any] | None,
    total_rows: int,
    fallback_counter: Counter[str],
) -> dict[str, Any]:
    if not selected_value_id and selected_value == "":
        return {
            "count": 0,
            "ratio": 0.0,
            "resolved_value": selected_value,
            "resolved_value_id": selected_value_id,
            "source": "empty",
        }

    safe_total_rows = max(int(total_rows or 0), 1)

    def _item_ratio(item: dict[str, Any], count: int) -> float:
        ratio_raw = item.get("ratio")
        ratio = float(ratio_raw) if isinstance(ratio_raw, (int, float)) else (count / safe_total_rows)
        return max(0.0, min(ratio, 1.0))

    if isinstance(active_recorte, dict):
        values_items = active_recorte.get("values") if isinstance(active_recorte.get("values"), list) else []
        preview_items = active_recorte.get("preview") if isinstance(active_recorte.get("preview"), list) else []
        if selected_value_id:
            for item in values_items:
                if not isinstance(item, dict):
                    continue
                item_value_id = str(item.get("value_id") or "")
                if not item_value_id or item_value_id != selected_value_id:
                    continue
                raw_value = item.get("value")
                count = int(item.get("count") or 0)
                return {
                    "count": count,
                    "ratio": _item_ratio(item, count),
                    "resolved_value": raw_value,
                    "resolved_value_id": item_value_id,
                    "source": "values_by_id",
                }

            for item in preview_items:
                if not isinstance(item, dict):
                    continue
                raw_value = item.get("value")
                item_value_id = str(item.get("value_id") or stable_value_id(raw_value))
                if item_value_id != selected_value_id:
                    continue
                count = int(item.get("frequency") or 0)
                ratio = count / safe_total_rows
                return {
                    "count": count,
                    "ratio": max(0.0, min(ratio, 1.0)),
                    "resolved_value": raw_value,
                    "resolved_value_id": item_value_id,
                    "source": "preview_by_id",
                }

        for item in values_items:
            if not isinstance(item, dict) or "value" not in item:
                continue
            raw_value = item.get("value")
            if str(raw_value) != selected_value:
                continue
            count = int(item.get("count") or 0)
            return {
                "count": count,
                "ratio": _item_ratio(item, count),
                "resolved_value": raw_value,
                "resolved_value_id": str(item.get("value_id") or stable_value_id(raw_value)),
                "source": "values_by_text",
            }

        for item in preview_items:
            if not isinstance(item, dict) or "value" not in item:
                continue
            raw_value = item.get("value")
            if str(raw_value) != selected_value:
                continue
            count = int(item.get("frequency") or 0)
            ratio = count / safe_total_rows
            return {
                "count": count,
                "ratio": max(0.0, min(ratio, 1.0)),
                "resolved_value": raw_value,
                "resolved_value_id": str(item.get("value_id") or stable_value_id(raw_value)),
                "source": "preview_by_text",
            }

    count = int(fallback_counter.get(selected_value, 0))
    ratio = count / safe_total_rows
    return {
        "count": count,
        "ratio": max(0.0, min(ratio, 1.0)),
        "resolved_value": selected_value,
        "resolved_value_id": selected_value_id,
        "source": "counter_fallback",
    }
