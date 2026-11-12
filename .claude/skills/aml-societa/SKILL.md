---
name: aml-societa
description: Verifica AML di una società italiana. Interroga le banche dati OpenAPI (visura, bilanci, protesti, cariche, titolari effettivi, catasto, screening), esegue una deep search web con browser e visione, analizza i bilanci pluriennali e genera il PDF "AML società personalizzato". Chiede all'utente il livello di ricerca (light / medium / strong, dal più economico al più costoso) e classifica la pratica in rischio basso, intermedio o alto (concreto rischio di riciclaggio o anomalie). Usala quando l'utente chiede una due diligence AML, una verifica antiriciclaggio su una società, un report Cribis-like o un controllo su titolare effettivo e bilanci.
---

# AML società: verifica con OpenAPI, deep search e analisi di bilancio

## File coinvolti

| Cosa | Percorso |
|---|---|
| Adattatore dati OpenAPI | `aml_societa/fetch_openapi.py` |
| Livelli di ricerca e endpoint | `aml_societa/config/openapi_endpoints.json` |
| Dati di esempio (fittizi) | `aml_societa/config/fixture_workspace_srl.json` |
| Generatore PDF | `aml_societa/build_report.py` |
| Output | `aml_societa/out/` |

## Regole fisse

1. **Nessun dato inventato.** Se un endpoint OpenAPI fallisce, lo si riporta nella sezione fonti del PDF e non si colma il vuoto con supposizioni.
2. **La chiave OpenAPI non va mai scritta nel repository.** Si legge da `OPENAPI_API_KEY`. Se manca, si usa `--fixture` e il PDF riporta "DATI DI ESEMPIO - NON REALI".
3. **Il livello di rischio è un supporto.** La decisione finale spetta al responsabile AML del soggetto obbligato, che deve documentarla.
4. **Nessuna segnalazione di operazione sospetta viene inviata automaticamente.** Si può solo suggerire di valutarla.

## Procedura

### Passo 1: raccogli i dati minimi
Chiedi (o estrai dalla richiesta):
- denominazione o partita IVA della società (la partita IVA è la chiave preferita per le API);
- scopo della verifica (nuovo cliente, revisione periodica, operazione straordinaria).

### Passo 2: scegli il livello di ricerca
Presenta all'utente i tre livelli con `AskUserQuestion`, dal più economico al più costoso. I costi per chiamata si leggono dal listino OpenAPI del proprio account: nel file di configurazione il campo `costo_stimato_eur` è da compilare.

| Livello | Endpoint OpenAPI | Deep search web | Browser e visione | Costo relativo |
|---|---|---|---|---|
| **Light** | visura, protesti e procedure, cariche | 1-2 query su fonti pubbliche | no | 1x |
| **Medium** | + bilanci, titolari effettivi, screening sanzioni e PEP | 5-10 query mirate (notizie, registri) | sì, su siti istituzionali | 3x |
| **Strong** | + catasto e catena dei legami societari | completa, multi-fonte, con analisi multi-anno | sì, con visione su documenti e pagine | 6x |

Non avviare chiamate a pagamento prima che l'utente abbia scelto il livello.

### Passo 3: interroga OpenAPI
```bash
cd aml_societa
export OPENAPI_API_KEY=...   # impostata dall'utente nell'ambiente, mai nel file
python3 fetch_openapi.py --piva <PARTITA_IVA> --profilo <light|medium|strong> --out out/dati.json
```
Se la chiave non è disponibile, esegui con `--fixture esempio` e dichiaralo all'utente.

### Passo 4: deep search web (medium e strong)
Per livello medium e strong:
- esegui le query su motori di ricerca e su registri pubblici (albo fornitori, ANAC, Gazzetta Ufficiale, albi professionali, notizie locali e nazionali);
- con il browser integrato apri i siti istituzionali della società e i documenti trovati, e usa la **visione** per leggere pagine, tabelle e certificati che non sono testo selezionabile;
- annota per ogni fonte data, URL e sintesi, e inseriscine l'elenco nella sezione 8 e 10 del PDF;
- riporta le notizie negative come `adverse_media` con valutazione `negativa` o `da verificare`, mai come certezza.

Nel livello light la deep search si limita a una o due query di conferma.

### Passo 5: analisi di bilancio
Con i dati `bilanci` calcola e commenta:
- crescita dei ricavi anno su anno e CAGR del periodo;
- margine EBITDA e andamento;
- patrimonio netto, rapporto patrimonio/attivo e indebitamento;
- liquidità immediata rispetto ai debiti a breve;
- oneri finanziari su EBITDA;
- coerenza tra addetti e ricavi per addetto;
- bilanci non depositati o incoerenti tra anni.

Il generatore calcola già questi indici. Commentali nel testo della sintesi con parole tue e solo sui dati presenti.

### Passo 6: classifica il rischio
Il generatore assegna il livello con regole trasparenti:

| Livello | Condizione | Significato per l'operatore |
|---|---|---|
| **BASSO** (verde, verifica ordinaria) | punteggio sotto 25, nessuna anomalia critica | identificazione ordinaria e monitoraggio periodico |
| **INTERMEDIO** (giallo, verifica rafforzata) | punteggio da 25 a 60 | fonte del patrimonio, documentazione aggiuntiva, approvazione del responsabile AML |
| **ALTO** (rosso, verifica rafforzata con valutazione di segnalazione) | anomalia critica (protesti, procedure, sanzioni, UIF) o punteggio oltre 60 | approfondimento, valutazione di segnalazione di operazione sospetta, decisione motivata |

Se il livello calcolato dal generatore non coincide con la tua lettura dei fatti, riporta la discordanza all'utente e non modificare il PDF di nascosto.

### Passo 7: genera il PDF
```bash
python3 build_report.py --dati out/dati.json --out "out/AML_società personalizzato <NOME SOCIETÀ>.pdf"
```
Poi verifica visivamente la prima pagina con `pdftoppm -r 60 -png -f 1 -l 1` e leggi il PNG prima di consegnare.

### Passo 8: consegna
Riporta all'utente:
- livello di ricerca scelto e fonti interrogate, con eventuali endpoint falliti;
- classe di rischio finale e i tre motivi principali;
- il percorso completo del PDF in `out/`;
- le limitazioni: dati OpenAPI da verificare, deep search come supporto, decisione del responsabile AML.

## Profili di spesa (da completare con il listino OpenAPI)

| Profilo | Chiamate | Quando sceglierlo |
|---|---|---|
| Light | poche visure e cariche | screening rapido di un cliente a basso rischio |
| Medium | bilanci e screening inclusi | nuovo cliente standard, revisione annuale |
| Strong | catasto, catena societaria, deep search completa | cliente ad alto rischio, anomalie già emerse, operazioni straordinarie |

## Cosa non fare
- Non dichiarare un soggetto "sanzionato", "PEP" o "in frode" senza un riscontro documentato.
- Non usare dati personali dei soci in richieste a servizi esterni oltre a quanto serve per lo screening.
- Non pubblicare il PDF né inviarlo a terzi senza richiesta esplicita dell'utente.
