# Plan zmian: gramatyka, którą chce się ćwiczyć

*Stan na 2026-11-16, wersja 3 (doszedł shadowing, sekcja 9). Większość planu jest wdrożona, patrz „Stan wdrożenia” poniżej.*

*Wersja 1 stawiała na rozmowę głosową w aplikacji. Odpada, bo rozmowa na żywo przez API jest droga, a do rozmawiania służy subskrypcja. Aplikacja ma robić to, czego subskrypcja nie robi dobrze: krótkie, mówione ćwiczenia, które utrwalają gramatykę aż do automatyzmu.*

## Stan wdrożenia (2026-11-16)

Zrobione i sprawdzone (testy automatyczne oraz próba w przeglądarce z podstawionym mikrofonem):

- rundy po 8 zadań z oceną po każdej odpowiedzi, powrót błędnego zadania, „powiedz jeszcze raz” (sekcja 5),
- mapa 56 umiejętności z poziomami i powtórkami po przerwach (sekcja 4), z sondą zamiast osobnego skanu,
- bank 950 zadań w repo i dogenerowywanie w tle (sekcja 7.2),
- formy: sytuacja, z pomocą, tłumaczenie z polskiego, popraw kolegę, o tobie, z twoich błędów (sekcja 6),
- most do subskrypcji: temat na dziś i import transkryptu (sekcja 8),
- shadowing z pomiarem nadążania, pętlą i odsłuchem „lektor, potem ja” (sekcja 9),
- nowy ekran startowy, stare moduły pod „more → Lab”, cel tygodniowy 5 dni.

Nie zrobione: formy „Odcinek”, „Sprint” i „Odpowiedz na głos”, przedimki, licznik kosztów, powiadomienia, wersja na telefon, aktualizacja `README.md` i `SPEC.md`.

Inaczej niż w planie: brakujące struktury (present perfect, czasy teraźniejsze, pytania pośrednie i inne) weszły od razu do katalogu; interfejs został po angielsku; do pisania zadań służy `gpt-6-sol`, do oceny `gpt-4.1`.

Opis techniczny: `docs/STAN_APLIKACJI.md`, sekcja „Codzienna ścieżka”.

## 1. Wniosek w trzech zdaniach

Rdzeniem aplikacji zostaje moduł Grammar, przebudowany z 30-minutowej sesji na 50 zadań w rundy po 8 zadań z oceną natychmiast po każdej odpowiedzi. Nad rundami pojawia się mapa opanowania: skończona lista umiejętności, z których każda ma jasny stan, a aplikacja sama wybiera, co dziś ćwiczysz. Rozmowa zostaje w subskrypcji, a aplikacja ją tylko zasila tematem i (opcjonalnie) wyciąga z niej Twoje prawdziwe błędy.

## 2. Co mówi baza danych

Sprawdziłem `data/app.db`. Od przebudowy 26 sierpnia minęło 81 dni:

| Moduł | Faktyczne użycie |
|---|---|
| Sesja główna (40 min, 7 faz) | 0 sesji, profil osobisty pusty |
| Grammar drills | 2 sesje, obie porzucone po 10 z ok. 50 zadań, po mniej więcej 2,5 minuty |
| Rozmowa (GPT-Live) | 2 podejścia: 81 sekund oraz jedno nigdy nie zakończone |
| Trener czytania | 4 próby jednego ranka |
| Diagnostyka, Recovery drill | 0 |

Gramatyka jest jedynym modułem ćwiczeniowym, do którego wróciłeś drugi raz, więc kierunek jest dobry. Dane pokazują też, dlaczego nie wciągnęła:

- **Zero informacji zwrotnej.** Ocena przychodzi jednym żądaniem po całej sesji. Obie sesje zostały przerwane, więc wszystkie 20 odpowiedzi mają w bazie pusty werdykt. Ani razu nie dowiedziałeś się, czy mówisz dobrze.
- **Pierwsze zadania były czytaniem gotowych zdań.** W zapisanym zestawie polecenie brzmiało „If I wake up late, I usually ...”, a podpowiedź „miss breakfast.”. Wystarczyło przeczytać. Do tego zdania z podręcznika („If you heat ice, it melts”).
- **Potem skok trudności.** Czas do rozpoczęcia odpowiedzi wzrósł z ok. 2 s do 18 s na pierwszym zadaniu bez gotowca, następna odpowiedź jest pusta i tu sesja się kończy.
- **Długie czekanie i odległy koniec.** Start zaczyna się od ekranu „Building your session... this takes up to a minute”, a licznik pokazuje „1 / 50”.
- **Jedna struktura do wyboru w praktyce.** Katalog ma 21 pozycji, ale tylko okresy warunkowe są zgrupowane sensownie, a zakończenie żadnej sesji nie zostawia śladu postępu.

Zestawy generował `gpt-4o-mini`. Obecny prompt (`generate_grammar_set.md`) jest nowszy niż obie sesje, zakazuje pokazywania gotowej odpowiedzi i nie był jeszcze użyty, więc część problemu z jakością może być już rozwiązana. Nie sprawdzałem tego wywołaniem API.

## 3. Zasady projektowe

1. **Start w 5 sekund.** Jeden przycisk, żadnego wyboru struktury, żadnego czekania na generowanie.
2. **Runda trwa 3 minuty i jest całością.** Osiem zadań, wynik, koniec. Kolejna runda to osobna decyzja.
3. **Ocena od razu po każdym zdaniu.** Błąd poprawiasz ustami w tej samej chwili.
4. **Znaczenie przed regułą.** To już jest w obecnym module i zostaje: żadnych nazw szkolnych, tylko „żałuję czegoś z przeszłości → taki kształt zdania”.
5. **Każda runda ma inną formę.** Ta sama struktura wraca w ośmiu różnych przebraniach.
6. **Postęp jest widoczny i skończony.** „Opanować gramatykę” musi mieć definicję i mapę, inaczej nigdy się nie kończy.

## 4. Co znaczy „opanować”

Umiejętność to para znaczenie → kształt zdania, na przykład „coś, czego żałuję z przeszłości”. Okresy warunkowe to pięć umiejętności, nie jedna. Każda ma poziom:

| Poziom | Warunek | Co widać na mapie |
|---|---|---|
| 0 Nowa | jeszcze nie ćwiczona | szare pole |
| 1 Z pomocą | poprawnie, gdy widać kształt i początek zdania | zarys |
| 2 Samodzielnie | poprawnie z samej sytuacji, bez podpowiedzi | połowa |
| 3 Szybko | poprawnie i start odpowiedzi poniżej ok. 2 s, w rundzie mieszanej z innymi strukturami | prawie pełne |
| 4 Trwale | poziom 3 utrzymany po przerwach 3, 7 i 21 dni | pełne |
| ★ W rozmowie | użyta poprawnie w rozmowie z subskrypcji (sekcja 8, opcjonalne) | gwiazdka |

Poziom 4 na całej mapie to operacyjna definicja „mastered”. Poziom spada o jeden, gdy po przerwie pojawiają się błędy. To nie kara, tylko sygnał, że umiejętność wraca do powtórek.

**Katalog trzeba rozszerzyć.** Obecne 21 struktur (`data/language_config.json`) to czasy przyszłe i przeszłe, okresy warunkowe, spekulacje, strona bierna, mowa zależna, zdania względne, gerund kontra bezokolicznik, wish. Brakuje tego, co Polakom sprawia najwięcej kłopotu w mowie:

- present perfect kontra past simple, present perfect continuous
- przedimki (a, the, brak przedimka)
- czasy teraźniejsze (simple kontra continuous, czasowniki stanu)
- pytania, w tym pośrednie („Do you know where he is?”) i pytania o podmiot
- czasowniki modalne obowiązku i rady (should have, didn't need to, had better)
- zdania czasowe bez *will* po when, as soon as, until
- rzeczowniki policzalne i niepoliczalne, much/many/few/little
- stopniowanie i porównania (the more… the more, as… as)
- konstrukcje have/get something done

Razem wyjdzie ok. 45-55 umiejętności. Przy trzech nowych tygodniowo to mniej więcej cztery miesiące do pierwszego przejścia całej mapy.

## 5. Sesja dzienna

### 5.1 Ekran startowy

```
            [  Zacznij · 3 min  ]

  Dziś: 5 powtórek · nowe: „żałuję czegoś z przeszłości”

  Mapa:  ████████░░░░░░░░░░░░   9 z 48 opanowanych · 6 w toku
  Tydzień: ●●●○○  3 z 5 dni
  ─────────────────────────────────
  mapa · więcej
```

Żadnego wyboru. Aplikacja sama układa rundę z tego, co wymaga powtórki, i z jednej umiejętności w toku. Kto chce, może wejść w mapę i wybrać umiejętność ręcznie.

### 5.2 Runda

Osiem zadań, każde na jeden oddech:

1. Pojawia się zadanie i od razu rusza nagrywanie (tak jak dziś).
2. Kończysz mówić, nagranie zatrzymuje się po ciszy.
3. Po 2-3 sekundach werdykt:
   - **Dobrze:** zielony znak, Twoje zdanie, czas reakcji. Dalej automatycznie.
   - **Prawie:** Twoje zdanie z zaznaczonym miejscem, poprawna wersja, jedno zdanie wyjaśnienia wiążące formę ze znaczeniem. Przycisk „powiedz jeszcze raz” i mówisz poprawną wersję. To drugie podejście nie jest oceniane na punkty, ma tylko przejść przez usta.
   - **Ominięte:** zdanie poprawne, ale bez ćwiczonej struktury. Pokazuje wersję ze strukturą.
4. Zadanie z błędem wraca jeszcze raz pod koniec tej samej rundy, w innej sytuacji.

Na końcu: „7 z 8. Jedno wraca jutro.” oraz zmiana na mapie, jeśli jakaś umiejętność awansowała. Potem dwa przyciski: „jeszcze jedna runda” i „koniec na dziś”.

Wyjście w trakcie niczego nie traci, bo każda odpowiedź jest oceniona osobno.

### 5.3 Skąd runda wie, co dać

- **Powtórki:** każda umiejętność ma termin następnej powtórki (odstępy rosną po sukcesie, skracają się po błędzie). Mechanizm tego typu już istnieje w `chunk_scheduler.py` dla zwrotów i można go przenieść.
- **Mieszanie:** od poziomu 2 umiejętność pojawia się wyłącznie w rundach mieszanych. Dopiero gdy nie wiesz z góry, o jaką strukturę chodzi, wybierasz ją znaczeniem, tak jak w rozmowie.
- **Nowe:** najwyżej jedna nowa umiejętność na rundę i tylko wtedy, gdy powtórek jest mało. Pierwsze zetknięcie to 3-4 zadania z widocznym kształtem zdania, bez osobnej karty do czytania. Ściąga zostaje pod przyciskiem z boku.
- **Łagodniejsze schodki:** między „widzę kształt i początek” a „widzę tylko sytuację” dochodzą stopnie pośrednie (sam początek zdania, potem samo znaczenie jako podpowiedź). Podpowiedź jest dostępna zawsze, a jej użycie tylko wstrzymuje awans.

### 5.4 Skan na początek

Zamiast pytać, co chcesz ćwiczyć: jednorazowa runda 12-15 zadań przekrojowych, po jednym na grupę struktur. Wynik ustawia mapę (część pól od razu na poziomie 2 lub 3) i wyznacza kolejność. Dzięki temu nie zaczynasz od rzeczy, które już umiesz, co przy Twoim poziomie rozumienia byłoby najszybszą drogą do nudy.

## 6. Formy zadań

Różnorodność jest tu głównym lekarstwem na nudę. Każda runda ma jedną formę, a formy rotują.

| Forma | Jak wygląda | Po co |
|---|---|---|
| Sytuacja | Krótka scena i pytanie, odpowiadasz jak w życiu | Podstawa, już istnieje |
| Jak to powiedzieć | Polskie zdanie, w którym polszczyzna podpowiada zły kształt („Jak będę wiedział, dam ci znać”) | Najszybciej trafia w błędy typowe dla Polaków |
| Odcinek | Osiem zadań to jedna mała historia (awaria w dniu premiery, zaginiony bagaż). Twoje kwestie ją popychają | Ciekawość, co dalej, trzyma przy rundzie |
| Odpowiedz na głos | Słyszysz kwestię rozmówcy (synteza mowy) i reagujesz | Namiastka rozmowy bez kosztu rozmowy na żywo |
| Ta sama scena, inna rzeczywistość | Dwie prawie identyczne sytuacje, które wymagają różnych form | Rozróżnianie znaczeń, już istnieje jako „choose” |
| Popraw kolegę | Ktoś mówi z błędem, powtarzasz naturalnie i poprawnie | Wyłapywanie błędów, już istnieje jako „fix” |
| O tobie | Pytanie osobiste, które wymusza strukturę („What would you have done differently in your first job?”). Po ocenie jedno zdanie reakcji na treść | Twoje własne zdania zostają w pamięci najdłużej |
| Sprint | 60 sekund, ile poprawnych odpowiedzi zdążysz. Tylko umiejętności z poziomu 2 i wyżej | Automatyzacja, rekord do pobicia |
| Z twoich błędów | Zadania zbudowane wokół błędów, które faktycznie zrobiłeś | Powtórka dokładnie tam, gdzie boli |

Treść zadań bierze się z Twojego świata (praca na styku marketingu, produktu i technologii, co widać w tekstach z trenera czytania). Profil w bazie jest pusty, więc na start wystarczy jedno pole z trzema zdaniami o sobie.

## 7. Zmiany techniczne

### 7.1 Ocena po każdym zadaniu

Dziś: transkrypcja w tle, jedno żądanie oceniające na końcu (`grade_session`). Po zmianie: po transkrypcji od razu krótkie żądanie oceniające jedno zadanie, z tym samym promptem co dziś, przyciętym do jednej pozycji. Frontend już odpytuje `/answers/{id}`, wystarczy, żeby zwracał także werdykt, poprawkę i wyjaśnienie.

Model odpowiedzi pokazuje się natychmiast (jest w zestawie), a werdykt dochodzi po chwili, więc nie ma martwego ekranu.

### 7.2 Bank zadań zamiast generowania na starcie

Nowa tabela `grammar_items`: umiejętność, forma, stopień pomocy, polecenie, podpowiedź, kształt, odpowiedź wzorcowa, warianty, źródło (wygenerowane, z błędu, z rozmowy), licznik pokazań. Generator działa w tle i dba, żeby każda umiejętność miała zapas zadań. Runda składa się z banku w ułamku sekundy.

Przy generowaniu w tle czas nie gra roli, więc można użyć mocniejszego modelu (ustawienie `OPENAI_GRAMMAR_MODEL` już istnieje) i dodać automatyczną kontrolę jakości: odrzucać zadanie, gdy widoczna podpowiedź zawiera odpowiedź, gdy zdanie wzorcowe nie zawiera ćwiczonej struktury (pola `detect` w katalogu opisują, jak ją rozpoznać) albo gdy powtarza się z istniejącym.

### 7.3 Mapa i harmonogram

Nowa tabela `grammar_skills`: struktura, znaczenie, poziom, termin powtórki, odstęp, seria poprawnych, mediana czasu reakcji. `grammar_results` dostaje odniesienie do umiejętności i werdykt zapisywany od razu. Dotychczasowe `grammar_sessions` z planem w JSON przestają być potrzebne dla nowych rund.

### 7.4 Ograniczenie, o którym trzeba wiedzieć

Rozpoznawanie mowy potrafi po cichu naprawić gramatykę. Dla okresów warunkowych czy czasów to rzadko przeszkadza, ale przy przedimkach i końcówce *-s* w trzeciej osobie transkrypt bywa „lepszy” niż to, co padło. Dla tych umiejętności ocena z mowy będzie mniej wiarygodna. Rozsądne wyjście to forma mieszana: mówisz zdanie, a potem jednym kliknięciem wskazujesz, którego przedimka użyłeś. Warto to sprawdzić na próbce, zanim przedimki trafią na mapę.

### 7.5 Koszt

Jedno zadanie to kilka sekund transkrypcji i jedno krótkie żądanie tekstowe. To rzędy wielkości taniej niż głos na żywo, ale nie znam aktualnego cennika, więc do ustawień warto dodać licznik wydatków z bieżącego miesiąca. Synteza mowy w formie „Odpowiedz na głos” jest dodatkowym kosztem i jej nagrania można zapisywać razem z zadaniem w banku, żeby płacić raz.

## 8. Most do rozmów w subskrypcji

Ćwiczenia utrwalają formę, ale dopiero rozmowa sprawdza, czy sięgasz po nią sam. Dwa lekkie połączenia, oba opcjonalne:

- **Temat na dziś.** Po rundzie aplikacja pokazuje gotowy tekst do wklejenia w rozmowie głosowej w subskrypcji, ułożony pod umiejętności z tego tygodnia. Przykład: „Porozmawiajmy po angielsku o decyzjach zawodowych, których żałuję. Zadawaj pytania hipotetyczne, nie poprawiaj mnie w trakcie.”
- **Import transkryptu.** Wklejasz zapis rozmowy. Aplikacja wyciąga z Twoich wypowiedzi błędy gramatyczne, przypisuje je do umiejętności na mapie i robi z nich zadania w formie „Z twoich błędów”. Poprawne użycia dają gwiazdkę „w rozmowie”.

To drugie daje coś, czego nie da żaden generator: listę rzeczy, które naprawdę mówisz źle.

## 9. Shadowing

Shadowing to mówienie razem z nagraniem, pół sekundy za lektorem, z naśladowaniem rytmu i melodii. Da się go zrobić dobrze, pod warunkiem że aplikacja obiecuje tylko to, co umie zmierzyć.

### 9.1 Po co Ci to

- Ćwiczy usta, rytm i łączenie słów bez wymyślania treści. Tempo narzuca nagranie, więc nie ma pustki w głowie ani momentu, w którym trzeba się zmusić do mówienia. To najmniej męcząca forma mówienia na głos, dobra na rozgrzewkę i na dni, kiedy nie chce się myśleć.
- Utrwala gramatykę, jeśli teksty są nasycone strukturami, które akurat ćwiczysz. Poprawny kształt zdania przechodzi przez usta kilkanaście razy w naturalnym tempie, zanim trzeba go zbudować samemu.
- Nie zastępuje rund. Shadowing nie uczy wyboru formy ani szukania słów, więc jest dodatkiem do rund gramatycznych, nie ich zamiennikiem.

### 9.2 Jak wygląda runda

Jeden fragment trwa 20-40 sekund, cała runda ok. 3 minut.

1. **Posłuchaj.** Raz, z tekstem na ekranie.
2. **Mów razem, z tekstem.** Nagranie leci w słuchawkach, bieżące słowo jest podświetlone.
3. **Mów razem, bez tekstu.** Tylko ze słuchu.
4. **Wynik i pętla.** Aplikacja pokazuje miejsce, w którym odpadłeś, i zapętla samo to zdanie, najpierw wolniej (0,85), potem w normalnym tempie.
5. **Porównanie.** Twoje nagranie zdania odtwarzane zaraz po lektorze. Samo usłyszenie różnicy uczy więcej niż jakikolwiek wskaźnik.

Każdy krok można pominąć. Poziom trudności to tempo (0,85 → 1,0 → 1,15) i to, czy tekst jest widoczny.

### 9.3 Skąd teksty i głos

- **Teksty:** generowane pod umiejętności z mapy, które są w toku, oraz pod Twoje tematy. Najlepiej krótkie dialogi i monologi w rejestrze mówionym. Dobrym źródłem jest też historia z rundy „Odcinek”: najpierw ją odgrywasz, potem cieniujesz jej wzorcową wersję.
- **Głos:** synteza mowy przez API, generowana raz i zapisywana obok tekstu, kilka głosów na zmianę. W aplikacji nie ma dziś żadnej syntezy, trzeba ją dodać. Jakość syntezy do shadowingu trzeba ocenić własnym uchem na kilku próbkach przed budowaniem reszty, bo jeśli melodia zdania jest płaska, cały moduł traci sens.
- **Własne nagrania:** jako późniejsza opcja wgranie pliku audio z transkryptem (fragment podcastu). Prawdziwa mowa jest lepszym wzorem niż synteza, ale wymaga więcej pracy przy przygotowaniu.

### 9.4 Co da się zmierzyć

Większość potrzebnych części już jest w trenerze czytania (`services/reading.py`): dopasowanie tego, co powiedziałeś, do tekstu wzorcowego słowo po słowie, lokalne tempo, pauzy.

| Pomiar | Wiarygodność | Jak |
|---|---|---|
| Ile słów nadążyłeś powiedzieć | dobra | dopasowanie transkryptu do tekstu, tak jak w trenerze czytania |
| Gdzie odpadłeś | dobra | pierwsze dłuższe ciągi pominiętych słów |
| Opóźnienie względem lektora i czy rośnie w trakcie | średnia | znaczniki czasu słów w Twoim nagraniu kontra w nagraniu wzorcowym (to drugie transkrybowane raz, przy generowaniu) |
| Zgodność pauz i rytmu fraz | średnia | porównanie miejsc pauz |
| Wymowa głosek, akcent, intonacja | **nie mierzymy** | rozpoznawanie mowy tego nie ocenia, a udawana ocena wymowy byłaby szkodliwa. Do tego służy porównanie na słuch |

Dwa haczyki techniczne:

- **Słuchawki są konieczne**, inaczej mikrofon nagra lektora.
- **Słuchawki Bluetooth opóźniają dźwięk** o 150-300 ms, co zafałszuje pomiar opóźnienia. Dlatego wynik pokazuje zmianę opóźnienia w trakcie fragmentu i między podejściami, a nie wartość bezwzględną.

W sierpniu z aplikacji został usunięty moduł „Shadow Conversation”. Z historii zmian nie wynika dlaczego, więc jeśli powód był konkretny (jakość głosu, pomiar, nuda), warto go uwzględnić przed budową.

### 9.5 Miejsce w sesji

Shadowing jest jedną z form rundy, obok ośmiu zadań gramatycznych. Aplikacja proponuje go jako rozgrzewkę albo jako „jeszcze jedną rundę” po gramatyce, na materiale z tych samych umiejętności.

## 10. Co z resztą aplikacji

| Element | Decyzja |
|---|---|
| Moduł Rozmowa (GPT-Live) | Wyłączony i schowany. Drogi, a w testach rozmówca nie zaczynał rozmowy i wykrywanie tur gubiło wypowiedzi. Nie warto tego naprawiać, skoro rozmawiasz w subskrypcji |
| Sesja 40 min, rundy, sondy near/far, poziomy wsparcia | Schowane pod „więcej → laboratorium”. 0 użyć w 81 dni |
| Keyword planning, writing rehearsal, autotranskrypcja, diagnostyka wąskiego gardła, recovery drill | Do usunięcia razem ze starą sesją albo do laboratorium |
| Kalibracja jako bramka przed startem | Do usunięcia. Gramatyka jej nie potrzebuje |
| Trener czytania | Zostaje pod „więcej” |
| VAD i pomiar czasu reakcji | Zostają, bo czas reakcji decyduje o poziomie 3 |

Wygląd: dziś szary tekst na czarnym tle. Proponuję jeden kolor akcentu, wyraźne zielone i bursztynowe stany werdyktu, krótki dźwięk przy poprawnej odpowiedzi i małą animację przy awansie na mapie. Bez punktów doświadczenia, lig i maskotek.

## 11. Kolejność prac

Każdy etap zostawia aplikację lepszą niż przed nim.

**Etap 1: runda, która nagradza.** Najmniejsza zmiana o największym skutku, w całości na istniejącym module.
- Ocena po każdym zadaniu, „powiedz jeszcze raz”, powrót błędnego zadania w tej samej rundzie.
- Rundy po 8 zadań z wynikiem i przyciskiem „jeszcze jedna”.
- Przerwana runda zachowuje oceny.
- Test: klikam, w 5 sekund widzę zadanie, po odpowiedzi w 3 sekundy wiem, czy było dobrze.

**Etap 2: bank zadań i start bez czekania.** Tabela `grammar_items`, generator w tle, kontrola jakości, łagodniejsze stopnie pomocy.

**Etap 3: mapa.** `grammar_skills`, poziomy, harmonogram powtórek, rundy mieszane, skan początkowy, nowy ekran startowy z jednym przyciskiem.

**Etap 4: formy.** Jak to powiedzieć, Odcinek, O tobie, Sprint, Odpowiedz na głos.

**Etap 5: shadowing.** Najpierw próba głosu: 3-4 fragmenty z syntezy do odsłuchania, bez żadnego kodu poza generowaniem. Jeśli brzmi dobrze: runda z trzema przejściami, wynik „ile nadążyłeś i gdzie odpadłeś”, pętla na trudnym zdaniu, porównanie na słuch. Ten etap nie zależy od mapy, więc można go zrobić wcześniej, zaraz po Etapie 1, jeśli wolisz.

**Etap 6: pełny katalog.** Brakujące struktury z sekcji 4, próba z przedimkami.

**Etap 7: most do subskrypcji.** Temat na dziś, import transkryptu, zadania z własnych błędów.

**Etap 8: porządki.** Schowanie Rozmowy i starej sesji, cel tygodniowy, licznik kosztów, aktualizacja `README.md`, `SPEC.md` i plików w `docs/`.

## 12. Jak sprawdzić, czy to działa

- **Użycie:** co najmniej 4 dni w tygodniu z przynajmniej jedną rundą, przez 4 kolejne tygodnie. Dziś zero. Jeśli po Etapie 1 to się nie ruszy, trzeba zmieniać rundę, a nie budować dalej.
- **Nauka:** liczba umiejętności na poziomie 4 oraz mediana czasu reakcji w rundach mieszanych.
- **Przeniesienie:** gwiazdki z importu rozmów. To jedyny dowód, że gramatyka przeszła do mówienia.

## 13. Decyzje, które należą do Ciebie

1. **Język wyjaśnień.** Rekomenduję wyjaśnienia po angielsku z jednym zdaniem kontrastu po polsku tam, gdzie błąd wynika z polszczyzny. Dziś wszystko jest po angielsku.
2. **Forma „Jak to powiedzieć”.** Tłumaczenie z polskiego jest skuteczne, ale obecny prompt celowo unika polskiego. Rekomenduję dopuścić.
3. **Moduł Rozmowa.** Rekomenduję schować, nie kasować, na wypadek gdyby ceny spadły.
4. **Mocniejszy model do generowania zadań.** Poprawia jakość treści, kosztuje więcej za zestaw, ale działa w tle i rzadko. Rekomenduję.
5. **Shadowing: kiedy.** Rekomenduję zaraz po Etapie 1, zaczynając od próby głosu. Jeśli synteza nie zabrzmi wystarczająco naturalnie, zostaje wariant z własnymi nagraniami albo rezygnacja.
