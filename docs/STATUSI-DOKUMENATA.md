# Statusi i brojači dokumenata

Ovaj dokument opisuje pravila koja aplikacija koristi za prikaz statusa i brojače u
glavnoj navigaciji. Brojač predstavlja otvorene dokumente: dokumente koji traže rad ili
čiji se tok još odvija. Nije ukupan broj dokumenata.

## SEF eFakture

Otvoreni statusi obuhvataju nacrte, slanje, nove/primljene dokumente, poslate i pregledane
fakture, dospele fakture i greške koje treba ispraviti. Kao završeni se tretiraju statusi
`Approved`, `Paid`, `Rejected`, `Cancelled`, `Storno`, `Deleted` i `Archived`.

Odbijena faktura je konačno završena na SEF-u i zato se ne računa u navigacioni brojač,
ali se i dalje prikazuje u metrici „Pažnja“ i može se pronaći statusnim filterom.

## eOtpremnice i ePrijemnice

„Prijemnice“ predstavljaju ulazni tok robe: primljene eOtpremnice i ePrijemnice koje firma
šalje kao odgovor. „Otpremnice“ predstavljaju izlazni tok robe: eOtpremnice koje firma šalje
i ePrijemnice koje prima od kupca.

Za eOtpremnicu su `Sent`/`Received` i `Delivered` otvoreni statusi. `Delivered` znači samo
fizički prijem robe; proces tada još nije usaglašen. Završni statusi su `Fulfilled`,
`Cancelled` i `Seized`.

Za ePrijemnicu su `Sent` i `Received` otvoreni, a `Accepted`, `Rejected` i `Cancelled`
završni statusi. Početak prevoza se prikazuje kao događaj/oznaka, a nije poseban status
dokumenta.

## Izvori

- Tehničko uputstvo za eOtpremnice 1.4.0:
  https://eotpremnica.efaktura.gov.rs/extfile/sr/5377/%D0%A2%D0%B5%D1%85%D0%BD%D0%B8%D1%87%D0%BA%D0%BE%20%D1%83%D0%BF%D1%83%D1%82%D1%81%D1%82%D0%B2%D0%BE%201.4.0.pdf
- Najčešća pitanja sistema eOtpremnica:
  https://www.eotpremnica.efaktura.gov.rs/tekst/6563/najcesce-postavljena-pitanja.php
- SEF API dokumentacija:
  https://efaktura.gov.rs/extfile/en/5376/API%20dokumentacija%2030.04.2026.pdf
