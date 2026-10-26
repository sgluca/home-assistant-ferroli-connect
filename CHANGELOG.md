# Changelog

## 0.2.0

- Aggiunte richieste di lettura delle zone all'avvio, dopo la conferma delle sottoscrizioni, e ogni 120 secondi.
- Aggiunto un dispositivo separato per la caldaia: stato del relè, tipo di collegamento e connessione OpenTherm, se disponibili.
- Invio limitato a pacchetti QUERY; setpoint, modalità e programmi non vengono modificati.
- Aggiunti contatori diagnostici per richieste di lettura ed errori di consegna. Un ACK MQTT non viene interpretato come risposta del dispositivo.
- Esclusi i pacchetti QUERY eventualmente riflessi dal cloud dalle letture, per non mostrare i loro valori segnaposto.
- Test simulati su frequenza delle letture, isolamento delle zone e dello stato caldaia; la risposta sul gateway reale resta da verificare.

## 0.1.1

- Prima pubblicazione del repository, con installazione come repository personalizzato HACS.
- Corretto il caricamento bloccante dei certificati TLS durante l'avvio del client: l'opener HTTPS viene creato alla prima richiesta, eseguita fuori dal ciclo principale di Home Assistant.
- Aggiunti test di regressione per il caricamento dei certificati e la costruzione del client.
- Aggiunti documentazione, licenza, icona originale e controlli automatici.

## 0.1.0

- Beta iniziale in sola lettura, distribuita manualmente.
- Letture separate per zona tramite corrispondenza tra SDID cloud e messaggi del termostato.
- Configurazione tramite interfaccia, conservazione del solo token e diagnostica anonimizzata.
