# Spec: Genesis Markdown/60-UI/Index Movers.md
"""Holdings parsing and group summaries. No network: a tiny xlsx is built here."""

from __future__ import annotations

import io
import zipfile
from html import escape

from genesis.marketdata import index_map


def _xlsx(rows: list[list[object]]) -> bytes:
    strings: list[str] = []
    cells = []
    for i, row in enumerate(rows, 1):
        out = []
        for j, v in enumerate(row):
            ref = f"{chr(65 + j)}{i}"
            if isinstance(v, str):
                strings.append(v)
                out.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                out.append(f'<c r="{ref}"><v>{v}</v></c>')
        cells.append(f'<row r="{i}">{"".join(out)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{''.join(cells)}</sheetData></worksheet>")
    return buf.getvalue()


def test_parse_holdings_keeps_equities_and_drops_futures_cash_and_footer():
    blob = _xlsx([
        ["Fund Name:", "SPDR Dow"],
        ["Holdings:", "As of 10-Sep-2026"],
        ["Name", "Ticker", "Identifier", "SEDOL", "Weight"],
        ["GOLDMAN SACHS", "GS", "x", "x", 11.6],
        ["BERKSHIRE B", "BRK.B", "x", "x", 2.5],
        ["S&P FUTURE", "IXPU6", "x", "x", 0.1],
        ["PLACEHOLDER", "2682320D", "x", "x", 0.01],
        ["US DOLLAR", "-", "x", "x", 0.2],
        ["Before investing, read the prospectus."],
    ])
    out = index_map.parse_holdings(blob)
    assert out["as_of"] == "10-Sep-2026"
    assert out["members"] == {"GS": ("GOLDMAN SACHS", 11.6), "BRK-B": ("BERKSHIRE B", 2.5)}


def test_summary_weights_the_change_and_splits_gainers_from_losers():
    rows = [
        {"symbol": s, "weight": w, "change_pct": c}
        for s, w, c in [("A", 60, 1.0), ("B", 30, -2.0), ("C", 10, 0.0), ("D", 5, 4.0)]
    ]
    g = index_map.summarise_group(rows, top=5)
    assert g["change_pct"] == round((60 * 1 - 60 + 20) / 105, 2)
    assert [r["symbol"] for r in g["gainers"]] == ["D", "A"]
    assert [r["symbol"] for r in g["losers"]] == ["B"]  # flat C is neither
    assert (g["advancers"], g["decliners"]) == (2, 1)


def test_change_carries_cap_and_volume_and_leaves_missing_volume_null():
    q = {"regularMarketPrice": 110, "regularMarketPreviousClose": 100, "marketCap": 5e9, "regularMarketVolume": 2000}
    out = index_map._change("X", q)
    assert (out["change_pct"], out["market_cap"], out["volume"], out["dollar_volume"]) == (10.0, 5e9, 2000, 220000)
    no_vol = index_map._change("X", {**q, "regularMarketVolume": None})
    assert (no_vol["volume"], no_vol["dollar_volume"]) == (None, None)
