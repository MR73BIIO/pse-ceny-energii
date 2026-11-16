# pse-ceny-energii

Skoki cen prądu w Polsce jesienią 2026, policzone na publicznych danych PSE.

Okno: 1 października – 14 listopada 2026 (1 081 godzin). Skok = godzina z ceną RCE powyżej 1 000 zł/MWh. Takich godzin było 310.

Chciałem sprawdzić, skąd biorą się te skoki i kto na nich zarabia. Każdy test ma próg zaliczenia zapisany przed liczeniem (`docs/progi.md`). Wyniki, które moich podejrzeń nie potwierdziły, są tu tak samo jak te, które potwierdziły.

## Wyniki

| Test | Pytanie | Próg | Wynik | Werdykt |
| --- | --- | --- | --- | --- |
| 1 | Czy skoki przypadają na godziny najmniejszej rezerwy mocy? | ≥ 80% skoków | 49,7% (losowo ok. 28,7%) | niezaliczony |
| 2 | Czy godzin z rezerwą poniżej 1 GW przybywa rok do roku? | 2× więcej | 103 (2025) wobec 113 (2026) | nie rośnie |
| 3 | Czy cena w skokach przekraczała koszt paliwa i CO2 najdroższej typowej elektrowni (stary blok gazowy)? | ≥ 50% skoków | 53,9% (167 z 310) | skoki ponad koszt |
| 4a | Czy ubytki mocy dużych grup rosną w godzinach skoków? | ≥ +20% | od −4% do −12% | brak sygnału |
| 4b | Czy ubytki grup podążają za ceną w ciągu dnia? | korelacja ≥ 0,30 | od −0,65 do −0,07 | brak sygnału |

Pełne wydruki: `wyniki/`.

Co z tego wynika:

- W godzinach skoków zapotrzebowanie było średnio o 3,5 GW wyższe, wiatr dawał 1,6 GW zamiast 3,2 GW, fotowoltaika 0,9 GW zamiast 2,2 GW.
- W ponad połowie skoków cena była wyższa niż koszt zmienny starego bloku gazowego (średnio ok. 1 255 zł/MWh, liczony dzień po dniu z ceny gazu TGEgasDA i ceny CO2 z PSE). Margines nad progiem jest mały.
- Godzinowego wycofywania bloków w danych nie ma. W drogich godzinach ubytki były niższe niż zwykle.
- Duże elektrownie wyprodukowały w 310 godzinach skoków 1 588 GWh. Produkcja razy (cena minus koszt starego bloku gazowego) daje ok. 432 mln zł, z czego ok. 87% przypada na grupy kontrolowane przez Skarb Państwa. To nie jest zysk firm: większość energii jest sprzedawana wcześniej w kontraktach.

## Czego te dane nie pokazują

- ofert poszczególnych wytwórców i tego, które z nich ustalały cenę,
- rzeczywistych przychodów i zabezpieczeń kontraktowych firm,
- intencji kogokolwiek.

Przypisanie elektrowni do właścicieli (`OWNERS` w `src/koszt_i_zarobek.py`) zrobiłem z wiedzy ogólnej, bez sprawdzenia w rejestrach. 10 elektrowni (11,5% produkcji w skokach) zostało nieprzypisanych.

Kierunek przepływów na granicach: przyjąłem, że wartości dodatnie oznaczają przepływ do Polski.

## Jak odtworzyć

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python3 src/zapas_mocy.py --out wyniki_lokalne_testy_1_2.txt
python3 src/tge_gaz.py --od 2026-10-01 --do 2026-11-14 --out gaz_tge.csv
python3 src/koszt_i_zarobek.py --ceny-csv gaz_tge.csv --out wyniki_lokalne_testy_3_4.txt
```

Dane PSE pobierają się do `dane_pse/` (nie ma ich w repo, każdy pobierze je sam). Ceny gazu pobiera skrypt ze strony TGE; samych cen w repo nie publikuję, bo to dane TGE.

## Źródła danych

- API PSE: https://api.raporty.pse.pl (raporty: rce-pln, his-wlk-cal, pk5l-wp, gen-jw, pdwkseub, przeplywy-mocy, rcco2)
- TGE, Rynek Dnia Następnego gazu: https://tge.pl/gaz-rdn
- Kurs EUR/PLN: NBP, tabela A

## In English, briefly

Autumn 2026 power price spikes in Poland, analysed on public PSE (Polish TSO) data with pass/fail thresholds fixed before running each test. In 54% of the 310 hours above 1,000 PLN/MWh the price exceeded the variable cost of an old gas peaker; no sign of hour-by-hour capacity withholding by the four largest groups.

---

Marcin Ruszczak (MR73BIIO) · analiza danych, Python, GIS · PL / DE / RU / EN
