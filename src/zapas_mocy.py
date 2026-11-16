#!/usr/bin/env python3
"""pse_margines_001.py - skoki cen energii a zapas mocy w KSE (dane: publiczne API PSE).

Progi ustalone PRZED zobaczeniem wyniku (15.11.2026):

TEST 1  Czy skoki cen wynikaja z braku zapasu mocy?
        skok        = godzina ze srednia cena RCE > 1000 zl/MWh
        okno        = 2026-10-01 .. 2026-11-14
        regula      = N = liczba godzin-skokow; bierzemy N godzin o najnizszym zapasie mocy;
                      ZALICZONE, gdy >= 80% skokow wypada w tych N godzinach
        (pierwotny wariant "10% godzin o najnizszym zapasie" liczony pomocniczo - patrz raport)

TEST 2  Czy godzin z zapasem < 1 GW przybywa?
        porownanie  = 01.01-14.11.2025 vs 01.01-14.11.2026
        ROSNIE, gdy godzin w 2026 jest >= 2x wiecej niz w 2025 i co najmniej 10

Zapas mocy = pole surplus_cap_avail_tso (Nadwyzka mocy dostepna dla OSP) z raportu pk5l-wp.
Gdy pokrycie danych < 90% godzin, werdykt brzmi NIEROZSTRZYGNIETE - bez zgadywania.

Uzycie:  python3 pse_margines_001.py --out wynik_pse_margines_001.txt
"""
import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests

BASE = "https://api.raporty.pse.pl/api/"

# --- progi (nie zmieniac po zobaczeniu wyniku) ---
SPIKE_PLN = 1000.0
PASS_SHARE = 0.80
LOW_MARGIN_MW = 1000.0
T1_START, T1_END = "2026-10-01", "2026-11-14"
T2_A = ("2025-01-01", "2025-11-14")
T2_B = ("2026-01-01", "2026-11-14")
T2_RATIO, T2_MIN_HOURS = 2.0, 10
MIN_COVERAGE = 0.90


def fetch(endpoint, d0, d1_excl):
    """Pobiera rekordy z [d0, d1_excl). Probuje kolejnych pol daty, bo raporty roznia sie nazwami."""
    last_err = None
    for field in ("business_date", "dtime", "plan_dtime"):
        url = urljoin(BASE, endpoint)
        params = {"$filter": f"{field} ge '{d0}' and {field} lt '{d1_excl}'", "$first": 20000}
        rows, bad_field = [], False
        while url:
            for attempt in range(5):
                r = requests.get(url, params=params, timeout=90)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            if r.status_code == 400:
                bad_field, last_err = True, r.text[:200]
                break
            r.raise_for_status()
            j = r.json()
            rows.extend(j.get("value", []))
            nxt = j.get("nextLink") or j.get("@odata.nextLink")
            url, params = (urljoin(BASE, nxt), None) if nxt else (None, None)
            time.sleep(0.3)
        if not bad_field:
            return pd.DataFrame(rows)
    raise RuntimeError(f"{endpoint}: API odrzucilo filtr daty ({last_err})")


def load(endpoint, start, end, cache):
    """Miesiac po miesiacu, z pamiecia podreczna w CSV (biezacy miesiac zawsze pobierany na nowo)."""
    cache.mkdir(parents=True, exist_ok=True)
    this_month = pd.Timestamp.now().strftime("%Y-%m")
    parts = []
    for m in pd.period_range(start, end, freq="M"):
        f = cache / f"{endpoint}_{m}.csv"
        if f.exists() and str(m) != this_month:
            df = pd.read_csv(f, low_memory=False)
        else:
            print(f"  pobieram {endpoint} {m} ...", flush=True)
            df = fetch(endpoint, f"{m}-01", (m + 1).strftime("%Y-%m-01"))
            df.to_csv(f, index=False)
        parts.append(df)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def hour_key(df, utc_col, local_col):
    """Poczatek godziny (UTC). Znaczniki PSE oznaczaja KONIEC okresu, stad -1 s."""
    if utc_col in df.columns:
        ts = pd.to_datetime(df[utc_col], utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(df[local_col], errors="coerce").dt.tz_localize(
            "Europe/Warsaw", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return (ts - pd.Timedelta(seconds=1)).dt.floor("h")


def hourly(df, cols, utc_col, local_col):
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    df["h"] = hour_key(df, utc_col, local_col)
    for c in cols:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    return df.dropna(subset=["h"]).groupby("h")[cols].mean()


def hourly_plan(df):
    cols = ["surplus_cap_avail_tso", "grid_demand_fcst"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.copy()
    df["h"] = hour_key(df, "plan_dtime_utc", "plan_dtime")
    if "publication_ts" in df.columns:
        df = df.sort_values("publication_ts")
    for c in cols:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    return df.dropna(subset=["h"]).groupby("h")[cols].last()


def align_plan(plan, real):
    """Dobiera przesuniecie planu (-1/0/+1 h) po zgodnosci prognozy zapotrzebowania z wykonaniem.
    Uzywa wylacznie zapotrzebowania, nigdy ceny."""
    best, best_c = 0, -2.0
    for s in (-1, 0, 1):
        p = plan["grid_demand_fcst"].copy()
        p.index = p.index + pd.Timedelta(hours=s)
        c = p.corr(real["demand"])
        if pd.notna(c) and c > best_c:
            best, best_c = s, c
    out = plan.copy()
    out.index = out.index + pd.Timedelta(hours=best)
    return out, best, best_c


def window(df, start, end):
    a = pd.Timestamp(start, tz="Europe/Warsaw").tz_convert("UTC")
    b = (pd.Timestamp(end, tz="Europe/Warsaw") + pd.Timedelta(days=1)).tz_convert("UTC")
    return df[(df.index >= a) & (df.index < b)], int((b - a) / pd.Timedelta(hours=1))


def test1(df, L):
    w, total = window(df, T1_START, T1_END)
    w = w.dropna(subset=["price"])
    cov = w["margin"].notna().sum() / total
    spikes = w["price"] > SPIKE_PLN
    n = int(spikes.sum())
    L.append(f"TEST 1  okno {T1_START}..{T1_END}, godzin w oknie: {total}")
    L.append(f"  godzin z cena: {len(w)}, pokrycie zapasu mocy: {cov:.1%}")
    L.append(f"  skokow (> {SPIKE_PLN:.0f} zl/MWh): {n} ({n / max(len(w), 1):.1%} godzin)")
    if n:
        # pomocniczo: obciazenie resztkowe (zapotrzebowanie - wiatr - PV), N godzin o najwyzszym
        r = w.dropna(subset=["residual"])
        rs = r["price"] > SPIKE_PLN
        if rs.sum():
            top = r["residual"].rank(method="first", ascending=False) <= rs.sum()
            L.append(f"  [pomocniczo] skoki w N godzinach o najwyzszym obciazeniu resztkowym: "
                     f"{(rs & top).sum() / rs.sum():.1%}")
    if cov < MIN_COVERAGE or n == 0:
        L.append("  WERDYKT: NIEROZSTRZYGNIETE (" +
                 ("brak skokow w oknie" if n == 0 and cov >= MIN_COVERAGE
                  else "za malo danych o zapasie mocy w API") + ")")
        return
    m = w.dropna(subset=["margin"])
    ms = m["price"] > SPIKE_PLN
    nm = int(ms.sum())
    low_n = m["margin"].rank(method="first") <= nm
    share = (ms & low_n).sum() / nm
    L.append(f"  skoki w N={nm} godzinach o najnizszym zapasie: {share:.1%} "
             f"(losowo byloby ok. {nm / len(m):.1%}; prog {PASS_SHARE:.0%})")
    low10 = m["margin"] <= m["margin"].quantile(0.10)
    ceil10 = min(1.0, low10.sum() / nm)
    L.append(f"  [pierwotny wariant 10%] {(ms & low10).sum() / nm:.1%} "
             f"(maksimum mozliwe do osiagniecia: {ceil10:.1%})")
    L.append(f"  mediana zapasu: w skokach {m.loc[ms, 'margin'].median():.0f} MW, "
             f"poza skokami {m.loc[~ms, 'margin'].median():.0f} MW")
    L.append("  WERDYKT: " + ("ZALICZONE" if share >= PASS_SHARE else "NIEZALICZONE"))


def test2(df, L):
    res = []
    for a, b in (T2_A, T2_B):
        w, total = window(df, a, b)
        cov = w["margin"].notna().sum() / total
        low = int((w["margin"] < LOW_MARGIN_MW).sum())
        res.append((cov, low))
        L.append(f"  {a}..{b}: godzin z zapasem < {LOW_MARGIN_MW:.0f} MW: {low} "
                 f"(pokrycie danych {cov:.1%})")
    (c25, h25), (c26, h26) = res
    if min(c25, c26) < MIN_COVERAGE:
        L.append("  WERDYKT: NIEROZSTRZYGNIETE (za malo danych o zapasie mocy w API)")
    else:
        up = h26 >= T2_RATIO * h25 and h26 >= T2_MIN_HOURS
        L.append("  WERDYKT: " + ("ROSNIE" if up else "NIE ROSNIE"))


def capture(df, L):
    w, _ = window(df, T1_START, T1_END)
    w = w.dropna(subset=["price", "wi"])
    if len(w) and w["wi"].sum() > 0:
        cap = (w["wi"] * w["price"]).sum() / w["wi"].sum()
        base = w["price"].mean()
        L.append(f"  cena srednia: {base:.0f} zl/MWh, cena uchwycona przez wiatr: {cap:.0f} zl/MWh "
                 f"({cap / base:.0%} sredniej)")
        L.append(f"  srednia generacja wiatru: w skokach "
                 f"{w.loc[w['price'] > SPIKE_PLN, 'wi'].mean():.0f} MW, "
                 f"poza skokami {w.loc[w['price'] <= SPIKE_PLN, 'wi'].mean():.0f} MW")


def build(price, real, plan):
    plan, shift, corr = align_plan(plan, real)
    df = price.join(real, how="outer").join(plan[["surplus_cap_avail_tso"]], how="outer")
    df = df.rename(columns={"rce_pln": "price", "surplus_cap_avail_tso": "margin"})
    df["residual"] = df["demand"] - df["wi"] - df["pv"]
    return df, shift, corr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="wynik_pse_margines_001.txt")
    ap.add_argument("--cache", default="dane_pse")
    a = ap.parse_args()
    cache = Path(a.cache)
    start, end = T2_A[0], T2_B[1]

    price = hourly(load("rce-pln", start, end, cache), ["rce_pln"], "dtime_utc", "dtime")
    real = hourly(load("his-wlk-cal", start, end, cache), ["demand", "wi", "pv"], "dtime_utc", "dtime")
    plan = hourly_plan(load("pk5l-wp", start, end, cache))
    df, shift, corr = build(price, real, plan)

    L = ["pse_margines_001 - skoki cen a zapas mocy (API PSE: rce-pln, his-wlk-cal, pk5l-wp)",
         f"uruchomiono: {pd.Timestamp.now():%Y-%m-%d %H:%M}",
         f"godzin lacznie: {len(df)}, zakres: {df.index.min()} .. {df.index.max()}",
         f"wyrownanie planu PK5L: przesuniecie {shift:+d} h, korelacja prognozy z wykonaniem {corr:.3f}",
         ""]
    test1(df, L)
    L += ["", "TEST 2  godziny z zapasem mocy ponizej 1 GW"]
    test2(df, L)
    L += ["", f"INFORMACYJNIE  wiatr w oknie {T1_START}..{T1_END}"]
    capture(df, L)
    txt = "\n".join(L) + "\n"
    Path(a.out).write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"zapisano: {a.out}")


if __name__ == "__main__":
    sys.exit(main())
