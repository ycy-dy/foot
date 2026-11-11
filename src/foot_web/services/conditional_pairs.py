"""Explicit low-confidence pair state, never a fabricated evidence certification."""
REVISION = '2026-11-09-required-pairs-01'
STATUS = 'conditional_low_confidence'
WARNING = '低置信度条件推荐 · 高风险 · 未通过70分证据及人工来源门槛'


def enabled(manifest):
    return manifest.get('conditional_pair_required') is True and manifest.get('spec_revision') == REVISION


def marked(leg):
    return leg.get('recommendation_status') == STATUS


def valid(leg):
    return (marked(leg) and leg.get('conditional_policy_revision') == REVISION
            and leg.get('confidence') == WARNING and bool(leg.get('evidence_gaps'))
            and leg.get('model_probability') is None and leg.get('EV') is None
            and leg.get('price_advantage') == 'unproven'
            and len([reason for reason in leg.get('reasons', []) if str(reason).strip()]) >= 2
            and bool(leg.get('risk')) and bool(leg.get('withdraw_if')))
