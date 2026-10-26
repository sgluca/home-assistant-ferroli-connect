# Security

Non pubblicare credenziali, token, backup di Home Assistant o catture di traffico nelle issue. Per segnalazioni ordinarie usa la diagnostica anonimizzata dell'integrazione. Per una vulnerabilità usa la segnalazione privata di GitHub, se disponibile nella scheda Security del repository.

## Protezioni attive

- `main` richiede una pull request, le conversazioni risolte e i test Python 3.13 e 3.14 superati su un ramo aggiornato rispetto alla base. I check sono associati all'app GitHub Actions.
- Nessun bypass è configurato, nemmeno per gli amministratori.
- Force push e cancellazione di `main` sono bloccati. Sono ammessi solo merge squash, con cronologia lineare.
- I tag `v*` non possono essere cancellati o riscritti; le nuove versioni usano nuovi tag.
- Secret scanning e push protection sono abilitati; Dependabot segnala dipendenze vulnerabili e propone aggiornamenti.
- Non è richiesta un'approvazione esterna: il progetto può essere mantenuto da una sola persona. Il requisito di PR e CI rimane attivo.

Le configurazioni dei ruleset sono conservate in `.github/rulesets/`; GitHub applica le copie impostate nelle opzioni del repository. Modificare i file non aggiorna automaticamente le regole lato server. Le regole non equivalgono a una verifica completa del comportamento sul dispositivo reale.
