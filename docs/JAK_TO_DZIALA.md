# Speaking Automaticity Trainer — jak działa aplikacja i ćwiczenia

Ten dokument opisuje aplikację od strony użytkownika: co robi, dlaczego, i dokładnie
jak przebiega każde ćwiczenie. Pełna specyfikacja techniczna (metryki, model danych,
API) jest w [SPEC.md](../SPEC.md).

---

## 1. Czemu służy aplikacja

Aplikacja jest dla osoby, która **rozumie angielski dobrze, ale mówienie jej nie
wychodzi automatycznie**: zna słowo, ale nie wyskakuje ono w czasie rzeczywistym;
zaczyna zdanie zbyt skomplikowane i nie potrafi go dokończyć; świadomie pilnuje
gramatyki zamiast mówić swobodnie.

To **nie jest problem wiedzy**, tylko problem dostępu do wiedzy pod presją czasu.
Dlatego aplikacja:

- **nigdy nie poprawia gramatyki w trakcie mówienia** (i w zasadzie w ogóle rzadko),
- **nie pokazuje transkrypcji na żywo** — użytkownik zacząłby czytać i kontrolować się,
- **nie ocenia "poprawności"** jako głównego wyniku,
- **nie uczy słownictwa ani gramatyki** (brak fiszek, list, wyjaśnień),
- mierzy przede wszystkim **czas**: jak szybko zaczynasz mówić, jak długo mówisz bez
  przerwy, gdzie wypadają twoje pauzy.

Błąd gramatyczny wypowiedziany płynnie to sukces. Wahanie przy budowaniu poprawnego
zdania to porażka, którą aplikacja ma zredukować.

---

## 2. Główne pojęcia

- **Sesja nauki (Learning Session)** — kontener, w którym uruchamiasz dowolną liczbę
  ćwiczeń (drilli) pod rząd. Otwierasz sesję, robisz tyle prób ile chcesz, zamykasz —
  wtedy dostajesz podsumowanie.
- **Ćwiczenie / drill** — jeden z 8 modułów opisanych w sekcji 4. Wszystkie działają
  na tej samej maszynie stanów, różni je tylko konfiguracja (czasy, liczba rund, itd.).
- **Próba (attempt)** — pojedyncze nagranie w ramach ćwiczenia.
- **Struktura gramatyczna (target_structure)** — opcjonalny filtr, który można nałożyć
  na dowolne ćwiczenie, żeby wymusić konkretną konstrukcję (np. trzeci okres
  warunkowy) bez mówienia o niej wprost.

---

## 3. Przebieg pojedynczej próby (dotyczy każdego ćwiczenia)

Każda próba przechodzi przez te same etapy:

```
IDLE → PRESENT (bodziec) → [PREP?] → RECORD → PROCESS → FEEDBACK → kolejna próba / koniec
```

1. **PRESENT** — na ekranie pojawia się bodziec: pytanie, temat lub polecenie, dużą
   czcionką, wyśrodkowane. Nic poza tym.
2. **PREP** (opcjonalny, tylko w niektórych ćwiczeniach) — kilka sekund na
   zaplanowanie wypowiedzi, zanim zacznie się nagrywanie.
3. **RECORD** — nagrywanie startuje. Widoczny jest **tylko** odliczający timer i pasek
   "mówisz / cisza". Żaden angielski tekst poza bodźcem się nie pojawia — zero
   podpowiedzi, zero autouzupełniania, zero transkrypcji na żywo. Nagrywanie kończy
   się automatycznie po ciszy (`auto_stop_silence_s`) albo po przekroczeniu
   maksymalnego czasu.
4. **PROCESS** — nagranie leci na serwer: wykrywanie mowy/ciszy (VAD), transkrypcja
   (Whisper), obliczenie metryk. Trwa ok. 2-4 sekundy.
5. **FEEDBACK** — krótki ekran (3-4 s, potem auto-przejście dalej) z trzema liczbami:
   czas startu wypowiedzi, najdłuższy nieprzerwany odcinek mówienia, liczba długich
   pauz. Transkrypcja jest dostępna pod rozwinięciem, domyślnie schowana. Żadnej oceny
   poprawności tutaj.

Timer jest zawsze widoczny i nieusuwalny — presja czasu jest częścią treningu, nie
efektem ubocznym.

---

## 4. Osiem ćwiczeń

Wszystkie poniższe parametry pochodzą z aktualnej konfiguracji w
`apps/api/app/drills/*.json`.

### Rapid Response
Krótkie pytanie, mów od razu. Bez przygotowania (`prep 0 s`), mówisz 5-15 s,
1 runda, 12 prób w sesji. Cel: `czas do pierwszego słowa (ttfw) ≤ 1.5 s`. Metryki
wiodące: `ttfw`, liczba długich pauz. Bez oceny LLM — to czysto pomiar czasu.

### Unexpected Questions
Jak Rapid Response, ale pytania są zaskakujące/nietypowe, żeby uniemożliwić
przygotowaną odpowiedź. Bez przygotowania, 5-15 s mówienia, 12 prób. Cel:
`ttfw ≤ 1.5 s`. Trudność pytań adaptuje się do wyniku (patrz sekcja 5).

### Fluency Sprint
Jeden prosty temat, mówisz **120 sekund bez przerywania** (60-120 s dozwolone,
cisza tolerowana do 4 s zanim nagranie się zatrzyma). Tylko 3 próby w sesji — to
ćwiczenie wyczerpujące. Metryki wiodące: udział czasu mówienia w całości nagrania
(`phonation_time_ratio`) i liczba długich pauz. Feedback pokazuje wykres, gdzie w
czasie się zacinałeś. Bez oceny LLM.

### Describe Without the Word
Opisujesz pojęcie, nie używając słowa docelowego ani jego form pochodnych i
podanych synonimów (**lista słów zakazanych**). Mówisz 10-30 s, 10 prób w sesji.
Użycie zakazanego słowa = nieudana próba. LLM ocenia po fakcie, czy opis w ogóle
pozwalał odgadnąć pojęcie. Metryki wiodące: `ttfw`, udział pauz w środku frazy.

### Paraphrase
Ta sama myśl, powiedziana **trzy razy różnymi słowami** (3 rundy po max 15 s, 4
próby w sesji). LLM po fakcie sprawdza, czy parafraza rzeczywiście znaczy to samo, i
liczony jest dystans leksykalny między wersjami — muszą się parami różnić o więcej
niż 0.5, inaczej runda się nie liczy. Metryki wiodące: dystans leksykalny między
rundami, `ttfw` w rundzie 2 i 3 (powinien spadać — druga i trzecia wersja mają
wychodzić szybciej).

### Simplify
Dostajesz złożoną myśl/temat i **5 sekund na przygotowanie** (jedyne ćwiczenie z
niezerowym `prep_time_s`), potem masz 20 s, żeby powiedzieć to możliwie prostym
językiem. 1 runda, 8 prób w sesji. LLM ocenia, czy uproszczenie zachowało sens.
Metryki wiodące: indeks podrzędności zdań (ma spaść) i udział słów spoza 2000
najczęstszych.

### Idea Expansion
Rozwijasz jedną myśl w dłuższą wypowiedź: 15-45 s, cel to co najmniej 5 zdań, 6 prób
w sesji. LLM ocenia jakościowo. Metryki wiodące: średnia długość wypowiedzenia,
liczba zdań.

### Story Loop
Ta sama historia opowiadana **trzy razy z coraz krótszym limitem czasu**: 90 s → 60 s
→ 45 s (metoda 4/3/2 z metodyki nauczania języków). 2 próby (czyli 2 historie) w
sesji. Cel: przy trzeciej rundzie mówisz płynniej niż w pierwszej — wynik pokazany
jako różnica między rundami, nie wartość bezwzględna. Metryki wiodące: średnia
długość nieprzerwanego odcinka (ma rosnąć), częstość wypełniaczy typu "um/uh" (ma
maleć). Bez oceny LLM.

---

## 5. Wymiar struktur gramatycznych (opcjonalny filtr)

Struktura gramatyczna **nie jest osobnym ćwiczeniem** — to filtr, który można nałożyć
na dowolne z ośmiu ćwiczeń powyżej (np. Rapid Response tylko z trzecim okresem
warunkowym). Lista obejmuje 21 konstrukcji: czasy przyszłe, przeszłe, wszystkie okresy
warunkowe, spekulacje modalne, stronę bierną, mowę zależną, zdania względne, gerund
vs infinitive, `wish/if only`.

Dwa tryby:
- **jawny (explicit)** — nazwa struktury i przykład są widoczne przed startem; buduje
  automatyzację przez powtórzenie.
- **ukryty (implicit)** — prompt wymusza konstrukcję (np. "Jaka jedna decyzja
  całkowicie zmieniłaby twoją karierę?"), ale nie mówi wprost o gramatyce; mierzy, czy
  sięgasz po nią spontanicznie.

Kluczowa metryka to **unikanie (avoidance)** — czy zamiast trzeciego okresu
warunkowego powiedziałeś po prostu dwa zdania w czasie przeszłym. To częstsze niż się
wydaje: wypowiedź jest poprawna, komunikat przechodzi, a konstrukcja pozostaje
nieużywana latami. Różnica `avoidance` między trybem jawnym a ukrytym jest głównym
wynikiem tego podsystemu — pokazuje, czy znasz konstrukcję, ale po nią nie sięgasz.

Wyniki dostępne wyłącznie na osobnym ekranie **Struktury** (mapa cieplna), nigdy w
trakcie sesji ani bezpośrednio po próbie. System nie poprawia formy — jeśli powiesz
"if I would have known", zapisuje to bez komentarza.

---

## 6. Adaptacja trudności

Prosty, przewidywalny algorytm, liczony co 5 prób w danym module:

- mediana `ttfw` z ostatnich 5 prób **< 0.8 s** i brak nieudanych prób → trudność
  rośnie o 1,
- mediana **> 3.0 s** lub co najmniej 2 nieudane próby → trudność spada o 1,
- w innym wypadku bez zmian.

Skala trudności: 1-10. Limity czasowe **nie zmieniają się** wraz z trudnością — to
one tworzą presję, więc muszą zostać stałe, nawet gdy jest ciężko. Trudność dotyczy
treści zadania (abstrakcyjność, obcość tematu), nie ilości czasu na odpowiedź.

---

## 7. Po sesji: podsumowanie i obserwacje

Po zamknięciu sesji:
- **Podsumowanie sesji** — krzywa zmęczenia (czy `ttfw` rósł w drugiej połowie sesji),
  porównanie z medianą z ostatnich 7 dni, jedno zdanie interpretacji, plus feedback
  LLM dotyczący powtarzalnych wzorców gramatycznych z tej sesji — to jedyne miejsce,
  gdzie gramatyka w ogóle jest wspominana.
- Jeśli w trakcie sesji `ttfw` wzrośnie o 40% względem pierwszych 5 prób, aplikacja
  **sama kończy sesję** i informuje o tym wprost — to sygnał zmęczenia poznawczego,
  nie porażki.
- **Obserwacje** — ciągła diagnoza przebudowywana po każdej sesji: powtarzalne wzorce
  błędów widoczne poza treningiem, nigdy w jego trakcie.
- **Postęp** — wykresy szeregów czasowych `ttfw`, średniej długości nieprzerwanego
  odcinka i wskaźnika "złożoność vs płynność" (czy budujesz zdania, których nie
  utrzymujesz).

---

## 8. Osobne narzędzie: Trener tempa czytania

Nie jest częścią mowy spontanicznej i **nigdy nie wchodzi do statystyk powyżej** (nie
wpływa na z-score, adaptację trudności ani mapę struktur) — czytanie na głos nie ma
komponentu wydobywania słów z pamięci, więc mierzy coś innego.

Jak działa: wklejasz dowolny tekst, ustawiasz docelowe tempo (wpm), czytasz na głos.
Dostajesz:
- ogólne tempo brutto i tempo artykulacji (bez pauz),
- wskaźnik równomierności tempa,
- **mapę prędkości** — twój tekst z każdym słowem podświetlonym kolorem względem
  tempa docelowego (wolniej / w celu / szybciej), więc widać, gdzie zwalniasz i gdzie
  się zacinasz,
- listę pominiętych słów i słów, które nie zostały rozpoznane poprawnie (dopasowanie
  tekstu referencyjnego do transkrypcji przez `difflib`) — pokazywane jako "nie
  wybrzmiało", nigdy jako ocena wymowy, bo mechanizm łapie też zwykłe błędy
  transkrypcji.

Nagranie jest przetwarzane w pliku tymczasowym i **kasowane od razu po analizie**.

---

## 9. Co aplikacja świadomie pomija

- Korekty gramatycznej w trakcie mówienia — nigdy.
- Oceny "poziomu CEFR" czy poprawności jako głównego wyniku.
- Nauki słownictwa, fiszek, list gramatycznych.
- Modułów Conversation Simulation i Shadow Conversation (świadomie wycięte z zakresu).

Błędy gramatyczne są zbierane w tle wyłącznie po to, żeby raz na sesję (nigdy w jej
trakcie) pokazać 3-5 powtarzalnych wzorców jako obserwację, nie ocenę.
