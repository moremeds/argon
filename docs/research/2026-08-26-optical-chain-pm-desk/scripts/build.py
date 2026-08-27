"""Build the Optical-Communication PM dataset from the prod pull.

Every number is a reported line item or an arithmetic combination of two.
No model, no z-score, no estimate.
"""
import json, os, csv, datetime as dt
from collections import defaultdict

H = os.path.dirname(os.path.abspath(__file__))
F = lambda n: os.path.join(H, n)

LAYERS = [
    ("Upstream-Components", 10, ["AAOI", "COHR", "LITE", "POET"]),
    ("Semi-DSP-Switch",     20, ["AVGO", "CRDO", "MRVL"]),
    ("Module-Transceiver",  30, ["AAOI", "COHR", "FN", "LITE"]),
    ("Systems-Networking",  40, ["ANET", "CIEN", "NTAP"]),
    ("Customer-Cloud",      70, ["AMZN", "GOOGL", "META", "MSFT", "ORCL"]),
]
SUPPLY = [l for l, _, _ in LAYERS if l != "Customer-Cloud"]
CUST = dict((l, t) for l, _, t in LAYERS)["Customer-Cloud"]

NUM = ["rev", "gp", "oi", "cogs", "rd", "ni_inc", "inv", "tca", "ar", "eq", "capex", "ocf"]
COLS = ["ticker", "period", "stmt", "filed"] + NUM

# ---- load ---------------------------------------------------------------
cells = defaultdict(dict)     # (ticker, period) -> field -> value
filed = {}
for row in csv.reader(open(F("prod_stmt.tsv")), delimiter="\t"):
    if len(row) < len(COLS):
        continue
    d = dict(zip(COLS, row))
    key = (d["ticker"], d["period"])
    if d["filed"]:
        filed[key] = d["filed"]
    for f in NUM:
        v = d[f]
        if v not in ("", None):
            try:
                cells[key][f] = float(v)
            except ValueError:
                pass
    # net income appears on both the income and cash-flow statements; keep them
    # apart so the two can be reconciled rather than silently merged.
    if d["stmt"] == "cash_flow" and d["ni_inc"]:
        try:
            cells[key]["ni_cf"] = float(d["ni_inc"])
        except ValueError:
            pass
    if d["stmt"] == "income" and d["ni_inc"]:
        try:
            cells[key]["ni"] = float(d["ni_inc"])
        except ValueError:
            pass

def midpoint_q(period):
    """Calendar quarter containing the fiscal quarter's MIDPOINT.

    A fiscal quarter ending 2026-04-30 spans Feb-Apr; its midpoint is mid-March,
    so it belongs to calendar Q1, not Q2. Mapping on the END date alone pushes
    every off-calendar filer one quarter forward and manufactures a lead that
    is not in the data.
    """
    y, m, d = map(int, period.split("-"))
    end = dt.date(y, m, d)
    mid = end - dt.timedelta(days=45)
    return mid.year * 4 + (mid.month - 1) // 3

qlabel = lambda i: f"{i // 4}Q{i % 4 + 1}"

# ---- per-ticker quarterly series ---------------------------------------
series = defaultdict(dict)    # ticker -> qidx -> record
for (tk, per), d in cells.items():
    rev, gp, cogs, inv = d.get("rev"), d.get("gp"), d.get("cogs"), d.get("inv")
    rec = {
        "period": per, "filed": filed.get((tk, per)),
        "rev": rev, "gp": gp, "inv": inv, "capex": d.get("capex"),
        "gm": (gp / rev) if rev and gp is not None else None,
        "om": (d["oi"] / rev) if rev and d.get("oi") is not None else None,
        "rd": (d["rd"] / rev) if rev and d.get("rd") is not None else None,
        "dio": (inv / cogs * 91.25) if inv and cogs else None,
        "ni": d.get("ni"), "ni_cf": d.get("ni_cf"),
    }
    k = midpoint_q(per)
    prev = series[tk].get(k)
    # two fiscal quarters can land in one calendar quarter; keep the later
    if prev is None or per > prev["period"]:
        series[tk][k] = rec

def matched(tickers, k, field):
    now = ago = 0.0
    names = []
    for tk in tickers:
        a, b = series[tk].get(k), series[tk].get(k - 4)
        if a and b and a.get(field) is not None and b.get(field) is not None:
            now += abs(a[field]); ago += abs(b[field]); names.append(tk)
    return (now / ago - 1, names) if names and ago else (None, [])

def total(tickers, k, field):
    v, names = 0.0, []
    for tk in tickers:
        a = series[tk].get(k)
        if a and a.get(field) is not None:
            v += abs(a[field]); names.append(tk)
    return (v, names) if names else (None, [])

def wmargin(tickers, k, field):
    num = den = 0.0
    names = []
    for tk in tickers:
        a = series[tk].get(k)
        if a and a.get(field) is not None and a.get("rev"):
            num += a[field] * a["rev"]; den += a["rev"]; names.append(tk)
    return (num / den, names) if den else (None, [])

allk = sorted({k for tk in series for k in series[tk]})
START = 2023 * 4
rows = []
for k in [x for x in allk if x >= START]:
    cx, cn = total(CUST, k, "capex")
    cy, cm = matched(CUST, k, "capex")
    r = {"q": qlabel(k), "k": k, "capex": cx, "capex_n": len(cn),
         "capex_yoy": cy, "capex_matched": len(cm), "layers": {}}
    for l in SUPPLY:
        tks = dict((a, c) for a, _, c in LAYERS)[l]
        rv, rn = total(tks, k, "rev")
        ry, rm = matched(tks, k, "rev")
        gm, _ = wmargin(tks, k, "gm")
        iy, im = matched(tks, k, "inv")
        r["layers"][l] = {"rev": rv, "n": len(rn), "yoy": ry, "yoy_n": len(rm),
                          "gm": gm, "inv_yoy": iy, "inv_n": len(im)}
    rows.append(r)

# ---- integrity: cross-statement net income ------------------------------
ok = bad = 0
worst = []
for tk in series:
    for k, r in series[tk].items():
        a, b = r.get("ni"), r.get("ni_cf")
        if a is None or b is None or k < 2024 * 4:
            continue
        if abs(a - b) <= 0.01 * abs(a or 1):
            ok += 1
        else:
            bad += 1
            worst.append({"t": tk, "p": r["period"], "inc": a, "cf": b})
worst.sort(key=lambda x: -abs(x["inc"] - x["cf"]))

# ---- valuation ----------------------------------------------------------
val = {}
for row in csv.reader(open(F("prod_val.tsv")), delimiter="\t"):
    if len(row) < 10:
        continue
    tk, ctype, method, spot, pct, buy, mid, hq, conf, asof = row[:10]
    val[tk] = {"type": ctype, "method": method, "spot": float(spot) if spot else None,
               "pct": float(pct) if pct else None, "buy": float(buy) if buy else None,
               "mid": float(mid) if mid else None, "hq": int(hq or 0),
               "conf": conf, "as_of": asof}

out = {
    "layers": [{"name": l, "rank": r, "tickers": t} for l, r, t in LAYERS],
    "supply": SUPPLY, "cust": CUST,
    "rows": rows,
    "series": {tk: {str(k): v for k, v in s.items()} for tk, s in series.items()},
    "val": val,
    "integrity": {"ni_ok": ok, "ni_bad": bad, "worst": worst[:6]},
}
json.dump(out, open(F("pm.json"), "w"))

# ---- report -------------------------------------------------------------
print(f"{'qtr':7s} {'capex$B':>8s} {'yoy':>6s} |" + "".join(f"{l[:9]:>11s}" for l in SUPPLY))
for r in rows[-10:]:
    line = f"{r['q']:7s} {r['capex']/1e9:8.1f} " + (f"{r['capex_yoy']*100:5.0f}%" if r["capex_yoy"] is not None else "     -") + " |"
    for l in SUPPLY:
        y = r["layers"][l]["yoy"]
        line += (f"{y*100:10.0f}%" if y is not None else " " * 11)
    print(line)
print("\nGM (rev-weighted) / INV YoY, last 6 quarters")
for l in SUPPLY:
    gm = " ".join(f"{r['layers'][l]['gm']*100:5.1f}" if r["layers"][l]["gm"] else "    -" for r in rows[-6:])
    iv = " ".join(f"{r['layers'][l]['inv_yoy']*100:5.0f}" if r["layers"][l]["inv_yoy"] is not None else "    -" for r in rows[-6:])
    print(f"  {l:22s} GM {gm}   INV {iv}")
print(f"\nintegrity: net income agrees {ok}/{ok+bad} quarters since 2024")
for w in worst[:4]:
    print(f"   {w['t']:5s} {w['p']}  income {w['inc']/1e6:9.1f}m  cashflow {w['cf']/1e6:9.1f}m")
print("\nvaluation percentile (yield pct: HIGH = cheap vs own history)")
for tk in sorted(val):
    v = val[tk]
    p = f"{v['pct']:.2f}" if v["pct"] is not None else "  -"
    print(f"   {tk:5s} {v['method']:14s} {p}  hq={v['hq']:2d} {v['conf']:7s} spot {v['spot']}")
