# Verifica Lume — 02/11/2026

## Versione 0.2: prove successive alla ricostruzione completa delle viste

Audit originale:30 screenshot pubblici ospite e misure DOM in reference-parity. Confronti e limiti:PARITA.md. Nuove prove UI: screens/parity-qa.json e screens/PARITY-FRONTEND-QA.md. Misure finali senza cronologia di test: rail60px; hero(x65,y5,h440); posterTop 10 196×294; intestazione piattaforme y461, tessere y510, Top 10 y628. Schermate desktop1440 e mobile390 senza overflow dopo correzione calendario; nessun errore JavaScript rilevato. Le immagini hanno caricamento differito: sono state attese prima delle catture.

Verificati impostazioni e liste CRUD, filtroAzione, ricerca/follow calendario, profili locali e stato connettori non configurati. Matrix reale nella nuova UI: avanzamento1,019s,1920px di larghezza, pausa e nessun errore; verificati anche volume0,5 e velocità1,25. Nessuna connessione account, richiesta permesso notifiche o scrobble remoto eseguita.

Suite automatica:55 test passati tra backend, catalogo/metadati, HTTP locale, profili/backup/libreria/download e connettori (mock). Include roundtripDPAPI su Windows con segreto sintetico e protezioneCSRF con bodyHTTP, corretta una race di reset connessione su Windows.

DownloadHLS tecnico reale: qa_download.py genera una playlist locale dal video sintetico, la serve tramite HTTP con URL proxy senza estensione, avvia FFmpeg e completa un MP4 da5723byte/11,7s. Non è un download di film. Risultato: screens/download-hls-tecnico.json.

MotoreMPV reale: un frame di Matrix decodificato con video/audio null e chiusura automatica, returncode0 in circa4,6s; nessuna finestra e nessun film su disco. Risultato: screens/mpv-tecnico-reale.json. Questo non verifica la GUI o tutti i codec.

Restano le differenze esplicite diPARITA.md: Google/cloud, Chromecast e AI/premium assenti; servizi a pagamento configurabili ma senza account di test; nessuna sessione video lunga quanto un film. Le sezioni sottostanti conservano la cronologia delle verifiche della versione0.1.

## Aggiornamento: riproduzione reale riuscita

Dopo la conferma dell'utente che Veezie riproduceva Matrix, confrontati main.js del pacchetto già analizzato con REA e channels.min.js pubblico. Il percorso Vidxgo usa richieste HTML con contesto iframe e un Referer di canale, poi richieste CDN con contesto cors. La risposta del player contiene gli indirizzi HLS come literal offuscati con XOR/base64. Implementata una lettura statica in codice proprio; nessun eval, script pubblicitario, credenziale, backend Veezie o flag premium riutilizzato. La pagina conteneva riferimenti a Cloudflare nei propri script, ma il documento restituito era il player del film, non una schermata di verifica. Nessun CAPTCHA superato o challenge eseguita.

Le richieste corrette restituiscono HTTP200; master manifest, varianti e segmenti passano attraverso il proxy locale con il contesto HTTP della sorgente. QA reale su istanza isolata 8777, senza mock o intercettazioni:

- Matrix: 1920×800, durata 8177,874s, readyState4, avanzamento 1,00572s, nessun errore media o JavaScript.
- Dexter: Resurrection, primo episodio: 1920×1080, durata 3154,965s, readyState4, avanzamento 1,010374s, nessun errore media o JavaScript.

Riproduzioni fermate dopo la verifica, nessun film salvato su file. Risultati in screens/player-reale-matrix.json e screens/player-reale-dexter-resurrection.json. Dieci test backend passati. Il fallback MPV riceve ora anche i campi HTTP necessari per questi flussi; la sua riproduzione non è stata provata. Non è stata verificata una sessione di due ore o ogni host possibile. Le sezioni sottostanti documentano la fase precedente alla correzione.

Analisi non ufficiale. Non affiliato a Veezie.st né da esso approvato. I marchi appartengono ai loro proprietari.

## Eseguito con sorgenti reali

- Importazione della sezione Lista Canali da https://www.giardiniblog.it/canali-veezie/ senza prendere link pubblicitari, store o articoli correlati: cinque indirizzi.
- Cataloghi letti da quattro canali; il quinto è escluso perché il DNS di questa macchina lo risolve su un indirizzo non pubblico. Non viene modificato il DNS di Windows.
- Home iniziale con circa 140 schede reali: il numero cambia con aggiornamenti delle fonti e deduplicazione. Il conteggio riguarda la pagina letta di ciascun canale, non l'intero catalogo.
- Ricerca Matrix: 15 risultati complessivi nel controllo finale (7+7 nei due canali principali, 1 nell'altro); zero risultati su un canale di sole serie. Ogni risultato conserva il canale sorgente.
- Dettaglio film e sorgenti; dettaglio serie Dexter con 11 voci episodio lette dai dati della pagina. Le disponibilità degli episodi non sono state provate riproducendo il contenuto.
- Preferito aggiunto/rimosso/aggiunto e poi ripristinato allo stato iniziale: favorites vuoto. Nessun dato di test lasciato nei preferiti dell'istanza principale.
- Host video risposto HTTP403: errore visibile nel dettaglio, player non aperto come se avesse un video. Nessun tentativo di superare CAPTCHA o controlli anti-bot. Il nuovo resolver non usa backend, chiavi o flag premium di Veezie.

## Interfaccia

Edge headless a 1440×900 e 390×844: home popolata, canali, ricerca, dettaglio e messaggio di errore sorgente. Nessun errore JavaScript e nessun overflow orizzontale del documento nei controlli eseguiti. Screenshot in screens/. I poster fuori viewport sono lazy: un full-page screenshot non dimostra il caricamento di tutte le immagini. Alcuni poster remoti possono fallire e vengono sostituiti dallo stato grafico vuoto.

## Player tecnico isolato

qa_player.cjs usa una seconda istanza su 8777 con dati in una cartella temporanea dedicata. Cataloghi e dettagli reali; solamente la risposta del resolver e il video sono intercettati dal test con un MP4 sintetico di 12 secondi, arancione, generato localmente con FFmpeg. Riproduzione 320×180, avanzamento di circa 1,8 secondi salvato nell'istanza QA, chiusura del dialogo corretta e zero errori JavaScript. La seconda istanza è stata arrestata e il test non modifica i progressi dell'istanza principale.

Prima fixture WebM senza durata affidabile: il test di avanzamento non poteva passare; sostituita con MP4 con durata dichiarata. Il test finale è passato. Questa prova NON dimostra la riproduzione dei film dai canali.

## Test backend

Nove test unittest passati: estrazione selettiva dei link, deduplicazione immagini/titoli, parsing Next come dati inerti, esclusione trailer, rifiuto URL privati, ricerca senza risultati estranei, errore403, persistenza atomica Unicode e riscrittura HLS di segmenti/URI mantenendo query e referer. Controllo sintattico app.js passato.

## Da risolvere per la parità richiesta

La riproduzione dei film dai due host principali resta bloccata. Nel codice originale ci sono percorsi specifici per ciascun host, richieste native con header dedicati e resolver remoti aggiornabili: il resolver generico di Lume non li sostituisce tutti. È stata chiesta all'utente una prova dello stesso titolo nel Veezie originale per distinguere un blocco condiviso da una differenza del nuovo client. Non dichiarare il compito completamente raggiunto fino a una prova reale catalogo→sorgente→video.

Nessun video di un film scaricato o riprodotto nei controlli. Nessuna pubblicazione o commit. Lume è avviata localmente su 127.0.0.1:8766 e non esposta in rete.
