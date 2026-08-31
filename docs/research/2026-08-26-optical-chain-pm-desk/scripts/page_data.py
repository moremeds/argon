"""Assemble exactly what the page renders. Nothing derived at render time."""
import json, os, datetime as dt

H = os.path.dirname(os.path.abspath(__file__))
P = json.load(open(os.path.join(H, "pm.json")))
ALL = json.load(open(os.path.join(H, "..", "alldata.json")))

series, val, rows = P["series"], P["val"], P["rows"]
LAYERS = P["layers"]
layer_of = {}
for L in LAYERS:
    for t in L["tickers"]:
        layer_of.setdefault(t, []).append(L["name"])

SHORT = {"Upstream-Components": "Components", "Semi-DSP-Switch": "DSP / switch silicon",
         "Module-Transceiver": "Modules", "Systems-Networking": "Systems",
         "Customer-Cloud": "Hyperscale demand"}

cal = {c[0]: {"date": c[1], "when": c[2], "period": c[3], "px": c[4],
              "move_usd": c[5], "past": c[6], "src": c[7]} for c in ALL["calendar"]}
expo = {e["ticker"]: e for e in ALL["exposures"]}

def latest(tk):
    ks = sorted(int(k) for k in series[tk])
    return ks[-1], series[tk][str(ks[-1])]

names = []
for tk in sorted(series):
    k, r = latest(tk)
    prev = series[tk].get(str(k - 4))
    v = val.get(tk, {})
    c = cal.get(tk)
    e = expo.get(tk)
    names.append({
        "t": tk,
        "layers": [SHORT[l] for l in layer_of.get(tk, [])],
        "period": r["period"], "filed": r["filed"],
        "rev": r["rev"],
        "rev_yoy": (r["rev"] / prev["rev"] - 1) if prev and prev.get("rev") and r.get("rev") else None,
        "gm": r["gm"],
        "gm_d": (r["gm"] - prev["gm"]) if prev and prev.get("gm") is not None and r.get("gm") is not None else None,
        "om": r["om"],
        "dio": r["dio"],
        "inv_yoy": (r["inv"] / prev["inv"] - 1) if prev and prev.get("inv") and r.get("inv") else None,
        "val_pct": v.get("pct"), "val_method": v.get("method"),
        "val_conf": v.get("conf"), "val_type": v.get("type"), "spot": v.get("spot"),
        "next": c["date"] if c else None,
        "next_when": c["when"] if c else None,
        "next_src": c["src"] if c else None,
        # UW publishes implied_move as a DOLLAR figure at the quoted price.
        "implied": (c["move_usd"] / c["px"]) if c and c.get("px") else None,
        "past_moves": c["past"] if c else None,
        "expo": e["mag"] if e else None,
        "expo_ref": e["ref"] if e else None,
    })

# revenue-share sparkline series per layer, and capex series
spark = {}
for L in LAYERS:
    if L["name"] == "Customer-Cloud":
        continue
    spark[L["name"]] = [
        {"q": r["q"], "gm": r["layers"][L["name"]]["gm"],
         "yoy": r["layers"][L["name"]]["yoy"],
         "inv": r["layers"][L["name"]]["inv_yoy"]}
        for r in rows]

json.dump({
    "asof": "2026-08-26",
    "calendar_fetched": ALL["calendar_fetched_at"],
    "layers": [{"name": L["name"], "short": SHORT[L["name"]], "rank": L["rank"],
                "tickers": L["tickers"]} for L in LAYERS],
    "rows": rows, "names": names, "spark": spark,
    "integrity": P["integrity"],
    "livetest": ALL["livetest"],
    "expo_all": ALL["exposures"],
}, open(os.path.join(H, "page.json"), "w"))

print("names", len(names))
for n in names:
    if n["t"] in ("COHR", "CRDO", "ANET", "AMZN"):
        print(n["t"], n["period"], "rev", n["rev"], "yoy", n["rev_yoy"],
              "gm_d", n["gm_d"], "val", n["val_pct"], "next", n["next"],
              "implied", n["implied"])
print("\nchain totals 2026Q2:")
last = rows[-1]
print(" capex", round(last["capex"]/1e9,1), "yoy", last["capex_yoy"])
for l, d in last["layers"].items():
    print(f"  {l:22s} rev={d['rev'] and round(d['rev']/1e9,2)} yoy={d['yoy']} inv={d['inv_yoy']} n={d['n']}")
