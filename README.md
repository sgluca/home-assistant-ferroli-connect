# Ferroli Connect for Home Assistant

Unofficial, experimental Home Assistant integration for thermostats controlled by the **Ferroli CONNECT** app (`com.szacs.ferroliconnect`). Each zone has a separate device, sensors and a `climate` entity. A separate device represents boiler status.

**Stato attuale:** ricezione e distinzione di due zone verificate su un impianto. La **0.3.0** aggiunge `climate`, comandi delle zone e letture HTTPS supplementari per i valori mancanti. Queste nuove funzioni hanno superato test simulati e richiedono ancora verifica sull'impianto. Non è un'integrazione ufficiale Ferroli e non è inclusa nel catalogo predefinito HACS.

## Installazione con HACS

Richiede Home Assistant **2026.10 o successivo** e accesso all'account Ferroli Connect.

1. Apri HACS, seleziona il menu e **Repository personalizzati**.
2. Aggiungi `https://github.com/sgluca/home-assistant-ferroli-connect` con categoria **Integrazione**.
3. Cerca **Ferroli Connect**, abilita le versioni beta, seleziona la versione desiderata e riavvia Home Assistant.
4. Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Ferroli Connect**.
5. Inserisci account e password nella schermata di Home Assistant.

Se avevi installato la beta manuale, conserva lo stesso dominio e la stessa cartella `custom_components/ferroli_connect`: non creare una seconda integrazione. Dopo l'aggiornamento riavvia Home Assistant. Gli identificativi delle entità sono invariati rispetto alla 0.1.0.

### Installazione manuale

Copia `custom_components/ferroli_connect` nella cartella `/config/custom_components/` e riavvia Home Assistant. Deve esistere `/config/custom_components/ferroli_connect/manifest.json`.

## Funzioni disponibili

Per ciascuna zona, quando presenti nella telemetria:

- temperatura ambiente, setpoint e temperatura manuale;
- temperature comfort, economy e antigelo;
- modalità operativa;
- batteria scarica e richiesta di riscaldamento.

Per la caldaia espone **Relè caldaia attivo**, **Collegamento caldaia** (`on_off` / `opentherm`) e **OpenTherm connesso**, se il dispositivo restituisce questi dati. Lo stato del relè rappresenta il contatto del ricevitore e non conferma che la fiamma sia accesa. Con collegamento ON/OFF temperature interne e pressione della caldaia potrebbero non essere disponibili; questa versione non le espone e non le deduce dalle zone.

I sensori esistenti sono mantenuti. Non richiede un broker MQTT locale, modifiche al router o una nuova associazione dei termostati.

### Entità climate e scritture delle zone

Ogni zona espone un termostato `climate` con temperatura ambiente e obiettivo. Le modalità sono **Heat = Manuale**, **Auto = programma automatico** e **Off = spento del termostato**; Off non equivale necessariamente a disalimentare la caldaia o disattivare l'antigelo.

- In Manuale la temperatura modifica il setpoint manuale.
- In Automatico la temperatura imposta una modifica temporanea, senza riscrivere il programma settimanale.
- Selezionare esplicitamente Auto annulla la modifica temporanea e torna al programma.
- Da Off scegli Manuale/Automatico prima di cambiare temperatura, oppure specifica insieme temperatura e modalità nell'azione di Home Assistant.
- Il comando di accensione sceglie Manuale. Non sono esposti comandi di scrittura per la caldaia, gli installatori o i programmi.

Le temperature sono accettate solo in Celsius, con passo 0,5 °C, entro i limiti effettivamente letti dal termostato. Se modalità, unità o limiti non sono disponibili o sono vecchi, la scrittura viene rifiutata. Non vengono eseguiti comandi all'avvio, al ripristino dello stato o alla riconnessione.

Ogni comando è inviato una sola volta, senza retained o ritrasmissione dopo una riconnessione, e viene seguito da una richiesta di lettura. Il successo richiede valori ricevuti via MQTT dalla stessa zona dopo l'invio, entro 20 secondi: una conferma di trasporto o la cache HTTPS non bastano. L'interfaccia non anticipa il valore desiderato. Un timeout può significare che la modifica è stata applicata ma non confermata: controlla l'app prima di riprovare.

### Aggiornamento con l'app chiusa

Dopo la conferma delle sottoscrizioni MQTT richiede lo stato di ciascuna zona e della caldaia. Ripete la lettura ogni **120 secondi** e dopo una riconnessione. Le richieste periodiche sono pacchetti Topband QUERY, senza retained. Solo un'azione esplicita su `climate` invia un pacchetto CONTROL di zona; non esiste un comando DELETE.

La lettura HTTPS `thermostat_points/{wifi_box_code}/{sdid}`, usata anche dall'app, integra i campi mancanti separatamente per ogni zona. I valori sono stringhe esadecimali; campi assenti o non validi non diventano zero. La cache viene accettata solo con timestamp valido e recente, senza sovrascrivere telemetria MQTT più nuova. La sua età è riferita allo snapshot del cloud: il servizio non fornisce qui un timestamp per ogni singolo campo. Un errore o una mancata risposta di una zona non interrompe le letture dell'altra.

Se un valore non viene aggiornato per dieci minuti, diventa non disponibile. La freschezza è verificata per ciascun valore: un aggiornamento del setpoint non rende recente la temperatura ambiente. I messaggi MQTT retained e le eventuali copie delle richieste QUERY non vengono usati come letture.

## Come funziona

L'integrazione usa il cloud europeo Topband tramite HTTPS per la sessione, l'inventario e la configurazione MQTT; riceve quindi la telemetria mediante MQTT con TLS verificato. Distingue le zone confrontando il campo binario `0x0017` con `child_devices.sdid` del cloud, come l'app Android. Gli ID mancanti, duplicati o non riconosciuti non vengono attribuiti a un'altra zona.

Il client MQTT ha un identificativo separato dall'app. La convivenza in ascolto passivo è stata verificata durante brevi prove; il funzionamento con letture automatiche, le riconnessioni e il rinnovo del token richiedono ancora validazione sul servizio reale. Non si tratta di un'integrazione locale: serve la disponibilità del cloud.

## Credenziali e diagnostica

La password viene usata solo durante l'accesso e non viene salvata dall'integrazione. Home Assistant conserva il token di sessione nella propria configurazione; anche i backup possono contenerlo. Non condividere `.storage`, token o backup per segnalare un problema.

La diagnostica scaricabile dalla pagina dell'integrazione include soltanto conteggi, età dei dati ed errori generici. Esclude configurazione, account, nomi delle zone, ID, token, topic e messaggi grezzi. In una issue indica la versione di Home Assistant, la versione dell'integrazione e il comportamento osservato; verifica sempre eventuali log prima di pubblicarli.

## Limiti della beta

- Nessun controllo locale e nessuna modifica di programmi, parametri installatore o comandi caldaia.
- Le nuove interrogazioni sono ricostruite dal percorso di lettura dell'app 1.5.2; la risposta effettiva del gateway ad app chiusa va verificata sul tuo firmware.
- Le temperature sono supportate in Celsius; se viene segnalata l'unità Fahrenheit diventano non disponibili.
- Il flag di richiesta riscaldamento non dimostra che la fiamma della caldaia sia accesa.
- Zone con SDID assente, non valido o duplicato bloccano l'avvio; dopo modifiche all'elenco delle zone ricarica l'integrazione.
- Il token HTTP viene rinnovato ogni trenta minuti; un accesso rifiutato richiede nuova autenticazione. I tentativi di riconnessione MQTT sono distanziati di almeno due minuti.
- I test automatici verificano protocollo e trasporto simulato. Non equivalgono a una prova completa in Home Assistant o su ogni firmware.

## Verifica consigliata della beta

Chiudi l'app e verifica prima le letture di entrambe le zone per almeno due cicli (circa quattro minuti). Poi, su una sola zona in Manuale, modifica il setpoint di 0,5 °C e controlla nell'app e sul termostato che sia cambiata soltanto quella zona; ripristina il valore iniziale. Verifica separatamente Automatico e la modifica temporanea. Le scritture sono sperimentali finché non sono state provate sul tuo firmware.

## Sviluppo e test

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

I test non richiedono account Ferroli o accesso ai dispositivi. La pipeline esegue anche controlli di sintassi Python e metadati JSON. Include una regressione per evitare il caricamento bloccante dei certificati TLS durante la costruzione del client nel ciclo principale di Home Assistant.

## Riferimenti

- [Prodotto Ferroli Connect](https://www.ferroli.com/it/products/complementi-residenziale-riscaldamento/connect)
- [Precedente ricerca indipendente sul protocollo](https://github.com/Suxsem/Ferroli-connect-reverse-engineering)
- [Documentazione HACS sui repository di integrazione](https://www.hacs.xyz/docs/publish/integration/)

Il repository contiene il client Python e test sintetici; non contiene APK, sorgenti decompilati, catture di traffico o dati dell'account usato per le prove. Il codice è distribuito con licenza MIT. Marchi e nomi dei prodotti appartengono ai rispettivi titolari.
