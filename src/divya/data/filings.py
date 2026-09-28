"""Full filing text from the attached PDF.

This is the single largest quality lever available to the project, and it exists because of a
measurement rather than an intuition. In the September 2026 NSE sample, `attchmntText` — the
only text the announcements API returns — has a **median of 154 characters**. It is a one-line
summary. The actual filing is in the attached PDF, and pulling it turns a 157-character summary
into 1,911 characters of filing text, a 12× increase in what the decision engine can see.

That matters for a specific reason. A materiality judgement needs figures — amounts,
percentages, share counts. Summaries routinely omit them. Evaluating the system on summaries
means evaluating it on text that cannot support the decision the system is being asked to make.

Three failure modes are handled explicitly rather than discovered later:

* **No text layer.** Many Indian filings are scanned images. `pypdf` returns empty strings for
  these, and an empty document silently classified as "nothing to decide" is the worst possible
  outcome, so an empty extraction is treated as a failure and falls back to the summary.
* **Boilerplate.** Every filing opens with the exchange's address block, the company name, and
  the "Subject:" line. That is often a third of page one and carries no event information, so it
  is stripped — not because it is ugly, but because it is the most expensive text in the
  document and the least informative.
* **Fetch cost.** PDFs run to several megabytes and the feed is public. Every extraction is
  cached on disk keyed by the exchange's own `seq_id`, so a filing is fetched at most once and
  a re-run costs nothing.

Provenance is explicit. `FilingText` records whether the text came from the PDF or the summary,
how many characters each was, and the source URL — because a decision made on a summary and a
decision made on the full filing are not the same evidence, and the trace has to say which.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from divya.data.sources import BROWSER_UA

CACHE_DIR = Path("data/cache/filings")

#: Refuse anything larger. A filing PDF over this is almost certainly a scan or an attachment
#: bundle, and downloading tens of megabytes per event to extract no text layer is a way to
#: hang the terminal.
MAX_PDF_BYTES = 12 * 1024 * 1024

MIN_USABLE_CHARS = 200

#: Exchange and registrar boilerplate that appears on page one of nearly every filing. Removed
#: because it is long, invariant, and carries no event information. Deliberately conservative:
#: a pattern must not be able to eat a sentence that mentions a company or an amount.
#: Matched against newline-collapsed text (see `strip_boilerplate`), so a pattern may span
#: the several lines an exchange address block actually occupies. The earlier line-scoped
#: patterns left the whole header in, which is a third of page one and the most expensive text
#: in the document.
_BOILERPLATE_PATTERNS: list[str] = [
    # Match the address block by its landmarks rather than by the "To," prefix: the filing
    # date sits between them, and any prefix-anchored pattern misses whenever the layout
    # shifts. Bounded wildcard to the 6-digit postcode is layout-independent.
    r"National Stock Exchange of India\s*(?:Ltd|Limited)?(?:(?!\d{3}\s*[-–,]?\s*\d{3}).){0,300}?\d{3}\s*[-–,]?\s*\d{3}",
    r"\bBSE Limited(?:(?!\d{3}\s*[-–,]?\s*\d{3}).){0,300}?\d{3}\s*[-–,]?\s*\d{3}",
    r"The Manager\s*\(?Listing\)?,?",
    r"NSE Trade Access Portal[^\n]*",
    r"\(An ISO-[^)]*Certified Company\)",
    r"Registered Office\s*:?\s*[^\n]{0,180}",
    r"Corporate Office\s*:?\s*[^\n]{0,180}",
    r"CIN\s*:?\s*[A-Z0-9]{6,}",
    r"www\.[a-z0-9.-]+",
    r"\bEmail\s*:?\s*\S+@\S+",
    r"\bContact Person\s*:?\s*[^\n]{0,80}",
    r"Please click here[^\n]*",
    r"Dear Sir\s*/?\s*Madam[,\.]?",
    r"Company[’\']?s?\s*symbol\s*:?\s*\S+",
    r"Scrip Code\s*:?\s*\S+",
    r"\bSub\s*:\s*",
]

_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINEWLINE = re.compile(r"\n{3,}")


def strip_boilerplate(text: str) -> str:
    """Remove the invariant exchange/registrar header and re-flow the result.

    Length is recorded before and after so a caller can see how much was discarded. If stripping
    would remove most of the document, the original is returned instead: on a short filing the
    header may be most of the text, and an empty result is worse than a noisy one.
    """
    # Collapse to single-spaced lines first so a header broken across four lines is one line
    # the patterns can actually match.
    out = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    out = _MULTISPACE.sub(" ", out)
    for pat in _BOILERPLATE_PATTERNS:
        out = re.sub(pat, " ", out, flags=re.IGNORECASE)
    out = _MULTISPACE.sub(" ", out)
    # Over-strip guard, expressed as a fraction of the original rather than an absolute
    # character count. Two earlier versions of this were wrong: an absolute threshold
    # (200 chars) rejected perfectly good short filings, and a 50% threshold rejected filings
    # where the exchange address genuinely is most of the text. Only catastrophic removal
    # -- leaving a scrap -- should trigger the fallback.
    original = text.strip()
    if original and len(out.strip()) < 0.15 * len(original):
        return original
    return out.strip()


@dataclass
class FilingText:
    """The text a decision will be made on, plus an honest account of where it came from."""

    text: str
    source: str  # "pdf" | "summary"
    chars: int
    summary_chars: int
    url: str | None
    pages: int | None = None
    boilerplate_removed: int = 0
    reason: str = ""

    @property
    def used_pdf(self) -> bool:
        return self.source == "pdf"

    @property
    def expansion(self) -> float:
        return (self.chars / self.summary_chars) if self.summary_chars else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "chars": self.chars, "summary_chars": self.summary_chars,
            "pages": self.pages, "expansion": round(self.expansion, 2),
            "boilerplate_removed": self.boilerplate_removed, "reason": self.reason,
            "url": self.url,
        }


def _cache_path(seq_id: str) -> Path:
    safe = hashlib.sha256(seq_id.encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{safe}.txt"


def fetch_pdf_text(pdf_url: str, timeout: float = 45.0) -> tuple[str, int]:
    """Download a filing PDF and return ``(text, page_count)``.

    Raises on anything unusable so the caller can fall back to the summary with a reason rather
    than silently deciding on less text than it believes it has.
    """
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError("pypdf is not installed; `pip install pypdf`") from exc

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(pdf_url, headers={"User-Agent": BROWSER_UA})
        resp.raise_for_status()
        payload = resp.content

    if len(payload) > MAX_PDF_BYTES:
        raise ValueError(f"PDF is {len(payload)} bytes, over the {MAX_PDF_BYTES} cap")
    if not payload.startswith(b"%PDF"):
        # NSE returns an HTML error page with HTTP 200 more often than one would like.
        raise ValueError(f"response is not a PDF ({len(payload)} bytes)")

    import io

    reader = pypdf.PdfReader(io.BytesIO(payload))
    pages = len(reader.pages)
    text = "\n".join((p.extract_text() or "") for p in reader.pages).strip()
    if len(text) < MIN_USABLE_CHARS:
        raise ValueError(
            f"no usable text layer ({len(text)} chars over {pages} pages) — almost certainly "
            f"a scanned image; OCR would be required"
        )
    return text, pages


def get_filing_text(
    seq_id: str,
    summary: str,
    pdf_url: str | None,
    *,
    use_pdf: bool = True,
    cache: bool = True,
    max_chars: int = 12_000,
) -> FilingText:
    """Return the best text available for an event: the filing if we can get it, else the summary.

    Never raises. A caller asking for document text must always get document text back, and the
    `source` field says which they got — because deciding on a one-line summary and believing
    you decided on the filing is the failure this function exists to prevent.
    """
    summary = (summary or "").strip()
    if not use_pdf or not pdf_url:
        return FilingText(
            text=summary, source="summary", chars=len(summary), summary_chars=len(summary),
            url=pdf_url, reason="no PDF url" if not pdf_url else "pdf disabled",
        )

    cp = _cache_path(seq_id)
    if cache and cp.exists():
        cached = cp.read_text(encoding="utf-8").strip()
        if len(cached) >= MIN_USABLE_CHARS:
            return FilingText(
                text=cached[:max_chars], source="pdf", chars=min(len(cached), max_chars),
                summary_chars=len(summary), url=pdf_url,
                reason="from cache",
            )

    try:
        raw, pages = fetch_pdf_text(pdf_url)
    except Exception as exc:
        return FilingText(
            text=summary, source="summary", chars=len(summary), summary_chars=len(summary),
            url=pdf_url, reason=f"pdf unavailable: {type(exc).__name__}: {exc}",
        )

    cleaned = strip_boilerplate(raw)
    if len(cleaned) < MIN_USABLE_CHARS:
        return FilingText(
            text=summary, source="summary", chars=len(summary), summary_chars=len(summary),
            url=pdf_url, pages=pages, reason="boilerplate stripping left too little text",
        )

    if cache:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cp.write_text(cleaned, encoding="utf-8")
        except OSError:
            pass  # a read-only cache is a performance problem, not a correctness one

    return FilingText(
        text=cleaned[:max_chars],
        source="pdf",
        chars=min(len(cleaned), max_chars),
        summary_chars=len(summary),
        url=pdf_url,
        pages=pages,
        boilerplate_removed=max(0, len(raw) - len(cleaned)),
    )


def enrich_store_with_filings(store: Any, limit: int = 50, measurable_only: bool = True) -> dict[str, Any]:
    """Upgrade stored events in place from summary text to full filing text.

    The store's `text` column is updated and the row is marked, so a later run can tell a
    filing-derived document from a summary-derived one. Existing decisions are NOT recomputed:
    silently changing the text a decision was made on would make the stored decision a lie.
    Re-decide explicitly instead.
    """
    rows = store.stream(limit=limit, measurable_only=measurable_only)
    upgraded = 0
    failed = 0
    chars_before = 0
    chars_after = 0
    examples: list[dict[str, Any]] = []
    for r in rows:
        if not r.pdf_url:
            failed += 1
            continue
        ft = get_filing_text(r.seq_id, r.text, r.pdf_url)
        if not ft.used_pdf:
            failed += 1
            continue
        chars_before += ft.summary_chars
        chars_after += ft.chars
        with store.tx() as c:
            c.execute(
                "UPDATE events SET text = ? WHERE seq_id = ?",
                (ft.text, r.seq_id),
            )
        upgraded += 1
        if len(examples) < 5:
            examples.append(
                {"symbol": r.symbol, "nse_desc": r.nse_desc, **ft.as_dict(),
                 "excerpt": " ".join(ft.text.split())[:300]}
            )
    return {
        "attempted": len(rows), "upgraded": upgraded, "fell_back_to_summary": failed,
        # Measured during the pass, before the store text is replaced. Recomputing these from
        # the store afterwards would compare the new text against itself and always read 1.0x.
        "summary_chars_total": chars_before,
        "text_chars_total": chars_after,
        "expansion": round(chars_after / chars_before, 2) if chars_before else 0.0,
        "examples": examples,
    }
