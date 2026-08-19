# MyDashboard Chrome reconciliation and Query Studio

Issue #1178 implements the first protected Query Studio slice on top of the
owner-only identity, capability, settings, and feature-flag contracts merged in
PR #1177. It does not revive the older unrouted `MyDashboardWorkbenchPage.jsx`
and it does not add a second reporting backend.

## Recovered design reference

The audit recovered the exact prior visual artifacts rather than reconstructing
the concept from memory:

- `AI-powered MLB login page design.png`
- `MLBGPT AI-powered dashboard mockup.png`
- `Liquid chrome UI concept design.png`

They establish a pearl, silver, graphite, and restrained-purple visual language,
with a split authentication composition, liquid-chrome forms, glass surfaces,
and a dense analytical workspace. They are design references only. The shipped
implementation is repository-owned React and inline component styling; no
browser-injected CSS or JavaScript is used.

The reference images also contain unsupported controls and claims. Partner logos,
social login, password recovery, remember-me duration, security guarantees, and
decorative usage metrics were intentionally excluded because the current server
does not provide those contracts. The real screen retains only password-backed
sign-in/registration and truthful reporting capabilities.

`/my-dashboard` continues to resolve to
`MyDashboardReportBuilderPage.jsx`. That component owns both the signed-out
landing state and the authenticated workspace. The current Report Builder,
saved-report shelf, rename controls, report overlay, and existing persistence
formats remain the routed architecture. Franklin Gothic is used for headings,
navigation, tabs, and buttons; Century Gothic is used for copy, controls, labels,
and result data. Responsive breakpoints collapse the split landing and workspace
columns without substituting a separate mobile page.

The landing and authenticated workspace also expose Light, Dark, and System
display modes. System follows the browser's live operating-system preference.
The selected display preference is stored locally under a presentation-only key;
it is never used for identity, capability, report, or authorization decisions.

## Query Studio authorization

The Query Studio panel appears only when the authenticated server response
contains `workbench.advanced`. Its private endpoints enforce authorization again:

| Endpoint | Required capability |
| --- | --- |
| `GET /my-dashboard/query-studio/metadata` | `workbench.advanced` |
| `POST /my-dashboard/query-studio/preview` | `workbench.advanced` |
| `POST /my-dashboard/query-studio/execute` | `workbench.advanced` and `workbench.execute` |

All endpoints also require the default-off `workbench_query_enabled` feature flag
to be enabled for the authenticated profile. The flag does not grant either
capability. Missing authentication returns 401; missing capabilities or a locked
flag returns 403. Client role, email, username, plan, local storage, or submitted
capability fields do not authorize the feature.

## Constrained language

Version `mlbgpt_query_v1` accepts exactly one bounded selection:

```text
SELECT field [, field ...]
FROM logical_object
[WHERE field operator value [AND ...]]
[ORDER BY sortable_field [ASC|DESC]]
LIMIT 1-250
```

The current vertical slice supports registered comparison and null operators
that already exist in each field's server-owned catalog. Literal values are
converted to the registered field type. Quoted strings, ISO dates/datetimes,
numbers, integers/IDs, and booleans are normalized into structured filter values.

The parser rejects wildcards and expressions, unregistered or non-queryable
objects, unknown fields, unsupported field operators, comments, semicolons,
multiple statements, joins, unions, subqueries/common-table expressions,
grouping, offsets, `OR`, physical schema names, and every DDL or DML verb.
`LIMIT` is mandatory and cannot exceed 250.

The authored statement is never sent to SQLAlchemy or a database driver. It is
converted to a structured plan and dispatched to the existing
`query_player_report`, `query_related_report`, `query_projection_report`, or
`query_player_trends` service. Those services retain
the existing allowlisted fields/operators, filtering-before-pagination,
deterministic sorting, freshness/provenance, and report-population behavior.
Metadata exposes logical objects only and omits physical base/source details.

Model Projection statements use an equality `game_date` filter to select the
shared daily artifact; when omitted, the MLB business date is used. Player
Trends statements must provide equality filters for `player_type`,
`selected_window_days`, and `metric`. `comparison_baseline` defaults to
`previous_n_days`, and `freshness_date` defaults to the MLB business date.
These controls are converted into the existing Player Trends runtime
configuration before the remaining allowlisted filters are applied.

## Saved results and deferred language features

Executed results can be exported for the current page and saved as the existing
`workbench_view` item type. The schema-v4 payload stores the validated plan,
selected columns, original statement, and result snapshot. Reopening restores
both the saved report snapshot and the Query Studio statement without changing
folder membership, rollups, or other report contents.

Aggregates, grouping, registered relationships, as-of date syntax, natural
language proposal generation, and richer cost controls remain follow-up work.
They must extend this same parser-to-structured-report boundary and pass server
validation; they must not introduce raw SQL execution.
