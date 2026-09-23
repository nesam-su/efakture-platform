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

## Lokalno pokretanje

1. Kopirati `.env.example` u `.env`.
2. Napraviti vrednosti:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. Dodati u `.env` i promenljive bez prefiksa: `POSTGRES_PASSWORD` i `APP_DOMAIN`.
4. Pokrenuti: `docker compose up --build -d`.
5. Kreirati prvog administratora jednim pozivom na `POST /api/v1/auth/bootstrap` (Swagger je na `/api/docs` u development režimu).

Nikada ne čuvati produkcijske tajne u Git-u. Bootstrap endpoint se automatski zatvara nakon prvog korisnika.

## Sledeći koraci

1. Dodati periodične sync poslove za SEF i eOtpremnice na postojeći PostgreSQL worker.
2. Prebaciti storage adapter na Hetzner Object Storage sa enkripcijom i retention pravilima.
3. Implementirati generatore UBL dokumenata kao tipizirane forme, uz obaveznu proveru kroz državne XML validatore.
4. Uvesti pozivnice, reset lozinke i 2FA pre produkcije.
5. Dodati PostgreSQL RLS kao drugi sloj tenant izolacije.
6. Tek uz zasebne sandbox ključeve izvršiti end-to-end testove prema demo okruženjima.

## Prvi višekorisnički tok

1. Prijavljeni korisnik može napraviti dodatnu firmu preko `POST /api/v1/organizations`.
2. Vlasnik ili administrator bira firmu zaglavljem `X-Organization-Id` i pravi poziv preko `POST /api/v1/invitations`.
3. API vraća jednokratni `invitation_token`; u produkciji ga treba poslati primaocu preko budućeg email servisa, ne zapisivati u log.
4. Primalac prihvata poziv preko `POST /api/v1/auth/invitations/accept`. Novi korisnik navodi ime i lozinku, a postojeći potvrđuje svoju lozinku.
5. Token se u bazi čuva samo kao SHA-256 otisak, ima rok trajanja i ne može se ponovo upotrebiti.

## Tok slanja dokumenta

1. Kreirati dokument preko `POST /api/v1/documents`.
2. Dodati XML kao `multipart/form-data` preko `POST /api/v1/documents/{id}/artifacts`, sa poljem `kind=source_xml` i poljem `file`.
3. Pozvati `POST /api/v1/documents/{id}/queue`; odgovor sadrži stanje trajnog posla.
4. Servis `worker` iz `compose.yaml` preuzima posao i šalje ga odgovarajućem servisu koristeći šifrovani ključ izabrane firme.
5. Rezultat i greške se vide kroz `GET /api/v1/jobs` i dokument API, a svaka promena se auditira.

Detaljnije odluke su u [`docs/ARHITEKTURA.md`](docs/ARHITEKTURA.md), zahtevi u [`docs/MATRICA-ZAHTEVA.md`](docs/MATRICA-ZAHTEVA.md), a tehnički nalazi u [`docs/ZAHTEVI-IZ-DOKUMENTACIJE.md`](docs/ZAHTEVI-IZ-DOKUMENTACIJE.md).
