# Changelog

## 0.1.1

- Prima pubblicazione del repository, con installazione come repository personalizzato HACS.
- Corretto il caricamento bloccante dei certificati TLS durante l'avvio del client: l'opener HTTPS viene creato alla prima richiesta, eseguita fuori dal ciclo principale di Home Assistant.
- Aggiunti test di regressione per il caricamento dei certificati e la costruzione del client.
- Aggiunti documentazione, licenza, icona originale e controlli automatici.

## 0.1.0

- Beta iniziale in sola lettura, distribuita manualmente.
- Letture separate per zona tramite corrispondenza tra SDID cloud e messaggi del termostato.
- Configurazione tramite interfaccia, conservazione del solo token e diagnostica anonimizzata.
