# Changelog

## 1.0.0

- Prima release stabile, dopo conferma dell’utente su letture e comandi dell’impianto a due zone.
- Un termostato climate per zona, controllo temperatura e modalità, sensori delle zone e stato caldaia, con l’app ufficiale utilizzabile.
- Include la correzione dei limiti 0/0 della 0.3.2 e le letture sequenziali per le zone.
- Nuova icona con monogramma **SL**, firma di **sgluca**.
- Installazione da HACS senza abilitare le beta; aggiornamento dalla 0.3.2 senza ricreare l’integrazione.
- Compatibilità verificata su un impianto; altri firmware e funzionamento a lungo termine restano da osservare.

## 0.3.2

- Corretti i pulsanti +/− quando il ricevitore restituisce minimo = massimo = 0: il valore veniva vincolato a zero e inviato al dispositivo. In questo caso si usa ora l’intervallo 5–35 °C del controllo manuale/automatico dell’app ufficiale, anche per validare i comandi. I limiti validi ricevuti restano prioritari; altre coppie incoerenti bloccano la scrittura.

- L'entità **Caldaia accesa** perde il suffisso “(app)”, mantenendo identificativo e significato dello stato.
- Aggiunte istruzioni per provare i comandi di temperatura sulle due zone tramite le entità Termostato, già disponibili dalla 0.3.0.
- Aggiornamento delle letture e stato caldaia confermati dall'utente sull'impianto a due zone con la 0.3.1; scritture ancora da verificare sul dispositivo reale.

## 0.3.1

- Aggiunta **Caldaia accesa (app)** con il significato usato dall'app ufficiale: `1` = spenta, `2` = accesa. Il contatto grezzo del relè resta distinto; l'entità precedente non viene invertita silenziosamente.
- Richieste delle zone sequenziali, con attesa limitata e correlazione di zona e progressivo, invece di invii ravvicinati dopo la sola conferma del broker.
- Diagnostica per zona con campi presenti, richieste, risposte correlate, timeout ed esito HTTPS, senza valori o ID reali.
- Il problema di aggiornamento completo della zona Slave richiede ancora una prova sul dispositivo reale.

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
