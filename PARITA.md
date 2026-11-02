# Veezie → Lume: matrice di parità

## Aggiornamento implementazione 0.2

Le tabelle di audit sottostanti conservano la baseline precedente. Dopo l'audit sono state implementate le viste e le funzioni elencate qui; i dettagli e le prove sono in README.md, VERIFICA.md e screens/PARITY-FRONTEND-QA.md.

| Area | Stato implementato/verificato | Differenza o verifica mancante |
|---|---|---|
| Home e navigazione | Rail 60/275, font Mulish, hero da 440, carousel, piattaforme e righeTop 10; misure reali a 1440/390 | Nome/logoLume; loghipiattaforme testuali, dati e rankinggiornalieri del canale differenti dall'originale |
| Esplora e ricerca | 25 categorie, tipo/genere/provider/anno/ordinamento, paginazione; filtroAzione7risultati nelcampione | Al cinema dipende dai flag della fonte (campionevuoto); classifica settimanale originale non disponibile |
| Dettaglio | Pagina ampia, backdrop/titolograficoquando disponibile, voto/trama/cast/galleria/metadati/simili/episodi/sorgenti | Dati da canali+fotoTVmaze; foto mancanti mantengono segnaposto |
| Preferiti, liste, Visti, ripresa | CRUDliste, selezionemultipla, cronologia conepisodio, progressi e profili separati | VerificheHTTP e UI; fineepisodio/autoplay non provati per un episodiointero |
| Player | HLSrealeMatrix, seek/audio/subtitle/quality/speed/volume/fullscreen, episodiosuccessivo | Ognihost e ogni codec/traccia non provati; MPV decodifica1frame reale senza GUI |
| Download e libreria | QueueHTTP/HLS/cancel, cartellelocali/opaqueID/Range206, FFmpegfixtureHLScompletata | Nessun film completo scaricato per test; pausa/ripresa HTTP persistente non implementata |
| Impostazioni e backup | Settingspersistenti, export/import conbackup precedente, profili localiseparati | BackupJSON non include serie seguite/notifiche conservate nel browser |
| Calendario | TVmaze live, ricerca, followperprofilo, permesso notifiche suclick | Notifiche soloappaperta; nessun permesso OS concesso nei test |
| RD/TorBox/Trakt | Connettori reali/configurabili, DPAPI, test conmock e roundtrip cifraturaWindows | Non verificati conaccount; TorBox con sola cache; Scrobble Trakt solorichiestaesplicita |
| Google/cloud, Chromecast, AI/premium | Non implementati | Richiedono servizi/progettoOAuth/hardware o infrastruttura e credenziali proprie; nessuna parità dichiarata |

**Questa consegna non è una replica completa al100%.** La matrice serve a rendere verificabili i progressi e le differenze rimaste, senza sostituire i test con la semplice presenza dei pulsanti.

Analisi non ufficiale, 02/11/2026. Non affiliato a Veezie.st né da esso approvato. I marchi appartengono ai loro proprietari.

Questa matrice descrive il riferimento osservato e la **baseline Lume 0.1 all'inizio dell'audit**, prima degli interventi paralleli del turno corrente. Non è un certificato di parità della versione finale. Le funzioni nuove vanno ricontrollate nella colonna di verifica del progetto.

## Metodo e copertura

1. Artefatto Windows 1.0.18 già analizzato con REA nel turno precedente: app.asar SHA-256 `41e00ed1c94223adfb26f9e79f88bb73143b60328ba804ca2fbdd6b6f6ff3a11`; genitore REA `ev_96e8d6dd4ceb20aa2231235d8ca75a1685bfe7352974e40b2917da376d9705b6`. Lettura ordinaria supplementare di main.js, preload.js, player-overlay.html e moduli download/MPV. L'analisi REA dichiarava copertura semantica parziale: nessuna assenza viene dedotta da un semplice risultato non trovato.
2. App pubblica `https://app.veezie.st/new/`, contesto Edge ospite nuovo, nessun account personale, nessuna modifica dell'installazione. Aperta con “Continua senza account”. Screenshot viewport 1440×900 e 390×844, misure DOM e template pubblici in `reference-parity/`.
3. Media, iframe esterni, reti pubblicitarie e analytics bloccati nella sola cattura di audit. Non è stata avviata riproduzione o richiesta pubblicità. L'hero mostra dunque la grafica statica di riferimento, non un trailer in esecuzione. Nessun CAPTCHA incontrato o risolto.
4. Canali/modalità automatiche sono state aperte per cattura senza salvare indirizzi, scegliere file locali o cancellare elementi. Nessun acquisto, login, invio o pubblicazione.

**O** = osservato in UI ospite e screenshot; **S** = dichiarato nel codice/template, non provato end-to-end; **E** = servizio esterno/autenticato, non verificato. I contenuti di film/copertine cambiano nel tempo: l'identità del titolo in uno screenshot non è un token grafico.

## Riferimento visivo misurato

| Componente | Misura/struttura del riferimento | Prova |
|---|---|---|
| Fondo | Quasi nero `#131212`; testi bianchi/grigi, accento arancione | Screenshot e snapshot precedente |
| Font UI | Muli/Mulish, corpo 14px, sezioni 20px, barra titolo 17px; bottoni home 12px peso600 | JSON controlli, CSS calcolato |
| Rail | Chiuso circa60px; espanso275px; voci alte45px; gruppo/logo centrati verticalmente | sidebar-hover/channels screenshot, menu DOM |
| Rail aperto | Sposta l'area contenuti e il punto d'inizio delle sezioni; evidenzia la voce attiva con trattino arancione | sidebar-channels-1440.png |
| Home | Nessuna topbar permanente con ricerca/logo testuale; grande hero in alto, rail laterale | home-1440.png |
| Hero desktop | Da y≈5 a440px, titolo grafico a sinistra, anno/voto, trama e azioni y≈357; dissolvenze laterale e inferiore | home-1440.png e home.json |
| Azioni home | Primario bianco 109×40px; secondario grigio102×40px; audio circolare circa40px; dots carosello centrati in basso | home.json |
| Piattaforme | Intestazione y≈462; tessere161×84px, raggio12px, gap circa10px | home-1440.png, variabili root |
| Top 10 | Intestazione y≈629; item256px, poster196×294px; numero gigante con contorno parzialmente sovrapposto | home-1440.png, variabili root |
| Poster normali |140×210px; fila orizzontale, etichetta sezione e possibili controlli ai bordi | variabili root osservate |
| Continua a guardare | Tessera280×151px, contenitore fila minimo186px | variabili root; sezione non popolata nell'ospite |
| Esplora | Film/Serie TV in pill centrale: x623,y59,127×44 ciascuna a1440px; sotto griglia categorie | discover.json |
| Categorie Esplora |252×126px, gap10px orizzontale e15px verticale; 5 colonne a1440px; titolo in basso a sinistra | discover screenshot/JSON |
| Watchlists/Visti | Barra titolo, tab Film/Serie; stato vuoto centrale con icona grigia grande e singola riga testuale | watchlists/history screenshot |
| Impostazioni | Titolo/back in alto; sezioni arancioni; riga card da x70,width1360,height92px nelle prime voci; gap10px, radius12px | settings.json |
| Impostazioni mobile | Rail preservato; card da x70 a380 con testo multilinea e valore a destra; pagina scorre verticalmente | settings-390.png |
| Modali canali | Quasi fullscreen, header/back, superficie appena trasparente sul contenuto, icona monitor grande, campo largo quasi viewport; non dialogo card centrale | add-channels/dynamic-list screenshot |
| Dettaglio | Pagina completa: backdrop grande, testo/titolo sovrapposto nella metà bassa, azioni, poi trama/cast/dettagli | detail-1440/390.png |
| Cast/episodi | Foto cast78px; stagione h192px, poster130px; still episodio173×98px, riga114px, max-width700px | variabili root osservate |
| Player desktop | Overlay trasparente, gradienti neri, titolo in alto, controlli centrali, timeline e locandina in basso; progressione arancione `#ff6800` | S: player-overlay.html |

I titoli grafici dei film sono immagini, non caratteri di Muli. Le piattaforme hanno loghi propri: il prodotto indipendente non deve incorporarli come propria identità. Non copiare file di font o asset dai pacchetti Veezie: usare una fonte libera verificata per Mulish e risorse indipendenti/autorizzate.

## Navigazione e catalogo

| Funzione | Riferimento/evidenza | Baseline Lume | Cosa serve per parità |
|---|---|---|---|
| Home a sezioni orizzontali | O: dashboard | Griglia aggregata con hero singolo | Righe, composizione e navigazione equivalenti |
| Hero a carosello con dots | O: dashboard | Singolo titolo | Carosello vero e cambio selezione/dots |
| Film/Serie più popolari | O: dashboard | Titoli di canali aggregati | Dati di popolarità reali; non etichettare arbitrariamente una fila come popolare |
| Top 10 settimanale | O: dashboard | Assente | Dati con criterio verificabile e trattamento grafico numerato |
| Esplora per piattaforma | O: dashboard | Assente | Filtraggio effettivo per provider, con dati provider reali |
| Esplora Film/Serie | O: discover | Assente | Sezioni e schede categorie con dati filtrabili |
| Esplora per genere/categorie editoriali | O: discover | Assente | Filtri e griglie; le categorie editoriali non equivalgono a semplici generi |
| Ricerca globale | O: global-search; S: globalSearch() | Presente nei canali | Adeguare layout e comportamenti; preservare distinzione metadati/sorgente disponibile |
| Ricerca nel singolo canale | S: menu `isState(channel)?search():globalSearch()` | Presente via selettore | UI canale corrispondente, filtro locale visibile |
| Cronologia navigazione/back | O: header/back | Cambio viste JS, dettagli dialogo | Pagine e stato precedente coerenti |
| Film/Serie separati nelle raccolte | O: favourites/watched | Preferiti unificati | Tab Film/Serie e stato attivo |
| Navigazione TV/tastiera | S: attributi nav-focusable/nav-group e app.js TV | Focus basilare | Test direzionali/Enter/back sui dispositivi effettivamente supportati |

## Canali e file

| Funzione | Riferimento/evidenza | Baseline Lume | Cosa serve per parità |
|---|---|---|---|
| Espansione menu “I miei canali” | O: sidebar-channels | Pagina canali separata | Submenu con azioni e indirizzi |
| Aggiunta multipla uno per riga | O: add-channels; S: channelManager | Presente | Adeguare schermata e mantenere validazione distinta da parsing |
| Lista automatica TXT/HTML | O: dynamic-list; S: channelManager | Presente GiardiniBlog/TXT/JSON | In originale template promette aggiornamento **a ogni avvio**, baseline ogni6h |
| Rimozione lista automatica | O: dynamic-list | Assente come azione separata | Disattivare aggiornamento senza cancellare automaticamente canali personali |
| Rimozione canali multipla | O: remove-channels | Singola rimozione | Selezione multipla e conferma chiara |
| Esporta lista canali | O: settings | Assente | Download file importabile |
| Correzione domini cambiati | S: checkChannels/correctChannels/redirectChannel | Segue redirect HTTP normali | Implementazione indipendente verificata, senza dipendere dal backend originale |
| Canali cartella locale | O: pulsante; S: openFileManager | Assente | Scelta cartella con dialogo nativo e scansione, niente accesso arbitrario a file dal web |
| File locale riproducibile | S: localLibrary/canali locali | Solo prima prova statica, non app0.1 | Aggiunta sorgente/file con concessione esplicita |
| Riproduci da URL | S/O: impostazione e route singlelink/play | Non esposto in app0.1 | Modale/form e resolver collegati al player |
| Download integrato | S: download-manager.js e IPC download-* | Assente | Coda, avanzamento, annullamento, percorso, errori e apertura file |
| Download libreria Video/Film/Serie | O: localLibrary | Assente | Indicizzazione dei propri file e filtri |
| Sincronizza libreria | O: localLibrary | Assente | Scansione locale controllata e aggiornamento UI |

## Dettaglio, raccolte e riproduzione

| Funzione | Riferimento/evidenza | Baseline Lume | Cosa serve per parità |
|---|---|---|---|
| Dettaglio pagina, backdrop/trama | O: detail | Dialogo con pochi campi | Struttura pagina e campi ricchi |
| Anno/generi/durata/produzione | O: detail; template movie | Solo anno/trama parziali | Dati effettivi del canale o provider metadata proprio |
| Valutazioni TMDB e conteggio | O: detail | Assente | Fonte con accesso legittimo; nessun numero inventato |
| Valutazioni/recensioni comunità Veezie | E/S: movie/commenti e backend | Assente | Non è una funzione locale clonabile con medesimi dati/account senza servizio originale |
| Cast e schede attore | O/S: movie `openActor` | Assente | Metadati cast e navigazione verificata |
| Trailer/galleria | O/S: movie | Assente | Visualizzazione/filtri con risorse autorizzate; niente autoplay ads |
| Collezioni e simili | O/S: movie | Assente | Dati reali e dettagli navigabili |
| Aggiungi/rimuovi preferito | O/S: movie/favourites | Presente | Adeguare icona e punto di accesso |
| Selezione multipla preferiti | S: selectModePress/deleteFavorites | Assente | Selezione e rimozione multipla |
| Segna visto/non visto | S: markAsSeen | Assente distinta dal progresso | Stato persistente esplicito |
| Cronologia Visti | O: watched | Progressi salvati ma nessuna vista | Pagina con Film/Serie, stati vuoti e cancellazione |
| Continua a guardare | S/O: dashboard struttura, bookmarks | Progressi presenti | Fila con ripresa reale, titolo/stagione/episodio |
| Lista stagioni e dettaglio episodi | O/S: movie openSeason | Episodi piatti quando parser li trova | Gerarchia e stato episodio |
| Autoplay prossimo episodio | O impostazioni; S controller/player | Assente | Evento ended e selezione prossimo, errori e interruzione |
| Selezione host prima/durante player | S: movie e overlay hosts | Prima della riproduzione soltanto | Lista e cambio host nel player, con ripresa posizione |
| Play/pausa | S: player-overlay/MPV | Presente HTML5 | Overlay uguale e gestione stato/loading |
| Seek progressivo e ±10s | S: overlay | Timeline browser nativa | Controlli propri e test seek |
| Audio/sottotitoli/qualità | S: overlay getTracks/setTrack | Solo controlli browser/HLS predefiniti | Elenco tracce reale, selezione e disattivazione sottotitoli |
| Overlay auto-hide3s | S: player-overlay | Controlli nativi browser | Timer, mouse/tocco e focus corretti |
| Scorciatoie Space,←/→,Esc,H | S: player-overlay | Browser base, Esc dialogo | Mappatura e priorità menu aperti |
| Codec/MPV integrato desktop | S: main.js+mpv-manager | Fallback MPV finestra separata | Parità geometrica richiede integrazione nativa distinta dall'HTML5 |
| Volume/velocità/fullscreen overlayMPV | Non trovati esplicitamente nel file overlay desktop | Browser ha funzioni proprie | Non dichiararli “identici all'originale” senza ulteriori prove; web/mobile possono differire |

## Impostazioni e servizi

| Funzione | Riferimento/evidenza | Baseline Lume | Cosa serve per parità |
|---|---|---|---|
| Mostra URL, notizie, trailer automatici | O: settings ospite | Assente | Preferenze persistenti applicate alla Home |
| Dimensione locandine piccole/medie/grandi | O: settings | CSS fisso | Ridimensionamento reale di poster, Top 10, cast/episodi e layout mobile |
| Player predefinito | O: settings | Fallback manuale | Preferenza effettiva HTML5/MPV |
| Buffer player | O: settings | HLS maxBufferLength fisso30s | Preferenza applicata al loader/player |
| Lingua sottotitoli | O: settings | Assente | Preferenza con auto-selezione delle tracce disponibili |
| Autoplay episodi | O: settings | Assente | Interruttore e comportamento ended |
| Metodo/destinazione download | O: settings | Assente | Configurazione e download veri, non solo campo salvato |
| Profili multipli e Home personalizzata | S: template premium e services/profiles | Assente | Profili locali indipendenti possibili; non equivalgono a sync premium originale |
| Login Google/Apple e sync originali | E/S: authManager | Assente | Richiedono identità/backend propri o integrazione ufficiale; non usare token/clientID altrui |
| Trakt sync/import | O: settings, E: account | Assente | OAuth/device-flow con credenziali proprie e login umano; prove non eseguite |
| Real-Debrid/TorBox | O: settings, E: token utente | Assente | Account/API token personali esterni; non inventare funzionalità se non integrate/testate |
| Magnet/torrent | O impostazione, S parser | Assente | Dipendenze/account/risoluzione separati, non ottenuti dall'import lista |
| DNS alternativi | S: template, nativo main.jsDoH | DNS sistema con esclusione reti private | Non cambiare silenziosamente impostazioni OS; funzionalità distinta dalla UI toggle |
| Calendario episodi/ricerca/follow | O: calendar, S: TvCalendarCtrl | Assente | Dati reali schedule, preferenze follow, fuso/data |
| Notifiche nuove uscite | S: notificationManager e calendar | Assente | Permessi/browser o servizio locale, da verificare sul dispositivo |
| Chromecast con controlli | S: menu castPlayer, services | Assente | Dispositivo reale e prova trasmissione; non testabile con soli bottoni |
| AI consigli premium | S: template premium | Assente | Servizio/modello e propria configurazione; non una funzione locale garantita |
| Backup/reset/cancella account | O/S: settings | Stato JSON interno, nessuna UI backup | Export/import dati propri; reset reversibile/locali distinguendo account originali |
| Acquisti/premium/ads | O/S: template | Nessun SDK pubblicitario | Escludere ads/gate pubblicitari; non simulare acquisti né alterare premium dell'originale |

## Asset ed evidenze

- `reference-parity/*.json`: URL effettiva, testi UI, controlli e misure. Alcune misure sidebar rappresentano elementi del menu nel DOM con larghezza275 anche da chiuso: usare gli screenshot per la visibilità effettiva.
- `reference-parity/templates/`: copie pubbliche per analisi, non incorporate nel prodotto.
- `reference-parity/screens/`: home, discover, watchlists, history, settings, localLibrary, calendar, detail, single-link, modali canali, sidebar e ricerca globale a 1440/390 dove indicato.
- **Non usare** `singleLink-*.png` come prova del form: la prima route tentata era errata e ricadeva sulla dashboard. La route verificata è `#/app/singlelink/play`, screenshot `single-link-*.png`.
- Non sono stati provati login, acquisti, casting, notifiche OS, servizi esterni, file locali, download o riproduzione nell'originale durante questo audit. Il funzionamento della riproduzione Lume è documentato separatamente nei test del progetto, non da queste catture.

Per dire “tutto identico” servono prove per ogni riga e per i relativi stati, non la sola presenza del pulsante. I servizi autenticati e l'ecosistema originale restano un limite esplicito: la loro interfaccia può essere ricostruita, ma non si devono presentare dati/account simulati come gli originali.
