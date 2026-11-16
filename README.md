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
| 5 | Czy w najdroższych kwadransach 9–10.11 Polska wykorzystała maksymalny import z domeny flow-based (JAO Core)? | ≥ 80% kwadransów na ≥ 95% | 0 z 19 (wykorzystanie 39–51%) | import nie był ograniczeniem (miara wadliwa, patrz niżej) |
| 6 | Czy przesuwnik fazowy Mikułowa (PSE, granica PL–DE) częściej blokuje import w godzinach skoków? Okno 1.10–8.11, bez 9–10.11 | ≥ 2× częściej niż w innych godzinach | 49,4% wobec 7,2% (6,9×) | sygnał |

Pełne wydruki: `wyniki/`.

Co z tego wynika:

- W godzinach skoków zapotrzebowanie było średnio o 3,5 GW wyższe, wiatr dawał 1,6 GW zamiast 3,2 GW, fotowoltaika 0,9 GW zamiast 2,2 GW.
- W ponad połowie skoków cena była wyższa niż koszt zmienny starego bloku gazowego (średnio ok. 1 255 zł/MWh, liczony dzień po dniu z ceny gazu TGEgasDA i ceny CO2 z PSE). Margines nad progiem jest mały.
- Godzinowego wycofywania bloków w danych nie ma. W drogich godzinach ubytki były niższe niż zwykle.
- Duże elektrownie wyprodukowały w 310 godzinach skoków 1 588 GWh. Produkcja razy (cena minus koszt starego bloku gazowego) daje ok. 432 mln zł, z czego ok. 87% przypada na grupy kontrolowane przez Skarb Państwa. To nie jest zysk firm: większość energii jest sprzedawana wcześniej w kontraktach.

Połączenia z sąsiadami (testy 5 i 6):

- Maksymalny import z JAO to wartość skrajna, liczona tak, jakby wszystkie inne strefy dostosowały się pod Polskę. W praktyce jest nieosiągalna, więc werdykt testu 5 niewiele mówi.
- Lepiej opisuje to, które elementy sieci były aktywnym ograniczeniem (shadow price > 0). 9–10.11 przesuwnik fazowy w Mikułowej był nim we wszystkich 19 kwadransach z ceną powyżej 3 000 zł/MWh, a w pozostałych kwadransach tych dni w 40%. Ten wynik był eksploracyjny, więc sprawdziłem go na innych dniach z progiem ustalonym wcześniej (test 6): w godzinach skoków od 1.10 do 8.11 Mikułowa była ograniczeniem w 49,4% godzin, w pozostałych w 7,2%.
- To pokazuje, gdzie w drogich godzinach kończyła się możliwość taniego importu. Nie mówi, czy ustawienie tego elementu było właściwe; to pytanie do PSE.

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
python3 src/import_test.py --out wyniki_lokalne_test_5.txt
python3 src/mikulowa_test.py --out wyniki_lokalne_test_6.txt
```

Dane PSE pobierają się do `dane_pse/` (nie ma ich w repo, każdy pobierze je sam). Ceny gazu pobiera skrypt ze strony TGE; samych cen w repo nie publikuję, bo to dane TGE.

## Źródła danych

- API PSE: https://api.raporty.pse.pl (raporty: rce-pln, his-wlk-cal, pk5l-wp, gen-jw, pdwkseub, przeplywy-mocy, rcco2)
- TGE, Rynek Dnia Następnego gazu: https://tge.pl/gaz-rdn
- JAO Publication Tool, region Core: https://publicationtool.jao.eu/core (maxNetPos, netPos, shadowPrices)
- Kurs EUR/PLN: NBP, tabela A

## In English, briefly

Autumn 2026 power price spikes in Poland, analysed on public PSE (Polish TSO) data with pass/fail thresholds fixed before running each test. In 54% of the 310 hours above 1,000 PLN/MWh the price exceeded the variable cost of an old gas peaker; no sign of hour-by-hour capacity withholding by the four largest groups.

---

Marcin Ruszczak (MR73BIIO) · analiza danych, Python, GIS · PL / DE / RU / EN
