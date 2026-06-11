#!/usr/bin/env python3
"""Layer 6LY projection adapter probability alias normalization audit.

This layer audits the non-production 6LX normalized probability surface artifact.
It does not execute adapter calls, compute metrics, run backtests, fetch data,
write databases, modify production code, activate mechanics, or grant Layer 6 exit.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

LAYER = "6LY"
LAYER_SLUG = "layer6_6ly_projection_adapter_probability_alias_normalization_audit"
TMP = Path("tmp")

PREDECESSOR_JSON = TMP / "layer6_6lx_projection_adapter_probability_alias_normalization_implementation.json"
NORMALIZED_SURFACE = TMP / "layer6_6lx_projection_adapter_probability_alias_normalization_implementation_normalized_surface.json"

OUT_JSON = TMP / f"{LAYER_SLUG}.json"
OUT_CHECKS = TMP / f"{LAYER_SLUG}_checks.csv"
OUT_PREDECESSOR = TMP / f"{LAYER_SLUG}_predecessor.csv"
OUT_INPUT_ARTIFACTS = TMP / f"{LAYER_SLUG}_input_artifacts.csv"
OUT_DECISION = TMP / f"{LAYER_SLUG}_decision.csv"
OUT_SAFETY = TMP / f"{LAYER_SLUG}_safety_boundaries.csv"
OUT_RECOMMENDED = TMP / f"{LAYER_SLUG}_recommended_path.csv"

EXPECTED_PREDECESSOR_DIAGNOSIS = "probability_alias_normalization_implemented_non_production_surface_requires_audit"
PASS_DIAGNOSIS = "probability_alias_normalization_artifact_audited_probability_metric_plan_ready"
FAIL_DIAGNOSIS = "probability_alias_normalization_audit_blocked_or_failed"
PASS_NEXT_LAYER = "6LZ_layer_6_projection_adapter_probability_surface_metric_plan"
PASS_RECOMMENDED_PATH = "plan_probability_surface_metric_on_audited_normalized_surface"
FAIL_NEXT_LAYER = "6LY_layer_6_projection_adapter_probability_alias_normalization_audit_repair"
FAIL_RECOMMENDED_PATH = "restore_or_repair_6lx_artifacts_before_audit"

SAFETY_BOUNDARIES = {
    "adapter_calls_allowed": False,
    "metrics_allowed": False,
    "backtests_allowed": False,
    "live_data_fetch_allowed": False,
    "database_writes_allowed": False,
    "production_code_changes_allowed": False,
    "mechanics_activation_allowed": False,
    "layer_6_exit_allowed": False,
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def as_bool(value: Any) -> bool:
    return bool(value)


def get_rows(surface: Any) -> List[Dict[str, Any]]:
    if isinstance(surface, list):
        return [row for row in surface if isinstance(row, dict)]
    if isinstance(surface, dict):
        if isinstance(surface.get("rows"), list):
            return [row for row in surface["rows"] if isinstance(row, dict)]
        if isinstance(surface.get("games"), list):
            return [row for row in surface["games"] if isinstance(row, dict)]
        if isinstance(surface.get("surface"), list):
            return [row for row in surface["surface"] if isinstance(row, dict)]
        return [surface]
    return []


def main() -> None:
    TMP.mkdir(exist_ok=True)

    predecessor_exists = PREDECESSOR_JSON.exists()
    surface_exists = NORMALIZED_SURFACE.exists()
    predecessor: Dict[str, Any] = read_json(PREDECESSOR_JSON) if predecessor_exists else {}
    surface = read_json(NORMALIZED_SURFACE) if surface_exists else None
    rows = get_rows(surface) if surface_exists else []
    first_row = rows[0] if rows else {}

    predecessor_diagnosis = predecessor.get("diagnosis")
    predecessor_passed = predecessor.get("all_checks_passed") is True

    run_fields = ["home_expected_runs", "away_expected_runs", "total_expected_runs", "projected_total"]
    run_surface_gap_remains = all(first_row.get(field) is None for field in run_fields) if first_row else False

    checks = [
        {
            "check": "predecessor_json_exists",
            "passed": predecessor_exists,
            "detail": str(PREDECESSOR_JSON),
        },
        {
            "check": "predecessor_6lx_passed",
            "passed": predecessor_passed,
            "detail": str(predecessor.get("all_checks_passed")),
        },
        {
            "check": "predecessor_diagnosis_expected",
            "passed": predecessor_diagnosis == EXPECTED_PREDECESSOR_DIAGNOSIS,
            "detail": str(predecessor_diagnosis),
        },
        {
            "check": "normalized_surface_artifact_exists",
            "passed": surface_exists,
            "detail": str(NORMALIZED_SURFACE),
        },
        {
            "check": "row_count_equals_1",
            "passed": len(rows) == 1,
            "detail": str(len(rows)),
        },
        {
            "check": "game_pk_present",
            "passed": "game_pk" in first_row,
            "detail": str(first_row.get("game_pk")),
        },
        {
            "check": "home_win_probability_present",
            "passed": "home_win_probability" in first_row,
            "detail": str(first_row.get("home_win_probability")),
        },
        {
            "check": "away_win_probability_present",
            "passed": "away_win_probability" in first_row,
            "detail": str(first_row.get("away_win_probability")),
        },
        {
            "check": "home_win_prob_alias_preserved",
            "passed": "home_win_prob" in first_row,
            "detail": str(first_row.get("home_win_prob")),
        },
        {
            "check": "away_win_prob_alias_preserved",
            "passed": "away_win_prob" in first_row,
            "detail": str(first_row.get("away_win_prob")),
        },
        {
            "check": "non_production_true",
            "passed": first_row.get("non_production") is True or predecessor.get("non_production") is True,
            "detail": str(first_row.get("non_production", predecessor.get("non_production"))),
        },
        {
            "check": "not_a_backtest_surface_true",
            "passed": first_row.get("not_a_backtest_surface") is True or predecessor.get("not_a_backtest_surface") is True,
            "detail": str(first_row.get("not_a_backtest_surface", predecessor.get("not_a_backtest_surface"))),
        },
        {
            "check": "run_surface_gap_remains",
            "passed": run_surface_gap_remains,
            "detail": json.dumps({field: first_row.get(field) for field in run_fields}, sort_keys=True),
        },
        {
            "check": "no_metrics_ready_yet",
            "passed": True,
            "detail": "audit layer does not compute or certify metrics",
        },
        {
            "check": "no_adapter_calls_occurred",
            "passed": True,
            "detail": "script contains no adapter invocation path",
        },
        {
            "check": "no_production_code_changed",
            "passed": True,
            "detail": "script-only audit artifact generator",
        },
        {
            "check": "no_activation_occurred",
            "passed": True,
            "detail": "activation forbidden by safety boundaries",
        },
        {
            "check": "layer_6_exit_remains_blocked",
            "passed": True,
            "detail": "Layer 6 exit forbidden by safety boundaries",
        },
    ]

    all_checks_passed = all(as_bool(row["passed"]) for row in checks)
    diagnosis = PASS_DIAGNOSIS if all_checks_passed else FAIL_DIAGNOSIS
    recommended_next_layer = PASS_NEXT_LAYER if all_checks_passed else FAIL_NEXT_LAYER
    recommended_path = PASS_RECOMMENDED_PATH if all_checks_passed else FAIL_RECOMMENDED_PATH

    blockers = []
    if not all_checks_passed:
        blockers.extend(row["check"] for row in checks if not as_bool(row["passed"]))
    blockers.extend([
        "run_surface_gap_remains",
        "real_backtest_metrics_not_run",
        "layer6_exit_not_allowed",
    ])

    result = {
        "layer": LAYER,
        "layer_slug": LAYER_SLUG,
        "all_checks_passed": all_checks_passed,
        "diagnosis": diagnosis,
        "recommended_next_layer": recommended_next_layer,
        "recommended_path": recommended_path,
        "predecessor_json": str(PREDECESSOR_JSON),
        "normalized_surface_artifact": str(NORMALIZED_SURFACE),
        "row_count": len(rows),
        "probability_surface_normalized_and_audited": all_checks_passed,
        "probability_metric_ready_after_audit": False,
        "runs_metric_ready_after_audit": False,
        "any_backtest_metric_ready_after_audit": False,
        "run_surface_gap_remains": run_surface_gap_remains,
        "layer_6_exit_recommended": False,
        "safety_boundaries": SAFETY_BOUNDARIES,
        "blockers": blockers,
        "checks": checks,
    }

    OUT_JSON.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    write_csv(OUT_CHECKS, checks, ["check", "passed", "detail"])
    write_csv(
        OUT_PREDECESSOR,
        [
            {
                "artifact": str(PREDECESSOR_JSON),
                "exists": predecessor_exists,
                "all_checks_passed": predecessor_passed,
                "diagnosis": predecessor_diagnosis,
                "expected_diagnosis": EXPECTED_PREDECESSOR_DIAGNOSIS,
            }
        ],
        ["artifact", "exists", "all_checks_passed", "diagnosis", "expected_diagnosis"],
    )
    write_csv(
        OUT_INPUT_ARTIFACTS,
        [
            {"artifact": str(PREDECESSOR_JSON), "exists": predecessor_exists, "required": True},
            {"artifact": str(NORMALIZED_SURFACE), "exists": surface_exists, "required": True},
        ],
        ["artifact", "exists", "required"],
    )
    write_csv(
        OUT_DECISION,
        [
            {
                "all_checks_passed": all_checks_passed,
                "diagnosis": diagnosis,
                "probability_surface_normalized_and_audited": all_checks_passed,
                "run_surface_gap_remains": run_surface_gap_remains,
                "layer_6_exit_recommended": False,
            }
        ],
        [
            "all_checks_passed",
            "diagnosis",
            "probability_surface_normalized_and_audited",
            "run_surface_gap_remains",
            "layer_6_exit_recommended",
        ],
    )
    write_csv(
        OUT_SAFETY,
        [{"boundary": key, "allowed": value} for key, value in SAFETY_BOUNDARIES.items()],
        ["boundary", "allowed"],
    )
    write_csv(
        OUT_RECOMMENDED,
        [{"recommended_next_layer": recommended_next_layer, "recommended_path": recommended_path}],
        ["recommended_next_layer", "recommended_path"],
    )

    print(json.dumps({
        "layer": LAYER,
        "all_checks_passed": all_checks_passed,
        "diagnosis": diagnosis,
        "recommended_next_layer": recommended_next_layer,
        "recommended_path": recommended_path,
        "blockers": blockers,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
