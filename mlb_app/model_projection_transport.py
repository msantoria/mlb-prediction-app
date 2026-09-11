"""Bound debug row transport without changing simulation results or summaries."""

from typing import Any

DIAGNOSTIC_ROW_LIMIT = 100
_ROW_FIELDS = {
    "canonical_probability_diagnostics_shadow_v1": ("observations",),
    "canonical_pitcher_appearance_sequence_audit_v1": ("records", "trials"),
}


def compact_projection_payload(value: Any) -> Any:
    """Copy a payload, pruning only known per-trial diagnostic arrays.

    This also handles already-persisted v7 artifacts, so deployment does not
    require a full simulation refresh before existing data becomes usable.
    Full counts, tier usage, anomalies, outcomes, and player projections stay
    intact. Unknown schemas and ordinary report rows are never truncated.
    """
    if isinstance(value, dict):
        row_fields = _ROW_FIELDS.get(value.get("schema_version"), ())
        result = {}
        transport = dict(value.get("diagnostic_row_transport") or {}) if row_fields else {}
        for key, item in value.items():
            if key in row_fields and isinstance(item, list):
                previous = transport.get(key, {})
                source_total = len(item)
                if key == "observations":
                    source_total = (value.get("observation_transport") or {}).get("total_count", source_total)
                total = previous.get("total_count", source_total)
                result[key] = compact_projection_payload(item[:DIAGNOSTIC_ROW_LIMIT])
                transport[key] = {
                    "total_count": total,
                    "included_count": len(result[key]),
                    "truncated": total > len(result[key]),
                }
            else:
                result[key] = compact_projection_payload(item)
        if row_fields:
            result["diagnostic_row_transport"] = transport
        return result
    if isinstance(value, (list, tuple)):
        return [compact_projection_payload(item) for item in value]
    return value
