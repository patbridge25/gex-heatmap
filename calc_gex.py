import argparse
import re
from datetime import datetime, date, timedelta

import pandas as pd
import requests

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{}.json"
OPT_RE = re.compile(r"^(.+?)(\d{6})([CP])(\d{8})$")  # e.g. SPY261016C00300000
WINDOW = 0.08  # keep strikes within +-8% of spot


def fetch(symbol):
    r = requests.get(URL.format(symbol), headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def default_start():
    """First expiration date to include: today (New York time), or tomorrow after the 4pm close."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now()
    start = now.date()
    if now.hour >= 16:
        start += timedelta(days=1)
    return start


def compute_gex(symbol, data=None, start=None):
    """Return GEX as {symbol, spot, strikes, exps, matrix} (same shape as the web page uses).
    Expirations before `start` are dropped (already expired)."""
    if data is None:
        data = fetch(symbol)
    if start is None:
        start = default_start()
    spot = float(data["current_price"])

    rows = []
    for o in data["options"]:
        m = OPT_RE.match(o["option"])
        if not m:
            continue
        _, ymd, cp, strike = m.groups()
        rows.append({
            "expiry": datetime.strptime(ymd, "%y%m%d").date(),
            "type": cp,
            "strike": int(strike) / 1000,
            "gamma": o.get("gamma"),
            "oi": o.get("open_interest"),
        })

    df = pd.DataFrame(rows)
    df["gamma"] = pd.to_numeric(df["gamma"], errors="coerce").fillna(0)
    df["oi"] = pd.to_numeric(df["oi"], errors="coerce").fillna(0)
    df = df[df["expiry"] >= start]
    df = df[(df["strike"] >= spot * (1 - WINDOW)) & (df["strike"] <= spot * (1 + WINDOW))]

    # calls positive, puts negative (standard dealer assumption)
    sign = df["type"].map({"C": 1, "P": -1})
    df["gex"] = sign * df["gamma"] * df["oi"] * 100 * spot ** 2 * 0.01

    pv = df.pivot_table(index="strike", columns="expiry", values="gex",
                        aggfunc="sum", fill_value=0).sort_index(ascending=False)

    return {
        "symbol": symbol,
        "spot": spot,
        "strikes": [float(k) for k in pv.index],
        "exps": [f"{d.month}/{d.day}/{str(d.year)[2:]}" for d in pv.columns],
        "matrix": pv.values.tolist(),
    }


def money(v):
    a = abs(v)
    s = "-" if v < 0 else ""
    if a >= 1e9:
        return f"{s}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{s}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{s}${a / 1e3:.1f}K"
    return f"{s}${a:.0f}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("symbol", nargs="?", default="SPY")
    p.add_argument("--from", dest="start", help="first expiration date to include, e.g. 2026-10-19")
    args = p.parse_args()

    symbol = args.symbol.upper()
    start = datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else None
    d = compute_gex(symbol, start=start)
    m = pd.DataFrame(d["matrix"], index=d["strikes"], columns=d["exps"])

    flat = m.stack()
    king_strike, king_exp = flat.abs().idxmax()
    first = d["exps"][0]
    first_king = m[first].abs().idxmax()

    print(f"{d['symbol']}  spot {d['spot']:.2f}")
    print(f"{len(d['strikes'])} strikes x {len(d['exps'])} expirations")
    print("Expirations:", ", ".join(d["exps"][:10]), "...")
    print(f"Net GEX: {money(m.values.sum())}")
    print(f"All-exp King: strike {king_strike:g}, exp {king_exp}, {money(flat[(king_strike, king_exp)])}")
    print(f"First expiry ({first}) King: strike {first_king:g}, {money(m.loc[first_king, first])}")

    near = min(range(len(m)), key=lambda i: abs(m.index[i] - d["spot"]))
    lo, hi = max(0, near - 4), near + 5
    print("\nStrikes around spot, first 5 expirations:")
    print(m.iloc[lo:hi, :5].map(money).to_string())

    # per-strike totals across all expirations, to compare with "All exp"
    tot = m.sum(axis=1)
    print("\nTop 5 strikes by |total GEX| (all expirations):")
    for k in tot.abs().sort_values(ascending=False).index[:5]:
        print(f"  {k:g}: {money(tot[k])}")


if __name__ == "__main__":
    main()
