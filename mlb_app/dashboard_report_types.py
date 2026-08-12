"""Explicit report-type contracts for the dashboard object model."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional


REPORT_TYPES: Dict[str, Dict[str, Any]] = {
    "all_active_hitters": {"label": "All Active Hitters", "ui_object": "hitters", "base_object": "dashboard_player_current", "population": {"is_active": True, "player_type": "hitter"}, "relationships": [], "queryable": True},
    "all_active_pitchers": {"label": "All Active Pitchers", "ui_object": "pitchers", "base_object": "dashboard_player_current", "population": {"is_active": True, "player_type": "pitcher"}, "relationships": [], "queryable": True},
    "hitters_current_matchup": {"label": "Hitters with Current Matchup Metrics", "ui_object": "hitters", "base_object": "dashboard_players", "population": {"is_active": True, "player_type": "hitter"}, "relationships": ["current_matchup_snapshot"]},
    "hitters_arsenal_splits": {"label": "Hitters with Arsenal Splits", "ui_object": "hitters", "base_object": "batter_pitch_type_matchups", "population": {"is_active": True, "player_type": "hitter"}, "relationships": ["dashboard_players"], "queryable": True},
    "players_lineup_history": {"label": "Players with Lineup History", "ui_object": "overall_players", "base_object": "dashboard_players", "population": {"lineup_appearance_count": {"gt": 0}}, "relationships": ["lineup_appearances"], "queryable": True},
    "teams_daily_analysis": {"label": "Teams with Daily Analysis", "ui_object": "teams", "base_object": "my_dashboard_records", "population": {"component": "teams", "is_current": True}, "relationships": ["daily_analytical_snapshot"], "queryable": True, "workbench_queryable": False},
    "games_totals_analysis": {"label": "Games with Totals Analysis", "ui_object": "totals", "base_object": "my_dashboard_records", "population": {"component": "totals", "is_current": True}, "relationships": ["totals_projection", "run_environment_snapshot"], "queryable": True, "workbench_queryable": False},
    "overall_players_daily_analysis": {"label": "Overall Players", "ui_object": "overall_players", "base_object": "my_dashboard_records", "population": {"component": "overall_players", "is_current": True}, "relationships": ["dashboard_player_current"], "queryable": True, "workbench_queryable": False},
    "model_projection_games": {"label": "Model Projections", "ui_object": "model_projections", "base_object": "model_projection_date_artifact", "population": {"row_type": "game"}, "relationships": ["model_projection_players"], "queryable": True, "workbench_queryable": False},
    "model_projection_players": {"label": "Model Projection Players", "ui_object": "model_projection_players", "base_object": "model_projection_date_artifact", "population": {"row_type": "player"}, "relationships": ["model_projection_games", "dashboard_player_current"], "queryable": True, "workbench_queryable": False},
    "model_tracker_snapshots": {"label": "Model Tracker", "ui_object": "model_tracker", "base_object": "model_tracker_snapshots", "population": {}, "relationships": ["games", "dashboard_player_current"], "queryable": True, "workbench_queryable": False},
    "competitive_batter_arsenal": {"label": "Batter vs Arsenal", "ui_object": "batter_arsenal", "base_object": "batter_pitch_type_matchups", "population": {}, "relationships": ["dashboard_players", "pitch_arsenal"], "queryable": True, "workbench_queryable": True},
    "player_trends": {"label": "Player Trends", "ui_object": "player_trends", "base_object": "player_trend_snapshots", "population": {"is_active": True, "player_type": "request_config"}, "relationships": ["dashboard_players", "statcast_events", "batter_id_rolling", "pitcher_id_rolling"], "queryable": True, "workbench_queryable": False},
}


def _field(
    name: str,
    label: str,
    data_type: str,
    group: str,
    *,
    sortable: bool = True,
    filterable: bool = True,
    selectable: bool = True,
    nillable: bool = True,
    operators: Optional[List[str]] = None,
    description: str,
    freshness: str = "current_projection",
    weight_aliases: Optional[List[str]] = None,
    source_object: str = "dashboard_player_current",
) -> Dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "data_type": data_type,
        "group": group,
        "sortable": sortable,
        "filterable": filterable,
        "selectable": selectable,
        "nillable": nillable,
        "source_object": source_object,
        "relationship_path": None,
        "description": description,
        "supported_operators": operators or (
            ["eq", "in"]
            if data_type == "id"
            else (
                ["eq", "neq", "contains", "in"]
                if data_type == "string"
                else (
                    ["eq", "neq", "is_null", "is_not_null"]
                    if data_type == "boolean"
                    else ["eq", "gt", "gte", "lt", "lte", "is_null", "is_not_null"]
                )
            )
        ),
        "freshness": freshness,
        "weight_aliases": weight_aliases or [],
    }


CURRENT_PLAYER_FIELDS: List[Dict[str, Any]] = [
    _field("mlb_player_id", "MLB Player ID", "id", "Identity", nillable=False, description="Canonical MLBAM player identifier.", freshness="canonical"),
    _field("full_name", "Player Name", "string", "Identity", nillable=False, operators=["eq", "neq", "contains", "in"], description="Resolved canonical player name.", freshness="canonical"),
    _field("player_type", "Player Type", "string", "Identity", nillable=False, description="Canonical hitter or pitcher classification.", freshness="canonical"),
    _field("team_id", "Team ID", "id", "Team", description="Current MLB team identifier.", freshness="canonical"),
    _field("team_name", "Team", "string", "Team", operators=["eq", "neq", "contains", "in"], description="Current MLB team name or source abbreviation.", freshness="canonical"),
    _field("primary_position", "Primary Position", "string", "Identity", description="Current primary-position abbreviation.", freshness="canonical"),
    _field("model_score", "Model Score", "double", "Scoring", description="Approved base model score before request-scoped weights.", weight_aliases=["Score"]),
    _field("confidence", "Confidence", "string", "Scoring", operators=["eq", "neq", "in", "gt", "gte", "lt", "lte"], description="Approved model confidence label."),
    _field("xwoba", "xwOBA", "double", "Hitting", description="Current approved expected weighted on-base average.", weight_aliases=["xwOBA", "xwOBA Allowed"]),
    _field("xba", "xBA", "double", "Hitting", description="Current approved expected batting average.", weight_aliases=["xBA", "xBA Allowed"]),
    _field("exit_velocity", "Exit Velocity", "double", "Contact", description="Current approved average exit velocity.", weight_aliases=["EV", "Exit Velocity"]),
    _field("launch_angle", "Launch Angle", "double", "Contact", description="Current approved average launch angle.", weight_aliases=["LA", "Launch Angle"]),
    _field("hard_hit_rate", "Hard-Hit Rate", "double", "Contact", description="Current approved hard-hit rate.", weight_aliases=["HardHit", "HardHit Allowed"]),
    _field("barrel_rate", "Barrel Rate", "double", "Contact", description="Current approved barrel rate.", weight_aliases=["Barrel"]),
    _field("strikeout_rate", "Strikeout Rate", "double", "Discipline", description="Current approved strikeout rate.", weight_aliases=["K%"]),
    _field("walk_rate", "Walk Rate", "double", "Discipline", description="Current approved walk rate.", weight_aliases=["BB%"]),
    _field("iso", "ISO", "double", "Production", description="Current approved isolated power.", weight_aliases=["ISO"]),
    _field("obp", "OBP", "double", "Production", description="Current approved on-base percentage.", weight_aliases=["OBP"]),
    _field("slg", "SLG", "double", "Production", description="Current approved slugging percentage.", weight_aliases=["SLG"]),
    _field("plate_appearances", "Plate Appearances", "integer", "Sample", description="Plate appearances for the approved analytical context.", weight_aliases=["PA", "Pitches Seen"]),
    _field("projection_version", "Projection Version", "string", "Audit", description="Atomic projection batch version."),
    _field("promoted_at", "Promoted At", "datetime", "Audit", description="Timestamp when this current row was promoted."),
    _field("updated_at", "Updated At", "datetime", "Audit", description="Timestamp when this current row last changed."),
    _field("metrics", "Extended Metrics", "json", "Audit", sortable=False, filterable=False, selectable=False, description="Server-owned extended metrics container. Registered scalar metrics are exposed as dedicated fields before they become selectable."),
]


def _current_player_fields(
    names: List[str],
    *,
    overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Build a role-specific current-player catalog without sharing field state."""

    source = {field["name"]: field for field in CURRENT_PLAYER_FIELDS}
    fields: List[Dict[str, Any]] = []
    for name in names:
        field = deepcopy(source[name])
        field.update((overrides or {}).get(name, {}))
        fields.append(field)
    return fields


PLAYER_PROFILE_STATCAST_FIELD_DIRECTORY: Dict[str, Dict[str, Any]] = {
    "batting_average": {
        "player_types": ("hitter",),
        "json_keys": ("batting_average", "AVG"),
        "label": "Batting Average",
        "data_type": "double",
        "group": "Production",
        "description": "Current batting average from the approved hitter aggregate.",
        "weight_aliases": ["AVG"],
    },
    "average_velocity": {
        "player_types": ("pitcher",),
        "json_keys": ("average_velocity", "Velocity"),
        "label": "Average Velocity",
        "data_type": "double",
        "group": "Pitch Characteristics",
        "description": "Average pitch velocity from the approved pitcher aggregate.",
        "weight_aliases": ["Velocity"],
    },
    "average_spin_rate": {
        "player_types": ("pitcher",),
        "json_keys": ("average_spin_rate", "Spin Rate"),
        "label": "Average Spin Rate",
        "data_type": "double",
        "group": "Pitch Characteristics",
        "description": "Average spin rate from the approved pitcher aggregate.",
        "weight_aliases": ["Spin Rate"],
    },
    "horizontal_break": {
        "player_types": ("pitcher",),
        "json_keys": ("horizontal_break",),
        "label": "Average Horizontal Break",
        "data_type": "double",
        "group": "Pitch Movement",
        "description": "Average horizontal pitch break from the approved pitcher aggregate.",
    },
    "vertical_break": {
        "player_types": ("pitcher",),
        "json_keys": ("vertical_break",),
        "label": "Average Vertical Break",
        "data_type": "double",
        "group": "Pitch Movement",
        "description": "Average vertical pitch break from the approved pitcher aggregate.",
    },
    "release_position_x": {
        "player_types": ("pitcher",),
        "json_keys": ("release_position_x",),
        "label": "Average Release Position X",
        "data_type": "double",
        "group": "Release",
        "description": "Average horizontal release position from the approved pitcher aggregate.",
    },
    "release_position_z": {
        "player_types": ("pitcher",),
        "json_keys": ("release_position_z",),
        "label": "Average Release Position Z",
        "data_type": "double",
        "group": "Release",
        "description": "Average vertical release position from the approved pitcher aggregate.",
    },
    "release_extension": {
        "player_types": ("pitcher",),
        "json_keys": ("release_extension",),
        "label": "Average Release Extension",
        "data_type": "double",
        "group": "Release",
        "description": "Average release extension from the approved pitcher aggregate.",
    },
}


def _player_profile_statcast_fields(player_type: str) -> List[Dict[str, Any]]:
    """Build report fields from the player-profile metric directory.

    The Control Center and MyDashboard both read FIELD_CATALOG, so registering a
    scalar Statcast profile metric here makes it available to both surfaces and
    to the validated player report query without a second field declaration.
    """

    fields: List[Dict[str, Any]] = []
    for name, definition in PLAYER_PROFILE_STATCAST_FIELD_DIRECTORY.items():
        if player_type not in definition["player_types"]:
            continue
        field = _field(
            name,
            definition["label"],
            definition["data_type"],
            definition["group"],
            description=definition["description"],
            source_object="dashboard_player_current",
            weight_aliases=definition.get("weight_aliases"),
        )
        field["field_directory"] = "player_profile_statcast"
        fields.append(field)
    return fields


_CURRENT_PLAYER_IDENTITY_FIELDS = [
    "mlb_player_id",
    "full_name",
    "player_type",
    "team_id",
    "team_name",
    "primary_position",
    "model_score",
    "confidence",
]
_CURRENT_PLAYER_AUDIT_FIELDS = [
    "projection_version",
    "promoted_at",
    "updated_at",
    "metrics",
]

HITTER_CURRENT_FIELDS = _current_player_fields(
    _CURRENT_PLAYER_IDENTITY_FIELDS
    + [
        "xwoba",
        "xba",
        "exit_velocity",
        "launch_angle",
        "hard_hit_rate",
        "barrel_rate",
        "strikeout_rate",
        "walk_rate",
        "iso",
        "obp",
        "slg",
        "plate_appearances",
    ]
    + _CURRENT_PLAYER_AUDIT_FIELDS,
)
HITTER_CURRENT_FIELDS[-4:-4] = _player_profile_statcast_fields("hitter")

PITCHER_CURRENT_FIELDS = _current_player_fields(
    _CURRENT_PLAYER_IDENTITY_FIELDS
    + [
        "xwoba",
        "xba",
        "hard_hit_rate",
        "strikeout_rate",
        "walk_rate",
    ]
    + _CURRENT_PLAYER_AUDIT_FIELDS,
    overrides={
        "xwoba": {
            "label": "xwOBA Allowed",
            "group": "Contact Suppression",
            "description": "Current approved expected weighted on-base average allowed.",
        },
        "xba": {
            "label": "xBA Allowed",
            "group": "Contact Suppression",
            "description": "Current approved expected batting average allowed.",
        },
        "hard_hit_rate": {
            "label": "Hard-Hit Rate Allowed",
            "group": "Contact Suppression",
            "description": "Current approved hard-hit rate allowed.",
        },
        "strikeout_rate": {
            "label": "Strikeout Rate",
            "group": "Pitching Skill",
            "description": "Current approved pitcher strikeout rate.",
        },
        "walk_rate": {
            "label": "Walk Rate",
            "group": "Pitching Skill",
            "description": "Current approved pitcher walk rate.",
        },
    },
)
PITCHER_CURRENT_FIELDS[-4:-4] = _player_profile_statcast_fields("pitcher")


LINEUP_HISTORY_FIELDS: List[Dict[str, Any]] = [
    _field("mlb_player_id", "MLB Player ID", "id", "Identity", nillable=False, description="Canonical MLBAM player identifier.", freshness="canonical"),
    _field("full_name", "Player Name", "string", "Identity", nillable=False, operators=["eq", "neq", "contains", "in"], description="Resolved canonical player name.", freshness="canonical"),
    _field("player_type", "Player Type", "string", "Identity", nillable=False, description="Canonical hitter or pitcher classification.", freshness="canonical"),
    _field("current_team_id", "Team ID", "id", "Team", description="Current MLB team identifier.", freshness="canonical"),
    _field("current_team_name", "Team", "string", "Team", operators=["eq", "neq", "contains", "in"], description="Current MLB team name.", freshness="canonical"),
    _field("most_recent_lineup_date", "Most Recent Lineup Date", "date", "Lineup History", description="Most recent verified confirmed-lineup date.", freshness="canonical"),
    _field("lineup_appearance_count", "Lineup Appearances", "integer", "Lineup History", description="Count of distinct verified lineup dates retained for this player.", freshness="canonical"),
    _field("most_recent_game_date", "Most Recent Tracked Game", "date", "Activity", description="Most recent tracked Statcast game date.", freshness="canonical"),
    _field("tracked_game_count", "Tracked Games", "integer", "Activity", description="Distinct tracked games retained for this player.", freshness="canonical"),
    _field("active_status_reason", "Active Status Reason", "string", "Activity", description="Verified eligibility path keeping the player active.", freshness="canonical"),
    _field("is_active", "Active", "boolean", "Activity", description="Whether the canonical player is currently reportable.", freshness="canonical"),
]
for field in LINEUP_HISTORY_FIELDS:
    field["source_object"] = "dashboard_players"

ARSENAL_SPLIT_FIELDS: List[Dict[str, Any]] = [
    _field("id", "Split Row ID", "id", "Identity", nillable=False, description="Persistent arsenal split row identifier."),
    _field("batter_id", "Batter MLB ID", "id", "Identity", nillable=False, description="Canonical batter MLBAM identifier."),
    _field("batter_name", "Batter", "string", "Identity", operators=["eq", "neq", "contains", "in"], description="Stored batter name for this split."),
    _field("batter_team_id", "Team ID", "id", "Team", description="Stored batter team identifier."),
    _field("opposing_pitcher_id", "Opposing Pitcher MLB ID", "id", "Matchup", nillable=False, description="Opposing pitcher MLBAM identifier."),
    _field("pitch_type", "Pitch Type", "string", "Matchup", nillable=False, operators=["eq", "neq", "in"], description="Statcast pitch type code."),
    _field("game_pk", "Game PK", "id", "Matchup", description="Associated MLB game identifier."),
    _field("target_date", "Target Date", "date", "Freshness", description="Report target date for the split."),
    _field("date_end", "Sample End Date", "date", "Freshness", description="Last date included in the analytical sample."),
    _field("pitches_seen", "Pitches Seen", "integer", "Sample", description="Deduplicated pitch exposure."),
    _field("pa_ended", "Plate Appearances Ended", "integer", "Sample", description="Plate appearances ending on this pitch type."),
    _field("xwoba", "xwOBA", "double", "Quality", description="Expected weighted on-base average against the pitch type."),
    _field("xba", "xBA", "double", "Quality", description="Expected batting average against the pitch type."),
    _field("avg_exit_velocity", "Exit Velocity", "double", "Contact", description="Average exit velocity against the pitch type."),
    _field("avg_launch_angle", "Launch Angle", "double", "Contact", description="Average launch angle against the pitch type."),
    _field("hard_hit_pct", "Hard-Hit Rate", "double", "Contact", description="Hard-hit rate against the pitch type."),
    _field("whiff_pct", "Whiff Rate", "double", "Discipline", description="Whiff rate against the pitch type."),
    _field("k_pct", "Strikeout Rate", "double", "Discipline", description="Strikeout rate against the pitch type."),
    _field("source", "Source", "string", "Audit", description="Materialization source."),
    _field("refreshed_at", "Refreshed At", "datetime", "Freshness", description="Last refresh timestamp."),
]
for field in ARSENAL_SPLIT_FIELDS:
    field["source_object"] = "batter_pitch_type_matchups"


def _dataset_field(
    name: str,
    label: str,
    data_type: str,
    group: str,
    *,
    sortable: bool = True,
    filterable: bool = True,
    metric_key: Optional[str] = None,
    description: str,
) -> Dict[str, Any]:
    field = _field(
        name,
        label,
        data_type,
        group,
        sortable=sortable,
        filterable=filterable,
        description=description,
        source_object="my_dashboard_records",
        freshness="daily_dashboard_dataset",
    )
    if metric_key:
        field["metric_key"] = metric_key
        field["payload_path"] = f"metrics.{metric_key}"
    return field


DATASET_FIELDS: List[Dict[str, Any]] = [
    _dataset_field("entity_id", "Entity ID", "string", "Identity", description="Stable report entity identifier."),
    _dataset_field("entity_name", "Name", "string", "Identity", description="Display name for the report row."),
    _dataset_field("entity_type", "Entity Type", "string", "Identity", description="Server-owned row classification."),
    _dataset_field("player_type", "Player Type", "string", "Identity", description="Hitter or pitcher classification when applicable."),
    _dataset_field("team", "Team", "string", "Matchup", description="Team associated with the row."),
    _dataset_field("opponent", "Opponent", "string", "Matchup", description="Opponent associated with the row."),
    _dataset_field("game_pk", "Game PK", "id", "Matchup", description="Canonical MLB game identifier."),
    _dataset_field("pitch_type", "Pitch Type", "string", "Matchup", description="Registered pitch-type code associated with the row."),
    _dataset_field("pitch_name", "Pitch Name", "string", "Matchup", description="Registered pitch name associated with the row."),
    _dataset_field("category", "Category", "string", "Classification", description="Server-owned report category."),
    _dataset_field("score", "Score", "double", "Scoring", description="Current report score."),
    _dataset_field("base_score", "Base Score", "double", "Scoring", description="Score before request-scoped weights."),
    _dataset_field("adjusted_score", "Adjusted Score", "double", "Scoring", description="Score after request-scoped weights."),
    _dataset_field("confidence", "Confidence", "string", "Scoring", description="Current confidence label."),
    _dataset_field("source", "Source", "string", "Audit", description="Registered source contract."),
    _dataset_field("primary_reason", "Primary Reason", "string", "Audit", sortable=False, description="Primary explanation attached to the row."),
    _dataset_field("lineup_verified", "Lineup Verified", "boolean", "Lineup", description="Whether the row belongs to a verified confirmed lineup."),
    _dataset_field("lineup_source", "Lineup Source", "string", "Lineup", description="Registered lineup source for the row."),
    _dataset_field("confirmed_lineup_date", "Confirmed Lineup Date", "date", "Lineup", description="MLB date of the verified lineup."),
    _dataset_field("lineup_revision", "Lineup Revision", "string", "Lineup", description="Version of the lineup used by the row."),
    _dataset_field("model_state", "Model State", "string", "Freshness", description="Model population state associated with the row."),
]

DATASET_FIELD_NAMES: Dict[str, List[str]] = {
    "teams_daily_analysis": [
        "entity_id", "entity_name", "entity_type", "team", "opponent", "game_pk",
        "category", "score", "base_score", "adjusted_score", "confidence", "source",
        "primary_reason",
    ],
    "games_totals_analysis": [
        "entity_id", "entity_name", "entity_type", "team", "opponent", "game_pk",
        "category", "score", "base_score", "adjusted_score", "confidence", "source",
        "primary_reason",
    ],
    "overall_players_daily_analysis": [
        "entity_id", "entity_name", "entity_type", "player_type", "team", "opponent",
        "game_pk", "pitch_type", "pitch_name", "category", "score", "base_score",
        "adjusted_score", "confidence", "source", "primary_reason", "lineup_verified",
        "lineup_source", "confirmed_lineup_date", "lineup_revision", "model_state",
    ],
}

DATASET_METRICS: Dict[str, List[tuple[str, str, str]]] = {
    "teams_daily_analysis": [
        ("edge_score", "Edge Score", "Edge Score"),
        ("win_edge", "Win Edge", "Win Edge"),
        ("run_differential", "Run Diff", "Run Differential"),
        ("iso", "ISO", "ISO"),
        ("obp", "OBP", "OBP"),
        ("slg", "SLG", "SLG"),
    ],
    "games_totals_analysis": [
        ("projected_total", "Projected Total", "Projected Total"),
        ("raw_total", "Raw Total", "Raw Total"),
        ("run_index", "Run Index", "Run Index"),
    ],
    "overall_players_daily_analysis": [
        ("xwoba", "xwOBA", "xwOBA"),
        ("exit_velocity", "EV", "Exit Velocity"),
        ("strikeout_rate", "K%", "Strikeout Rate"),
        ("xwoba_allowed", "xwOBA Allowed", "xwOBA Allowed"),
    ],
}


def _runtime_field(
    name: str,
    label: str,
    data_type: str,
    group: str,
    source_object: str,
    description: str,
    *,
    sortable: bool = True,
    filterable: bool = True,
    freshness: str,
) -> Dict[str, Any]:
    return _field(
        name,
        label,
        data_type,
        group,
        sortable=sortable,
        filterable=filterable,
        description=description,
        source_object=source_object,
        freshness=freshness,
    )


MODEL_PROJECTION_GAME_FIELDS = [
    _runtime_field("game_pk", "Game PK", "id", "Identity", "model_projection_date_artifact", "Canonical MLB game identifier.", freshness="projection_artifact"),
    _runtime_field("game_date", "Game Date", "date", "Identity", "model_projection_date_artifact", "Projection game date.", freshness="projection_artifact"),
    _runtime_field("game_time", "Game Time", "string", "Identity", "model_projection_date_artifact", "Scheduled game time.", freshness="projection_artifact"),
    _runtime_field("status", "Game Status", "string", "Identity", "model_projection_date_artifact", "Game status captured by the projection.", freshness="projection_artifact"),
    _runtime_field("venue", "Venue", "string", "Environment", "model_projection_date_artifact", "Scheduled venue.", freshness="projection_artifact"),
    _runtime_field("away_team_id", "Away Team ID", "id", "Teams", "model_projection_date_artifact", "Away team identifier.", freshness="projection_artifact"),
    _runtime_field("away_team_name", "Away Team", "string", "Teams", "model_projection_date_artifact", "Away team name.", freshness="projection_artifact"),
    _runtime_field("home_team_id", "Home Team ID", "id", "Teams", "model_projection_date_artifact", "Home team identifier.", freshness="projection_artifact"),
    _runtime_field("home_team_name", "Home Team", "string", "Teams", "model_projection_date_artifact", "Home team name.", freshness="projection_artifact"),
    _runtime_field("away_pitcher_id", "Away Pitcher ID", "id", "Starters", "model_projection_date_artifact", "Away probable pitcher identifier.", freshness="projection_artifact"),
    _runtime_field("away_pitcher_name", "Away Pitcher", "string", "Starters", "model_projection_date_artifact", "Away probable pitcher name.", freshness="projection_artifact"),
    _runtime_field("home_pitcher_id", "Home Pitcher ID", "id", "Starters", "model_projection_date_artifact", "Home probable pitcher identifier.", freshness="projection_artifact"),
    _runtime_field("home_pitcher_name", "Home Pitcher", "string", "Starters", "model_projection_date_artifact", "Home probable pitcher name.", freshness="projection_artifact"),
    _runtime_field("away_win_probability", "Away Win Probability", "double", "Probability", "model_projection_date_artifact", "Displayed Model Projections away win probability.", freshness="projection_artifact"),
    _runtime_field("home_win_probability", "Home Win Probability", "double", "Probability", "model_projection_date_artifact", "Displayed Model Projections home win probability.", freshness="projection_artifact"),
    _runtime_field("projected_away_runs", "Projected Away Runs", "double", "Runs", "model_projection_date_artifact", "Projected away runs from the shared projection output.", freshness="projection_artifact"),
    _runtime_field("projected_home_runs", "Projected Home Runs", "double", "Runs", "model_projection_date_artifact", "Projected home runs from the shared projection output.", freshness="projection_artifact"),
    _runtime_field("projected_total", "Projected Total", "double", "Runs", "model_projection_date_artifact", "Projected combined runs.", freshness="projection_artifact"),
    _runtime_field("model_version", "Model Version", "string", "Audit", "model_projection_date_artifact", "Displayed projection model version.", freshness="projection_artifact"),
    _runtime_field("probability_source", "Probability Source", "string", "Audit", "model_projection_date_artifact", "Registered displayed probability source.", freshness="projection_artifact"),
    _runtime_field("probability_is_fallback", "Fallback Probability", "boolean", "Audit", "model_projection_date_artifact", "Whether the displayed probability used a fallback.", freshness="projection_artifact"),
    _runtime_field("lineup_status", "Lineup Status", "string", "Freshness", "model_projection_date_artifact", "Lineup readiness captured by the projection.", freshness="projection_artifact"),
    _runtime_field("data_confidence", "Data Confidence", "string", "Freshness", "model_projection_date_artifact", "Projection data-confidence label.", freshness="projection_artifact"),
]
MODEL_PROJECTION_GAME_FIELDS.extend([
    _runtime_field(name, label, data_type, group, "model_projection_date_artifact", description, freshness="projection_artifact")
    for name, label, data_type, group, description in [
        ("away_starter_k_rate", "Away Starter K Rate", "double", "Starting Pitchers", "Away starter strikeout rate."),
        ("away_starter_bb_rate", "Away Starter Walk Rate", "double", "Starting Pitchers", "Away starter walk rate."),
        ("away_starter_xwoba_allowed", "Away Starter xwOBA Allowed", "double", "Starting Pitchers", "Away starter expected weighted on-base average allowed."),
        ("away_starter_hard_hit_rate_allowed", "Away Starter Hard-Hit Rate Allowed", "double", "Starting Pitchers", "Away starter hard-hit rate allowed."),
        ("home_starter_k_rate", "Home Starter K Rate", "double", "Starting Pitchers", "Home starter strikeout rate."),
        ("home_starter_bb_rate", "Home Starter Walk Rate", "double", "Starting Pitchers", "Home starter walk rate."),
        ("home_starter_xwoba_allowed", "Home Starter xwOBA Allowed", "double", "Starting Pitchers", "Home starter expected weighted on-base average allowed."),
        ("home_starter_hard_hit_rate_allowed", "Home Starter Hard-Hit Rate Allowed", "double", "Starting Pitchers", "Home starter hard-hit rate allowed."),
        ("away_offense_k_rate", "Away Offense K Rate", "double", "Offense", "Away offense strikeout rate."),
        ("away_offense_bb_rate", "Away Offense Walk Rate", "double", "Offense", "Away offense walk rate."),
        ("away_offense_obp", "Away Offense OBP", "double", "Offense", "Away offense on-base percentage."),
        ("away_offense_iso", "Away Offense ISO", "double", "Offense", "Away offense isolated power."),
        ("away_offense_slg", "Away Offense SLG", "double", "Offense", "Away offense slugging percentage."),
        ("home_offense_k_rate", "Home Offense K Rate", "double", "Offense", "Home offense strikeout rate."),
        ("home_offense_bb_rate", "Home Offense Walk Rate", "double", "Offense", "Home offense walk rate."),
        ("home_offense_obp", "Home Offense OBP", "double", "Offense", "Home offense on-base percentage."),
        ("home_offense_iso", "Home Offense ISO", "double", "Offense", "Home offense isolated power."),
        ("home_offense_slg", "Home Offense SLG", "double", "Offense", "Home offense slugging percentage."),
        ("away_bullpen_k_rate", "Away Bullpen K Rate", "double", "Bullpens", "Away bullpen strikeout rate."),
        ("away_bullpen_bb_rate", "Away Bullpen Walk Rate", "double", "Bullpens", "Away bullpen walk rate."),
        ("away_bullpen_xwoba_allowed", "Away Bullpen xwOBA Allowed", "double", "Bullpens", "Away bullpen expected weighted on-base average allowed."),
        ("home_bullpen_k_rate", "Home Bullpen K Rate", "double", "Bullpens", "Home bullpen strikeout rate."),
        ("home_bullpen_bb_rate", "Home Bullpen Walk Rate", "double", "Bullpens", "Home bullpen walk rate."),
        ("home_bullpen_xwoba_allowed", "Home Bullpen xwOBA Allowed", "double", "Bullpens", "Home bullpen expected weighted on-base average allowed."),
        ("run_scoring_index", "Run Scoring Index", "double", "Environment", "Run-scoring environment index."),
        ("hr_boost_index", "Home Run Boost Index", "double", "Environment", "Home-run environment index."),
        ("hit_boost_index", "Hit Boost Index", "double", "Environment", "Hit environment index."),
        ("temperature_f", "Temperature", "double", "Environment", "Game-time temperature in Fahrenheit."),
        ("weather_condition", "Weather Condition", "string", "Environment", "Game-time weather condition."),
        ("wind_speed_mph", "Wind Speed", "double", "Environment", "Game-time wind speed in miles per hour."),
        ("wind_direction", "Wind Direction", "string", "Environment", "Game-time wind direction."),
        ("away_matchup_biggest_edge", "Away Matchup Biggest Edge", "string", "Matchup", "Strongest pitch-type edge for the away offense."),
        ("away_matchup_confidence", "Away Matchup Confidence", "double", "Matchup", "Away matchup-analysis confidence."),
        ("home_matchup_biggest_edge", "Home Matchup Biggest Edge", "string", "Matchup", "Strongest pitch-type edge for the home offense."),
        ("home_matchup_confidence", "Home Matchup Confidence", "double", "Matchup", "Home matchup-analysis confidence."),
        ("simulation_count", "Simulation Count", "integer", "Simulation", "Trials in the shared game simulation."),
        ("tie_after_regulation_probability", "Tie After Regulation", "double", "Simulation", "Probability of a tie after regulation."),
        ("over_8_5_probability", "Over 8.5 Probability", "double", "Simulation", "Projected probability of more than 8.5 runs."),
        ("under_8_5_probability", "Under 8.5 Probability", "double", "Simulation", "Projected probability of fewer than 8.5 runs."),
    ]
])

MODEL_PROJECTION_PLAYER_FIELDS = [
    _runtime_field("game_pk", "Game PK", "id", "Identity", "model_projection_date_artifact", "Parent projection game identifier.", freshness="projection_artifact"),
    _runtime_field("game_date", "Game Date", "date", "Identity", "model_projection_date_artifact", "Parent projection game date.", freshness="projection_artifact"),
    _runtime_field("mlb_player_id", "MLB Player ID", "id", "Identity", "model_projection_date_artifact", "Resolved MLBAM player identifier.", freshness="projection_artifact"),
    _runtime_field("full_name", "Player Name", "string", "Identity", "model_projection_date_artifact", "Resolved player name.", freshness="projection_artifact"),
    _runtime_field("player_type", "Player Type", "string", "Identity", "model_projection_date_artifact", "Batter or pitcher projection row.", freshness="projection_artifact"),
    _runtime_field("team_side", "Team Side", "string", "Team", "model_projection_date_artifact", "Away or home side.", freshness="projection_artifact"),
    _runtime_field("team_id", "Team ID", "id", "Team", "model_projection_date_artifact", "Resolved current team identifier.", freshness="projection_artifact"),
    _runtime_field("team_name", "Team", "string", "Team", "model_projection_date_artifact", "Resolved current team name.", freshness="projection_artifact"),
    _runtime_field("primary_position", "Primary Position", "string", "Identity", "model_projection_date_artifact", "Resolved primary position.", freshness="projection_artifact"),
    _runtime_field("projected_dfs_points", "Projected DFS Points", "double", "Projection", "model_projection_date_artifact", "Mean projected fantasy points.", freshness="projection_artifact"),
    _runtime_field("dfs_floor", "DFS Floor", "double", "Projection", "model_projection_date_artifact", "Tenth-percentile projected fantasy points.", freshness="projection_artifact"),
    _runtime_field("dfs_median", "DFS Median", "double", "Projection", "model_projection_date_artifact", "Median projected fantasy points.", freshness="projection_artifact"),
    _runtime_field("dfs_ceiling", "DFS Ceiling", "double", "Projection", "model_projection_date_artifact", "Ninetieth-percentile projected fantasy points.", freshness="projection_artifact"),
    _runtime_field("simulation_count", "Simulation Count", "integer", "Audit", "model_projection_date_artifact", "Trials backing the player projection.", freshness="projection_artifact"),
]
MODEL_PROJECTION_PLAYER_FIELDS.extend([
    _runtime_field(name, label, "double", group, "model_projection_date_artifact", description, freshness="projection_artifact")
    for name, label, group, description in [
        ("plate_appearances", "Plate Appearances", "Batter Projection", "Mean projected plate appearances."),
        ("singles", "Singles", "Batter Projection", "Mean projected singles."),
        ("doubles", "Doubles", "Batter Projection", "Mean projected doubles."),
        ("triples", "Triples", "Batter Projection", "Mean projected triples."),
        ("home_runs", "Home Runs", "Batter Projection", "Mean projected home runs."),
        ("runs", "Runs", "Player Projection", "Mean projected runs."),
        ("rbi", "RBI", "Batter Projection", "Mean projected runs batted in."),
        ("walks", "Walks", "Player Projection", "Mean projected walks."),
        ("stolen_bases", "Stolen Bases", "Batter Projection", "Mean projected stolen bases."),
        ("strikeouts", "Strikeouts", "Player Projection", "Mean projected strikeouts."),
        ("batters_faced", "Batters Faced", "Pitcher Projection", "Mean projected batters faced."),
        ("outs_recorded", "Outs Recorded", "Pitcher Projection", "Mean projected outs recorded."),
        ("hits_allowed", "Hits Allowed", "Pitcher Projection", "Mean projected hits allowed."),
        ("hit_by_pitch", "Hit By Pitch", "Pitcher Projection", "Mean projected hit batters."),
        ("runs_allowed", "Runs Allowed", "Pitcher Projection", "Mean projected runs allowed."),
        ("earned_runs", "Earned Runs", "Pitcher Projection", "Mean projected earned runs."),
    ]
])

MODEL_TRACKER_FIELDS = [
    _runtime_field(name, label, data_type, group, "model_tracker_snapshots", description, freshness="tracker_snapshot")
    for name, label, data_type, group, description in [
        ("id", "Tracker Row ID", "id", "Identity", "Persistent tracker row identifier."),
        ("snapshot_date", "Snapshot Date", "date", "Identity", "Date captured by the tracker."),
        ("source", "Source", "string", "Source", "Registered product source."),
        ("source_component", "Source Component", "string", "Source", "Registered source component."),
        ("game_pk", "Game PK", "id", "Game", "Canonical MLB game identifier."),
        ("player_id", "Player ID", "id", "Identity", "Canonical player identifier when applicable."),
        ("player_name", "Player", "string", "Identity", "Player display name."),
        ("team_name", "Team", "string", "Game", "Team associated with the tracked row."),
        ("opponent_name", "Opponent", "string", "Game", "Opponent associated with the tracked row."),
        ("away_team", "Away Team", "string", "Game", "Away team name."),
        ("home_team", "Home Team", "string", "Game", "Home team name."),
        ("market_type", "Market Type", "string", "Pick", "Tracked market classification."),
        ("pick_type", "Pick Type", "string", "Pick", "Tracked pick classification."),
        ("pick_label", "Pick", "string", "Pick", "Tracked pick label."),
        ("model_name", "Model", "string", "Model", "Registered model name."),
        ("model_version", "Model Version", "string", "Model", "Registered model version."),
        ("model_probability", "Model Probability", "double", "Model", "Model probability at snapshot time."),
        ("market_implied_probability", "Market Implied Probability", "double", "Model", "Market implied probability at snapshot time."),
        ("edge", "Edge", "double", "Model", "Tracked model edge."),
        ("score", "Score", "double", "Model", "Tracked score."),
        ("confidence", "Confidence", "double", "Model", "Tracked numeric confidence."),
        ("line", "Line", "double", "Market", "Tracked market line."),
        ("price", "Price", "double", "Market", "Tracked market price."),
        ("expected_value", "Expected Value", "double", "Market", "Tracked expected value."),
        ("projected_total", "Projected Total", "double", "Projection", "Tracked projected total."),
        ("projected_home_runs", "Projected Home Runs", "double", "Projection", "Tracked projected home runs."),
        ("projected_away_runs", "Projected Away Runs", "double", "Projection", "Tracked projected away runs."),
        ("home_win_probability", "Home Win Probability", "double", "Projection", "Tracked home win probability."),
        ("away_win_probability", "Away Win Probability", "double", "Projection", "Tracked away win probability."),
        ("primary_reason", "Primary Reason", "string", "Audit", "Primary tracked reasoning summary."),
        ("game_status_at_snapshot", "Game Status", "string", "Result", "Game status at snapshot time."),
        ("result_status", "Result Status", "string", "Result", "Result comparison status."),
        ("grade", "Grade", "string", "Result", "Current tracker grade."),
        ("grade_reason", "Grade Reason", "string", "Result", "Reason for the current grade."),
        ("created_at", "Created At", "datetime", "Audit", "Snapshot creation time."),
        ("updated_at", "Updated At", "datetime", "Audit", "Snapshot update time."),
        ("last_compared_at", "Last Compared At", "datetime", "Audit", "Most recent result comparison time."),
    ]
]

COMPETITIVE_ARSENAL_FIELDS = deepcopy(ARSENAL_SPLIT_FIELDS)
for field in COMPETITIVE_ARSENAL_FIELDS:
    field["freshness"] = "competitive_matchup_snapshot"
COMPETITIVE_ARSENAL_FIELDS.extend([
    {
        **_field(
            "team_name",
            "Team Name",
            "string",
            "Team",
            operators=["eq", "neq", "contains", "in"],
            description="Current team name resolved from the batter's canonical player directory record.",
            freshness="canonical",
            source_object="dashboard_players",
        ),
        "field_directory": "canonical_player_directory",
        "relationship_path": "batter.current_team",
    },
    {
        **_field(
            "opposing_pitcher_name",
            "Opposing Pitcher Name",
            "string",
            "Matchup",
            operators=["eq", "neq", "contains", "in"],
            description="Current opposing pitcher name resolved from the canonical player directory record.",
            freshness="canonical",
            source_object="dashboard_players",
        ),
        "field_directory": "canonical_player_directory",
        "relationship_path": "opposing_pitcher",
    },
    {
        **_field(
            "opposing_team_name",
            "Opposing Team Name",
            "string",
            "Team",
            operators=["eq", "neq", "contains", "in"],
            description="Current opposing team name resolved from the opposing pitcher's canonical player directory record.",
            freshness="canonical",
            source_object="dashboard_players",
        ),
        "field_directory": "canonical_player_directory",
        "relationship_path": "opposing_pitcher.current_team",
    },
])
COMPETITIVE_ARSENAL_FIELDS.extend([
    _runtime_field(name, label, data_type, group, "pitch_arsenal", description, freshness="competitive_matchup_snapshot")
    for name, label, data_type, group, description in [
        ("pitcher_pitch_name", "Pitch Name", "string", "Pitcher Arsenal", "Opposing pitcher pitch name."),
        ("pitcher_pitch_count", "Pitcher Pitch Count", "integer", "Pitcher Arsenal", "Opposing pitcher pitch count."),
        ("pitcher_usage_pct", "Pitcher Usage", "double", "Pitcher Arsenal", "Opposing pitcher usage rate for the pitch type."),
        ("pitcher_whiff_pct", "Pitcher Whiff Rate", "double", "Pitcher Arsenal", "Opposing pitcher whiff rate for the pitch type."),
        ("pitcher_strikeout_pct", "Pitcher Strikeout Rate", "double", "Pitcher Arsenal", "Opposing pitcher strikeout rate for the pitch type."),
        ("pitcher_xwoba", "Pitcher xwOBA", "double", "Pitcher Arsenal", "Opposing pitcher xwOBA allowed for the pitch type."),
        ("pitcher_hard_hit_pct", "Pitcher Hard-Hit Rate", "double", "Pitcher Arsenal", "Opposing pitcher hard-hit rate allowed for the pitch type."),
        ("edge_score", "Edge Score", "double", "Competitive Analysis", "Existing competitive edge formula over batter quality, pitcher quality, and pitch usage."),
        ("matchup_confidence", "Matchup Confidence", "double", "Competitive Analysis", "Existing competitive sample-and-usage confidence."),
    ]
])

PLAYER_TREND_FIELDS = [
    _runtime_field(name, label, data_type, group, "player_trend_snapshots", description, freshness="cached_trend_snapshot")
    for name, label, data_type, group, description in [
        ("rank", "Rank", "integer", "Identity", "Report-engine rank after the saved sort."),
        ("player_id", "MLB Player ID", "id", "Identity", "Canonical MLBAM player identifier."),
        ("player_name", "Player Name", "string", "Identity", "Canonical player name."),
        ("player_type", "Player Type", "string", "Identity", "Hitter or pitcher."),
        ("team", "Team", "string", "Identity", "Current canonical team."),
        ("metric", "Metric", "string", "Trend", "Rolling-page metric API name."),
        ("metric_label", "Metric Name", "string", "Trend", "Rolling-page metric display name."),
        ("selected_window_days", "Window Days", "integer", "Configuration", "User-selected N-day window."),
        ("comparison_baseline", "Comparison Baseline", "string", "Configuration", "User-selected authoritative comparison period."),
        ("window_start", "Window Start", "date", "Window", "Inclusive trend-window start date."),
        ("window_end", "Window End", "date", "Window", "Inclusive trend-window end date."),
        ("baseline_start", "Baseline Start", "date", "Window", "Inclusive comparison-period start date."),
        ("baseline_end", "Baseline End", "date", "Window", "Inclusive comparison-period end date."),
        ("window_sample_size", "Window Sample", "integer", "Sample", "Plate appearances for hitters or batters faced for pitchers."),
        ("baseline_sample_size", "Baseline Sample", "integer", "Sample", "Comparison plate appearances or batters faced."),
        ("current_value", "Window Value", "double", "Trend", "Metric value in the selected window."),
        ("baseline_value", "Baseline Value", "double", "Trend", "Metric value in the comparison period."),
        ("absolute_change", "Absolute Change", "double", "Trend", "Window value minus baseline value."),
        ("percentage_change", "Percentage Change", "double", "Trend", "Change divided by the absolute baseline when nonzero."),
        ("trend_direction", "Trend Direction", "string", "Trend", "Deterministic improving, declining, or stable classification."),
        ("favorable_direction", "Favorable Direction", "string", "Trend", "Metric-aware higher- or lower-is-better rule."),
        ("freshness_date", "Freshness Date", "date", "Audit", "Requested as-of date for the calculation."),
        ("dataset_generated_at", "Dataset Generated At", "datetime", "Audit", "Time the cached trend dataset was generated."),
        ("source", "Source", "string", "Audit", "Cached trend dataset and authoritative rolling-page source."),
    ]
]

PLAYER_TREND_ROLLING_FIELDS = {
    "actual_pa": ("Plate Appearances", "integer"),
    "actual_ab": ("At Bats", "integer"),
    "event_count": ("Pitch Events", "integer"),
    "batters_faced": ("Batters Faced", "integer"),
    "pitch_count": ("Pitch Count", "integer"),
    "batted_ball_count": ("Batted Balls", "integer"),
    "hard_hit_count": ("Hard-Hit Balls", "integer"),
    "barrel_count": ("Barrels", "integer"),
    "hits": ("Hits", "integer"),
    "doubles": ("Doubles", "integer"),
    "triples": ("Triples", "integer"),
    "walks": ("Walks", "integer"),
    "strikeouts": ("Strikeouts", "integer"),
    "home_runs": ("Home Runs", "integer"),
    "total_bases": ("Total Bases", "integer"),
    "swings": ("Swings", "integer"),
    "whiffs": ("Whiffs", "integer"),
    "batting_avg": ("Batting Average", "double"),
    "on_base_pct": ("On-Base Percentage", "double"),
    "slugging_pct": ("Slugging Percentage", "double"),
    "ops": ("OPS", "double"),
    "iso": ("ISO", "double"),
    "avg_exit_velocity": ("Average Exit Velocity", "double"),
    "max_exit_velocity": ("Maximum Exit Velocity", "double"),
    "avg_launch_angle": ("Average Launch Angle", "double"),
    "hard_hit_pct": ("Hard-Hit Rate", "double"),
    "barrel_pct": ("Barrel Rate", "double"),
    "k_pct": ("Strikeout Rate", "double"),
    "bb_pct": ("Walk Rate", "double"),
    "whiff_pct": ("Whiff Rate", "double"),
    "contact_pct": ("Contact Rate", "double"),
    "avg_velocity": ("Average Pitch Velocity", "double"),
    "avg_spin_rate": ("Average Spin Rate", "double"),
    "xwoba": ("xwOBA Allowed", "double"),
    "xba": ("xBA Allowed", "double"),
    "avg_horiz_break": ("Average Horizontal Break", "double"),
    "avg_vert_break": ("Average Vertical Break", "double"),
}
for field_name, (label, data_type) in PLAYER_TREND_ROLLING_FIELDS.items():
    PLAYER_TREND_FIELDS.extend([
        _runtime_field(
            f"window_{field_name}",
            f"Window {label}",
            data_type,
            "Rolling Window",
            "player_trend_snapshots",
            f"{label} from the requested player-ID rolling window.",
            freshness="cached_trend_snapshot",
        ),
        _runtime_field(
            f"baseline_{field_name}",
            f"Baseline {label}",
            data_type,
            "Rolling Baseline",
            "player_trend_snapshots",
            f"{label} from the authoritative comparison window.",
            freshness="cached_trend_snapshot",
        ),
    ])

PLAYER_TREND_CHANGE_FIELDS = {
    "batting_avg": "Batting Average",
    "on_base_pct": "On-Base Percentage",
    "slugging_pct": "Slugging Percentage",
    "ops": "OPS",
    "iso": "ISO",
    "avg_exit_velocity": "Average Exit Velocity",
    "max_exit_velocity": "Maximum Exit Velocity",
    "avg_launch_angle": "Average Launch Angle",
    "hard_hit_pct": "Hard-Hit Rate",
    "barrel_pct": "Barrel Rate",
    "k_pct": "Strikeout Rate",
    "bb_pct": "Walk Rate",
    "whiff_pct": "Whiff Rate",
    "contact_pct": "Contact Rate",
    "avg_velocity": "Average Pitch Velocity",
    "avg_spin_rate": "Average Spin Rate",
    "xwoba": "xwOBA Allowed",
    "xba": "xBA Allowed",
    "avg_horiz_break": "Average Horizontal Break",
    "avg_vert_break": "Average Vertical Break",
}
for metric_name, label in PLAYER_TREND_CHANGE_FIELDS.items():
    PLAYER_TREND_FIELDS.extend([
        _runtime_field(
            f"{metric_name}_change",
            f"{label} Change",
            "double",
            "Metric Changes",
            "player_trend_snapshots",
            f"Absolute change in {label.lower()} from baseline to window.",
            freshness="cached_trend_snapshot",
        ),
        _runtime_field(
            f"{metric_name}_change_pct",
            f"{label} Change %",
            "double",
            "Metric Changes",
            "player_trend_snapshots",
            f"Percentage change in {label.lower()} from baseline to window.",
            freshness="cached_trend_snapshot",
        ),
        _runtime_field(
            f"{metric_name}_direction",
            f"{label} Direction",
            "string",
            "Metric Changes",
            "player_trend_snapshots",
            f"Metric-aware improving, declining, or stable classification for {label.lower()}.",
            freshness="cached_trend_snapshot",
        ),
    ])

FIELD_CATALOG: Dict[str, List[Dict[str, Any]]] = {}
for key, config in REPORT_TYPES.items():
    if key == "all_active_hitters":
        FIELD_CATALOG[key] = deepcopy(HITTER_CURRENT_FIELDS)
    elif key == "all_active_pitchers":
        FIELD_CATALOG[key] = deepcopy(PITCHER_CURRENT_FIELDS)
    elif key == "players_lineup_history":
        FIELD_CATALOG[key] = deepcopy(LINEUP_HISTORY_FIELDS)
    elif key == "hitters_arsenal_splits":
        FIELD_CATALOG[key] = deepcopy(ARSENAL_SPLIT_FIELDS)
    elif key in DATASET_METRICS:
        allowed = set(DATASET_FIELD_NAMES[key])
        FIELD_CATALOG[key] = [
            deepcopy(field)
            for field in DATASET_FIELDS
            if field["name"] in allowed
        ]
        FIELD_CATALOG[key].extend([
            _dataset_field(
                field_name,
                label,
                "double",
                "Metrics",
                description=f"Registered {label.lower()} value from the daily report snapshot.",
                metric_key=metric_key,
            )
            for field_name, metric_key, label in DATASET_METRICS[key]
        ])
    elif key == "model_projection_games":
        FIELD_CATALOG[key] = deepcopy(MODEL_PROJECTION_GAME_FIELDS)
    elif key == "model_projection_players":
        FIELD_CATALOG[key] = deepcopy(MODEL_PROJECTION_PLAYER_FIELDS)
    elif key == "model_tracker_snapshots":
        FIELD_CATALOG[key] = deepcopy(MODEL_TRACKER_FIELDS)
    elif key == "competitive_batter_arsenal":
        FIELD_CATALOG[key] = deepcopy(COMPETITIVE_ARSENAL_FIELDS)
    elif key == "player_trends":
        FIELD_CATALOG[key] = deepcopy(PLAYER_TREND_FIELDS)
    elif config["base_object"] == "dashboard_players":
        FIELD_CATALOG[key] = deepcopy(CURRENT_PLAYER_FIELDS[:6])
        for field in FIELD_CATALOG[key]:
            field["source_object"] = "dashboard_players"
    else:
        FIELD_CATALOG[key] = []


def describe_report_type(report_type: str) -> Dict[str, Any]:
    if report_type not in REPORT_TYPES:
        raise ValueError(f"Unsupported report type: {report_type}")
    return {
        **deepcopy(REPORT_TYPES[report_type]),
        "api_name": report_type,
        "queryable": bool(REPORT_TYPES[report_type].get("queryable")),
        "fields": deepcopy(FIELD_CATALOG[report_type]),
    }


def list_report_types() -> List[Dict[str, Any]]:
    return [describe_report_type(name) for name in REPORT_TYPES]
