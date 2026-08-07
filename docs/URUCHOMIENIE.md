# Jak uruchomić aplikację — instrukcja krok po kroku

Ten dokument jest dla osób, które nie programują. Nie potrzebujesz terminala ani
znajomości gita. Zajmie to około 20 minut, z czego większość to czekanie na
instalację.

Masz dwie możliwości:

- **Na własnym komputerze** — za darmo, aplikacja działa tylko wtedy, gdy jest
  włączona. To zalecana droga.
- **Na serwerze w internecie** — dostępna z każdego urządzenia, ale płatna
  (kilkadziesiąt złotych miesięcznie). Opisana [na końcu](#wariant-b-na-serwerze-w-internecie).

W obu przypadkach potrzebujesz klucza OpenAI — [instrukcja niżej](#klucz-openai).

---

## Wariant A: na własnym komputerze (Windows)

### Krok 1. Zainstaluj dwa programy

Aplikacja korzysta z dwóch darmowych narzędzi. Jeśli już je masz, pomiń ten krok.

**Python** — pobierz z [python.org/downloads](https://www.python.org/downloads/)
i uruchom instalator. **Ważne:** na pierwszym ekranie instalatora zaznacz pole
**„Add Python to PATH"** na dole okna. Bez tego aplikacja nie znajdzie Pythona.

**Node.js** — pobierz wersję oznaczoną **LTS** z [nodejs.org](https://nodejs.org/)
i zainstaluj, klikając „Dalej" na każdym ekranie.

Po instalacji obu programów **uruchom komputer ponownie**.

### Krok 2. Pobierz aplikację

Na stronie projektu na GitHubie kliknij zielony przycisk **Code**, a potem
**Download ZIP**. Rozpakuj pobrany plik w wybranym miejscu, na przykład
`C:\SpeakingTrainer`.

Unikaj folderów synchronizowanych z chmurą (OneDrive, Dropbox) — potrafią
blokować pliki w trakcie działania aplikacji.

### Krok 3. Uruchom instalację

Wejdź do rozpakowanego folderu i kliknij dwukrotnie **`setup.bat`**.

Otworzy się czarne okno, które przez kilka minut będzie wypisywać komunikaty —
pobiera biblioteki i modele językowe (razem około 1 GB). Poczekaj, aż zobaczysz
napis **„Gotowe"**, i zamknij okno.

Jeśli Windows wyświetli ostrzeżenie o nieznanym wydawcy, wybierz **Więcej
informacji → Uruchom mimo to**.

### Krok 4. Zdobądź klucz OpenAI

Zobacz [osobną sekcję niżej](#klucz-openai). Wróć tutaj, gdy będziesz mieć
skopiowany klucz.

### Krok 5. Uruchom aplikację

Kliknij dwukrotnie **`start.bat`**. Otworzy się czarne okno, a po chwili
przeglądarka z aplikacją pod adresem `http://127.0.0.1:8000`.

**To czarne okno musi pozostać otwarte** — zamknięcie go wyłącza aplikację.
Możesz je zminimalizować.

Od teraz uruchamiasz aplikację wyłącznie przez `start.bat`. `setup.bat` był
jednorazowy.

### Krok 6. Pierwsze ustawienia

1. Kliknij **settings** i wklej klucz OpenAI w pole `sk-...`, potem **Save key**.
   Aplikacja od razu sprawdzi klucz w OpenAI i powie, czy działa.
2. Wróć i kliknij **Calibrate**. Nagraj **10 sekund ciszy** w pokoju, w którym
   będziesz ćwiczyć — aplikacja zmierzy poziom szumu i dostroi wykrywanie mowy.
   Bez tego pauzy będą mierzone błędnie.
3. Przeglądarka zapyta o dostęp do mikrofonu — zezwól.

Gotowe. Kliknij **Start session** i zacznij.

---

## Klucz OpenAI

Aplikacja używa OpenAI do dwóch rzeczy: zamiany nagrania na tekst oraz
przygotowania podsumowania po sesji. Płacisz bezpośrednio OpenAI za to, ile
zużyjesz — nie ma abonamentu ani opłaty za samą aplikację.

### Jak go utworzyć

1. Załóż konto na [platform.openai.com](https://platform.openai.com/signup)
   (to inne konto niż ChatGPT — możesz użyć tego samego adresu e-mail).
2. Wejdź w **Settings → Billing** i doładuj konto. Minimalna kwota to zwykle
   5 USD i przy normalnym używaniu wystarczy na wiele tygodni. **Bez doładowania
   klucz nie zadziała** — to najczęstsza przyczyna problemów.
3. Wejdź na [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
   i kliknij **Create new secret key**. Nazwij go dowolnie, na przykład
   „trener wymowy".
4. **Skopiuj klucz od razu** — zaczyna się od `sk-` i zostanie pokazany tylko ten
   jeden raz. Jeśli go zgubisz, po prostu utwórz nowy.
5. Wklej go w aplikacji w **settings**.

### Ile to kosztuje

Orientacyjnie, według cennika OpenAI znanego w połowie 2026 roku:

| Co | Koszt |
|---|---|
| Transkrypcja nagrań | ok. 0,006 USD za minutę mowy |
| Podsumowanie i feedback po sesji | ułamki centa |
| Generowanie nowych zadań | kilka centów, sporadycznie |

Sesja treningowa trwa 10–15 minut, z czego mówisz około 8–10 minut. To znaczy
**około 25 groszy za sesję**, czyli przy codziennym ćwiczeniu **rzędu 10 złotych
miesięcznie**.

Ceny sprawdź na [openai.com/api/pricing](https://openai.com/api/pricing) — mogły
się zmienić. Na koncie OpenAI możesz ustawić miesięczny limit wydatków, żeby mieć
pewność, że nic Cię nie zaskoczy.

---

## Wariant B: na serwerze w internecie

Ma sens, jeśli chcesz ćwiczyć na różnych urządzeniach albo nie chcesz trzymać
włączonego komputera. Kosztuje osobno — poza opłatami dla OpenAI.

**Ważne:** aplikacja jest jednoosobowa. Nie ma kont użytkowników, a cała historia
należy do jednej osoby. Każda osoba potrzebuje własnej instancji.

### Ile to kosztuje

Aplikacja potrzebuje co najmniej **1 GB pamięci RAM** (mniej nie wystarczy —
modele językowe się nie zmieszczą) oraz **2 GB dysku** na bazę i nagrania. W
zależności od dostawcy i planu to zwykle kilkadziesiąt złotych miesięcznie.
Sprawdź aktualne cenniki, bo się zmieniają:

- [Render](https://render.com/pricing) — najprostszy; plik `render.yaml` w
  repozytorium konfiguruje wszystko automatycznie
- [Railway](https://railway.com/pricing) — rozliczenie za faktyczne zużycie
- [Fly.io](https://fly.io/docs/about/pricing/) — najtaniej, ale wymaga terminala

### Jak to zrobić na Render

1. Załóż konto na [render.com](https://render.com) i połącz je ze swoim kontem
   GitHub (musisz mieć kopię tego repozytorium na swoim koncie — użyj przycisku
   **Fork** na stronie projektu).
2. W panelu Render wybierz **New → Blueprint** i wskaż to repozytorium. Render
   sam odczyta plik `render.yaml`.
3. Render zapyta o dwie wartości, **zanim** uruchomi aplikację:
   - `APP_PASSWORD` — wymyśl mocne hasło, którym będziesz się logować
   - `OPENAI_API_KEY` — klucz z sekcji wyżej
4. Poczekaj na zakończenie wdrożenia (pierwsze trwa kilkanaście minut) i wejdź
   na przydzielony adres. Zaloguj się hasłem, potem skalibruj mikrofon.

### Bezpieczeństwo

Aplikacja **nie uruchomi się publicznie bez hasła** — to celowe zabezpieczenie.
Gdyby ktoś obcy trafił na Twój adres bez hasła, mógłby nagrywać na Twój koszt.
Jeśli zobaczysz komunikat o konieczności ustawienia `APP_PASSWORD`, to znaczy, że
zabezpieczenie zadziałało.

Hasło możesz później zmienić w aplikacji w **settings**, bez ponownego wdrażania.

---

## Co robić, gdy coś nie działa

**Okno `setup.bat` zamyka się od razu / pisze, że nie znaleziono Pythona.**
Python nie został dodany do PATH. Zainstaluj go ponownie i zaznacz „Add Python to
PATH", a potem uruchom komputer ponownie.

**Przeglądarka pisze „nie można połączyć się z serwerem".**
Okno `start.bat` zostało zamknięte albo aplikacja jeszcze wstaje. Uruchom
`start.bat` i odczekaj kilkanaście sekund.

**Nagrywam, ale nie ma transkrypcji ani feedbacku.**
Najczęściej brak środków na koncie OpenAI albo nieważny klucz. Wejdź w
**settings** i zapisz klucz ponownie — aplikacja od razu powie, czy OpenAI go
akceptuje.

**Przeglądarka nie prosi o mikrofon albo go blokuje.**
Kliknij ikonę kłódki obok adresu i zezwól na dostęp do mikrofonu. Wchodź zawsze
na `http://127.0.0.1:8000` — pod innymi adresami przeglądarka zablokuje mikrofon
ze względów bezpieczeństwa.

**Aplikacja mierzy dziwne pauzy.**
Powtórz kalibrację (**recalibrate**) w tym samym pokoju i z tym samym mikrofonem,
którego używasz do ćwiczeń. Zmiana mikrofonu również wymaga ponownej kalibracji —
wyniki sprzed zmiany nie są z nowymi porównywalne.

**Gdzie są moje dane?**
W folderze `data` obok aplikacji: baza `app.db` i nagrania w `audio`. Nagrania
kasują się automatycznie po 30 dniach, wyniki zostają. Jeśli chcesz zacząć od
zera, zamknij aplikację i usuń plik `app.db`.
