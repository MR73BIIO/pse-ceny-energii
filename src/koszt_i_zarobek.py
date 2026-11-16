#!/usr/bin/env python3
"""pse_margines_006.py - czy skoki cen da sie wyjasnic kosztem paliwa i CO2, i kto na nich zarobil.

Progi ustalone PRZED zobaczeniem wyniku (15.11.2026):

TEST 3  Czy skoki cen wynikaja z kosztu, czy z ofert ponad koszt?
        skok    = godzina z cena RCE > 1000 zl/MWh (jak w 001)
        okno    = 2026-10-01 .. 2026-11-14 (jak w 001)
        sufit   = koszt zmienny najdrozszej typowej technologii: stara szczytowa jednostka gazowa
                  sufit = gaz / 0.38 + 0.53 t CO2/MWh * EUA * EURPLN
        regula  = jesli >= 50% godzin-skokow ma cene powyzej sufitu -> "SKOKI PONAD KOSZT"
                  (skokow nie da sie wyjasnic kosztem paliwa i CO2, tylko ofertami);
                  w przeciwnym razie "SKOKI W GRANICACH KOSZTU"

TEST 4  Czy ubytki mocy duzych grup rosna w godzinach skokow? (raport pdwkseub, pole non_us_cap,
        tylko ubytki elektrowniane - bez ograniczen sieciowych nakladanych przez PSE; godziny 7-21)
        4a  ubytki grupy w godzinach skokow vs w zwyklych godzinach o tej samej porze dnia;
            SYGNAL, gdy w skokach sa wyzsze o >= 20%
        4b  zmiennosc w ciagu dnia: korelacja ubytkow grupy z cena po odjeciu sredniej dnia
            (prawdziwe awarie trwaja dniami, nie podazaja za cena z godziny na godzine);
            SYGNAL, gdy srednia korelacja >= 0.30
        Sygnal nie jest dowodem zamiaru - awarie same podnosza cene.

KTO POKRYL I ZAROBIL (pomiar, bez progu)
        - struktura pokrycia zapotrzebowania w godzinach skokow i poza nimi (his-wlk-cal)
        - import/eksport wg kraju (przeplywymocy)
        - elektrownie centralnie dysponowane (gen-jw): produkcja, wartosc po cenie spot
          i nadwyzka ponad sufit w godzinach skokow, zsumowane po wlascicielach

Kurs EURPLN pobierany z NBP. Ceny gazu i EUA: z pliku --ceny-csv (kolumny: data,gaz_pln_mwh,eua_eur)
albo stale --gaz / --eua dla calego okna (przyblizenie - zaznaczone w raporcie).

Uzycie:  python3 pse_margines_002.py --out wynik_pse_margines_006.txt [--ceny-csv ceny.csv]
"""
import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests

BASE = "https://api.raporty.pse.pl/api/"

# --- progi i parametry (nie zmieniac po zobaczeniu wyniku) ---
SPIKE_PLN = 1000.0
T3_SHARE = 0.50
T4A_RATIO = 1.20
T4B_CORR = 0.30
T4_HOURS = range(7, 21)
T4_GROUPS = ["PGE", "Tauron", "Orlen (z Energa)", "Enea"]
EFF_PEAKER = 0.38
CO2_PEAKER_T = 0.53
WIN_START, WIN_END = "2026-10-01", "2026-11-14"

# Wlasciciele elektrowni (dopasowanie po fragmencie nazwy). DO WERYFIKACJI - nieznane trafiaja do "inni/?".
OWNERS = {
    "PGE": ["GRYFINO", "BEŁCHAT", "BELCHAT", "TURÓW", "TUROW", "OPOLE", "RYBNIK", "DOLNA ODRA", "ŻARNOW", "ZARNOW",
            "PORĄBKA", "PORABKA", "SOLINA", "POMORZANY", "GORZÓW", "GORZOW", "LUBLIN", "WROTK",
            "BYDGOSZCZ", "ZIELONA", "KRAKÓW", "KRAKOW", "ŁĘG", "RZESZÓW", "RZESZOW", "KIELCE"],
    "Enea": ["KOZIENIC", "POŁANIEC", "POLANIEC"],
    "Tauron": ["JAWORZNO", "ŁAGISZ", "LAGISZ", "ŁAZISK", "LAZISK", "SIERSZ"],
    "Tauron+Orlen (spolka wspolna)": ["STALOWA"],
    "Orlen (z Energa)": ["OSTROŁ", "OSTROL", "PŁOCK", "PLOCK", "WŁOCŁAW", "WLOCLAW", "SIEKIERK",
                         "ŻERAŃ", "ZERAN", "GRUDZI"],
    "ZE PAK": ["PĄTNÓW", "PATNOW", "ADAMÓW", "ADAMOW", "KONIN"],
}


def fetch(endpoint, d0, d1_excl):
    last_err = None
    for field in ("business_date", "dtime"):
        url = urljoin(BASE, endpoint)
        params = {"$filter": f"{field} ge '{d0}' and {field} lt '{d1_excl}'", "$first": 20000}
        rows, bad = [], False
        while url:
            for attempt in range(5):
                r = requests.get(url, params=params, timeout=120)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            if r.status_code == 400:
                bad, last_err = True, r.text[:200]
                break
            r.raise_for_status()
            j = r.json()
            rows.extend(j.get("value", []))
            nxt = j.get("nextLink") or j.get("@odata.nextLink")
            url, params = (urljoin(BASE, nxt), None) if nxt else (None, None)
            time.sleep(0.3)
        if not bad:
            return pd.DataFrame(rows)
    raise RuntimeError(f"{endpoint}: API odrzucilo filtr daty ({last_err})")


def load(endpoint, start, end, cache, by_day=False):
    """Pamiec podreczna w CSV; biezacy miesiac zawsze na nowo. by_day dla duzych raportow (gen-jw)."""
    cache.mkdir(parents=True, exist_ok=True)
    this_month = pd.Timestamp.now().strftime("%Y-%m")
    parts = []
    for m in pd.period_range(start, end, freq="M"):
        f = cache / f"{endpoint}_{m}.csv"
        if f.exists() and str(m) != this_month:
            parts.append(pd.read_csv(f, low_memory=False))
            continue
        print(f"  pobieram {endpoint} {m} ...", flush=True)
        if by_day:
            days = pd.date_range(f"{m}-01", (m + 1).to_timestamp() - pd.Timedelta(days=1))
            df = pd.concat([fetch(endpoint, f"{d:%Y-%m-%d}", f"{d + pd.Timedelta(days=1):%Y-%m-%d}")
                            for d in days], ignore_index=True)
        else:
            df = fetch(endpoint, f"{m}-01", (m + 1).strftime("%Y-%m-01"))
        df.to_csv(f, index=False)
        parts.append(df)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def hour_key(df):
    """Poczatek godziny (UTC). Znaczniki PSE oznaczaja KONIEC okresu, stad -1 s."""
    if "dtime_utc" in df.columns:
        ts = pd.to_datetime(df["dtime_utc"], utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(df["dtime"], errors="coerce").dt.tz_localize(
            "Europe/Warsaw", ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return (ts - pd.Timedelta(seconds=1)).dt.floor("h")


def hourly(df, cols):
    df = df.copy()
    df["h"] = hour_key(df)
    for c in cols:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    return df.dropna(subset=["h"]).groupby("h")[cols].mean()


def in_window(idx):
    a = pd.Timestamp(WIN_START, tz="Europe/Warsaw").tz_convert("UTC")
    b = (pd.Timestamp(WIN_END, tz="Europe/Warsaw") + pd.Timedelta(days=1)).tz_convert("UTC")
    return (idx >= a) & (idx < b)


def eurpln_nbp(start, end):
    r = requests.get(f"https://api.nbp.pl/api/exchangerates/rates/a/eur/{start}/{end}/?format=json",
                     timeout=60)
    r.raise_for_status()
    s = pd.Series({pd.Timestamp(x["effectiveDate"]): x["mid"] for x in r.json()["rates"]})
    return s.reindex(pd.date_range(start, end)).ffill().bfill()


def ceiling_by_day(args):
    days = pd.date_range(WIN_START, WIN_END)
    fx = eurpln_nbp(WIN_START, WIN_END)
    if args.ceny_csv:
        c = pd.read_csv(args.ceny_csv, parse_dates=["data"]).set_index("data")
        have = c["gaz_pln_mwh"].reindex(days).notna().sum()
        gas = c["gaz_pln_mwh"].reindex(days).ffill().bfill()
        eua = (c["eua_eur"].reindex(days).ffill().bfill() if "eua_eur" in c.columns
               else pd.Series(args.eua, index=days))
        src = (f"gaz dziennie z pliku {args.ceny_csv} ({have} z {len(days)} dni, braki uzupelnione "
               f"sasiednim dniem; srednia {gas.mean():.1f} zl/MWh)")
    else:
        gas = pd.Series(args.gaz, index=days)
        eua = pd.Series(args.eua, index=days)
        src = f"stale: gaz {args.gaz} zl/MWh, EUA {args.eua} EUR (PRZYBLIZENIE)"
    ceil = gas / EFF_PEAKER + CO2_PEAKER_T * eua * fx
    return ceil, src, fx.mean()


def co2_daily(df, fx):
    """Dzienna cena CO2 w zl/t z raportu PSE rcco2. Jednostke rozpoznaje po nazwie pola."""
    if df.empty:
        return "rcco2: brak danych", None
    d = df.copy()
    dcol = "business_date" if "business_date" in d.columns else None
    if dcol is None:
        return "rcco2: brak pola daty, pola: " + ", ".join(map(str, d.columns[:12])), None
    num = [c for c in d.columns if c not in (dcol,) and "ts" not in c and "time" not in c
           and pd.to_numeric(d[c], errors="coerce").notna().mean() > 0.9]
    info = "rcco2 pola liczbowe: " + ", ".join(f"{c} (sr. {pd.to_numeric(d[c]).mean():.2f})" for c in num)
    eur = [c for c in num if "eur" in c.lower()]
    pln = [c for c in num if "pln" in c.lower()]
    d[dcol] = pd.to_datetime(d[dcol])
    if pln:
        s = d.groupby(dcol)[pln[0]].mean().astype(float)
        return info + f"; uzyte {pln[0]} jako zl/t", s
    if eur:
        s = d.groupby(dcol)[eur[0]].mean().astype(float) * fx
        return info + f"; uzyte {eur[0]} jako EUR/t x EURPLN", s
    return info + "; jednostka niejasna - CO2 ze stalej", None


def test4(ub, price, spike):
    L = ["TEST 4  ubytki mocy duzych grup a skoki cen (godz. 7-21, ubytki elektrowniane)"]
    if ub.empty or not {"power_plant", "non_us_cap"} <= set(ub.columns):
        L.append("  NIEROZSTRZYGNIETE: brak danych pdwkseub lub inne pola: "
                 + ", ".join(map(str, ub.columns[:12])))
        return L
    u = ub.copy()
    u["h"] = hour_key(u)
    u["non_us_cap"] = pd.to_numeric(u["non_us_cap"], errors="coerce")
    u["grupa"] = u["power_plant"].map(owner)
    key = "resource_code" if "resource_code" in u.columns else "power_plant"
    per_unit = u.groupby(["h", "grupa", key])["non_us_cap"].mean().reset_index()
    tab = per_unit.groupby(["h", "grupa"])["non_us_cap"].sum().unstack().reindex(price.index)
    loc = price.index.tz_convert("Europe/Warsaw")
    mask = pd.Series(loc.hour, index=price.index).isin(T4_HOURS)
    day = pd.Series(loc.normalize(), index=price.index)
    hod = pd.Series(loc.hour, index=price.index)
    cov = tab.notna().any(axis=1)[mask].mean()
    L.append(f"  pokrycie godzin danymi o ubytkach: {cov:.1%}")
    L.append(f"  {'grupa':18s} {'skoki MW':>9s} {'oczek. MW':>10s} {'4a stosunek':>12s} {'4b korelacja':>13s}  werdykt")
    for g in T4_GROUPS:
        if g not in tab.columns:
            L.append(f"  {g:18s} brak jednostek w danych")
            continue
        x = tab[g][mask]
        sp, hh = spike[mask], hod[mask]
        normal = x[~sp].groupby(hh[~sp]).mean()
        expected = hh[sp].map(normal).mean()
        actual = x[sp].mean()
        ratio = actual / expected if expected and expected > 0 else float("nan")
        d = day[mask]
        xd = x - x.groupby(d).transform("mean")
        pd_ = price[mask] - price[mask].groupby(d).transform("mean")
        cors = pd.concat([xd, pd_], axis=1).groupby(d).apply(
            lambda t: t.iloc[:, 0].corr(t.iloc[:, 1]) if t.iloc[:, 0].std() > 0 else float("nan"))
        cor = cors.mean()
        v = []
        if ratio >= T4A_RATIO:
            v.append("4a SYGNAL")
        if cor >= T4B_CORR:
            v.append("4b SYGNAL")
        L.append(f"  {g:18s} {actual:9.0f} {expected:10.0f} {ratio:12.2f} {cor:13.2f}  "
                 + (", ".join(v) if v else "brak sygnalu")
                 + f"  (dni z ruchem ubytkow: {cors.notna().sum()})")
    L.append(f"  progi: 4a >= {T4A_RATIO:.2f}, 4b >= {T4B_CORR:.2f}")
    return L


def owner(name):
    n = str(name).upper()
    for o, keys in OWNERS.items():
        if any(k in n for k in keys):
            return o
    return "inni/?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="wynik_pse_margines_006.txt")
    ap.add_argument("--cache", default="dane_pse")
    ap.add_argument("--ceny-csv", dest="ceny_csv")
    ap.add_argument("--gaz", type=float, default=406.0)
    ap.add_argument("--eua", type=float, default=82.0)
    a = ap.parse_args()
    cache = Path(a.cache)

    price = hourly(load("rce-pln", WIN_START, WIN_END, cache), ["rce_pln"])["rce_pln"]
    mixcols = ["demand", "wi", "pv", "jgw1", "jgw2", "jgm1", "jgm2", "jga", "jnwrb", "swm_p", "swm_np"]
    mix = hourly(load("his-wlk-cal", WIN_START, WIN_END, cache), mixcols)
    notes = []

    def optional(endpoint, **kw):
        """Raporty dodatkowe: blad 404 nie przerywa liczenia, tylko trafia do raportu."""
        try:
            return load(endpoint, WIN_START, WIN_END, cache, **kw)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            notes.append(f"raport '{endpoint}' niedostepny w API (HTTP {code}) - pominiety")
            return pd.DataFrame()

    flows = optional("przeplywy-mocy")
    if flows.empty:
        flows = optional("przeplywymocy")
    co2 = optional("rcco2")
    ub = optional("pdwkseub", by_day=True)
    gen = optional("gen-jw", by_day=True)

    price = price[in_window(price.index)].dropna()
    ceil_day, src, fx = ceiling_by_day(a)
    co2_note, eua_day = co2_daily(co2, fx)
    gas_day = None
    if a.ceny_csv:
        c = pd.read_csv(a.ceny_csv, parse_dates=["data"]).set_index("data")
        gas_day = c["gaz_pln_mwh"].reindex(ceil_day.index).ffill().bfill()
    if eua_day is not None:
        days = ceil_day.index
        eua_pln = eua_day.reindex(days).ffill().bfill()
        gas_part = gas_day if gas_day is not None else a.gaz
        ceil_day = gas_part / EFF_PEAKER + CO2_PEAKER_T * eua_pln
        src = (src if gas_day is not None else f"gaz stala {a.gaz} zl/MWh (PRZYBLIZENIE)") \
            + "; CO2 dziennie z PSE rcco2"
    local_day = price.index.tz_convert("Europe/Warsaw").normalize().tz_localize(None)
    ceil = pd.Series(ceil_day.reindex(local_day).values, index=price.index)
    spike = price > SPIKE_PLN
    over = price > ceil

    L = ["pse_margines_006 - koszt a cena w skokach; kto pokryl zapotrzebowanie i kto zarobil",
         f"uruchomiono: {pd.Timestamp.now():%Y-%m-%d %H:%M}",
         f"okno {WIN_START}..{WIN_END}, godzin z cena: {len(price)}, skokow: {int(spike.sum())}",
         f"sufit kosztowy (gaz szczytowy, spr. {EFF_PEAKER}, {CO2_PEAKER_T} t CO2/MWh): {src}; "
         f"EURPLN NBP sr. {fx:.4f}",
         f"sufit w oknie: min {ceil.min():.0f}, sr. {ceil.mean():.0f}, max {ceil.max():.0f} zl/MWh", ""]

    L.insert(4, f"CO2: {co2_note}")
    n = int(spike.sum())
    L.append("TEST 3  skoki powyzej sufitu kosztowego")
    if n == 0:
        L.append("  WERDYKT: NIEROZSTRZYGNIETE (brak skokow)")
    else:
        sh = (spike & over).sum() / n
        L.append(f"  skokow powyzej sufitu: {(spike & over).sum()} z {n} = {sh:.1%} (prog {T3_SHARE:.0%})")
        L.append(f"  wszystkich godzin powyzej sufitu: {over.sum()} ({over.mean():.1%})")
        L.append("  WERDYKT: " + ("SKOKI PONAD KOSZT" if sh >= T3_SHARE else "SKOKI W GRANICACH KOSZTU"))
        # wrazliwosc: przy jakiej (stalej) cenie gazu udzial spada do progu
        gas_h = (pd.Series(gas_day.reindex(local_day).values, index=price.index)
                 if gas_day is not None else pd.Series(a.gaz, index=price.index))
        co2_part = ceil - gas_h / EFF_PEAKER
        sp = price[spike]
        need = ((sp - co2_part[spike]) * EFF_PEAKER).sort_values(ascending=False)
        k = int(round(T3_SHARE * n))
        be = need.iloc[k - 1] if k >= 1 else float("nan")
        if gas_day is None:
            L.append(f"  [wrazliwosc] werdykt odwraca sie, gdy srednia cena gazu w oknie przekracza "
                     f"ok. {be:.0f} zl/MWh (przyjeto {a.gaz:.0f})")
        else:
            gs = gas_h[spike]
            L.append(f"  [gaz w godzinach skokow] srednio {gs.mean():.0f} zl/MWh, min {gs.min():.0f}, "
                     f"max {gs.max():.0f}")

    L += [""] + test4(ub, price, spike)

    # --- kto pokryl zapotrzebowanie ---
    m = mix.reindex(price.index)
    L += ["", "KTO POKRYL ZAPOTRZEBOWANIE (srednio MW: w skokach | poza skokami)"]
    labels = {"demand": "zapotrzebowanie KSE", "jgw1": "wytworcze JGw1 (centralnie dysp.)",
              "jgw2": "wytworcze JGw2", "jnwrb": "nieaktywne na RB (m.in. ciepłownie, przemysl)",
              "wi": "wiatr", "pv": "fotowoltaika", "jgm1": "magazyny JGm1", "jgm2": "magazyny JGm2",
              "jga": "agregaty JGa", "swm_p": "saldo wymiany (rownolegla, + import?)",
              "swm_np": "saldo wymiany (nierownolegla)"}
    for c, lab in labels.items():
        if c in m and m[c].notna().any():
            L.append(f"  {lab:48s} {m.loc[spike, c].mean():8.0f} | {m.loc[~spike, c].mean():8.0f}")

    if not flows.empty and {"section_code", "value"} <= set(flows.columns):
        f = flows.copy()
        f["h"] = hour_key(f)
        f["value"] = pd.to_numeric(f["value"], errors="coerce")
        f = f.groupby(["h", "section_code"])["value"].mean().unstack()
        f = f.reindex(price.index)
        L += ["", "WYMIANA WG KIERUNKU (srednio MW: w skokach | poza skokami)"]
        for c in sorted(f.columns):
            L.append(f"  {str(c)[:48]:48s} {f.loc[spike, c].mean():8.0f} | {f.loc[~spike, c].mean():8.0f}")

    # --- kto zarobil: elektrownie centralnie dysponowane ---
    if not gen.empty and {"power_plant", "value"} <= set(gen.columns):
        g = gen.copy()
        g["h"] = hour_key(g)
        g["value"] = pd.to_numeric(g["value"], errors="coerce")
        g = g.groupby(["h", "power_plant"])["value"].mean().reset_index()
        g = g[g["h"].isin(price[spike].index)]
        g["cena"] = g["h"].map(price)
        g["sufit"] = g["h"].map(ceil)
        g["wartosc_mln"] = g["value"] * g["cena"] / 1e6
        g["nadwyzka_mln"] = g["value"] * (g["cena"] - g["sufit"]).clip(lower=0) / 1e6
        g["wlasciciel"] = g["power_plant"].map(owner)
        tot_mwh = g["value"].sum()
        L += ["", "ELEKTROWNIE CENTRALNIE DYSPONOWANE W GODZINACH SKOKOW (gen-jw)",
              "  wartosc = produkcja x cena spot; nadwyzka = produkcja x (cena - sufit), gdy dodatnia",
              "  UWAGA: to wartosc po cenie spot, nie przychod - wiekszosc energii jest sprzedana wczesniej",
              "  w kontraktach terminowych; realnie zarabia na skoku tylko niezabezpieczona czesc.",
              f"  produkcja razem: {tot_mwh / 1e3:.0f} GWh", "",
              f"  {'wlasciciel':18s} {'GWh':>8s} {'udzial':>7s} {'wartosc mln zl':>15s} {'nadwyzka mln zl':>16s}"]
        by_o = g.groupby("wlasciciel")[["value", "wartosc_mln", "nadwyzka_mln"]].sum() \
            .sort_values("value", ascending=False)
        for o, r in by_o.iterrows():
            L.append(f"  {o:18s} {r['value'] / 1e3:8.0f} {r['value'] / tot_mwh:7.1%} "
                     f"{r['wartosc_mln']:15.0f} {r['nadwyzka_mln']:16.0f}")
        L += ["", f"  {'elektrownia (top 15)':30s} {'wlasciciel':18s} {'GWh':>7s} {'nadwyzka mln zl':>16s}"]
        by_p = g.groupby("power_plant")[["value", "nadwyzka_mln"]].sum() \
            .sort_values("value", ascending=False).head(15)
        for p, r in by_p.iterrows():
            L.append(f"  {str(p)[:30]:30s} {owner(p):18s} {r['value'] / 1e3:7.1f} {r['nadwyzka_mln']:16.1f}")
        unk = sorted(g.loc[g["wlasciciel"] == "inni/?", "power_plant"].unique())
        if unk:
            L += ["", "  nieprzypisane nazwy (do uzupelnienia w OWNERS): " + ", ".join(map(str, unk))]
    elif not gen.empty:
        L += ["", "gen-jw: inne nazwy pol niz oczekiwane: " + ", ".join(map(str, gen.columns[:15]))]

    if notes:
        L += ["", "UWAGI"] + [f"  {x}" for x in notes]
    txt = "\n".join(L) + "\n"
    Path(a.out).write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"zapisano: {a.out}")


if __name__ == "__main__":
    sys.exit(main())
