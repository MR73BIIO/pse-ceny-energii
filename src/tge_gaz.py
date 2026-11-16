#!/usr/bin/env python3
"""tge_gaz.py - dzienny indeks TGEgasDA ze strony TGE (Rynek Dnia Nastepnego gazu).

Dla kazdej daty pobiera strone tge.pl/gaz-rdn?dateShow=DD-MM-YYYY, odczytuje z niej date dostawy
i wartosc TGEgasDA i zapisuje CSV: data,gaz_pln_mwh. Data w CSV to data dostawy odczytana ze strony,
nie data z zapytania - wiec nawet jesli strona przesuwa dzien, wartosci trafiaja pod wlasciwa date.

Uzycie:  python3 tge_gaz.py --od 2026-10-01 --do 2026-11-14 --out gaz_tge.csv
"""
import argparse
import re
import sys
import time

import pandas as pd
import requests

URL = "https://tge.pl/gaz-rdn"
UA = {"User-Agent": "Mozilla/5.0 (analiza danych publicznych; kontakt: mr73biio)"}
NUM = r"(\d{1,3}(?:[  ]\d{3})*,\d{2})"


SERIES = re.compile(r'"date":\s*"(\d{4}-\d{2}-\d{2})",\s*"kurs1":\s*\'([\d.]+)\'')
TABLE = re.compile(r'>TGEgasDA</b>.*?align="right">\s*([\d\s\u00a0]+,\d{2})\s*</td>', re.S)


def parse(html):
    """Zwraca {data_dostawy: kurs}. Strona TGE zawiera w wykresie kilka ostatnich dni (data dostawy,
    kurs TGEgasDA), wiec jedno zapytanie daje ok. tygodnia danych. Dla pewnosci porownujemy z tabela."""
    out = {pd.Timestamp(d): float(v) for d, v in SERIES.findall(html) if v}
    m_date = re.search(r"dostawy w dniu\s*(\d{2}-\d{2}-\d{4})", html)
    m_tab = TABLE.search(html)
    if m_date and m_tab:
        d = pd.to_datetime(m_date.group(1), format="%d-%m-%Y")
        v = float(re.sub(r"[\s\u00a0]", "", m_tab.group(1)).replace(",", "."))
        if d in out and abs(out[d] - v) > 0.01:
            print(f"  UWAGA: {d:%Y-%m-%d} wykres {out[d]} vs tabela {v} - biore tabele")
        out[d] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--od", default="2026-10-01")
    ap.add_argument("--do", dest="do_", default="2026-11-14")
    ap.add_argument("--out", default="gaz_tge.csv")
    ap.add_argument("--probka", default="probka_tge.html", help="zapis pierwszej strony do diagnozy")
    a = ap.parse_args()
    found = {}
    first = True
    for d in pd.date_range(a.od, a.do_):
        q = d.strftime("%d-%m-%Y")
        try:
            r = requests.get(URL, params={"dateShow": q}, headers=UA, timeout=60)
            if first:
                open(a.probka, "w", encoding="utf-8").write(
                    f"<!-- HTTP {r.status_code} {r.url} -->\n" + r.text)
                print(f"  probka strony zapisana: {a.probka} (HTTP {r.status_code}, {len(r.text)} znakow)")
                first = False
            r.raise_for_status()
            got = parse(r.text)
        except requests.RequestException as e:
            print(f"  {q}: blad {e}", flush=True)
            got = {}
        found.update(got)
        print(f"  zapytanie {q} -> {len(got)} dni: "
              + (f"{min(got):%Y-%m-%d}..{max(got):%Y-%m-%d}" if got else "nie odczytano"), flush=True)
        time.sleep(1.0)
    s = pd.Series(found, dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    s = s[(s.index >= pd.Timestamp(a.od)) & (s.index <= pd.Timestamp(a.do_))]
    want = pd.date_range(a.od, a.do_)
    missing = [f"{d:%Y-%m-%d}" for d in want if d not in s.index]
    pd.DataFrame({"data": s.index.strftime("%Y-%m-%d"), "gaz_pln_mwh": s.values}).to_csv(a.out, index=False)
    print(f"\nzapisano {len(s)} z {len(want)} dni do {a.out}; srednia {s.mean():.2f} zl/MWh" if len(s) else
          f"\nNIE ODCZYTANO ZADNEGO DNIA - zapisano pusty {a.out}; sprawdz {a.probka}")
    if missing:
        print("brakujace dni: " + ", ".join(missing))
    return 0 if len(s) else 1


if __name__ == "__main__":
    sys.exit(main())
