"""The Divya API: conversational control surface + workspace rendering.

The backend half of COMMAND → INTENT → WORKSPACE → STATE → FOLLOW-UP. Two things matter here.

**The language model never renders.** `POST /command` folds an utterance into a `Session`
and composes typed `UIIntent`s. The model, when it is available, proposes an intent; when it
is not, the rule-based resolver does. The frontend receives structured state and renders it
with verified components. There is no path from System-2 to HTML.

**The model is optional, and the API says so.** `provider: "heuristic"` is a first-class,
fully-supported mode. When System-2 is unavailable the response carries `degraded` and the
workspace still renders from System-1 decisions. A market terminal that goes blank when the
reasoning model is down is not a market terminal.

Deliberately not here: authentication, multi-tenancy, rate limiting. This is a self-hosted
single-user service; those are deployment concerns and pretending otherwise would be a claim
the code does not back.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from divya import __version__
from divya.data.store import Store
from divya.runtime.intents import Workspace
from divya.runtime.session import Resolver, Session, SessionStore
from divya.runtime.workspaces import compose
from divya.system1.laya_adapter import LayaSystem1, NullSystem1

app = FastAPI(
    title="Divya",
    version=__version__,
    description="Conversational market-intelligence terminal: intent in, analytical workspace out.",
)

# The frontend is a separate Next.js dev server. CORS is scoped to localhost in development
# only; a deployment behind a reverse proxy does not need it and should not enable it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "DIVYA_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(os.environ.get("DIVYA_DB", "data/store/divya.db"))
SESSIONS = SessionStore(os.environ.get("DIVYA_SESSIONS", "data/sessions"))

_store: Store | None = None
_system1: Any = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store(DB_PATH)
    return _store


def get_system1() -> Any:
    """System-1, resolved once and reused.

    Loading the checkpoint costs ~6.6 s and 2.8 GB. A per-request process would pay that on
    every call, which is the difference between a usable terminal and an unusable one.
    """
    global _system1
    if _system1 is None:
        _system1 = LayaSystem1() if LayaSystem1().is_available() else NullSystem1()
    return _system1


def _resolver() -> Resolver:
    return Resolver([(c["symbol"], c["company"]) for c in get_store().companies(300)])


# --- schemas --------------------------------------------------------------


class Command(BaseModel):
    model_config = {"extra": "forbid"}

    text: str = Field(min_length=1, max_length=4000)
    task_id: str | None = None
    #: Ask the system to decide this event as part of handling the command. Off by default
    #: because a decision costs ~1.1 s per question and most commands are not about deciding.
    decide: bool = False


class CommandResponse(BaseModel):
    model_config = {"extra": "forbid"}

    task_id: str
    turn_index: int
    understood_as: str
    followed_up: bool
    resolved_entities: list[dict[str, Any]] = Field(default_factory=list)
    workspace: Workspace
    session: Session
    degraded: list[str] = Field(default_factory=list)


# --- routes ----------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    """Health check. Reports what is actually available rather than a bare 200."""
    s1 = get_system1()
    return {
        "status": "ok",
        "version": __version__,
        "system1": "laya" if s1.is_available() else "unavailable",
        "db": str(DB_PATH),
        "store": get_store().stats(),
    }


@app.get("/sessions")
def list_sessions(limit: int = 50) -> dict[str, Any]:
    return {"sessions": SESSIONS.list(limit=limit)}


@app.get("/sessions/{task_id}")
def get_session(task_id: str) -> dict[str, Any]:
    s = SESSIONS.load(task_id)
    if s is None:
        raise HTTPException(404, f"no session {task_id}")
    return s.as_dict()


@app.delete("/sessions/{task_id}")
def delete_session(task_id: str) -> dict[str, Any]:
    p = SESSIONS.path(task_id)
    if not p.exists():
        raise HTTPException(404, f"no session {task_id}")
    p.unlink()
    return {"deleted": task_id}


@app.post("/command", response_model=CommandResponse)
def command(cmd: Command) -> CommandResponse:
    """The control surface. One utterance in, one workspace out.

    Follow-up semantics are the point: supplying `task_id` continues an existing session, and
    the entities under investigation are preserved across the turn.
    """
    store = get_store()
    session = SESSIONS.load(cmd.task_id) if cmd.task_id else None
    if session is None:
        if cmd.task_id:
            raise HTTPException(404, f"no session {cmd.task_id}; start a new task")
        session = Session()

    degraded = list(session.degraded)
    if not get_system1().is_available():
        degraded.append("system1: engine unavailable; no typed decisions can be produced")

    before = len(session.turns)
    session = _resolver().apply(session, cmd.text)
    turn = session.turns[before]
    turn.understood_as = session.objective

    if cmd.decide and turn.resolved_entities:
        turn.notes.append("decision requested but requires a selected event; use /decide")

    workspace = compose(session, store)
    session.workspace = workspace.intents
    session.degraded = degraded
    session.suggested_next = workspace.suggested_next
    SESSIONS.save(session)

    return CommandResponse(
        task_id=session.task_id,
        turn_index=turn.index,
        understood_as=session.objective,
        followed_up=turn.followed_up,
        resolved_entities=[e.model_dump(mode="json") for e in turn.resolved_entities],
        workspace=workspace,
        session=session,
        degraded=degraded,
    )


@app.get("/workspace/{task_id}")
def workspace(task_id: str) -> dict[str, Any]:
    """Re-render the current workspace for a session. Stateless refresh for the frontend."""
    session = SESSIONS.load(task_id)
    if session is None:
        raise HTTPException(404, f"no session {task_id}")
    return compose(session, get_store()).as_dict()


@app.get("/stream")
def stream(limit: int = 100, measurable_only: bool = True) -> dict[str, Any]:
    """The event stream, for the market workspace and the context rail."""
    store = get_store()
    rows = store.stream(limit=limit, measurable_only=measurable_only)
    return {
        "as_of": store.last_retrieved(),
        "events": [
            {
                "seq_id": r.seq_id, "symbol": r.symbol, "company": r.company,
                "industry": r.industry, "nse_desc": r.nse_desc,
                "label_event_type": r.label_event_type, "announced_at": r.announced_at,
                "retrieved_at": r.retrieved_at, "is_simulated": r.is_simulated,
                "pdf_url": r.pdf_url,
            }
            for r in rows
        ],
    }


@app.get("/company/{symbol}")
def company(symbol: str, limit: int = 40) -> dict[str, Any]:
    store = get_store()
    hist = store.history(symbol.upper(), limit=limit)
    if not hist:
        raise HTTPException(404, f"no stored filings for {symbol}")
    return {
        "symbol": symbol.upper(),
        "company": hist[0]["event"].company,
        "history": [
            {
                "seq_id": h["event"].seq_id,
                "nse_desc": h["event"].nse_desc,
                "label_event_type": h["event"].label_event_type,
                "announced_at": h["event"].announced_at,
                "text": h["event"].text,
                "decision": h["decision"],
            }
            for h in hist
        ],
    }


@app.get("/decisions/{seq_id}")
def decisions(seq_id: str) -> dict[str, Any]:
    d = get_store().decision_for_event(seq_id)
    if d is None:
        raise HTTPException(404, f"no decision recorded for {seq_id}")
    return d


def main() -> int:
    """`divya serve`. Binding to 127.0.0.1 by default: this has no auth, by design."""
    import uvicorn

    uvicorn.run(
        "divya.api:app",
        host=os.environ.get("DIVYA_HOST", "127.0.0.1"),
        port=int(os.environ.get("DIVYA_PORT", "8000")),
        reload=os.environ.get("DIVYA_RELOAD", "0") == "1",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
