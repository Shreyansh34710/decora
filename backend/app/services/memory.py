import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from app.core.schemas import Alternative


_TOPIC_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "the", "to", "use", "using", "with", "we",
    "choose", "select", "adopt", "implement", "support", "enable", "allow", "accept",
    "approve", "proposal", "decision", "option", "approach", "system", "service",
    "project", "primary", "database", "storage", "feature", "solution",
}
_POSITIVE_DIRECTIONS = {"use", "adopt", "select", "choose", "enable", "allow", "accept", "approve", "keep", "retain"}
_NEGATIVE_DIRECTIONS = {"reject", "avoid", "decline", "prohibit", "disable", "remove", "deprecate", "disallow", "ban"}


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    proposal_key TEXT NOT NULL,
    proposal TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'rejected', 'unresolved', 'contested')),
    outcome_basis TEXT NOT NULL,
    summary TEXT,
    source_title TEXT NOT NULL,
    source_reference TEXT,
    source_repository TEXT,
    evidence_json TEXT NOT NULL,
    outcome_evidence_json TEXT NOT NULL,
    rejection_reasons_json TEXT NOT NULL,
    rejection_reasons_text TEXT NOT NULL,
    history_json TEXT NOT NULL,
    source_timestamps_json TEXT NOT NULL,
    verified INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source_key, proposal_key)
)
"""
_CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_decisions_created_at ON decisions(created_at DESC)"
_SCHEMA = _CREATE_TABLE + ";\n" + _CREATE_INDEX + ";"


class DecisionMemory:
    """Small SQLite store for extracted decisions and their source evidence."""

    def __init__(self, db_path: Optional[str] = None):
        configured = db_path if db_path is not None else os.getenv("DECORA_DB_PATH")
        if configured:
            path = Path(configured).expanduser()
            self.db_path = path if path.is_absolute() else Path.cwd() / path
        else:
            backend_dir = Path(__file__).resolve().parents[2]
            self.db_path = backend_dir / "data" / "decora.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self):
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'decisions'"
            ).fetchone()
            if not existing:
                connection.executescript(_SCHEMA)
                return

            current_columns = {row["name"] for row in connection.execute(
                "PRAGMA table_info(decisions)").fetchall()}
            needs_status_migration = "'contested'" not in (existing["sql"] or "").lower()
            needs_repository_column = "source_repository" not in current_columns
            if needs_status_migration or needs_repository_column:
                # Upgrade old constraints/columns without losing saved rows.
                connection.execute("DROP INDEX IF EXISTS idx_decisions_created_at")
                connection.execute("ALTER TABLE decisions RENAME TO decisions_phase3")
                connection.execute(_CREATE_TABLE)
                columns = [
                    "id", "source_key", "proposal_key", "proposal", "status",
                    "outcome_basis", "summary", "source_title", "source_reference",
                    "source_repository", "evidence_json", "outcome_evidence_json",
                    "rejection_reasons_json", "rejection_reasons_text", "history_json",
                    "source_timestamps_json", "verified", "payload_json", "created_at",
                    "updated_at",
                ]
                old_columns = {row["name"] for row in connection.execute(
                    "PRAGMA table_info(decisions_phase3)").fetchall()}
                select_columns = [column if column in old_columns else "NULL"
                                  for column in columns]
                connection.execute(
                    "INSERT INTO decisions ({}) SELECT {} FROM decisions_phase3".format(
                        ", ".join(columns), ", ".join(select_columns)))
                connection.execute("DROP TABLE decisions_phase3")
            connection.execute(_CREATE_INDEX)

    @staticmethod
    def _proposal_key(proposal: str) -> str:
        return " ".join(proposal.casefold().split())

    @staticmethod
    def _topic_tokens(proposal: str) -> set:
        return {
            token for token in re.findall(r"[a-z0-9]+", proposal.casefold())
            if token not in _TOPIC_STOPWORDS and len(token) > 1
        }

    @staticmethod
    def _direction(proposal: str) -> Optional[str]:
        tokens = set(re.findall(r"[a-z0-9]+", proposal.casefold()))
        negative = bool(tokens & _NEGATIVE_DIRECTIONS) or bool(
            re.search(r"\b(?:do|does|did|will|should|must)\s+not\s+(?:use|adopt|allow|accept)\b",
                      proposal.casefold()))
        if negative:
            return "negative"
        positive = bool(tokens & _POSITIVE_DIRECTIONS)
        if positive:
            return "positive"
        return None

    @classmethod
    def _related_score(cls, first: str, second: str) -> float:
        first_tokens = cls._topic_tokens(first)
        second_tokens = cls._topic_tokens(second)
        if not first_tokens or not second_tokens:
            return 0.0
        return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)

    @classmethod
    def _conflict_reasons(cls, current: dict, historical: dict) -> List[str]:
        reasons = []
        current_status = current.get("status")
        historical_status = historical.get("status")
        decisive = {"accepted", "rejected", "contested"}
        if (current_status in decisive and historical_status in decisive
                and current_status != historical_status):
            reasons.append("the stored and new outcomes differ")
        current_direction = cls._direction(current.get("proposal", ""))
        historical_direction = cls._direction(historical.get("proposal", ""))
        if (current_direction and historical_direction
                and current_direction != historical_direction):
            reasons.append("the proposal directions differ")
        return reasons

    @staticmethod
    def _source_key(title: str, reference: Optional[str], source_text: str) -> str:
        reference = reference.strip() if reference and reference.strip() else None
        identity = (["reference", reference.strip()] if reference
                    else ["content", title.strip(), source_text])
        data = json.dumps(
            identity,
            ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    def _payload(decision: Alternative) -> dict:
        return {
            "proposal": decision.proposal,
            "status": decision.status,
            "reason": decision.reason,
            "outcome_basis": decision.outcome_basis,
            "evidence": [item.model_dump(mode="json") for item in decision.evidence],
            "outcome_evidence": [item.model_dump(mode="json") for item in decision.outcome_evidence],
            "rejection_reasons": [item.model_dump(mode="json") for item in decision.rejection_reasons],
            "history": decision.history,
            "verified": decision.verified,
        }

    def save(self, title: str, source_text: str, decisions: List[Alternative],
             source_reference: Optional[str] = None,
             source_repository: Optional[str] = None) -> dict:
        source_title = title.strip() or "Untitled discussion"
        source_reference = source_reference.strip() if source_reference else None
        source_repository = source_repository.strip() if source_repository else None
        source_key = self._source_key(source_title, source_reference, source_text)
        persisted_ids = []
        conflicts = []

        with self._connection() as connection:
            for decision in decisions:
                proposal_key = self._proposal_key(decision.proposal)
                payload = self._payload(decision)
                payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                existing = connection.execute(
                    "SELECT id, payload_json, source_repository FROM decisions WHERE source_key = ? AND proposal_key = ?",
                    (source_key, proposal_key),
                ).fetchone()
                if existing:
                    if (existing["payload_json"] == payload_json
                            and existing["source_repository"] == source_repository):
                        persisted_ids.append(existing["id"])
                    else:
                        # Keep the original record intact and surface the conflict.
                        conflicts.append(decision.proposal)
                    continue

                record_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL, "decora:{}:{}".format(source_key, proposal_key)))
                evidence_json = json.dumps(
                    [item.model_dump(mode="json") for item in decision.evidence],
                    ensure_ascii=False,
                )
                outcome_json = json.dumps(
                    [item.model_dump(mode="json") for item in decision.outcome_evidence],
                    ensure_ascii=False,
                )
                reasons_json = json.dumps(
                    [item.model_dump(mode="json") for item in decision.rejection_reasons],
                    ensure_ascii=False,
                )
                reasons_text = "\n".join(item.text for item in decision.rejection_reasons)
                timestamp_values = []
                evidence_groups = [decision.evidence, decision.outcome_evidence]
                evidence_groups.extend(reason.evidence for reason in decision.rejection_reasons)
                for group in evidence_groups:
                    for evidence in group:
                        if evidence.timestamp and evidence.timestamp not in timestamp_values:
                            timestamp_values.append(evidence.timestamp)
                connection.execute(
                    """INSERT INTO decisions (
                        id, source_key, proposal_key, proposal, status, outcome_basis,
                        summary, source_title, source_reference, source_repository, evidence_json,
                        outcome_evidence_json, rejection_reasons_json,
                        rejection_reasons_text, history_json,
                        source_timestamps_json, verified, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, source_key, proposal_key, decision.proposal, decision.status,
                     decision.outcome_basis, decision.reason, source_title, source_reference,
                     source_repository, evidence_json, outcome_json, reasons_json, reasons_text,
                     json.dumps(decision.history, ensure_ascii=False),
                     json.dumps(timestamp_values, ensure_ascii=False), int(decision.verified),
                     payload_json),
                )
                persisted_ids.append(record_id)

        return {
            "decision_ids": persisted_ids,
            "conflicts": conflicts,
            "persisted": not conflicts,
        }

    @staticmethod
    def _to_dict(row):
        return {
            "id": row["id"],
            "proposal": row["proposal"],
            "status": row["status"],
            "reason": row["summary"],
            "outcome_basis": row["outcome_basis"],
            "evidence": json.loads(row["evidence_json"]),
            "outcome_evidence": json.loads(row["outcome_evidence_json"]),
            "rejection_reasons": json.loads(row["rejection_reasons_json"]),
            "history": json.loads(row["history_json"]),
            "verified": bool(row["verified"]),
            "source_title": row["source_title"],
            "source_reference": row["source_reference"],
            "source_repository": row["source_repository"],
            "source_timestamps": json.loads(row["source_timestamps_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _like_pattern(query: str) -> str:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return "%{}%".format(escaped)

    def list_decisions(self, query: Optional[str] = None, limit: int = 50,
                       offset: int = 0) -> List[dict]:
        with self._connection() as connection:
            if query:
                pattern = self._like_pattern(query)
                rows = connection.execute(
                    """SELECT * FROM decisions
                       WHERE proposal LIKE ? ESCAPE '\\'
                          OR COALESCE(summary, '') LIKE ? ESCAPE '\\'
                          OR rejection_reasons_text LIKE ? ESCAPE '\\'
                       ORDER BY created_at DESC, id LIMIT ? OFFSET ?""",
                    (pattern, pattern, pattern, limit, offset),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM decisions ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        return [self._to_dict(row) for row in rows]

    def find_related(self, proposals: List[dict], source_title: str, source_text: str,
                     source_reference: Optional[str] = None, limit: int = 20,
                     minimum_score: float = 0.25) -> List[dict]:
        """Return deterministic keyword matches from other sources only.

        The score is token Jaccard similarity after lowercasing and removing a
        small, explicit stopword list. This is lexical retrieval, not semantic
        or vector search.
        """
        current = []
        for proposal in proposals:
            if hasattr(proposal, "model_dump"):
                proposal = proposal.model_dump()
            if isinstance(proposal, str):
                proposal = {"proposal": proposal, "status": None}
            if isinstance(proposal, dict) and isinstance(proposal.get("proposal"), str):
                name = proposal["proposal"].strip()
                if name:
                    current.append({"proposal": name, "status": proposal.get("status")})
        if not current:
            return []

        current_source = self._source_key(
            source_title.strip() or "Untitled discussion", source_reference, source_text)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM decisions WHERE source_key != ?",
                (current_source,),
            ).fetchall()

        matches = []
        for row in rows:
            historical = self._to_dict(row)
            matched = []
            scores = []
            conflicts = []
            for proposal in current:
                score = self._related_score(proposal["proposal"], historical["proposal"])
                if score < minimum_score:
                    continue
                matched.append(proposal["proposal"])
                scores.append(score)
                for reason in self._conflict_reasons(proposal, historical):
                    if reason not in conflicts:
                        conflicts.append(reason)
            if not matched:
                continue
            historical.update({
                "relevance_score": max(scores),
                "matched_proposals": matched,
                "potential_conflict": bool(conflicts),
                "conflict_reasons": conflicts,
            })
            matches.append(historical)

        matches.sort(key=lambda item: (
            -item["relevance_score"], item["created_at"], item["id"]))
        return matches[:limit]


def get_memory_store() -> DecisionMemory:
    return DecisionMemory()
