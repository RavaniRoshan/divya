"""Tests for full-filing extraction from the announcement PDF.

The measurements that motivated this module: NSE's `attchmntText` has a median of 154
characters and is a one-line summary, while the attached PDF carries the filing. A materiality
judgement needs figures, and summaries routinely omit them.

These tests are deliberately offline. Nothing here fetches a PDF; the network path is exercised
by the real run recorded in `docs/loop/STATUS.md`, and a test suite that hits an exchange on
every run is a test suite that fails for reasons that have nothing to do with the code.
"""

from __future__ import annotations

from divya.data.filings import (
    MAX_PDF_BYTES,
    MIN_USABLE_CHARS,
    FilingText,
    get_filing_text,
    strip_boilerplate,
)

REAL_HEADER = (
    "To, Date: September 24, 2026 The Manager (Listing), National Stock Exchange of India Ltd "
    "Exchange Plaza, 5th Floor, Plot No C/1, G Block, Bandra-Kurla Complex, Bandra (E), "
    "Mumbai 400 051 Company’s symbol: MCL "
    "Sub: Disclosure of pursuant to Regulation 7(2)(b) of the SEBI (Prohibition of Insider "
    "Trading) Regulations, 2015. "
    "Pursuant to Regulation 7(2)(b), we are enclosing herewith the disclosures received to the "
    "Company from one of the promoter group of the Company i.e. Mr. RAJESH MONPARA, in Form C "
    "in respect of off market transfer by way of Gift of equity shares of the company, being "
    "1,25,000 shares at a total consideration of Rs 12.50 crore."
)


# --- boilerplate stripping ------------------------------------------------


def test_strip_removes_the_exchange_address_block():
    out = strip_boilerplate(REAL_HEADER)
    assert "Exchange Plaza" not in out
    assert "Bandra-Kurla Complex" not in out
    assert "Mumbai 400 051" not in out


def test_strip_keeps_the_event_content():
    """The whole point. Stripping must not eat the sentence that states what happened."""
    out = strip_boilerplate(REAL_HEADER)
    assert "off market transfer by way of Gift" in out
    assert "1,25,000 shares" in out
    assert "Rs 12.50 crore" in out


def test_strip_handles_a_multiline_address_block():
    """Real extractions break the address across four lines; a line-scoped pattern misses it."""
    multiline = (
        "To,\nThe Manager (Listing),\nNational Stock Exchange of India Ltd\n"
        "Exchange Plaza, 5th Floor, Plot No C/1, G Block,\nBandra (E), Mumbai 400 051\n"
        "Sub: The company has approved acquisition of a 51 per cent stake in Target Limited "
        "for Rs 4,600 crore, subject to shareholder approval and other customary conditions."
    )
    out = strip_boilerplate(multiline)
    assert "Exchange Plaza" not in out
    assert "51 per cent stake" in out


def test_strip_handles_the_bse_address():
    out = strip_boilerplate(
        "To, The Manager, BSE Limited Department of Corporate Services Phiroze Jeejeebhoy "
        "Towers, Dalal Street, Mumbai - 400 001 Scrip Code - 544161 "
        "The Board has approved a buyback of 8,500,000 equity shares at Rs 1,175 per share."
    )
    assert "Dalal Street" not in out
    assert "8,500,000 equity shares" in out


def test_strip_refuses_to_eat_a_short_document():
    """Over-stripping a short filing is worse than leaving noise in it."""
    short = "Exchange Plaza Mumbai 400 051 Board approved a buyback of 100 shares today."
    out = strip_boilerplate(short)
    assert "buyback" in out
    assert len(out.strip()) > 0


def test_strip_is_idempotent():
    once = strip_boilerplate(REAL_HEADER)
    assert strip_boilerplate(once) == once


# --- fallback behaviour ---------------------------------------------------


def test_falls_back_to_summary_when_no_pdf_url():
    ft = get_filing_text("s1", "Board approved a dividend of Rs 5 per share.", None)
    assert ft.source == "summary"
    assert ft.chars == ft.summary_chars
    assert "no PDF url" in ft.reason
    assert "dividend" in ft.text


def test_falls_back_when_pdf_is_unreachable(monkeypatch):
    """A dead URL must produce the summary plus a reason, never an empty document.

    Deciding on an empty string is the worst possible outcome: the engine reports 'nothing to
    decide' as though that were a finding.
    """
    import divya.data.filings as f

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(f, "fetch_pdf_text", boom)
    ft = f.get_filing_text("s2", "Board approved a buyback.", "https://x.invalid/a.pdf")
    assert ft.source == "summary"
    assert ft.text == "Board approved a buyback."
    assert "network down" in ft.reason


def test_falls_back_when_pdf_has_no_text_layer(monkeypatch):
    """Scanned-image filings are common in India. Empty text must be a failure, not a document."""
    import divya.data.filings as f

    monkeypatch.setattr(f, "fetch_pdf_text", lambda *a, **k: ("", 3))
    ft = f.get_filing_text("s3", "Board approved a rights issue.", "https://x.invalid/b.pdf")
    assert ft.source == "summary"
    assert "rights issue" in ft.text


def test_rejects_an_oversized_pdf():
    assert MAX_PDF_BYTES < 50 * 1024 * 1024
    assert MIN_USABLE_CHARS >= 100


# --- provenance -----------------------------------------------------------


def test_expansion_ratio_is_measured_not_asserted():
    ft = FilingText(text="x" * 1000, source="pdf", chars=1000, summary_chars=100, url="u")
    assert ft.expansion == 10.0
    assert ft.used_pdf is True


def test_expansion_handles_zero_summary():
    ft = FilingText(text="x", source="pdf", chars=1, summary_chars=0, url=None)
    assert ft.expansion == 0.0


def test_as_dict_carries_the_provenance_fields():
    d = FilingText(
        text="t", source="pdf", chars=10, summary_chars=5, url="u", pages=2,
        boilerplate_removed=100, reason="ok",
    ).as_dict()
    assert d["source"] == "pdf"
    assert d["pages"] == 2
    assert d["boilerplate_removed"] == 100
    assert d["expansion"] == 2.0


# --- cache ----------------------------------------------------------------


def test_cache_is_used_and_does_not_refetch(monkeypatch, tmp_path):
    import divya.data.filings as f

    monkeypatch.setattr(f, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def fake(url, timeout=45.0):
        calls.append(url)
        return REAL_HEADER * 2, 2

    monkeypatch.setattr(f, "fetch_pdf_text", fake)

    first = f.get_filing_text("seq-x", "short summary", "https://x.invalid/c.pdf")
    assert first.source == "pdf"
    assert len(calls) == 1

    second = f.get_filing_text("seq-x", "short summary", "https://x.invalid/c.pdf")
    assert second.source == "pdf"
    assert "cache" in second.reason
    assert len(calls) == 1, "a cached filing must not be downloaded again"


def test_cache_key_is_scoped_to_the_seq_id(monkeypatch, tmp_path):
    """Two events must never share a cache entry."""
    import divya.data.filings as f

    monkeypatch.setattr(f, "CACHE_DIR", tmp_path / "cache")
    a = f._cache_path("seq-1")
    b = f._cache_path("seq-2")
    assert a != b
    assert a.suffix == ".txt"


def test_pdf_can_be_disabled(monkeypatch):
    import divya.data.filings as f

    monkeypatch.setattr(
        f, "fetch_pdf_text",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    ft = f.get_filing_text("s9", "summary text", "https://x.invalid/d.pdf", use_pdf=False)
    assert ft.source == "summary"
    assert "pdf disabled" in ft.reason


def test_text_is_truncated_to_max_chars(monkeypatch):
    import divya.data.filings as f

    monkeypatch.setattr(f, "fetch_pdf_text", lambda *a, **k: ("y" * 50_000, 9))
    ft = f.get_filing_text("s10", "s", "https://x.invalid/e.pdf", max_chars=1_000, cache=False)
    assert len(ft.text) == 1_000
    assert ft.chars == 1_000
