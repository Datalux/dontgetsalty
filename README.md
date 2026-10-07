# Don't Get Salty 🤫

Party game web per gruppi di amici: si propongono domande (scomode, curiose, imbarazzanti...)
e si vota anonimamente chi si pensa corrisponda a ciascuna domanda. Nessuno vede chi ha scritto
una domanda né chi ha votato cosa: si vede solo il risultato aggregato.

## Come si gioca

1. Un giocatore crea una **stanza** e riceve un codice a 5 caratteri.
2. Gli altri entrano dal browser inserendo il codice e il proprio nome (minimo 3 giocatori).
3. L'host avvia la partita scegliendo il **numero di round**.
4. Ad ogni round, ognuno propone **una domanda** in forma anonima.
5. Quando tutte le domande sono state inviate, partono le **votazioni**: le domande vengono
   estratte una alla volta (ordine mescolato) e ognuno vota chi pensa sia la risposta giusta
   (è ammesso anche votare se stessi). Dopo ogni domanda si vede il tally dei voti (solo conteggi,
   mai chi ha votato cosa), poi l'host passa alla successiva.
6. Esaurite le domande del round si passa al round successivo, fino alla fine; alla fine si vede
   un riepilogo completo di tutte le domande e i relativi risultati.

## Anonimato

Ai giocatori non viene **mai** mostrato l'autore di una domanda né il dettaglio dei singoli voti:
l'API pubblica e i messaggi WebSocket restituiscono solo testo delle domande e conteggi aggregati
(vedi `app/game.py::public_state`). Non esiste nel codice nessuna vista, endpoint o query che
esponga chi ha scritto una domanda o chi ha votato cosa — quel dato non viene mai restituito a
nessun client.

Il database (`app/db.py`) è **SQLite in-memory**: nessun dato di gioco viene mai scritto su
disco. Non esiste un file `.db` da aprire — chi ha accesso al filesystem del server (backup,
dashboard dell'hosting, disco del container) non trova nulla, perché non c'è nulla lì. Tutto
vive solo nella RAM del processo per la durata della partita e sparisce a un riavvio.

## Come conseguenza: niente persistenza tra riavvii

Essendo il database in memoria, un riavvio del processo (redeploy, crash, sleep del piano Free)
**azzera tutte le partite in corso**. È il compromesso scelto per garantire l'anonimato anche a
chi amministra l'infrastruttura: nessun dato "a riposo" da proteggere o esporre per errore.

## Domande suggerite

Il pool di domande proposte ai giocatori nella fase "Serve un'idea?" (categorie *semplice*,
*piccante*, *esplicito*) è seminato nel database al primo avvio a partire da
`app/suggestions_seed.py`. Per modificarlo, cambia quel file e rideploya.

## Avvio in locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

L'app è disponibile su http://127.0.0.1:8000. Il database vive solo in memoria (vedi sopra).

### Variabili d'ambiente

| Variabile              | Default              | Descrizione                              |
|-------------------------|-----------------------|-------------------------------------------|
| `GGAME_MIN_PLAYERS`         | `3`                          | Numero minimo di giocatori per avviare    |
| `GGAME_RECONNECT_GRACE_SECONDS` | `30`                    | Secondi entro cui un disconnesso conta ancora come presente (vedi sotto) |

### Continuare se qualcuno sparisce

Se un giocatore chiude la scheda (batteria scarica, distrazione...) durante l'invio delle
domande o il voto, il gioco **non resta bloccato**: dopo `GGAME_RECONNECT_GRACE_SECONDS`
secondi (default 30, per assorbire un semplice refresh di pagina) quel giocatore smette di
contare per le soglie "hanno risposto tutti" / "hanno votato tutti", e il round prosegue con
chi resta. Se è l'**host** a sparire (oltre la stessa finestra di grazia), qualsiasi altro
giocatore può avviare la partita o avanzare al suo posto.

Per i casi limite (qualcuno è connesso ma non risponde), l'host ha anche due pulsanti
manuali: "Forza inizio votazione" (durante l'invio domande, se almeno una è stata proposta)
e "Forza chiusura voto" (durante la votazione, chiude la domanda corrente con i voti
raccolti finora).

### Test

```bash
pytest
```

## Deploy con Docker (locale / generico)

```bash
docker compose up --build
```

Espone l'app sulla porta 8000. Nessun volume da configurare: il database è in memoria (vedi
sopra), non c'è nulla da persistere.

Funziona su qualunque piattaforma che accetti un'immagine Docker con supporto WebSocket,
ad esempio:

- **Fly.io**: `fly launch` (rileva il Dockerfile).
- **Render**: vedi sezione dedicata sotto.
- Una qualsiasi **VPS** con Docker: `docker compose up -d --build` dietro un reverse proxy
  (es. Caddy/nginx) con TLS.

## Deploy su Render

Il repo include un [`render.yaml`](render.yaml) (Blueprint) che configura tutto in automatico:
web service Docker e variabili d'ambiente. Non serve un disco persistente.

1. **Metti il codice su GitHub** (Render deploya da un repository Git):
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<tuo-utente>/<tuo-repo>.git
   git push -u origin main
   ```
2. Su [render.com](https://render.com), **New** → **Blueprint**, seleziona il repository appena
   creato. Render legge `render.yaml` e propone di creare il servizio `ggame` con piano
   **Starter** (a pagamento, sempre attivo — niente sleep né cold start). Conferma con **Apply**.
3. Al termine del build (qualche minuto) l'app è live sull'URL `https://ggame-xxxx.onrender.com`
   fornito da Render. Condividi quell'URL agli amici al posto di `localhost`.

Se preferisci configurare il servizio a mano invece di usare il Blueprint: **New** → **Web
Service** → collega il repo → Render rileva il `Dockerfile` → imposta piano **Starter** →
imposta la variabile d'ambiente della tabella sopra.

**Nota sul piano Free**: funziona per provare l'app, ma il servizio va in sleep dopo 15 minuti
di inattività — e siccome il database è in memoria (vedi sopra), ogni sleep/risveglio azzera
le partite in corso. Per una vera serata di gioco (pause tra un round e l'altro, sessioni di
ore) è consigliato il piano Starter, che resta sempre attivo e quindi non perde stato finché
non lo si redeploya esplicitamente.

### Limiti noti

Lo stato delle connessioni WebSocket e il database sono entrambi tenuti in memoria di processo
(`app/connection_manager.py`, `app/db.py`): l'app va quindi deployata come **singolo
processo/istanza** (nessun worker multiplo, nessun autoscaling orizzontale) e un riavvio
azzera le partite in corso. Per un gioco da tavolo tra amici è più che sufficiente; per
persistenza/scala servirebbe un database esterno condiviso tra i processi, a costo di dover
proteggere quel dato a riposo.
