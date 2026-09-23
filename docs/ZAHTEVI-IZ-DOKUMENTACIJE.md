# Tehnički zahtevi SEF i eOtpremnice

Analizirani paket sadrži 32 PDF dokumenta sa ukupno 1.356 strana, tri OpenAPI specifikacije sa 86 operacija i 33 XML primera. Implementacija prioritet daje API dokumentaciji od 31.07.2026, SEF OpenAPI v1/v2, verziji SEF 4.1.1 od 21.08.2026, tehničkom uputstvu eOtpremnice 1.6.0 i UBL primerima 1.1.0.

## Provera zvaničnih izvora 23.09.2026.

- SEF demo i produkcija su na verziji 4.1.1, dok je EPP na 3.0.0.
- Zvanični javni eOtpremnice Swagger i dalje objavljuje API ugovor 1.6.0. Operativno izdanje je 1.6.3 u demo i 1.6.1 u produkcionom okruženju.
- Beleške za 1.6.1 opisuju kopiranje ulazne eOtpremnice u nacrt, a 1.6.3 optimizaciju performansi; nije objavljena promena javnog API ugovora.
- Za produkciju treba dozvoliti izlazni HTTPS/443 prema `eotpremnica.mfin.gov.rs`, `efaktura.mfin.gov.rs`, `api.eotpremnica.mfin.gov.rs` i `auth.sef.mfin.gov.rs`.
- Zvanični Swagger potvrđuje množinu u putanji `application-responses/{id}/xml/download`; ona je implementirana u klijentu.
- Poziv `/public/documents/requests/changes` sa `requestId` služi za reconciliation i nakon uspešne obrade vraća identifikator dokumenta.
- Početak prevoza može se evidentirati bez skeniranog dokumenta; PDF ostaje deo koverte/dokumentacije, pa model priloga mora podržati naknadno povezivanje.

## Propisi koje poslovna pravila moraju pratiti

Izmene Zakona o elektronskim otpremnicama iz „Službenog glasnika RS“ 80/2026 stupile su na snagu 08.09.2026. Za implementaciju su naročito važne sledeće tačke:

- izuzeci obuhvataju određene manje količine reprezentacije kupljene u maloprodaji, vrednosne vaučere, akcizne markice, novac, novine, časopise i slična dobra;
- prevoznik koji nema pristup sistemu može predstaviti eOtpremnicu QR kodom koji je sistem kreirao;
- kada se koristi taj tok, pošiljalac najkasnije pre početka kretanja prilaže spoljni prikaz eOtpremnice preko sistema;
- eventualne greške u iskazanim podacima se u nadzoru ne uzimaju u obzir do zaključno sa 01.01.2027, ali aplikacija i dalje mora validirati i auditovati podatke.

Ovo nije zamena za pravno tumačenje. Pravila i rokovi moraju biti konfigurabilni i ponovo potvrđeni pre produkcijskog puštanja.

## SEF

- Produkcijska baza: `https://efaktura.mfin.gov.rs`.
- Autentikacija: HTTP zaglavlje `ApiKey`.
- Slanje izlazne fakture: `POST /api/publicApi/sales-invoice/ubl`, telo `application/xml`; podržani su `requestId`, `sendToCir` i `executeValidation`.
- Promene statusa: `POST` na `/sales-invoice/changes` i `/purchase-invoice/changes`, sa date-time parametrom.
- Preuzimanje XML/PDF-a je poseban poziv po `invoiceId`.
- Prihvatanje/odbijanje ulazne fakture koristi `invoiceId`, `accepted` i opcioni `comment`.
- Public API v1 ima 73 operacije. Public API v2 ima 12 operacija i odnosi se na pojedinačnu i zbirnu evidenciju PDV, uključujući korekcije, storniranje i PDF.
- Izlazni statusi uključuju: `New`, `Draft`, `Sent`, `Paid`, `Mistake`, `OverDue`, `Archived`, `Sending`, `Deleted`, `Approved`, `Rejected`, `Cancelled`, `Storno`, `Unknown`.
- Ulazni statusi uključuju: `New`, `Seen`, `ReNotified`, `Approved`, `Rejected`, `Storno`.
- Verzija 4.1.0 uvodi dodatna polja i validacije zbirne evidencije PDV; verzija 4.1.1 je optimizacija performansi bez novog API ugovora.

## eOtpremnice

- Demo API: `https://api.demoeotpremnica.mfin.gov.rs`.
- Produkcijski API: `https://api.eotpremnica.mfin.gov.rs`.
- Offline demo/produkcija: `https://offline.demoeotpremnica.mfin.gov.rs` i `https://offline.eotpremnica.mfin.gov.rs`.
- Autentikacija: HTTP zaglavlje `Api-key`.
- UBL verzija 1.1.0 koristi `DespatchAdvice`, `ReceiptAdvice` i `ApplicationResponse`.
- UBL slanje: `POST /public/documents/requests`, multipart polja `RequestId` i `File`; obrada je asinhrona.
- Rezultat obrade: `GET /public/documents/requests/changes`, obavezni datum `yyyy-MM-dd`, stranice počinju od 0, opcioni `requestId`.
- Greška obrade sadrži `businessMessages`: `code`, `xmlValidationCode`, `severity`, `details` i XML `path`.
- PULL tokovi su odvojeni po ulogama: `/suppliers/changes`, `/customers/changes` i `/carriers/changes`.
- Za svaki tip/ulogu postoje status, XML, PDF i gde je primenljivo potpis/QR endpoint-i.
- PUSH pretplata: `POST /public/webhook-notifications/subscribe`; pretplata važi od narednog dana.
- XML validator: `POST /public/xml-validator/validate-document`, a katalog poruka je poseban GET endpoint.
- Offline OpenAPI 1.5.0 prima PDF sa ugrađenim QR kodom preko `POST /public/offline` i vraća RFC 9110 Problem Details greške sa `traceId` i detaljima.

## Statusi eOtpremnica po ulozi

| Dokument i uloga | Sistemski statusi |
|---|---|
| Otpremnica, pošiljalac | `Sent`, `Cancelled`, `Delivered`, `Seized`, `Fulfilled` |
| Otpremnica, primalac | `Received`, `Cancelled`, `Delivered`, `Seized`, `Fulfilled` |
| Prijemnica, pošiljalac | `Received`, `Cancelled`, `Accepted`, `Rejected` |
| Prijemnica, primalac | `Sent`, `Cancelled`, `Accepted`, `Rejected` |
| Prevoznik | Vidi statuse kao pošiljalac robe |

## Posledice za implementaciju

- API ključ mora biti šifrovan zasebno po firmi i servisu.
- `RequestId` i SEF `requestId` moraju biti jedinstveni i ponovljivi radi idempotency/reconciliation procesa.
- PULL cursor mora biti zaseban za svaki servis, firmu, ulogu i tok.
- Izvorni payload, odgovor, `traceId` i poslovne poruke treba čuvati bez tajnih zaglavlja.
- PDF/XML datoteke treba čuvati u objektnom skladištu sa SHA-256 checksum-om, ne u PostgreSQL redu.
- Notifikacije i slanje moraju biti background poslovi; HTTP web zahtev samo kreira posao.
- Pre slanja eOtpremnice treba pozvati XML validator; lokalna provera ne zamenjuje državnu poslovnu validaciju.
- Ulazni webhook mora biti idempotentan, rate-limited i auditovan.
- Verzije i propisi moraju se pratiti periodično; operativna verzija sistema nije nužno jednaka verziji objavljenog OpenAPI ugovora.
