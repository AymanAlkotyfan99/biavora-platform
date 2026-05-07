from __future__ import annotations

def merge_chart_config_with_fresh(stored_chart_config: dict | None, fresh_chart_contract: dict | None) -> dict:
    stored = stored_chart_config if isinstance(stored_chart_config, dict) else {}
    fresh = fresh_chart_contract if isinstance(fresh_chart_contract, dict) else {}
    fresh_chart_type = str(fresh.get("final_chart_type") or fresh.get("selected_chart_type") or "").strip().lower()
    stored_chart_type = str(stored.get("final_chart_type") or stored.get("selected_chart_type") or stored.get("chart_type") or "").strip().lower()
    if fresh_chart_type:
        effective = {**stored, **fresh}
        source = "fresh_execution"
    else:
        effective = dict(stored)
        source = "stored_fallback"
    effective_chart_type = str(
        effective.get("final_chart_type")
        or effective.get("selected_chart_type")
        or effective.get("chart_type")
        or "table"
    ).strip().lower()
    effective.update(
        {
            "chart_config_source": source,
            "stored_chart_type": stored_chart_type,
            "fresh_chart_type": fresh_chart_type,
            "effective_chart_type": effective_chart_type,
            "stored_overrode_fresh": False,
        }
    )
    return effective
