# Matrica zahteva i otvorena pitanja

## Potvrđeno iz zahteva korisnika

| Zahtev | Početno rešenje | Status |
|---|---|---|
| Web aplikacija | FastAPI API + responsive web shell | Započeto |
| Više korisnika | Users, memberships, pet uloga i jednokratne pozivnice | Implementiran temelj |
| Više firmi | Tenant model sa `organization_id` i kreiranje dodatne firme | Implementiran temelj |
| Veći obim podataka | PostgreSQL, indeksi, keyset smernica | Započeto |
| Hetzner VPS | Docker Compose, privatna DB mreža, Caddy TLS | Započeto |
| Python 3.14+ | `requires-python >=3.14`, 3.14 Docker image | Započeto |
| eFakture i eOtpremnice | Konkretni SEF/eOtpremnice API klijenti | Započeto |

## Izvučeno iz dokumentacije

| Oblast | Pitanja |
|---|---|
| Okruženja | SEF produkcija i eOtpremnice demo/produkcija/offline domene su mapirane |
| Autentikacija | SEF koristi `ApiKey`; eOtpremnice koristi `Api-key`, po kompaniji |
| eFakture | Izlazni UBL, ulazni/izlazni statusi, XML/PDF, storno, prihvatanje/odbijanje, PDV v1/v2 |
| eOtpremnice | DespatchAdvice, ReceiptAdvice i ApplicationResponse UBL 1.1.0 |
| Formati | SEF `application/xml`; eOtpremnice `multipart/form-data` sa `RequestId` i XML fajlom |
| Sinhronizacija | SEF promene po vremenu; eOtpremnice PULL po datumu/stranici i PUSH pretplata |
| Deduplikacija događaja | Jedinstven događaj po firmi, servisu, toku i udaljenom ID-u; cursor po svakom toku |
| Greške | eOtpremnice BusinessMessages i RFC 9110 offline greške; čuvaju se strukturirano |
| Statusi | Statusi se čuvaju kao izvorne vrednosti, odvojeno od internog workflow statusa |
| Uloge | eOtpremnice tokovi su odvojeni na supplier, customer i carrier |
| Produkcijska mreža | Izlazni HTTPS/443 ka četiri zvanična SEF/eOtpremnice hosta mora biti dozvoljen |
| Verzije | SEF 4.1.1; eOtpremnice API 1.6.0, demo izdanje 1.6.3 i produkcijsko 1.6.1, provereno 23.09.2026. |
| Zakon 80/2026 | Novi izuzeci, QR tok za prevoznika bez pristupa i obaveza spoljnog prikaza moraju biti poslovna pravila |

## Još treba potvrditi u sandbox-u

- Tačan produkcijski payload i odgovor za svaki endpoint kod kog PDF i OpenAPI nisu potpuno usklađeni.
- Rate limit i ponašanje pri 429/5xx; retry neće biti aktiviran naslepo.
- Maksimalna veličina dokumenata/priloga i timeout-i za realne dokumente.
- PUSH webhook potpis/autentikacija, javna dostupnost i ponavljanje dostave.
- Pravila rotacije i opoziva API ključeva.
- Potpuna XSD/Schematron validacija; lokalni paket sadrži primere, ali ne i kompletan skup šema.
- Potvrditi kako produkcijski API tehnički izlaže novi zakonski QR/spoljni-prikaz tok ako to nije deo javnog Swagger ugovora 1.6.0.

## Poslovne odluke koje treba potvrditi

- Da li platforma služi jednoj grupi povezanih firmi ili je SaaS za nepovezane klijente?
- Očekivani broj firmi, korisnika i dokumenata dnevno/godišnje.
- Da li se računi kreiraju u aplikaciji ili samo uvoze/sinhronizuju iz ERP-a?
- Potrebni ERP/računovodstveni konektori i format izvoza.
- Da li su potrebni kvalifikovani elektronski potpis i lokalni sertifikati.
- Koji je ciljani domen, region servera, RPO/RTO i očekivani SLA.
