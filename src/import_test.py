#!/usr/bin/env python3
"""import_test.py - Test 5: czy w najdrozszych kwadransach 9-10.11.2026 rynek wykorzystal mozliwosci importu?

Prog ustalony PRZED liczeniem (16.11.2026):

  kwadranse krytyczne = kwadranse 9 i 10 listopada 2026 z cena RCE > 3000 zl/MWh (dane PSE)
  dla kazdego: wykorzystanie importu = netto pozycja PL (Core, wynik rynku dnia nastepnego)
               / minimalna mozliwa netto pozycja PL (maksymalny import w domenie flow-based)
               (obie z JAO, publicationtool.jao.eu/core; import = wartosci ujemne)
  kwadrans "na limicie", gdy wykorzystanie >= 95%
  WERDYKT:  >= 80% kwadransow na limicie  -> IMPORT NA LIMICIE (polaczenia ograniczaly)
            <= 20%                         -> IMPORT NIE BYL OGRANICZENIEM
            pomiedzy                       -> MIESZANE

Pomocniczo: liczba aktywnych ograniczen sieci (shadow price > 0) w kwadransach krytycznych
i ile z nich dotyczy elementow PSE.

Ograniczenia: dotyczy tylko regionu Core (granice PL-DE, PL-CZ, PL-SK). Granice z Litwa, Szwecja
i Ukraina dzialaja poza flow-based i nie sa tu liczone.

Uzycie (z folderu, w ktorym jest cache PSE dane_pse/):
  python3 import_test.py --out wynik_test5.txt
"""
import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

JAO = "https://publicationtool.jao.eu/core/api/data/"
FROM_UTC, TO_UTC = "2026-11-08T23:00:00.000Z", "2026-11-10T23:00:00.000Z"
SPIKE = 3000.0
AT_LIMIT, PASS_HI, PASS_LO = 0.95, 0.80, 0.20


def jao(endpoint, L):
    rows, skip, take = [], 0, 50000
    while True:
        r = requests.get(JAO + endpoint, params={"FromUtc": FROM_UTC, "ToUtc": TO_UTC,
                                                 "skip": skip, "take": take}, timeout=120)
        if r.status_code != 200:
            L.append(f"  JAO {endpoint}: HTTP {r.status_code} {r.text[:200]}")
            return pd.DataFrame()
        j = r.json()
        part = j.get("data", j if isinstance(j, list) else [])
        rows += part
        total = j.get("totalRowsWithFilter", len(rows)) if isinstance(j, dict) else len(rows)
        if len(part) < take or len(rows) >= total:
            break
        skip += take
        time.sleep(0.5)
    df = pd.DataFrame(rows)
    L.append(f"  JAO {endpoint}: {len(df)} rekordow; pola: {', '.join(map(str, df.columns[:40]))}")
    if len(df):
        L.append(f"    przyklad: {df.iloc[0].to_dict()}")
    return df


def time_col(df):
    for c in df.columns:
        if "utc" in c.lower() or "datetime" in c.lower():
            return c
    return None


def pl_cols(df):
    return [c for c in df.columns if "PL" in c.upper().replace("PLAN", "") and c.upper().endswith("PL")
            or c.upper() in ("PL", "HUB_PL")]


def rce_quarters(cache):
    parts = [pd.read_csv(f, low_memory=False) for f in sorted(Path(cache).glob("rce-pln_2026-11*.csv"))]
    if not parts:
        return pd.Series(dtype=float)
    d = pd.concat(parts)
    ts = (pd.to_datetime(d["dtime_utc"], utc=True) if "dtime_utc" in d.columns else
          pd.to_datetime(d["dtime"]).dt.tz_localize("Europe/Warsaw", ambiguous="NaT").dt.tz_convert("UTC"))
    q = (ts - pd.Timedelta(seconds=1)).dt.floor("15min")
    return pd.Series(pd.to_numeric(d["rce_pln"], errors="coerce").values, index=q).groupby(level=0).mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="wynik_test5.txt")
    ap.add_argument("--cache", default="dane_pse")
    a = ap.parse_args()
    L = ["Test 5 - wykorzystanie importu w najdrozszych kwadransach 9-10.11.2026 (JAO Core + PSE)",
         f"uruchomiono: {pd.Timestamp.now():%Y-%m-%d %H:%M}", "", "DANE"]

    rce = rce_quarters(a.cache)
    a0, a1 = pd.Timestamp(FROM_UTC), pd.Timestamp(TO_UTC)
    rce = rce[(rce.index >= a0) & (rce.index < a1)]
    crit = rce[rce > SPIKE]
    L.append(f"  RCE z cache PSE: {len(rce)} kwadransow 9-10.11; krytycznych (> {SPIKE:.0f} zl/MWh): {len(crit)}")

    mnp = jao("maxNetPos", L)
    npos = jao("netPos", L)
    sp = jao("shadowPrices", L)

    verdict_lines = ["", "TEST 5"]
    tm, tn = time_col(mnp), time_col(npos)
    pm, pn = pl_cols(mnp), pl_cols(npos)
    L.append(f"  rozpoznane: maxNetPos czas={tm} PL={pm}; netPos czas={tn} PL={pn}")
    min_col = next((c for c in pm if "min" in c.lower()), None)
    if not (len(crit) and tm and tn and min_col and pn):
        verdict_lines.append("  WERDYKT: NIEROZSTRZYGNIETE - nie rozpoznano pol danych; patrz sekcja DANE")
    else:
        m = mnp.assign(q=pd.to_datetime(mnp[tm], utc=True)).set_index("q")[min_col].astype(float).sort_index()
        n = npos.assign(q=pd.to_datetime(npos[tn], utc=True)).set_index("q")["hub_PL" if "hub_PL" in pn else pn[0]].astype(float)
        # maxNetPos publikowane godzinowo, netPos co kwadrans: kazdy kwadrans dostaje wartosc swojej godziny
        m_q = m.reindex(m.index.union(crit.index)).ffill().reindex(crit.index)
        verdict_lines.append(f"  maxNetPos: {len(m)} wartosci (godzinowe), przypisane do kwadransow wg godziny")
        t = pd.DataFrame({"rce": crit, "netpos": n.reindex(crit.index), "min_netpos": m_q})
        t["wykorzystanie"] = t["netpos"] / t["min_netpos"]
        t = t.dropna()
        verdict_lines.append(f"  kwadransow krytycznych z danymi JAO: {len(t)} z {len(crit)}")
        for q, r in t.iterrows():
            verdict_lines.append(f"  {q.tz_convert('Europe/Warsaw'):%d.%m %H:%M}  RCE {r.rce:7.0f}  "
                                 f"netto PL {r.netpos:8.0f} MW  maks. import {r.min_netpos:8.0f} MW  "
                                 f"wykorzystanie {r.wykorzystanie:6.1%}")
        if len(t):
            share = (t["wykorzystanie"] >= AT_LIMIT).mean()
            verdict_lines.append(f"  kwadransow na limicie (>= {AT_LIMIT:.0%}): {share:.0%}")
            verdict_lines.append("  WERDYKT: " + ("IMPORT NA LIMICIE" if share >= PASS_HI else
                                                  "IMPORT NIE BYL OGRANICZENIEM" if share <= PASS_LO else "MIESZANE"))
        else:
            verdict_lines.append("  WERDYKT: NIEROZSTRZYGNIETE - brak zgodnych znacznikow czasu")

    ts_ = time_col(sp)
    if len(sp) and ts_ and "shadowPrice" in sp.columns:
        s_ = sp.assign(q=pd.to_datetime(sp[ts_], utc=True), shadowPrice=pd.to_numeric(sp["shadowPrice"], errors="coerce"))
        s_ = s_[s_["shadowPrice"] > 0]
        all_q = rce.index
        other = all_q.difference(crit.index)
        verdict_lines += ["", "EKSPLORACYJNIE (dodane po wyniku wersji 001, bez progu): aktywne ograniczenia sieci",
                          f"  kwadranse krytyczne: {len(crit)}, pozostale kwadranse 9-10.11: {len(other)}",
                          f"  {'element (cnecName)':42s} {'tso':10s} {'PTDF PL':>8s} {'kryt.':>6s} {'inne':>6s} {'max SP':>8s}"]
        g = s_.groupby("cnecName")
        rows = []
        for k, d in g:
            qs = set(d["q"])
            rows.append((k, d["tso"].iloc[0] if "tso" in d else "", pd.to_numeric(d.get("hub_PL"), errors="coerce").mean(),
                         len(qs & set(crit.index)) / max(len(crit), 1), len(qs & set(other)) / max(len(other), 1),
                         d["shadowPrice"].max()))
        rows.sort(key=lambda r: -r[3])
        for k, tso, ptdf, c, o, mx in rows[:12]:
            verdict_lines.append(f"  {str(k)[:42]:42s} {str(tso)[:10]:10s} {ptdf:8.3f} {c:6.0%} {o:6.0%} {mx:8.1f}")
        verdict_lines.append("  kryt./inne = odsetek kwadransow, w ktorych element byl aktywnym ograniczeniem; "
                             "SP = shadow price, EUR/MW")
        if "hub_PL_SE4_SwePol" in npos.columns and "minPL_SE4_SwePol" in mnp.columns:
            sw = npos.assign(q=pd.to_datetime(npos[tn], utc=True)).set_index("q")["hub_PL_SE4_SwePol"].astype(float)
            swm = mnp.assign(q=pd.to_datetime(mnp[tm], utc=True)).set_index("q")["minPL_SE4_SwePol"].astype(float).sort_index()
            swm_q = swm.reindex(swm.index.union(crit.index)).ffill().reindex(crit.index)
            u = (sw.reindex(crit.index) / swm_q).dropna()
            verdict_lines.append(f"  SwePol w kwadransach krytycznych: wykorzystanie srednio {u.mean():.0%}, "
                                 f"na limicie (>=95%) w {(u >= 0.95).mean():.0%} kwadransow")

    txt = "\n".join(L + verdict_lines) + "\n"
    Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    sys.exit(main())
