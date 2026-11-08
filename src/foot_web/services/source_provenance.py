"""Local provenance artifacts, NOT an attestation that a URL was fetched.

Only trusted application capture calls and authenticated human-action calls may
invoke the writers. AI payload flags are never authority. The caller owns actor
authentication and protects the store directory; a process with arbitrary write
access to that directory is outside this module's trust boundary. No network,
DNS, database, environment, or production gate integration is performed here.
Offsets are Python Unicode character offsets, [start, end), not UTF-8 bytes.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

MAX_TEXT_BYTES = 2 * 1024 * 1024
ODDS_DIMENSIONS = frozenset({5, 8, 16, 20})
_ID = re.compile(r"^[0-9a-f]{64}$")


class ProvenanceError(ValueError):
    """An artifact, citation, binding, or trusted action is invalid."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _time(value: datetime | str) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone required")
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProvenanceError("invalid timezone-aware timestamp") from exc


def _label(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ProvenanceError(f"invalid {name}")
    return value


def _safe_url(value: str) -> str:
    _label(value, "url")
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme not in {"http", "https"} or not host or parts.username is not None
                or parts.password is not None or parts.fragment or parts.port not in {None, 80, 443}
                or any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value
                or "%" in parts.netloc):
            raise ValueError()
        host = host.rstrip(".").lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ("." not in host or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
                    or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x)
                               for x in host.split("."))
                    or all(x.isdigit() for x in host.split("."))):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
        path = parts.path
        for _ in range(8):
            decoded = unquote(path)
            if decoded == path:
                break
            path = decoded
        if ("%" in path or "\\" in path or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or any(x in {".", ".."} for x in path.split("/"))):
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ProvenanceError("unsafe public source URL") from exc
    return value


class SourceProvenanceStore:
    """Append-only local UTF-8 content and content-addressed receipt store."""

    def __init__(self, root: str | Path):
        root = Path(root).absolute()
        # Reject symlinked ancestors as well as symlinked storage subdirectories.
        for part in (root, *root.parents):
            if part.is_symlink():
                raise ProvenanceError("symlink store path")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        for name in ("objects", "snapshots", "quotes", "reviews"):
            directory = root / name
            if directory.is_symlink():
                raise ProvenanceError("symlink store directory")
            directory.mkdir(exist_ok=True)

    def _path(self, kind: str, artifact_id: str) -> Path:
        if not isinstance(artifact_id, str) or not _ID.fullmatch(artifact_id):
            raise ProvenanceError("invalid artifact ID")
        directory = self.root / kind
        if directory.is_symlink() or self.root.is_symlink():
            raise ProvenanceError("symlink store directory")
        return directory / artifact_id

    def _read(self, kind: str, artifact_id: str) -> bytes:
        path = self._path(kind, artifact_id)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                import stat
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ProvenanceError("not a regular artifact")
                data = stream.read(MAX_TEXT_BYTES * 2 + 65537)
            if len(data) > MAX_TEXT_BYTES * 2 + 65536 or _digest(data) != artifact_id:
                raise ProvenanceError("artifact hash mismatch")
            return data
        except OSError as exc:
            raise ProvenanceError("missing or unsafe artifact") from exc

    def _put(self, kind: str, data: bytes) -> str:
        artifact_id = _digest(data)
        path = self._path(kind, artifact_id)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        except FileExistsError:
            # Identical content can be reused, but existing bytes are never overwritten.
            if self._read(kind, artifact_id) != data:
                raise ProvenanceError("existing artifact differs")
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        return artifact_id

    def _record(self, kind: str, artifact_id: str) -> dict[str, Any]:
        try:
            value = json.loads(self._read(kind, artifact_id))
            if not isinstance(value, dict) or value.get("version") != 1 or value.get("kind") != kind:
                raise ProvenanceError("invalid artifact schema")
            return value
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProvenanceError("invalid artifact JSON") from exc

    def capture(self, url: str, text: str, retrieved_at: datetime | str,
                source_type: str) -> dict[str, Any]:
        """Persist trusted caller-supplied text; does not fetch or authenticate URL content."""
        _safe_url(url)
        if not isinstance(text, str) or not text:
            raise ProvenanceError("nonempty source text required")
        data = text.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            raise ProvenanceError("source text exceeds 2 MiB")
        if source_type not in {"non_odds", "odds"}:
            raise ProvenanceError("invalid source type")
        timestamp = _time(retrieved_at).isoformat()
        content_hash = self._put("objects", data)
        record = {"version": 1, "kind": "snapshots", "url": url,
                  "retrieved_at": timestamp, "source_type": source_type,
                  "content_sha256": content_hash, "text_bytes": len(data)}
        source_id = self._put("snapshots", _json(record))
        return {**record, "source_id": source_id}

    def _binding(self, claim: dict[str, Any], *, as_of: datetime | str,
                 match_id: str, option_id: str, dimension_id: int) -> dict[str, Any]:
        if not isinstance(claim, dict):
            raise ProvenanceError("claim must be an object")
        cutoff = _time(as_of)
        for key, expected in (("match_id", match_id), ("option_id", option_id)):
            _label(expected, key)
            if claim.get(key) != expected:
                raise ProvenanceError(f"unrelated {key}")
        if (type(dimension_id) is not int or not 1 <= dimension_id <= 23
                or dimension_id in ODDS_DIMENSIONS or type(claim.get("dimension_id")) is not int
                or claim.get("dimension_id") != dimension_id):
            raise ProvenanceError("unrelated or odds dimension")
        source = self._record("snapshots", claim.get("source_id"))
        if _time(source["retrieved_at"]) > cutoff:
            raise ProvenanceError("future source")
        _safe_url(source["url"])
        if (source["source_type"] != "non_odds" or claim.get("source_type") != "non_odds"
                or claim.get("support_status") != "supports"):
            raise ProvenanceError("non-odds supporting evidence required")
        if claim.get("url") != source["url"] or claim.get("content_sha256") != source["content_sha256"]:
            raise ProvenanceError("source URL/hash mismatch")
        body = self._read("objects", source["content_sha256"]).decode("utf-8")
        quote = _label(claim.get("quote"), "quote")
        locator = claim.get("locator")
        if not isinstance(locator, dict) or set(locator) != {"start", "end"}:
            raise ProvenanceError("exact start/end locator required")
        start, end = locator["start"], locator["end"]
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body)
                or body[start:end] != quote):
            raise ProvenanceError("quote is not the located source substring")
        # Only these semantic fields are authoritative; self-asserted flags are discarded.
        binding = {"claim_id": _label(claim.get("claim_id"), "claim_id"),
                "claim": _label(claim.get("claim"), "claim"),
                "source_id": claim["source_id"], "url": source["url"],
                "content_sha256": source["content_sha256"], "quote": quote,
                "locator": {"start": start, "end": end}, "source_type": "non_odds",
                "support_status": "supports", "match_id": match_id,
                "option_id": option_id, "dimension_id": dimension_id}
        if claim.get('task_id'):
            binding['task_id'] = _label(claim['task_id'], 'task_id')
        return binding

    def check_quote(self, claim: dict[str, Any], *, as_of: datetime | str,
                    match_id: str, option_id: str, dimension_id: int) -> dict[str, Any]:
        """Check literal citation and binding, NOT semantic entailment; persist receipt."""
        binding = self._binding(claim, as_of=as_of, match_id=match_id,
                                option_id=option_id, dimension_id=dimension_id)
        record = {"version": 1, "kind": "quotes", "binding": binding,
                  "binding_sha256": _digest(_json(binding)), "as_of": _time(as_of).isoformat()}
        receipt_id = self._put("quotes", _json(record))
        return {**record, "receipt_id": receipt_id}

    def record_manual_review(self, quote_receipt_id: str, *, actor: str,
                             reviewed_at: datetime | str) -> dict[str, Any]:
        """Trusted human action asserts support for this EXACT claim/quote/binding.

        Caller must authenticate/authorize actor outside AI payload processing.
        Merely passing AI-provided actor/time here does not authenticate a human.
        """
        actor = _label(actor, "human actor")
        quote = self._record("quotes", quote_receipt_id)
        timestamp = _time(reviewed_at)
        if timestamp < _time(quote["as_of"]):
            raise ProvenanceError("review precedes quote check")
        binding = quote["binding"]
        # Revalidate original snapshot/quote, including mutations since quote creation.
        current = self._binding(binding, as_of=timestamp, match_id=binding["match_id"],
                                option_id=binding["option_id"], dimension_id=binding["dimension_id"])
        if _digest(_json(current)) != quote["binding_sha256"]:
            raise ProvenanceError("quote binding changed")
        record = {"version": 1, "kind": "reviews", "quote_receipt_id": quote_receipt_id,
                  "binding_sha256": quote["binding_sha256"], "actor": actor,
                  "reviewed_at": timestamp.isoformat(), "decision": "supports"}
        receipt_id = self._put("reviews", _json(record))
        return {**record, "receipt_id": receipt_id}

    def verify_support(self, claim: dict[str, Any], *, quote_receipt_id: str | None = None,
                       manual_review_receipt_id: str | None = None,
                       as_of: datetime | str, match_id: str, option_id: str,
                       dimension_id: int) -> dict[str, Any]:
        """Fail closed: require both on-disk receipts and recheck every bound artifact."""
        try:
            binding = self._binding(claim, as_of=as_of, match_id=match_id,
                                    option_id=option_id, dimension_id=dimension_id)
            quote = self._record("quotes", quote_receipt_id)
            review = self._record("reviews", manual_review_receipt_id)
            digest = _digest(_json(binding))
            if (quote["binding"] != binding or quote["binding_sha256"] != digest
                    or review["binding_sha256"] != digest
                    or review["quote_receipt_id"] != quote_receipt_id
                    or review["decision"] != "supports"):
                raise ProvenanceError("receipt binding mismatch")
            _label(review["actor"], "human actor")
            if not _time(quote["as_of"]) <= _time(review["reviewed_at"]) <= _time(as_of):
                raise ProvenanceError("future or out-of-order receipt")
            return {"verified": True, "binding_sha256": digest,
                    "quote_receipt_id": quote_receipt_id,
                    "manual_review_receipt_id": manual_review_receipt_id,
                    "actor": review["actor"], "reviewed_at": review["reviewed_at"]}
        except (ProvenanceError, KeyError, TypeError, UnicodeError) as exc:
            return {"verified": False, "reason": str(exc)}


def store(root: str | Path) -> SourceProvenanceStore:
    """Convenience constructor; never enables a runtime recommendation gate."""
    return SourceProvenanceStore(root)
