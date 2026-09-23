# Početna arhitektura

## Izbor tehnologija

- **Python 3.14 + FastAPI**: tipiziran asinhroni API, jednostavna OpenAPI dokumentacija.
- **PostgreSQL 17**: pouzdane transakcije, JSONB za izvorni payload, indeksi i particionisanje za veći obim. SQLite nije prihvatljiv za višekorisničku produkciju.
- **Caddy**: automatski TLS i reverse proxy na Hetzner VPS-u.
- **Storage izvan baze**: XML/PDF su trenutno na trajnom Docker volumenu; baza čuva checksum, veličinu, MIME tip i object key. Interfejs je pripremljen da se produkcija kasnije prebaci na S3-kompatibilni Hetzner Object Storage.
- **PostgreSQL red + worker**: slanje se ne izvršava u HTTP zahtevu. Poslovi se trajno čuvaju, preuzimaju pomoću `FOR UPDATE SKIP LOCKED`, imaju eksponencijalni retry za 429/5xx i oporavak zastarelog lock-a.

## Tenant model

Jedan korisnik može pripadati većem broju firmi. Svaki poslovni red nosi `organization_id`, a API prihvata firmu preko `X-Organization-Id` tek nakon provere članstva. Uloge ograničavaju izmene. Pre produkcije treba dodati PostgreSQL Row Level Security kao dodatnu zaštitu od programerske greške.

Za vrlo velike klijente moguć je kasniji prelazak na zasebnu šemu ili bazu po firmi, bez menjanja API ugovora.

## Tok dokumenta

1. Korisnik ili uvoz kreira lokalni dokument sa jedinstvenim idempotency ključem.
2. XML/PDF prilog se upisuje izvan baze u tenant/document putanju, uz SHA-256 i ograničenje veličine.
3. API kreira trajan `send_document` posao, a worker validira konfiguraciju i šalje dokument.
4. SEF worker šalje XML sinhrono; eOtpremnice worker šalje multipart zahtev i čuva jedinstveni `RequestId` za asinhronu obradu.
5. Periodični posao čita SEF promene po vremenu, a eOtpremnice promene po datumu, ulozi i stranici; svaki tok ima svoj cursor/watermark.
6. Svaka poslovna akcija i promena statusa ulazi u audit.

Izvorni status državnog sistema čuva se kao tekstualna vrednost odvojeno od internog statusa. Time se ne gubi razlika između, na primer, `Sent` u SEF-u i `Sent` iz ugla pošiljaoca eOtpremnice.

## Kapacitet i baza

- Traženja su indeksirana po firmi + vremenu i firmi + statusu.
- Liste koriste ograničenu stranicu; produkcijska verzija treba stabilan `(created_at, id)` keyset cursor.
- `audit_events` i `business_documents` treba mesečno particionisati kada pojedina tabela dođe do desetina miliona redova.
- Connection pool treba računati prema broju Gunicorn/Uvicorn procesa; ne preći PostgreSQL `max_connections`.
- Read replica je potrebna tek kada izveštavanje počne da smeta transakcijama.

## Bezbednost pre produkcije

- Hetzner firewall: javno samo 80/443 i ograničen SSH; PostgreSQL nikad nije javno izložen.
- SSH ključevi, isključen password login, automatske sigurnosne zakrpe.
- Tajne kroz Docker secrets/secret manager, ne kroz repozitorijum.
- 2FA, pozivnice sa istekom, reset lozinke i opoziv sesija.
- Rate limit za prijavu i spoljne callback rute.
- Dnevni šifrovani backup baze i objekata, plus redovan restore test na drugoj lokaciji.
- DPA/retention politika, logovi bez API ključeva i osetljivih payload-a.

## Predlog Hetzner postavke

Početno: jedan CPX/CCX VPS za aplikaciju + odvojeni Managed PostgreSQL ako je dostupan u izabranom regionu, ili zaseban privatni DB VPS. Produkcijski dokumenti idu u Object Storage. Za ozbiljan SLA aplikaciju razdvojiti na dva čvora iza load balancera, a bazu voditi kao HA uslugu. Dimenzionisanje zavisi od broja firmi, dokumenata dnevno, veličine priloga i propisanog roka čuvanja.
