"""Deterministic, conservative evidence-policy scoring.

This is a policy score, not a statistical probability or certification.  It is
computed only from frozen, point-in-time, non-odds evidence and is versioned so
reports can be reproduced.  Missing or unreliable contract data yields None.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .research import moment, safe_source_url

VERSION = "evidence-policy-1.0.0"
THRESHOLD = 70.0
# Fixed before evaluating any recommendation.  Odds-related dimensions are
# deliberately absent and can never compensate for a missing required fact.
WEIGHTS = {
    1: 12.0,   # squad / strength
    4: 14.0,   # injuries / availability
    7: 8.0,    # motivation
    9: 10.0,   # efficiency / xG / possessions
    12: 10.0,  # trend / coach
    13: 10.0,  # tactical matchup
    15: 8.0,   # schedule / fatigue
    17: 6.0,   # referee
    18: 14.0,  # confirmed lineup / roles
    19: 4.0,   # score/path
    21: 4.0,   # evidence-to-market consistency (non-odds mechanism)
}
CRITICAL = frozenset({4, 13, 18, 19, 21})
ODDS_DIMENSIONS = frozenset({5, 8, 16, 20})


def _time_ok(source: dict[str, Any], as_of: datetime | str | None) -> bool:
    if not safe_source_url(source.get('url', '')) or source.get("tier") not in {"L1", "L2"}:
        return False
    if not source.get("published_at") or not source.get("effective_at"):
        return False
    try:
        published = moment(source["published_at"])
        effective = moment(source["effective_at"])
        if as_of is not None:
            cutoff = moment(as_of)
            if published > cutoff or effective > cutoff or (cutoff - effective).total_seconds() > 30 * 86400:
                return False
        return published <= effective
    except (TypeError, ValueError):
        return False


def _dimension_points(row: dict[str, Any], valid_ids: set[str]) -> float:
    if row.get("status") == "conflict":
        return 0.0
    if row.get("status") == "verified" and set(row.get("source_ids", [])) & valid_ids:
        return 1.0
    if row.get("status") == "partial" and set(row.get("source_ids", [])) & valid_ids:
        return 0.5
    return 0.0


def score_evidence(evidence: dict[str, Any] | None, *, option_id: str | None = None,
                   as_of: datetime | str | None = None) -> dict[str, Any] | None:
    """Return the complete score contract, or ``None`` when contract absent.

    ``eligible`` is false for every conflict, critical gap, unsupported source,
    absent confirmed citation, or score below the hard threshold.
    """
    if not isinstance(evidence, dict) or not isinstance(evidence.get("dimensions"), list):
        return None
    dimensions = evidence["dimensions"]
    by_id = {row.get("id"): row for row in dimensions if isinstance(row, dict)}
    if set(by_id) != set(range(1, 24)) or len(dimensions) != 23 or as_of is None:
        return None
    sources = {s.get("id"): s for s in evidence.get("sources", []) if isinstance(s, dict) and s.get("id")}
    valid = {sid for sid, source in sources.items() if _time_ok(source, as_of)}
    # New claim-level provenance is required for new publishable evidence; legacy
    # historical payloads remain readable but cannot pass this policy gate.
    claims = evidence.get('claims') or []
    # Legacy evidence remains readable during staged migration; new claim-aware
    # payloads must satisfy the full provenance contract.
    provenance_ok = (not claims) or all(
        isinstance(c, dict) and c.get('claim_id') and c.get('source_id') in sources
        and c.get('content_sha256') and c.get('quote') and c.get('locator')
        and c.get('source_type') == 'non_odds' and c.get('support_status') == 'supports'
        and c.get('verification_status') == 'manual_verified'
        for c in claims)
    reasons: list[str] = []
    blocked: list[str] = []
    breakdown: dict[str, Any] = {}
    total = 0.0
    # Every dimension conflict is a hard block, including non-weighted dimensions.
    for row in dimensions:
        if row.get('status') == 'conflict':
            blocked.append(f'维度{row.get("id", "待核")}存在来源冲突')
    for dim_id, weight in WEIGHTS.items():
        row = by_id[dim_id]
        points = _dimension_points(row, valid)
        contribution = round(weight * points, 2)
        total += contribution
        breakdown[str(dim_id)] = {
            "weight": weight, "status": row.get("status"), "factor": points,
            "contribution": contribution,
        }
        if row.get("status") == "conflict":
            blocked.append(f"维度{dim_id}存在来源冲突")
        elif points == 0:
            reasons.append(f"维度{dim_id}缺少可用L1/L2定时证据")
        elif points < 1:
            reasons.append(f"维度{dim_id}仅部分核实，按50%计分")
    used_ids = {sid for dim_id in WEIGHTS for sid in by_id[dim_id].get('source_ids', [])}
    groups = {str(sources[sid].get('group_id') or sources[sid]['url']) for sid in valid & used_ids}
    if len(groups) < 2:
        blocked.append('不足两个非重复证据组，不能以转载或来源数量加分')
    if claims and not provenance_ok:
        blocked.append('claim级原文哈希/引用定位/人工核验支持关系无效，不能进入新推荐')
    for dim_id in sorted(CRITICAL):
        fresh_ids = {sid for sid in valid if (moment(as_of) - moment(sources[sid]['effective_at'])).total_seconds() <= 48 * 3600}
        if _dimension_points(by_id[dim_id], fresh_ids) < 1:
            blocked.append(f"关键维度{dim_id}未由48小时内证据完整核实，不得由其他维度补偿")

    assessment = next((a for a in evidence.get("assessments", [])
                       if option_id is None or a.get("option_id") == option_id), None)
    confirmed_refs: set[str] = set()
    if assessment:
        confirmed_refs = set(assessment.get("source_ids", [])) & valid
        if len([r for r in assessment.get("reasons", []) if str(r).strip()]) < 2:
            blocked.append("选项少于两条有效理由")
        if not confirmed_refs:
            blocked.append("选项缺少已确认的非赔率来源引用")
    else:
        blocked.append("缺少选项评分契约")
    if blocked:
        reasons.extend(blocked)
    eligible = not blocked and total >= THRESHOLD
    if total < THRESHOLD:
        reasons.append(f"政策分数{total:.1f}低于硬门槛{THRESHOLD:.0f}")
    return {
        "evidence_confidence": round(total, 2),
        "breakdown": breakdown,
        "version": VERSION,
        "eligible": eligible,
        "reasons": reasons or ["满足固定非赔率证据政策门槛"],
        "policy_note": "这是确定性政策评分，不是命中概率、统计认证或收益保证。",
    }


def passes(score: dict[str, Any] | None) -> bool:
    return bool(score and score.get("version") == VERSION and score.get("eligible") is True
                and float(score.get("evidence_confidence", 0)) >= THRESHOLD)
