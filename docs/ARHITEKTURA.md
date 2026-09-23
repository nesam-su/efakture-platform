# Početna arhitektura

## Izbor tehnologija

- **Python 3.14 + FastAPI**: tipiziran asinhroni API, jednostavna OpenAPI dokumentacija.
- **PostgreSQL 17**: pouzdane transakcije, JSONB za izvorni payload, indeksi i particionisanje za veći obim. SQLite nije prihvatljiv za višekorisničku produkciju.
- **Caddy**: automatski TLS i reverse proxy na Hetzner VPS-u.
- **S3-kompatibilan storage**: XML/PDF van baze; baza čuva checksum, veličinu, MIME tip i object key.
- **Redis + worker (sledeća faza)**: slanje, polling i uvoz ne treba izvršavati u HTTP zahtevu.

## Tenant model

Jedan korisnik može pripadati većem broju firmi. Svaki poslovni red nosi `organization_id`, a API prihvata firmu preko `X-Organization-Id` tek nakon provere članstva. Uloge ograničavaju izmene. Pre produkcije treba dodati PostgreSQL Row Level Security kao dodatnu zaštitu od programerske greške.

Za vrlo velike klijente moguć je kasniji prelazak na zasebnu šemu ili bazu po firmi, bez menjanja API ugovora.

## Tok dokumenta

1. Korisnik ili uvoz kreira lokalni dokument sa jedinstvenim idempotency ključem.
2. Worker validira obavezna polja i zvaničnu XML/JSON šemu.
3. SEF worker šalje XML sinhrono; eOtpremnice worker šalje multipart zahtev i čuva jedinstveni `RequestId` za asinhronu obradu.
4. Periodični posao čita SEF promene po vremenu, a eOtpremnice promene po datumu, ulozi i stranici; svaki tok ima svoj cursor/watermark.
5. Svaka poslovna akcija i promena statusa ulazi u audit.

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
