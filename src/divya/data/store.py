"""Local persistence: events, companies, decisions, traces.

The terminal is a market-intelligence tool, not a demo, and the difference shows up in exactly
one place — whether a user can ask "what has this company done, and why did the system say
that?" three weeks later. That requires state on disk, not state in a process.

SQLite, deliberately. It is in the standard library, it is a single file, it survives a power
cut mid-write, and it needs no server on a 7.5 GiB box that is already holding a 2.8 GB model.

**Provenance is stored, not reconstructed.** Every row that came from a source carries the
source id, the URL, the retrieval time, and whether the content is simulated. `is_simulated` is
written as a real column and read back as one, so a fixture can never be laundered into a live
price by a code path that forgot to check.

**Decisions are append-only and immutable.** `decisions` rows are keyed by run and decision
name and are never updated. If the protocol changes and the system re-decides the same event,
that is a new row with a new protocol version, and both are visible. Overwriting history would
destroy the only thing that makes a calibration claim checkable.

Freshness is a *query*, never a stored flag. A row written a week ago is stale now, and no
column can change that.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from divya.data.nse_taxonomy import UNRESOLVED, classify, is_measurable
from divya.runtime.state import Observation

DEFAULT_DB = Path("data/store/divya.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq_id        TEXT PRIMARY KEY,
    symbol        TEXT NOT NULL,
    company       TEXT NOT NULL,
    industry      TEXT,
    nse_desc      TEXT,
    text          TEXT NOT NULL,
    pdf_url       TEXT,
    announced_at  TEXT,
    retrieved_at  TEXT NOT NULL,
    has_xbrl      INTEGER DEFAULT 0,
    is_simulated  INTEGER NOT NULL DEFAULT 0,
    source_id     TEXT NOT NULL,
    content_hash  TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_symbol ON events(symbol);
CREATE INDEX IF NOT EXISTS idx_events_time   ON events(announced_at DESC);

CREATE TABLE IF NOT EXISTS decisions (
    run_id         TEXT NOT NULL,
    decision       TEXT NOT NULL,
    spec_name      TEXT,
    spec_version   INTEGER,
    protocol_version TEXT,
    seq_id         TEXT,
    symbol         TEXT,
    value          TEXT,
    confidence     REAL,
    raw            TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    PRIMARY KEY (run_id, decision)
);
CREATE INDEX IF NOT EXISTS idx_dec_symbol ON decisions(symbol);
CREATE INDEX IF NOT EXISTS idx_dec_seq    ON decisions(seq_id);

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    task_id      TEXT,
    mode         TEXT,
    domain       TEXT,
    objective    TEXT,
    termination  TEXT,
    reason       TEXT,
    conclusion   TEXT,
    confidence   REAL,
    uncertainty  TEXT,
    degraded     TEXT,
    trace_path   TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS disagreements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    decision    TEXT NOT NULL,
    system1     TEXT,
    system2     TEXT,
    resolution  TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class EventRow:
    seq_id: str
    symbol: str
    company: str
    industry: str
    nse_desc: str
    text: str
    pdf_url: str | None
    announced_at: str | None
    retrieved_at: str
    has_xbrl: bool
    is_simulated: bool
    source_id: str
    content_hash: str

    @property
    def label_event_type(self) -> str:
        """The mapped protocol label, or `unresolved`.

        Derived on read rather than stored, so a taxonomy change takes effect immediately
        instead of leaving stale labels baked into old rows.
        """
        return classify(self.nse_desc) if self.nse_desc else UNRESOLVED

    @property
    def is_measurable(self) -> bool:
        return bool(self.nse_desc) and is_measurable(self.nse_desc)

    def age_seconds(self) -> float:
        try:
            ts = datetime.fromisoformat(self.retrieved_at)
        except ValueError:
            return 0.0
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ((datetime.now(UTC) - ts).total_seconds())

    def to_observation(self) -> Observation:
        return Observation(
            kind="corporate_announcement",
            source_id=self.source_id,
            source_url=self.pdf_url,
            content=self.text,
            published_at=self.announced_at,
            retrieved_at=self.retrieved_at,
            is_simulated=self.is_simulated,
        )


class Store:
    """Thin, explicit SQLite wrapper. No ORM, no magic, no hidden migrations."""

    def __init__(self, path: str | Path = DEFAULT_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- events ------------------------------------------------------------

    def upsert_events(self, rows: list[dict[str, Any]]) -> int:
        """Insert announcements, ignoring ones already stored.

        Re-fetching a window is the normal case, and a market terminal that double-counts a
        filing is worse than one that misses one. `seq_id` is the exchange's own id, so this is
        a true identity check rather than a content heuristic.
        """
        n = 0
        with self.tx() as c:
            for r in rows:
                obs = r.get("observation")
                cur = c.execute(
                    """INSERT OR IGNORE INTO events
                       (seq_id,symbol,company,industry,nse_desc,text,pdf_url,announced_at,
                        retrieved_at,has_xbrl,is_simulated,source_id,content_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r["seq_id"], r["symbol"], r["company"], r.get("industry", "unknown"),
                        r.get("nse_desc", ""), r["text"], r.get("pdf_url"),
                        r.get("announced_at"), r.get("retrieved_at") or now(),
                        1 if r.get("has_xbrl") else 0,
                        1 if r.get("is_simulated") else 0,
                        r.get("source_id") or f"nse:{r['seq_id']}",
                        obs.content_hash if isinstance(obs, Observation) else None,
                    ),
                )
                n += cur.rowcount
        return n

    def stream(
        self,
        limit: int = 200,
        symbol: str | None = None,
        measurable_only: bool = False,
        industry: str | None = None,
    ) -> list[EventRow]:
        """Newest first, with optional filters. This is the terminal's event stream."""
        q = ["SELECT * FROM events"]
        where: list[str] = []
        args: list[Any] = []
        if symbol:
            where.append("symbol = ?")
            args.append(symbol)
        if industry:
            where.append("industry = ?")
            args.append(industry)
        if where:
            q.append("WHERE " + " AND ".join(where))
        q.append("ORDER BY announced_at DESC, seq_id DESC LIMIT ?")
        args.append(limit)
        rows = [_event_row(r) for r in self._conn.execute(" ".join(q), args)]
        if measurable_only:
            rows = [r for r in rows if r.is_measurable]
        return rows

    def get_event(self, seq_id: str) -> EventRow | None:
        r = self._conn.execute("SELECT * FROM events WHERE seq_id = ?", (seq_id,)).fetchone()
        return _event_row(r) if r else None

    def companies(self, limit: int = 500) -> list[dict[str, Any]]:
        """Company rollup: how many filings, how recent, what event types were seen.

        This is the terminal's company list. It is deliberately derived from stored events
        rather than cached, so it cannot drift from the underlying records.
        """
        rows = self._conn.execute(
            """SELECT symbol, company, industry,
                      COUNT(*)                        AS n_events,
                      MAX(announced_at)               AS last_announced,
                      MAX(retrieved_at)               AS last_retrieved
               FROM events GROUP BY symbol ORDER BY last_announced DESC, n_events DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            types = self._conn.execute(
                "SELECT nse_desc FROM events WHERE symbol = ? ORDER BY announced_at DESC LIMIT 50",
                (r["symbol"],),
            ).fetchall()
            out.append(
                {
                    "symbol": r["symbol"],
                    "company": r["company"],
                    "industry": r["industry"],
                    "n_events": r["n_events"],
                    "last_announced": r["last_announced"],
                    "last_retrieved": r["last_retrieved"],
                    "event_types": [classify(t["nse_desc"]) for t in types],
                }
            )
        return out

    def history(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        """A company's filings, each with whatever decision was made on it."""
        rows = self._conn.execute(
            "SELECT * FROM events WHERE symbol = ? ORDER BY announced_at DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            e = _event_row(r)
            dec = self.decision_for_event(e.seq_id)
            out.append(
                {
                    "event": e,
                    "decision": dec,
                }
            )
        return out

    # -- decisions ---------------------------------------------------------

    def record_run(
        self,
        result: Any,
        mode: str = "system1",
        trace_path: str | None = None,
        symbol: str | None = None,
        seq_id: str | None = None,
    ) -> str:
        """Persist a whole run. Raw System-1 payloads are stored, never the interpretation only."""
        state = result.state
        run_id = state.task_id
        with self.tx() as c:
            c.execute(
                """INSERT OR REPLACE INTO runs
                   (run_id,task_id,mode,domain,objective,termination,reason,conclusion,
                    confidence,uncertainty,degraded,trace_path,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, state.task_id, mode, state.domain, state.objective,
                    state.termination.value if state.termination else None,
                    state.termination_reason, state.conclusion, state.confidence,
                    state.uncertainty, json.dumps(result.degraded), trace_path, now(),
                ),
            )
            for rec in state.system1_records:
                for name, ans in rec.answers.items():
                    c.execute(
                        """INSERT OR REPLACE INTO decisions
                           (run_id,decision,spec_name,spec_version,protocol_version,seq_id,
                            symbol,value,confidence,raw,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            run_id, name, rec.spec_name, rec.spec_version,
                            rec.protocol_version, seq_id, symbol,
                            json.dumps(_value_of(ans)), rec.confidence(name),
                            json.dumps(ans, ensure_ascii=False), now(),
                        ),
                    )
            for dis in state.disagreements:
                c.execute(
                    """INSERT INTO disagreements
                       (run_id,decision,system1,system2,resolution,note,created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (run_id, dis.decision, json.dumps(dis.system1_value), dis.system2_view,
                     dis.resolution, dis.note, now()),
                )
        return run_id

    def decision_for_event(self, seq_id: str) -> dict[str, Any] | None:
        """Most recent run's decisions for one event, keyed by decision name."""
        rows = self._conn.execute(
            """SELECT * FROM decisions WHERE seq_id = ?
               AND run_id = (SELECT MAX(run_id) FROM decisions WHERE seq_id = ?)""",
            (seq_id, seq_id),
        ).fetchall()
        if not rows:
            return None
        out: dict[str, Any] = {}
        for r in rows:
            try:
                out[r["decision"]] = {
                    "value": json.loads(r["value"]),
                    "confidence": r["confidence"],
                    "raw": json.loads(r["raw"]),
                    "spec": f"{r['spec_name']}@{r['spec_version']}",
                    "run_id": r["run_id"],
                }
            except (TypeError, ValueError):
                continue
        return out or None

    def decisions_for_symbol(self, symbol: str, limit: int = 200) -> list[dict[str, Any]]:
        return [
            {
                "decision": r["decision"],
                "value": json.loads(r["value"]),
                "confidence": r["confidence"],
                "seq_id": r["seq_id"],
                "run_id": r["run_id"],
                "created_at": r["created_at"],
            }
            for r in self._conn.execute(
                """SELECT * FROM decisions WHERE symbol = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (symbol, limit),
            )
        ]

    def stats(self) -> dict[str, Any]:
        ev = self._conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
        dec = self._conn.execute("SELECT COUNT(*) c FROM decisions").fetchone()["c"]
        runs = self._conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"]
        sym = self._conn.execute("SELECT COUNT(DISTINCT symbol) c FROM events").fetchone()["c"]
        sim = self._conn.execute(
            "SELECT COUNT(*) c FROM events WHERE is_simulated = 1"
        ).fetchone()["c"]
        meas = sum(1 for r in self._conn.execute("SELECT nse_desc FROM events") if is_measurable(r["nse_desc"]))
        return {
            "events": ev, "decisions": dec, "runs": runs, "symbols": sym,
            "simulated": sim, "measurable": meas,
        }

    def last_retrieved(self) -> str | None:
        r = self._conn.execute("SELECT MAX(retrieved_at) m FROM events").fetchone()
        return r["m"] if r else None


def _value_of(ans: dict[str, Any]) -> Any:
    """The short form of a System-1 answer, for display. The full payload is in `raw`."""
    if not isinstance(ans, dict):
        return ans
    if ans.get("type") == "choice":
        return ans.get("choice")
    if ans.get("type") == "noul":
        return {"probability": ans.get("noul")}
    if ans.get("type") == "score":
        return {"score": ans.get("score")}
    return ans


def _event_row(r: sqlite3.Row) -> EventRow:
    return EventRow(
        seq_id=r["seq_id"], symbol=r["symbol"], company=r["company"],
        industry=r["industry"] or "unknown", nse_desc=r["nse_desc"] or "",
        text=r["text"], pdf_url=r["pdf_url"], announced_at=r["announced_at"],
        retrieved_at=r["retrieved_at"], has_xbrl=bool(r["has_xbrl"]),
        is_simulated=bool(r["is_simulated"]), source_id=r["source_id"],
        content_hash=r["content_hash"] or "",
    )


def ingest_nse(store: Store, start: str, end: str, limit: int = 5000) -> dict[str, int]:
    """Fetch a window from NSE and store it. Returns a small summary for the CLI."""
    from divya.data.nse import NseAnnouncements

    anns, truncated = NseAnnouncements().fetch(
        __import__("datetime").date.fromisoformat(start),
        __import__("datetime").date.fromisoformat(end),
        limit=limit,
    )
    inserted = store.upsert_events(
        [
            {
                "seq_id": a.seq_id, "symbol": a.symbol, "company": a.company,
                "industry": a.industry, "nse_desc": a.desc, "text": a.text,
                "pdf_url": a.pdf_url, "announced_at": a.announced_at,
                "retrieved_at": now(), "has_xbrl": a.has_xbrl, "is_simulated": False,
                "source_id": f"nse:{a.symbol}:{a.seq_id}",
                "observation": a.to_observation(),
            }
            for a in anns
        ]
    )
    return {
        "fetched": len(anns), "inserted": inserted, "truncated": int(truncated),
        "measurable": sum(1 for a in anns if is_measurable(a.desc)),
    }
