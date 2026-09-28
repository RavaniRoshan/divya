"""Composing analytical workspaces from a conversational session.

The seam between "what the user asked for" and "what to render". Given a `Session` and a
`Store`, this produces typed `UIIntent`s containing real data, freshness and provenance.

Design rules, each aimed at a specific failure:

* **An intent is only emitted if it can be filled.** A workspace showing an empty table with a
  title looks like a working product with no data. When there is nothing to show, the intent
  is `EMPTY` and says why. Every builder in `intents.py` returns a note rather than raising.
* **Freshness travels with the data, not beside it.** Every workspace carries a
  `data_freshness` map keyed by source, so the frontend cannot render a price without also
  rendering when it was retrieved. This is the one thing a market terminal must never get
  wrong.
* **Degradation is attached to the workspace.** If System-1 was missing, the workspace says so
  rather than looking like a complete answer.
* **Ranking comes from the decision state.** The market view orders by System-1 materiality,
  not by a heuristic in this file. The ordering is the model's decision, and it is inspectable
  in the decision pane.
"""

from __future__ import annotations

from typing import Any

from divya.data.store import Store
from divya.runtime import intents
from divya.runtime.intents import Workspace
from divya.runtime.session import Session, suggested_for


def _freshness(store: Store) -> dict[str, str]:
    last = store.last_retrieved()
    if not last:
        return {"nse": "no data ingested — run `divya index`"}
    return {"nse": f"last retrieved {last}"}


def _event_payload(row: Any, decision: dict[str, Any] | None) -> dict[str, Any]:
    """One row for an event table. Every field the frontend might show is present."""
    d = decision or {}
    et = d.get("event_type", {})
    mat = d.get("is_material", {})
    return {
        "seq_id": row.seq_id,
        "symbol": row.symbol,
        "company": row.company,
        "industry": row.industry,
        "nse_desc": row.nse_desc,
        "label_event_type": row.label_event_type,
        "announced_at": row.announced_at,
        "retrieved_at": row.retrieved_at,
        "is_simulated": row.is_simulated,
        "pdf_url": row.pdf_url,
        "text_excerpt": " ".join(row.text.split())[:280],
        "decision": {
            "event_type": et.get("value"),
            "event_type_confidence": et.get("confidence"),
            "is_material_p": (mat.get("value") or {}).get("probability")
            if isinstance(mat.get("value"), dict) else None,
            "run_id": et.get("run_id"),
            "spec": et.get("spec"),
        } if d else None,
    }


def compose(session: Session, store: Store, *, limit: int = 100) -> Workspace:
    """Build the workspace for a session's current intent.

    Degrades by narrowing: if the store has nothing for the requested entity, the workspace
    says so rather than falling back to an unrelated market view. A workspace that quietly
    shows the wrong data is the failure this design exists to prevent.
    """
    degraded = list(session.degraded)
    freshness = _freshness(store)
    t = session.task_type
    out: list[Any] = []

    if t == "comparison":
        symbols = session.symbols()
        entities = []
        for sym in symbols:
            hist = store.history(sym, limit=20)
            entities.append(
                {
                    "symbol": sym,
                    "history": [
                        {
                            "seq_id": h["event"].seq_id,
                            "nse_desc": h["event"].nse_desc,
                            "label_event_type": h["event"].label_event_type,
                            "announced_at": h["event"].announced_at,
                            "decision": (h["decision"] or {}).get("event_type", {}).get("value"),
                        }
                        for h in hist
                    ],
                    "n_events": len(hist),
                }
            )
        dims = session.dimensions or ["event mix", "materiality", "recent activity"]
        out.append(intents.comparison(entities, dims, title=" vs ".join(symbols) or "Comparison"))

    elif t == "company":
        sym = session.symbols()[0] if session.symbols() else ""
        if not sym:
            out.append(intents.empty("I could not tell which company you mean.",
                                      reason="no symbol or company name resolved"))
        else:
            hist = store.history(sym, limit=40)
            dec = store.decision_for_event(hist[0]["event"].seq_id) if hist else None
            out.append(intents.company(sym, hist[0]["event"].company if hist else sym,
                                       hist, decision=dec))

    elif t == "evidence":
        syms = session.symbols()
        sources = []
        for sym in syms[:6]:
            for h in store.history(sym, limit=6):
                sources.append(
                    {
                        "symbol": sym,
                        "seq_id": h["event"].seq_id,
                        "source_id": h["event"].source_id,
                        "url": h["event"].pdf_url,
                        "announced_at": h["event"].announced_at,
                        "retrieved_at": h["event"].retrieved_at,
                        "excerpt": " ".join(h["event"].text.split())[:400],
                        "decision_made": (h["decision"] or {}).get("event_type", {}).get("value"),
                    }
                )
        out.append(intents.evidence(sources, claim=session.objective[:120]))

    elif t == "screen":
        rows = store.stream(limit=limit, measurable_only=True)
        payload = [
            {
                "symbol": r.symbol,
                "company": r.company,
                "label_event_type": r.label_event_type,
                "nse_desc": r.nse_desc,
                "announced_at": r.announced_at,
            }
            for r in rows
        ]
        out.append(intents.screen(payload, session.objective[:120], title="Event screen"))

    elif t == "investigation":
        steps = [
            {
                "turn": tu.index,
                "said": tu.said,
                "understood_as": tu.understood_as or tu.said,
                "at": tu.at,
            }
            for tu in session.turns
        ]
        out.append(intents.investigation(session.task_id, steps, status=session.status))

    else:  # market, evidence-less, or unknown
        rows = store.stream(limit=limit, measurable_only=True)
        payload = [_event_payload(r, store.decision_for_event(r.seq_id)) for r in rows]
        # Ordered by the decision where one exists, undecided events last rather than first.
        # An event the system has not judged is not "top priority"; it is unjudged.
        def _rank(e: dict[str, Any]) -> tuple[int, float]:
            p = ((e.get("decision") or {}).get("is_material_p"))
            if p is None:
                return (1, 0.0)  # unjudged sorts last, not first
            return (0, -float(p))

        payload.sort(key=_rank)
        out.append(
            intents.market(payload, title="Market events", universe=session.objective[:60])
        )

    if session.unresolved:
        out.append(
            intents.empty("; ".join(session.unresolved[:3]), reason="unresolved questions")
        )

    return Workspace(
        task_id=session.task_id,
        intents=out,
        suggested_next=suggested_for(session),
        degraded=degraded,
        data_freshness=freshness,
    )
