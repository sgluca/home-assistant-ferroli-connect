# Ferroli Connect for Home Assistant

Unofficial, experimental **read-only** integration for thermostats controlled by the **Ferroli CONNECT** app (`com.szacs.ferroliconnect`). Each zone is represented by a separate Home Assistant device, using its cloud name.

**Stato attuale:** letture e distinzione di due zone verificate su un impianto; nessun comando di temperatura o modalità. Non è un'integrazione ufficiale Ferroli e non è inclusa nel catalogo predefinito HACS.

## Installazione con HACS

Richiede Home Assistant **2026.10 o successivo** e accesso all'account Ferroli Connect.

1. Apri HACS, seleziona il menu e **Repository personalizzati**.
2. Aggiungi `https://github.com/sgluca/home-assistant-ferroli-connect` con categoria **Integrazione**.
3. Cerca **Ferroli Connect**, scaricala e riavvia Home Assistant.
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

Non crea ancora entità `climate` e non invia comandi MQTT. L'app ufficiale continua a essere usata per i comandi. Non richiede un broker MQTT locale, modifiche al router o una nuova associazione dei termostati.

Apri ogni zona nell'app ufficiale per ricevere i primi dati. Se un valore non viene aggiornato per dieci minuti, diventa non disponibile. La freschezza è verificata per ciascun valore: un aggiornamento del setpoint non rende recente la temperatura ambiente. I messaggi MQTT retained non rendono disponibili le letture e non sovrascrivono valori più recenti.

## Come funziona

L'integrazione usa il cloud europeo Topband tramite HTTPS per la sessione, l'inventario e la configurazione MQTT; riceve quindi la telemetria mediante MQTT con TLS verificato. Distingue le zone confrontando il campo binario `0x0017` con `child_devices.sdid` del cloud, come l'app Android. Gli ID mancanti, duplicati o non riconosciuti non vengono attribuiti a un'altra zona.

Il client MQTT ha un identificativo separato dall'app. La convivenza è stata verificata durante brevi prove; il funzionamento prolungato, le riconnessioni e il rinnovo automatico del token richiedono ancora validazione sul servizio reale. Non si tratta di un'integrazione locale: serve la disponibilità del cloud.

## Credenziali e diagnostica

La password viene usata solo durante l'accesso e non viene salvata dall'integrazione. Home Assistant conserva il token di sessione nella propria configurazione; anche i backup possono contenerlo. Non condividere `.storage`, token o backup per segnalare un problema.

La diagnostica scaricabile dalla pagina dell'integrazione include soltanto conteggi, età dei dati ed errori generici. Esclude configurazione, account, nomi delle zone, ID, token, topic e messaggi grezzi. In una issue indica la versione di Home Assistant, la versione dell'integrazione e il comportamento osservato; verifica sempre eventuali log prima di pubblicarli.

## Limiti della beta

- Nessuna modifica di setpoint, modalità o programmi, e nessun controllo locale.
- Non invia interrogazioni per forzare l'aggiornamento: la frequenza della telemetria spontanea ad app chiusa va verificata sul dispositivo.
- Le temperature sono supportate in Celsius; se viene segnalata l'unità Fahrenheit diventano non disponibili.
- Il flag di richiesta riscaldamento non dimostra che la fiamma della caldaia sia accesa.
- Zone con SDID assente, non valido o duplicato bloccano l'avvio; dopo modifiche all'elenco delle zone ricarica l'integrazione.
- Il token HTTP viene rinnovato ogni trenta minuti; un accesso rifiutato richiede nuova autenticazione. I tentativi di riconnessione MQTT sono distanziati di almeno due minuti.
- I test automatici verificano protocollo e trasporto simulato. Non equivalgono a una prova completa in Home Assistant o su ogni firmware.

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
