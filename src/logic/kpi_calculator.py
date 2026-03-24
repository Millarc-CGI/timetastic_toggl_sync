"""
KPI helpers for project statistics rows (report-project-stats).

Per-user shares are computed from aggregates over user_email so multi-row users
are not double-counted in denominators.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# Keys written onto each record for XLSX export
HOURS_SHARE_PCT = "hours_share_pct"
OVERTIME_SHARE_PCT = "overtime_share_pct"

# Lines appended under the sheet table — XLSX export (English)
KPI_LEGEND_LINES = (
    "KPI — Hours share %: this user's hours on the project as a share of the team's total hours in the report window.",
    "KPI — Overtime share %: this user's overtime (normal + weekend) as a share of the team's total overtime on this project.",
    "TOTAL row: hours and overtime are summed per distinct user; the % columns show 100% (shares add up to 100%).",
    "TEAM AVG row: per-user averages; headcount is users with total_hours > 0.",
)


def aggregate_by_user(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Sum hours and overtime per user_email.

    Each value has: user_email, user_name (best known), total_hours,
    normal_overtime, weekend_overtime, total_overtime.
    """
    buckets: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        email = (row.get("user_email") or "").strip().lower()
        if not email:
            continue
        if email not in buckets:
            buckets[email] = {
                "user_email": email,
                "user_name": (row.get("user_name") or email).strip() or email,
                "total_hours": 0.0,
                "normal_overtime": 0.0,
                "weekend_overtime": 0.0,
            }

        b = buckets[email]
        b["total_hours"] += float(row.get("total_hours") or 0.0)
        b["normal_overtime"] += float(row.get("normal_overtime") or 0.0)
        b["weekend_overtime"] += float(row.get("weekend_overtime") or 0.0)

    for b in buckets.values():
        b["total_overtime"] = b["normal_overtime"] + b["weekend_overtime"]

    return buckets


def compute_team_totals(aggregates: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Team-level numbers for TOTAL / TEAM AVG rows.

    n_users counts distinct users with total_hours > 0.
    """
    team_total_hours = sum(u["total_hours"] for u in aggregates.values())
    team_normal_ot = sum(u["normal_overtime"] for u in aggregates.values())
    team_weekend_ot = sum(u["weekend_overtime"] for u in aggregates.values())
    team_total_ot = team_normal_ot + team_weekend_ot
    n_users = sum(1 for u in aggregates.values() if u["total_hours"] > 0.0)

    return {
        "team_total_hours": team_total_hours,
        "team_normal_overtime": team_normal_ot,
        "team_weekend_overtime": team_weekend_ot,
        "team_total_overtime": team_total_ot,
        "n_users": n_users,
        "avg_hours_per_user": team_total_hours / n_users if n_users else 0.0,
        "avg_normal_ot_per_user": team_normal_ot / n_users if n_users else 0.0,
        "avg_weekend_ot_per_user": team_weekend_ot / n_users if n_users else 0.0,
        "avg_total_ot_per_user": team_total_ot / n_users if n_users else 0.0,
    }


def _user_shares(
    aggregates: Dict[str, Dict[str, Any]], team: Dict[str, Any]
) -> Dict[str, Tuple[float, float]]:
    """Map user_email -> (hours_share_pct, overtime_share_pct)."""
    th = team["team_total_hours"]
    tot = team["team_total_overtime"]
    out: Dict[str, Tuple[float, float]] = {}
    for email, u in aggregates.items():
        h_pct = (u["total_hours"] / th * 100.0) if th > 0 else 0.0
        u_ot = u["total_overtime"]
        ot_pct = (u_ot / tot * 100.0) if tot > 0 else 0.0
        out[email] = (h_pct, ot_pct)
    return out


def enrich_project_stat_rows(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Attach HOURS_SHARE_PCT and OVERTIME_SHARE_PCT to each row (from that user's aggregate).

    Returns enriched rows and a team summary dict for export (TOTAL / TEAM AVG).
    """
    if not rows:
        return [], {}

    aggregates = aggregate_by_user(rows)
    team = compute_team_totals(aggregates)
    shares = _user_shares(aggregates, team)

    enriched: List[Dict[str, Any]] = []
    for row in rows:
        email = (row.get("user_email") or "").strip().lower()
        h_pct, ot_pct = shares.get(email, (0.0, 0.0))
        new_row = dict(row)
        new_row[HOURS_SHARE_PCT] = h_pct
        new_row[OVERTIME_SHARE_PCT] = ot_pct
        enriched.append(new_row)

    return enriched, team
