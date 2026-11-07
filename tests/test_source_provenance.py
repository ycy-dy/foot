"""Pure local tests; no network, database, credentials, or production artifacts."""
from copy import deepcopy
import hashlib
import os

import pytest

from foot_web.services.source_provenance import (
    MAX_TEXT_BYTES, ProvenanceError, SourceProvenanceStore, store,
)

T0 = "2026-11-07T08:00:00+00:00"
T1 = "2026-11-07T09:00:00+00:00"
T2 = "2026-11-07T10:00:00+00:00"
CONTEXT = {"as_of": T1, "match_id": "match-a", "option_id": "home", "dimension_id": 4}


@pytest.fixture
def sample(tmp_path):
    s = store(tmp_path / "provenance")
    text = "赛前报道：主力伤愈，已参加训练。其他内容。"
    snapshot = s.capture("https://sports.example.com/news/42", text, T0, "non_odds")
    quote = "主力伤愈，已参加训练"
    start = text.index(quote)
    claim = {"claim_id": "c1", "claim": "主力已经恢复训练", "source_id": snapshot["source_id"],
             "url": snapshot["url"], "content_sha256": snapshot["content_sha256"],
             "quote": quote, "locator": {"start": start, "end": start + len(quote)},
             "source_type": "non_odds", "support_status": "supports",
             "match_id": "match-a", "option_id": "home", "dimension_id": 4}
    return s, snapshot, claim


def receipts(s, claim):
    q = s.check_quote(claim, **CONTEXT)
    r = s.record_manual_review(q["receipt_id"], actor="admin:42", reviewed_at=T1)
    return {"quote_receipt_id": q["receipt_id"], "manual_review_receipt_id": r["receipt_id"]}


def test_capture_hash_literal_quote_and_review(sample):
    s, snapshot, claim = sample
    assert isinstance(s, SourceProvenanceStore)
    body = (s.root / "objects" / snapshot["content_sha256"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == snapshot["content_sha256"]
    ids = receipts(s, claim)
    result = s.verify_support(claim, **ids, **CONTEXT)
    assert result["verified"] is True
    assert result["actor"] == "admin:42"
    assert (s.root / "quotes" / ids["quote_receipt_id"]).is_file()
    assert (s.root / "reviews" / ids["manual_review_receipt_id"]).is_file()


def test_identical_capture_reused_without_overwrite(sample):
    s, snap, _ = sample
    path = s.root / "snapshots" / snap["source_id"]
    original = path.stat()
    again = s.capture(snap["url"], "赛前报道：主力伤愈，已参加训练。其他内容。", T0, "non_odds")
    assert again == snap
    assert path.stat().st_ino == original.st_ino
    assert path.stat().st_mtime_ns == original.st_mtime_ns
    assert path.stat().st_mode & 0o222 == 0


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://localhost/x", "http://127.0.0.1/x",
    "http://10.0.0.1/x", "http://[::1]/x", "http://169.254.169.254/x",
    "https://user:pass@example.com/x", "https://sports.example.com/../private",
    "https://sports.example.com/%2e%2e/private", "https://sports.example.com/%252e%252e/x",
    "https://sports.example.com/a\\b", "https://sports.example.com/a#frag",
    "https://sports.example.com:9999/a", "https://sports.example.com/\nx",
    "http://2130706433/x", "http://127.1/x", "https://host.internal/x",
    "https://sports.example.com/%00hidden", "https://sports.example.com/%0d%0ax",
])
def test_unsafe_urls_rejected(tmp_path, url):
    with pytest.raises(ProvenanceError):
        store(tmp_path).capture(url, "body", T0, "non_odds")


def test_maximum_is_utf8_bytes(tmp_path):
    s = store(tmp_path)
    s.capture("https://example.com/x", "x" * MAX_TEXT_BYTES, T0, "non_odds")
    with pytest.raises(ProvenanceError):
        s.capture("https://example.com/x", "x" * (MAX_TEXT_BYTES + 1), T0, "non_odds")
    with pytest.raises(ProvenanceError):
        s.capture("https://example.com/x", "中" * (MAX_TEXT_BYTES // 3 + 1), T0, "non_odds")


@pytest.mark.parametrize("field,value", [
    ("quote", "原文没有这句话"), ("locator", {"start": -1, "end": 4}),
    ("locator", {"start": True, "end": 8}), ("locator", {"start": 0, "end": 99999}),
    ("source_id", "../../outside"), ("source_id", "a" * 64),
    ("content_sha256", "b" * 64), ("url", "https://example.com/unrelated"),
    ("match_id", "other-match"), ("option_id", "away"), ("dimension_id", 13),
    ("source_type", "odds"), ("support_status", "unrelated"),
])
def test_bad_quote_source_or_binding_cannot_issue_receipt(sample, field, value):
    s, _, original = sample
    claim = deepcopy(original)
    claim[field] = value
    with pytest.raises(ProvenanceError):
        s.check_quote(claim, **CONTEXT)
    assert list((s.root / "quotes").iterdir()) == []


def test_future_source_and_naive_time_rejected(sample):
    s, _, claim = sample
    with pytest.raises(ProvenanceError):
        s.check_quote(claim, **{**CONTEXT, "as_of": "2026-11-06T00:00:00Z"})
    with pytest.raises(ProvenanceError):
        s.capture("https://example.com/x", "text", "2026-11-07T09:00:00", "non_odds")


def test_odds_snapshot_and_odds_dimensions_rejected(sample):
    s, _, claim = sample
    snap = s.capture(claim["url"], claim["quote"], T0, "odds")
    claim.update(source_id=snap["source_id"], content_sha256=snap["content_sha256"],
                 locator={"start": 0, "end": len(claim["quote"])})
    with pytest.raises(ProvenanceError):
        s.check_quote(claim, **CONTEXT)
    for dim in (5, 8, 16, 20):
        claim["dimension_id"] = dim
        with pytest.raises(ProvenanceError):
            s.check_quote(claim, **{**CONTEXT, "dimension_id": dim})


def test_self_assertion_without_real_receipts_is_not_verification(sample):
    s, _, claim = sample
    claim.update(verification_status="manual_verified", manual_verified=True,
                 actor="admin", reviewed_at=T1,
                 manual_review_receipt={"decision": "supports", "actor": "admin"})
    assert s.verify_support(claim, **CONTEXT)["verified"] is False
    q = s.check_quote(claim, **CONTEXT)
    assert s.verify_support(claim, quote_receipt_id=q["receipt_id"], **CONTEXT)["verified"] is False
    assert s.verify_support(claim, quote_receipt_id=q["receipt_id"],
                            manual_review_receipt_id="a" * 64, **CONTEXT)["verified"] is False


@pytest.mark.parametrize("field,value", [("claim", "不同语义"), ("claim_id", "c2"),
                                          ("match_id", "b"), ("option_id", "away"),
                                          ("dimension_id", 13)])
def test_receipts_cannot_be_reused_for_different_claim(sample, field, value):
    s, _, claim = sample
    ids = receipts(s, claim)
    claim[field] = value
    context = {**CONTEXT}
    if field in {"match_id", "option_id", "dimension_id"}:
        context[field] = value
    assert s.verify_support(claim, **ids, **context)["verified"] is False


def test_receipt_future_and_human_action_parameters(sample):
    s, _, claim = sample
    q = s.check_quote(claim, **CONTEXT)
    for actor in (None, "", " "):
        with pytest.raises(ProvenanceError):
            s.record_manual_review(q["receipt_id"], actor=actor, reviewed_at=T1)
    with pytest.raises(ProvenanceError):
        s.record_manual_review(q["receipt_id"], actor="admin", reviewed_at=T0)
    with pytest.raises(ProvenanceError):
        s.record_manual_review(q["receipt_id"], actor="admin", reviewed_at=None)
    r = s.record_manual_review(q["receipt_id"], actor="admin", reviewed_at=T2)
    assert not s.verify_support(claim, quote_receipt_id=q["receipt_id"],
                                manual_review_receipt_id=r["receipt_id"], **CONTEXT)["verified"]


@pytest.mark.parametrize("kind", ["objects", "snapshots", "quotes", "reviews"])
def test_tamper_detected_on_every_artifact(sample, kind):
    s, snap, claim = sample
    ids = receipts(s, claim)
    artifact_id = {"objects": snap["content_sha256"], "snapshots": snap["source_id"],
                   "quotes": ids["quote_receipt_id"], "reviews": ids["manual_review_receipt_id"]}[kind]
    path = s.root / kind / artifact_id
    os.chmod(path, 0o600)  # Simulate an attacker with filesystem write privileges.
    path.write_bytes(b"tampered")
    assert s.verify_support(claim, **ids, **CONTEXT)["verified"] is False
    if kind == "objects":
        with pytest.raises(ProvenanceError):
            s.capture(snap["url"], "赛前报道：主力伤愈，已参加训练。其他内容。", T0, "non_odds")
        assert path.read_bytes() == b"tampered"


def test_symlink_store_and_artifact_rejected(sample, tmp_path):
    s, snap, claim = sample
    link = tmp_path / "alias"
    link.symlink_to(s.root, target_is_directory=True)
    with pytest.raises(ProvenanceError):
        store(link)
    object_path = s.root / "objects" / snap["content_sha256"]
    outside = tmp_path / "outside"
    outside.write_bytes(object_path.read_bytes())
    object_path.unlink()
    object_path.symlink_to(outside)
    with pytest.raises(ProvenanceError):
        s.check_quote(claim, **CONTEXT)


def test_literal_quote_alone_does_not_claim_semantic_entailment(sample):
    s, _, claim = sample
    claim["claim"] = "该引用在语义上不支持这条任意断言"
    quote = s.check_quote(claim, **CONTEXT)
    assert quote["receipt_id"]
    assert not s.verify_support(claim, quote_receipt_id=quote["receipt_id"], **CONTEXT)["verified"]
