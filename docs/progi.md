# Progi zaliczenia i historia testów

Progi ustalałem 15.11.2026, przed uruchomieniem każdego testu. Poniżej zapisuję też zmiany, które zrobiłem po drodze, i dlaczego.

## Test 1: skoki a rezerwa mocy

- Skok: godzina z ceną RCE > 1 000 zł/MWh.
- Rezerwa mocy: pole `surplus_cap_avail_tso` z raportu pk5l-wp (nadwyżka mocy dostępna dla OSP).
- Pierwotnie: ≥ 80% skoków w 10% godzin o najmniejszej rezerwie.
- Zmiana przed uruchomieniem: skoków było więcej niż 10% okna, więc wariant 10% był nieosiągalny. Zastąpiłem go regułą: ≥ 80% skoków w N godzinach o najmniejszej rezerwie, gdzie N = liczba skoków. Wariant 10% skrypt liczy pomocniczo.
- Wynik: 49,7%. Niezaliczony.
- Zastrzeżenie: prognoza zapotrzebowania z planu zgadzała się z wykonaniem tylko w 0,828 (korelacja). Pole rezerwy z planu mogło być zaszumione.

## Test 2: godziny z rezerwą poniżej 1 GW

- Porównanie 01.01–14.11.2025 z 01.01–14.11.2026.
- Rośnie, gdy w 2026 jest ≥ 2× więcej godzin niż w 2025 i co najmniej 10.
- Wynik: 103 wobec 113. Nie rośnie.

## Test 3: cena a koszt

- Sufit kosztowy: stary szczytowy blok gazowy, sprawność 0,38, emisja 0,53 t CO2/MWh.
  sufit = cena gazu / 0,38 + 0,53 × cena CO2
- Skoki ponad koszt, gdy ≥ 50% skoków ma cenę powyżej sufitu.
- Historia przeliczeń:
  - gaz stały 406 zł/MWh, CO2 stałe 82 EUR/t: 57,7%,
  - gaz stały 406 zł/MWh, CO2 dziennie z PSE (rcco2): 56,1% (werdykt odwraca się przy średnim gazie > ok. 428 zł/MWh),
  - gaz dziennie z TGE (TGEgasDA, 45 z 45 dni), CO2 dziennie z PSE: **53,9%**. To wynik końcowy.
- Wynik: skoki ponad koszt. Margines nad progiem jest mały; przy innym założeniu o sprawności bloku werdykt mógłby być inny.

## Test 4: ubytki mocy dużych grup

- Raport pdwkseub, pole `non_us_cap` (ubytki elektrowniane, bez ograniczeń sieciowych), godziny 7–21.
- Grupy: PGE, Tauron, Orlen (z Energą), Enea.
- 4a: ubytki w skokach wobec ubytków w zwykłych godzinach o tej samej porze dnia. Sygnał przy ≥ +20%.
- 4b: korelacja ubytków z ceną w ciągu dnia, po odjęciu średniej dnia. Sygnał przy ≥ 0,30.
- Dlaczego dwa warianty: awarie same podnoszą ceny, więc 4a nie odróżnia awarii od wycofania mocy. Prawdziwa awaria trwa dniami; wycofanie mocy mogłoby podążać za ceną z godziny na godzinę, i to mierzy 4b.
- Wynik: brak sygnału w obu wariantach dla wszystkich grup.
- Czego test nie widzi: długich, zaplanowanych postojów i cen ofert.
