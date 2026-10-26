# Changelog

## 0.3.0

- Un'entità `climate` per ogni zona, mantenendo tutti i sensori precedenti.
- Comandi Manuale, Automatico e Off, temperatura manuale e modifica temporanea in Automatico, con limiti e passo verificati.
- Conferma dei comandi tramite nuova telemetria MQTT della zona interessata; nessuno stato ottimistico e nessuna ripetizione automatica dei controlli.
- Letture HTTPS supplementari dei punti di ciascuna zona, con controlli sul timestamp della cache e priorità ai dati MQTT più nuovi.
- Una zona che non risponde non interrompe la lettura delle altre.
- Test sui comandi e sull'adattatore climate, protezioni GitHub, CODEOWNERS e aggiornamenti Dependabot documentati.
- Scritture e lettura completa ad app chiusa da validare sul dispositivo reale.

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
