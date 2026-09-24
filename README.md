# eDokumenti — eFakture i eOtpremnice

Početni temelj višekorisničke web aplikacije za rad sa SEF eFakturama i eOtpremnicama. Projekat je spreman za Python 3.14, PostgreSQL i postavljanje na Hetzner VPS putem Docker Compose-a.

Integracioni sloj je mapiran prema lokalnoj dokumentaciji od 31. jula i 21. avgusta 2026, SEF OpenAPI v1/v2 ugovorima, tehničkom uputstvu eOtpremnice 1.6.0 i UBL primerima 1.1.0. Zvanični izvori su ponovo provereni 23.09.2026: SEF je na 4.1.1, javni eOtpremnice Swagger ugovor je 1.6.0, a operativna izdanja su 1.6.3 na demo i 1.6.1 na produkciji. Klijenti ne pozivaju državne servise bez eksplicitno konfigurisanog ključa firme.

## Šta već postoji

- korisnici, firme i članstvo korisnika u više firmi;
- uloge: vlasnik, administrator, knjigovođa, operater i pregled;
- kreiranje dodatnih firmi i jednokratne pozivnice sa istekom za nove ili postojeće korisnike;
- JWT prijava sa Argon2 lozinkama;
- stroga provera firme na svakom tenant API pozivu;
- šifrovanje API ključeva pomoću Fernet ključa;
- evidencija dokumenata, idempotency ključevi i audit događaji;
- metapodaci za XML/PDF priloge van baze;
- PostgreSQL migracija, Docker Compose i Caddy HTTPS proxy;
- osnovni responsive web ekran i OpenAPI dokumentacija u development režimu.
- konkretni SEF Public API klijent za slanje, promene, XML/PDF i prihvatanje/odbijanje;
- konkretni eOtpremnice klijent za asinhrono slanje, PULL tokove po ulozi, validaciju i priloge;
- poseban eOtpremnice offline klijent za PDF sa ugrađenim QR kodom;
- evidencija spoljnih zahteva, poslovnih grešaka i zasebnih sync cursor-a po firmi i toku.
- upload XML/PDF priloga sa ograničenjem veličine, SHA-256 proverom i zaštitom putanje;
- trajni PostgreSQL red poslova i zaseban worker za slanje dokumenata;
- kontrolisan retry samo za mrežne greške, HTTP 429 i 5xx odgovore, sa oporavkom nakon restarta.
- automatska SEF sinhronizacija izlaznih i ulaznih faktura sa vremenskim preklapanjem;
- paginirana eOtpremnice sinhronizacija zahteva i supplier/customer/carrier tokova;
- idempotentni dnevnik spoljnih događaja i automatsko preuzimanje XML-a novog dokumenta.
- responsive radni panel za dokumente, poslove, događaje, korisnike i integracije;
- poslovne forme za izlaznu fakturu i eksternu/internu eOtpremnicu, bez ručnog XML-a;
- ponovljive stavke, partner, adrese, poreski i transportni podaci u web interfejsu;
- automatsko generisanje i čuvanje UBL XML-a uz dokument, sa izborom nacrta ili slanja u red;
- ručni XML/PDF upload i preuzimanje priloga bez Swagger-a za napredne i uvozne tokove.
- JWT vezan za opozivu serversku sesiju, pregled uređaja i bezbedna odjava;
- distribuirana PostgreSQL zaštita prijave i sigurnosna HTTP/CSP zaglavlja.
- jednokratni reset lozinke preko email linka, uz opoziv svih postojećih sesija;
- trajni PostgreSQL email outbox sa SMTP STARTTLS slanjem i kontrolisanim ponavljanjem;
- TOTP dvofaktorska prijava, zaštita od ponovne upotrebe koda i jednokratni rezervni kodovi.
- kompletan web tok za dodavanje firme, email poziv i prihvatanje poziva za novog ili postojećeg korisnika.
- bezbedan izbor Demo/Produkcija za svaku integraciju, sa Demo okruženjem kao podrazumevanim i fiksnim zvaničnim API adresama.

## Lokalno pokretanje

### Izolovana Docker test verzija na Windows-u

Lokalni profil ne pokreće Caddy i ne zauzima portove 80/443. Aplikacija je vezana samo za `127.0.0.1:18080`, a Mailpit test sanduče samo za `127.0.0.1:18025`. PostgreSQL nije izložen host računaru.

```powershell
.\scripts\Initialize-LocalEnvironment.ps1
.\scripts\Start-LocalTest.ps1
```

Skripta generiše lokalne tajne i test administratorsku lozinku u datotekama koje su isključene iz Git-a, gradi kontejnere, izvršava migracije i proverava prijavu i pristup test firmi. Email poruke ne napuštaju računar već se vide u Mailpit-u.

Ako antivirus koristi HTTPS skeniranje, inicijalizaciona skripta izvozi samo njegov javni root sertifikat u Git-ignorisani `.docker-local` direktorijum i bira `Dockerfile.local`. TLS provera ostaje uključena i sistemski CA bundle koristi se i za lokalne izlazne API pozive; privatni ključevi se ne izvoze niti se koristi nesigurni `trusted-host` režim. `.dockerignore` sprečava slanje lokalnih tajni u Docker build context.

Zaustavljanje bez brisanja podataka:

```powershell
.\scripts\Stop-LocalTest.ps1
```

Brisanje isključivo lokalnih test volumena radi potpuno svežeg testa:

```powershell
.\scripts\Stop-LocalTest.ps1 -ResetData
```

### Standardni serverski profil

1. Kopirati `.env.example` u `.env`.
2. Napraviti vrednosti:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. Dodati u `.env` i promenljive bez prefiksa: `POSTGRES_PASSWORD` i `APP_DOMAIN`. Za reset lozinke obavezno podesiti `APP_PUBLIC_BASE_URL` i SMTP promenljive iz primera.
4. Pokrenuti: `docker compose up --build -d`.
5. Kreirati prvog administratora jednim pozivom na `POST /api/v1/auth/bootstrap` (Swagger je na `/api/docs` u development režimu).

Nikada ne čuvati produkcijske tajne u Git-u. Bootstrap endpoint se automatski zatvara nakon prvog korisnika.

## Demo nalozi državnih servisa

Lokalni administratorski nalog aplikacije kreira se automatski, ali SEF i eOtpremnice demo naloge aplikacija ne može da kreira umesto korisnika. Za oba servisa registracija ide preko eID-a, a API ključ se generiše u podešavanjima odgovarajućeg demo portala. Ključ je vezan za okruženje u kome je izdat i ne treba ga upisivati u `.env`, Git ili dokumentaciju.

1. SEF demo portal: `https://demoefaktura.mfin.gov.rs/` - u delu `Podešavanja / API menadžment` generisati ključ i aktivirati API status.
2. eOtpremnice demo portal: `https://demoeotpremnica.mfin.gov.rs/` - registrovati subjekt preko eID-a i u podešavanjima generisati demo API ključ.
3. U ovoj aplikaciji otvoriti `Integracije`, ostaviti okruženje `Demo` i nalepiti odgovarajući ključ za trenutno izabranu firmu.
4. Posle čuvanja koristiti dugme `Proveri vezu`; provera je bezbedna i ne šalje dokument.

API adrese se biraju na serveru iz fiksne liste zvaničnih Demo/Produkcija adresa. Time se sprečava da korisnički unos preusmeri worker na proizvoljan server. Izbor produkcije zahteva dodatnu potvrdu u interfejsu.

## Sledeći koraci

1. Prebaciti storage adapter na Hetzner Object Storage sa enkripcijom i retention pravilima.
2. Dodati obradu eOtpremnice `ApplicationResponse` XML događaja i njihovo vezivanje za izvorni dokument.
3. Proširiti tipizirane forme na avansne i konačne fakture, knjižna odobrenja/zaduženja,
   obračun PDV-a i opasnu robu, uz proveru kroz državne XML validatore.
4. Dodati administrativni tok za bezbedan reset MFA i obavezno ponovno potvrđivanje identiteta za osetljive promene.
5. Dodati PostgreSQL RLS kao drugi sloj tenant izolacije.
6. Tek uz zasebne sandbox ključeve izvršiti end-to-end testove prema demo okruženjima.

## Prvi višekorisnički tok

1. Prijavljeni korisnik može napraviti dodatnu firmu preko `POST /api/v1/organizations`.
2. Vlasnik ili administrator bira firmu zaglavljem `X-Organization-Id` i pravi poziv preko `POST /api/v1/invitations`.
3. Jednokratni link se automatski stavlja u email outbox; web interfejs ga prikazuje i jednom kao rezervu za ručno dostavljanje.
4. Primalac otvara link i prihvata poziv u web interfejsu. Novi korisnik navodi ime i novu lozinku, a postojeći potvrđuje svoju lozinku.
5. Token se u bazi čuva samo kao SHA-256 otisak, ima rok trajanja i ne može se ponovo upotrebiti.

## Unos fakture ili otpremnice bez XML-a

1. U delu `Podešavanja` jednom unesite poslovnu adresu i email izabrane firme.
   Pravni naziv, PIB/JMBG i matični broj moraju biti podaci subjekta kome pripada API ključ.
2. Na početnoj strani izaberite `Novi dokument`, a zatim SEF fakturu ili eOtpremnicu.
3. Unesite kupca/primaoca, datume i jednu ili više stavki. Za otpremnicu se dodatno
   unose mesto otpreme/isporuke i podaci o transportu.
4. Dugme `Generiši dokument` pravi UBL XML i čuva ga kao prilog nacrta. Opcija
   `Pošalji u red odmah nakon kreiranja` koristi prethodno sačuvan ključ izabrane firme.

Ključevi se ne unose uz svaki dokument. Šifrovano se čuvaju po firmi i okruženju,
a menjaju se samo kada korisnik želi da zameni ključ ili pređe sa Demo na Produkciju.
PIB pošiljaoca i primaoca mora imati 9 cifara (ili 13 cifara za JMBG), a primalac
mora biti registrovan u istom SEF Demo ili Produkcijskom okruženju. Serverske
validatorske poruke čuvaju se uz neuspešan dokument radi lakšeg otklanjanja greške.

Trenutna forma pokriva standardnu izlaznu fakturu i standardnu eksternu/internu
otpremnicu. Napredni poreski scenariji biće dodavani kao posebni tipovi dokumenata,
da se obavezna polja ne mešaju sa uobičajenim unosom.

## Ručni tok slanja dokumenta

1. Kreirati dokument preko `POST /api/v1/documents`.
2. Dodati XML kao `multipart/form-data` preko `POST /api/v1/documents/{id}/artifacts`, sa poljem `kind=source_xml` i poljem `file`.
3. Pozvati `POST /api/v1/documents/{id}/queue`; odgovor sadrži stanje trajnog posla.
4. Servis `worker` iz `compose.yaml` preuzima posao i šalje ga odgovarajućem servisu koristeći šifrovani ključ izabrane firme.
5. Rezultat i greške se vide kroz `GET /api/v1/jobs` i dokument API, a svaka promena se auditira.

## Automatska sinhronizacija

Worker periodično obrađuje svaki aktivni API ključ firme. SEF tokovi koriste zaseban dnevni cursor za prodajne i ulazne fakture i, prema ugovoru servisa, traže isključivo datume iz prošlosti. eOtpremnice koriste zaseban datum/stranicu za zahteve, pošiljaoca, primaoca i prevoznika. Greška jednog toka ne prekida ostale tokove. Događaj se jedinstveno prepoznaje po firmi, servisu, toku i udaljenom identifikatoru, pa ponovno čitanje ne pravi duplikate.

- `GET /api/v1/external-events` prikazuje primljene događaje.
- `GET /api/v1/sync-cursors` prikazuje trenutno mesto svakog toka.
- Novi udaljeni dokument automatski dobija lokalni zapis i `remote_xml` prilog.

## Web interfejs

Nakon prijave korisnik bira firmu kojoj pripada. Interfejs automatski šalje `X-Organization-Id` uz svaki tenant zahtev i prikazuje akcije prema ulozi korisnika. Vlasnik i administrator mogu da povežu servise i izdaju pozivnice; knjigovođa i operater mogu da kreiraju i šalju dokumente; korisnik sa ulogom pregleda nema akcije izmene.

JWT sadrži identifikator serverske sesije. Svaki zaštićeni zahtev proverava da sesija nije istekla ili opozvana. Korisnik može pregledati svoje aktivne uređaje i opozvati pojedinačnu sesiju; odjava opoziva trenutnu sesiju pre brisanja tokena iz browsera.

Reset lozinke uvek vraća isti javni odgovor bez obzira da li email postoji. Link sadrži nasumični token koji se u bazi čuva samo kao SHA-256 otisak, ističe i može se upotrebiti samo jednom. Worker šalje poruke iz `email_outbox` tabele; bez podešenog `APP_SMTP_HOST` poruke ostaju u redu i taj režim nije pogodan za produkciju.

TOTP se uključuje u delu „Korisnici“. Tajna se čuva Fernet-šifrovano, prihvata se samo mali vremenski prozor, a isti vremenski kod se ne može upotrebiti dva puta. Rezervni kodovi se prikazuju samo jednom i svaki se pojedinačno poništava nakon upotrebe.

Detaljnije odluke su u [`docs/ARHITEKTURA.md`](docs/ARHITEKTURA.md), zahtevi u [`docs/MATRICA-ZAHTEVA.md`](docs/MATRICA-ZAHTEVA.md), a tehnički nalazi u [`docs/ZAHTEVI-IZ-DOKUMENTACIJE.md`](docs/ZAHTEVI-IZ-DOKUMENTACIJE.md).
