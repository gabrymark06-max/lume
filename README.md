# Lume

## Versione0.3 — telefono, Android/Google TV e Vercel

Sito: https://lume-puce-nine.vercel.app · Codice: https://github.com/gabrymark06-max/lume

La versione online esegue anche le API su Vercel e funziona con il PC spento. L'accesso richiede il codice privato del proprietario, configurato nella variabile sensibile `LUME_ACCESS_KEY`; mai incluso nel codice o nell'APK. Sul PC del proprietario si trova in `%LOCALAPPDATA%/Lume/cloud-access.txt`. Le sessioni usano cookie firmati Secure/HttpOnly/SameSite; cambiare il codice invalida le sessioni precedenti.

- **Android/iPhone:** aprire il sito in Chrome/Safari e scegliere Installa app/Aggiungi alla schermata Home. In alternativa su Android installare l'APK della release GitHub.
- **Android/Google TV:** installare l'APK dalla release GitHub tramite un'app di trasferimento file oppure `adb install -r lume-android-tv.apk` dopo aver autorizzato il collegamento sulla TV. Lume compare nel launcher TV. Richiede Android8+ e un Android System WebView aggiornato. Il pacchetto è un contenitore HTTPS, non include un server Python sul televisore.
- **Telecomando:** frecce per il focus; OK attiva; Indietro chiude finestra/player/dettaglio; sul video destra/sinistra spostano di10secondi, su/giù regolano il volume. Si può provare dal browser aggiungendo `?tv=1`.
- **Dati:** profili, canali, preferiti e progressi sono salvati nel browser/WebView di ciascun dispositivo. Le API ricevono lo stato della singola operazione senza conservarlo su un disco condiviso. Non c'è sincronizzazione automatica tra dispositivi; esportare/importare il backup dal browser. Disinstallare l'APK o cancellare i dati del sito rimuove i dati locali.
- **PC:** `avvia.pyw` e il server originale rimangono utilizzabili; nessun dato locale è pubblicato. MPV, cartelle Windows, credenziali DPAPI e download in background appartengono alla versione desktop. Online il player è quello HTML5/HLS del dispositivo.

`tv-detox` e `cleanyourtv` sono launcher/debloater Android TV: non sono necessari per Lume, né convertono l'app. L'APK può essere avviato dai loro launcher. Questa repo non disabilita pacchetti di sistema della TV.

Build web: `npm ci && npm run build`. Backend cloud locale: `LUME_ACCESS_KEY` e `LUME_CLOUD_DEV=1`, poi `uvicorn cloud:app`; il build cloud va servito sullo stesso dominio delle API. Deploy: `vercel --prod`. Segreti firma APK in GitHub Actions: `LUME_KEYSTORE_BASE64`, `LUME_STORE_PASSWORD`; chiave privata conservata fuori dalla repo. Workflow `.github/workflows/android.yml` produce un APK release firmato; non pubblica sul Play Store.

Il player cloud usa manifest e segmenti in richieste separate con risposte streaming. Le sorgenti possono rifiutare IP dei datacenter e gli URL scadono: verificare il titolo effettivo. Vercel Hobby ha quote di traffico/esecuzione; non è un servizio di streaming illimitato. Ogni richiesta è limitata a300secondi, non la durata complessiva del film HLS. Non vengono memorizzati film su Vercel. Non è garantita compatibilità con ogni codec, host o modello TV. I report dettagliati della versione PC sottostante sono storici, non prove sull'hardware TV.

Font Mulish e HLS.js sono ridistribuiti con le rispettive licenze in `web/vendor/`. Immagini e metadati dei cataloghi vengono letti a runtime, non forniti come libreria multimediale. Analisi e screenshot dell'app originale sono esclusi dalla distribuzione.

## Versione 0.2: interfaccia e funzioni ampliate

Questa sezione aggiorna la consegna iniziale riportata sotto. Riferimento misurato nell'app Veezie ospite: 30 screenshot originali in reference-parity e matrice PARITA.md. Nome/identità dell'app restano Lume, ricostruzione non ufficiale.

- Rail 60→275px, font Mulish libero, hero da 440px con carosello e titolo grafico remoto quando disponibile; file orizzontali, Top 10 numerata, piattaforme e25 categorie Esplora. Impostazioni a gruppi/righe, watchlist/Visti con tab e selezione multipla, dettaglio a pagina con cast, galleria e metadati. Screenshot nuovi in screens/parity-*.
- Cataloghi e ricerca reali; filtri del provider per tipo, genere, anno, piattaforma e ordinamento, con paginazione. Il dato Top 10 disponibile è giornaliero del canale, non la classifica settimanale TMDB originale. La categoria Al cinema dipende dai flag forniti dal canale e può essere vuota.
- Watchlist multiple, cronologia e ripresa episodi, profili locali separati, export/import con copia preventiva dello stato. Canali condivisi tra profili, preferiti/progressi/liste/impostazioni separati.
- Libreria locale con scelta cartella e streaming Range; coda download HTTP/HLS con annullamento; player con tracce audio/sottotitoli disponibili, qualità, velocità, seek, volume, fullscreen e episodio successivo.
- Calendario TVmaze, ricerca e serie seguite per profilo; notifiche via browser solo dopo consenso esplicito e mentre l'app è aperta. Le serie seguite sono memorizzate nel profilo browser, non nel backup JSON dell'app.
- Connettori configurabili Real-Debrid/TorBox/Trakt: token validati dal servizio e cifrati con Windows DPAPI fuori dalla repo e dai backup. Trakt richiede anche un client_id proprio. TorBox risolve solo contenuti già in cache. Nessun account personale è stato collegato durante i test.

**Verifica:** 55 test automatici passati; controllo reale della nuova UI a 1440/390, player Matrix HLS oltre un secondo poi fermato, controlli volume/velocità verificati. MPV ha decodificato un frame reale senza finestra/audio. Un download HLS sintetico è stato completato davvero con FFmpeg (nessun film scaricato). Dettagli in VERIFICA.md e screens/PARITY-FRONTEND-QA.md.

**Non è parità totale:** accesso Google/sincronizzazione cloud dell'originale, Chromecast e funzioni AI/premium non sono replicati. Servono servizi propri o hardware/account per le relative integrazioni. Non sono state provate una riproduzione di due ore, ogni host, ogni traccia o le connessioni con account a pagamento. L'app non integra pubblicità; non rimuove pubblicità eventualmente già presente nel contenuto video.

Le piattaforme sono rappresentate con testo e i dati/immagini cambiano con i cataloghi. La corrispondenza grafica riguarda struttura e misure; non viene dichiarata identità pixel per pixel.

App locale con grafica e navigazione ricostruite dall'analisi di Veezie. Analisi non ufficiale: non affiliato a Veezie.st né da esso approvato. Codice e identità propri, nessuna modifica all'installazione Veezie.

Aprire **avvia.pyw** per usare Lume in una finestra dedicata di Edge. Il server ascolta solo su `http://127.0.0.1:8766/`. Per avviare da terminale: `python server.py --port 8766 --open`.

## Stato effettivo del 02/11/2026

- Lista GiardiniBlog indicata da Gabriele già importata: cinque canali. Quattro cataloghi leggibili, un indirizzo non raggiungibile da questa macchina (DNS verso indirizzo non pubblico, escluso dalle richieste).
- Aggiunta manuale, import da pagina GiardiniBlog/TXT/JSON, aggiornamento manuale e all'avvio se l'ultimo aggiornamento risale a oltre sei ore prima. I canali scomparsi dalla lista vengono segnalati e conservati.
- Cataloghi reali e ricerca attraverso i canali, con errori separati. Verificata ricerca Matrix: sette titoli per ciascuno dei due cataloghi principali. La disponibilità nel catalogo non è una garanzia di riproducibilità.
- Dettagli, sorgenti, stagioni/episodi quando presenti nei dati del canale; preferiti e avanzamento locali. Schede film/serie senza dati fittizi.
- Player HTML5 con HLS.js locale, proxy di manifest/segmenti e fallback al MPV installato sul PC. Nessuna pagina di host viene aperta nel renderer, nessun loro JavaScript eseguito, nessun SDK pubblicitario incorporato.
- **Riproduzione reale verificata:** corretto il protocollo delle richieste a `v.vidxgo.co` e aggiunto un parser statico per gli indirizzi HLS offuscati nel player. Matrix è stato riprodotto a 1920×800 e il primo episodio di Dexter: Resurrection a 1920×1080, entrambi nel player interno. Il precedente HTTP403 su questo percorso dipendeva dal tipo di richiesta. Nessuna challenge viene eseguita o risolta automaticamente. Il resolver alternativo Vixsrc non è ancora implementato; non viene promesso supporto a qualsiasi host.

Un collegamento a una nuova pagina/sito richiede un parser compatibile; non basta salvare l'URL per promettere ogni film. I parser correnti leggono i formati osservati dei canali della lista. Il resolver legge iframe, sorgenti letterali e il formato del player Vidxgo; gli altri host con protocolli o player dinamici diversi richiedono un adapter specifico. Nessuna autenticazione originale o flag premium Veezie viene riutilizzata. Gli URL temporanei vengono ottenuti nuovamente aprendo la sorgente; non è stata provata una sessione lunga quanto un intero film.

## Dati e componenti

Impostazioni, canali, preferiti e progressi sono in `%LOCALAPPDATA%/Lume/state.json`, fuori dalla repo. La cache dei cataloghi è solo in memoria. La finestra Edge usa un profilo separato in `%LOCALAPPDATA%/Lume/browser`. Il server non parte con Windows e non è esposto sulla rete locale.

Python usa requests e BeautifulSoup già presenti sul PC; dipendenze in requirements.txt. HLS.js 1.7.4 è incluso in web/vendor con la propria licenza BSD; versione risolta in package-lock.json. Node serve solo per ripristinare quel componente, non per avviare l'app.

MPV viene cercato in bin/mpv.exe oppure nell'installazione Veezie già presente, senza copiare o modificare il binario. Per una distribuzione indipendente andrà fornita o configurata un'installazione MPV separata e rispettata la sua licenza. Il fallback apre una finestra MPV distinta; non è incorporato geometricamente nel renderer.

Le immagini dei titoli sono richieste alle sorgenti durante l'uso e non incluse nel pacchetto. Nella UI i dati remoti sono trattati come testo non fidato. CSP blocca script remoti e frame; le operazioni di modifica controllano origine e Content-Type. I recuperi remoti escludono reti private e reindirizzamenti verso destinazioni private; nessuna cookie jar personale viene importata.

## Verifica

`python -m unittest test_backend.py -v` controlla estrazione selettiva della lista, esclusione di link pubblicitari, deduplicazione delle schede, parsing dei dati Next come JSON, distinzione trailer/film, parsing statico del player Vidxgo senza eval, blocco reti private, ricerca, errore HTTP403, salvataggio atomico e riscrittura HLS. Screenshot desktop/mobile e controlli browser in screens/ e VERIFICA.md.

Il video sintetico delle prime prove verifica il player tecnico. Le successive prove qa_live.cjs usano invece sorgenti reali, senza intercettazioni: caricano il video nel browser, verificano avanzamento oltre un secondo e lo fermano. Report privi di URL temporanei in screens/player-reale-*.json. Nessun contenuto audiovisivo completo scaricato nei test. Nessun commit o pubblicazione.
