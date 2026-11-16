#!/usr/bin/env python3
"""mikulowa_test.py - Test 6: czy przesuwnik fazowy Mikulowa czesciej blokuje import w godzinach skokow cen?

Prog ustalony PRZED liczeniem (16.11.2026), po eksploracji dni 9-10.11 (Test 5), na INNYCH dniach:

  okno     = 1.10.2026 00:00 - 9.11.2026 00:00 czasu polskiego (bez 9 i 10 listopada)
  skok     = godzina ze srednia cena RCE > 1000 zl/MWh (jak w testach 1-4)
  Mikulowa aktywna w godzinie = w co najmniej jednym MTU tej godziny dowolny element sieci
             z "Mikulowa" w nazwie ma shadow price > 0 (JAO Core, wynik rynku dnia nastepnego)
  udzial_skoki = odsetek godzin skokow z aktywna Mikulowa
  udzial_inne  = odsetek pozostalych godzin z aktywna Mikulowa
  WERDYKT: udzial_skoki >= 2 x udzial_inne -> SYGNAL; inaczej -> BRAK SYGNALU
           (oba udzialy 0 -> NIEROZSTRZYGNIETE; pokrycie danych JAO < 90% godzin -> NIEROZSTRZYGNIETE)

Kontekst bez progu: te same udzialy dla ograniczenia importu SwePol i linii Ensdorf - Vigy.

Uzycie (z folderu z cache PSE dane_pse/):
  python3 mikulowa_test.py --out wynik_test6.txt
"""
import argparse
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

JAO = "https://publicationtool.jao.eu/core/api/data/shadowPrices"
START = pd.Timestamp("2026-10-01", tz="Europe/Warsaw").tz_convert("UTC")
END = pd.Timestamp("2026-11-09", tz="Europe/Warsaw").tz_convert("UTC")
SPIKE, RATIO, MIN_COV = 1000.0, 2.0, 0.90
GROUPS = {"Mikulowa (prog)": r"miku[lł]owa",
          "SwePol import (kontekst)": r"swepol_import",
          "Ensdorf - Vigy (kontekst)": r"ensdorf.*vigy"}


def jao_day(d0, d1, cache):
    f = cache / f"shadowPrices_{d0:%Y%m%dT%H%M}.csv"
    if f.exists():
        return pd.read_csv(f, low_memory=False)
    rows, skip = [], 0
    while True:
        p = {"FromUtc": d0.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "ToUtc": d1.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
             "skip": skip, "take": 20000}
        for attempt in range(4):
            r = requests.get(JAO, params=p, timeout=120)
            if r.status_code == 200:
                break
            time.sleep(5 * (attempt + 1))
        r.raise_for_status()
        j = r.json()
        part = j.get("data", [])
        rows += part
        if len(part) < p["take"]:
            break
        skip += p["take"]
    df = pd.DataFrame(rows)
    df.to_csv(f, index=False)
    time.sleep(0.5)
    return df


def rce_hours(cache):
    parts = [pd.read_csv(f, low_memory=False) for f in sorted(Path(cache).glob("rce-pln_2026-1[01].csv"))]
    d = pd.concat(parts)
    ts = (pd.to_datetime(d["dtime_utc"], utc=True) if "dtime_utc" in d.columns else
          pd.to_datetime(d["dtime"]).dt.tz_localize("Europe/Warsaw", ambiguous="NaT").dt.tz_convert("UTC"))
    h = (ts - pd.Timedelta(seconds=1)).dt.floor("h")
    s = pd.Series(pd.to_numeric(d["rce_pln"], errors="coerce").values, index=h).groupby(level=0).mean()
    return s[(s.index >= START) & (s.index < END)].dropna()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="wynik_test6.txt")
    ap.add_argument("--cache", default="dane_pse")
    ap.add_argument("--jao-cache", default="dane_jao")
    a = ap.parse_args()
    jc = Path(a.jao_cache)
    jc.mkdir(exist_ok=True)

    price = rce_hours(a.cache)
    spike = price > SPIKE
    parts = []
    d = START
    while d < END:
        d1 = min(d + pd.Timedelta(days=1), END)
        print(f"  JAO {d:%Y-%m-%d %H:%M}Z", flush=True)
        parts.append(jao_day(d, d1, jc))
        d = d1
    sp = pd.concat([p for p in parts if len(p)], ignore_index=True)
    sp["h"] = pd.to_datetime(sp["dateTimeUtc"], utc=True).dt.floor("h")
    sp["shadowPrice"] = pd.to_numeric(sp["shadowPrice"], errors="coerce")
    covered = set(sp["h"])
    cov = price.index.isin(list(covered)).mean()

    L = ["Test 6 - Mikulowa jako ograniczenie importu w godzinach skokow (1.10-8.11.2026, bez 9-10.11)",
         f"uruchomiono: {pd.Timestamp.now():%Y-%m-%d %H:%M}",
         f"godzin z cena: {len(price)}, skokow (> {SPIKE:.0f} zl/MWh): {int(spike.sum())}, pozostalych: {int((~spike).sum())}",
         f"rekordow JAO shadowPrices: {len(sp)}, pokrycie godzin danymi JAO: {cov:.1%}", ""]
    act = sp[sp["shadowPrice"] > 0]
    names = act["cnecName"].astype(str).str.lower()
    verdict = None
    for label, rx in GROUPS.items():
        hours = set(act.loc[names.str.contains(rx, regex=True), "h"])
        on = pd.Series(price.index.isin(list(hours)), index=price.index)
        s_sk = on[spike].mean() if spike.any() else float("nan")
        s_in = on[~spike].mean() if (~spike).any() else float("nan")
        mx = act.loc[names.str.contains(rx, regex=True), "shadowPrice"].max()
        L.append(f"{label}")
        L.append(f"  aktywna w godzinach skokow: {s_sk:.1%} ({int(on[spike].sum())} z {int(spike.sum())})")
        L.append(f"  aktywna w pozostalych:      {s_in:.1%} ({int(on[~spike].sum())} z {int((~spike).sum())})")
        L.append(f"  stosunek: {s_sk / s_in:.2f}" if s_in > 0 else "  stosunek: brak (0 w pozostalych)")
        L.append(f"  max shadow price: {mx:.1f} EUR/MW" if pd.notna(mx) else "  max shadow price: brak")
        if label.startswith("Mikulowa"):
            if cov < MIN_COV:
                verdict = f"NIEROZSTRZYGNIETE (pokrycie danych JAO {cov:.0%} < {MIN_COV:.0%})"
            elif s_sk == 0 and s_in == 0:
                verdict = "NIEROZSTRZYGNIETE (Mikulowa nieaktywna w calym oknie)"
            else:
                verdict = "SYGNAL" if (s_in == 0 or s_sk >= RATIO * s_in) else "BRAK SYGNALU"
        L.append("")
    L.append(f"WERDYKT (Mikulowa, prog {RATIO:.0f}x): {verdict}")
    mik = act[names.str.contains(GROUPS['Mikulowa (prog)'], regex=True)]["cnecName"].unique()
    L.append("elementy uznane za Mikulowa: " + (", ".join(map(str, mik)) if len(mik) else "brak"))
    txt = "\n".join(L) + "\n"
    Path(a.out).write_text(txt, encoding="utf-8")
    print("\n" + txt)


if __name__ == "__main__":
    sys.exit(main())
