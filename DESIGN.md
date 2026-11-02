# Lume: cataloghi da canali, versione locale

## Estensione telefono e Android/Google TV

La versione online mantiene Mulish, palette scura, rail e locandine esistenti. Su telefono: installazione PWA, safe area, comandi da almeno44px. Su TV: modalità esplicita, focus bianco/arancione leggibile a distanza, spostamento geometrico con frecce, OK per attivare, Indietro per chiudere player/dettagli. Il launcher Android espone Lume senza sostituire il launcher di sistema. Riferimento visivo resta la UI già misurata e verificata, nessuna nuova direzione grafica.

Vercel ospita interfaccia e API stateless: preferiti, profili e progressi risiedono nel browser del dispositivo e viaggiano nella singola richiesta autenticata. Nessun disco server condiviso tra utenti; niente sincronizzazione automatica tra dispositivi. Un codice privato protegge API e video. MPV, cartelle Windows e download in background rimangono nella versione PC e vengono dichiarati indisponibili online. Il player usa richieste HLS separate in streaming; il funzionamento effettivo da un datacenter va verificato contro le sorgenti.

## Revisione richiesta: parità visiva e funzionale

Il 02/11/2026 Gabriele chiede esplicitamente grafica e funzionalità identiche a Veezie senza pubblicità. La UI precedente, con topbar persistente e catalogo unico, non soddisfa questa richiesta. Riferimenti aggiornati catturati dall'app pubblica ospite in reference-parity/screens; inventario distinto tra osservato, statico e non provato in PARITA.md. Le indicazioni seguenti prevalgono sulla prima specifica sottostante.

Riprodurre: rail di60px con gruppo logo/navigazione centrato verticalmente, voci Cerca/Home/Esplora/Watchlists/Canali/Impostazioni; niente topbar permanente sulla home. Hero a tutta larghezza alto circa440px con backdrop panoramico e sfumature verso fondo e testo, pulsanti bianchi/grigi e puntini del carosello. Contenuto a x75px e titoli sezioni20px peso500. File orizzontali di locandine, numeri delineati nella Top10, tessere piattaforme larghe160px alte85px. Ricerca in schermata dedicata. Esplora con tab Film/Serie, categorie e filtri. Impostazioni con gruppi arancioni e righe larghe su fondo #1f1f1f, titolo20px e spiegazione14px, selettore a destra. Watchlists e Visti con tab Film/Serie, selezione multipla e rimozione; stati vuoti coerenti. Dettaglio a pagina ampia con backdrop, metadati, cast, stagioni/episodi, sorgenti e azioni. Player con controlli propri, tracce, sottotitoli e cambio episodio, preservando HLS funzionante.

Font: usare Mulish open source da fonte indipendente e licenza OFL se reperibile; non copiare il file Muli distribuito da Veezie. Identità Lume autonoma: non viene copiato il logo Veezie né simulata l'affiliazione; nomi piattaforme in testo se non è disponibile un asset utilizzabile. Le risorse visive dei titoli vengono richieste ai canali a runtime, non incorporate nella distribuzione. I dati dei cataloghi cambiano: somiglianza valutata su misure, gerarchia e componenti, non sull'identità di un poster in un dato giorno.

Tutti i controlli mostrati devono eseguire una funzione reale. Servizi Trakt/Real-Debrid/TorBox/account cloud richiedono credenziali o backend proprio: non usare token dell'originale né pulsanti che fingono una connessione. Nessuna barriera pubblicitaria o modulo ads. Parità completa dichiarabile solo per le righe effettivamente verificate; integrazioni esterne non configurate restano esplicite nella matrice di verifica.

Il riferimento esplicito è Veezie.st: screenshot e misure in ../../docs/brand/app.veezie.st. Questa specifica precede l'implementazione dell'app vera e sostituisce l'obiettivo limitato della prova di stile.

Azioni principali: importare la lista di canali indicata dall'utente, cercare un titolo nei canali, scegliere un risultato e una sorgente, riprodurre nell'app. Mostrare lo stato effettivo di ogni canale e le cause dei fallimenti. Nessun finto catalogo e nessun successo simulato.

Stile: fondo #131212, superfici #1f1f1f e #303030, bianco principale, testo secondario #aaaaaa, arancione #ff9800, pulsante principale bianco. Segoe UI locale con gerarchie 14/17/20/32px, titoli di film resi come testo; evitare la grande intestazione serif della prima prova perché non è la tipografia UI Veezie. Rail laterale 60px, sottolineatura arancione della voce attiva. File di locandine 2:3 e dettagli con backdrop. Le immagini remote appartengono alle fonti e non sono incorporate nella distribuzione.

Desktop: rail fisso, ricerca visibile in alto, hero derivato da contenuti reali, catalogo con griglia densa e sezioni per canale. Canali in pannello con importazione lista, aggiunta manuale, aggiornamento e diagnosi individuale. Dettaglio titolo in dialogo con sorgenti/episodi selezionabili. Player sopra il dettaglio. Preferiti e avanzamento persistenti.

Mobile 390px: rail ridotto e area contenuti fluida, ricerca e controlli da 44px, griglia di due colonne, dialoghi a larghezza disponibile; nessuna eccedenza del documento. Focus visibile e Escape per chiudere; reduced motion rispettato.

Identità indipendente Lume, senza logo Veezie né sorgenti copiati. La misura di riferimento è analisi non ufficiale. Token normalizzati dalla precedente estrazione; risorse e gerarchie si adattano ai cataloghi veri.

Tecnologia iniziale: server Python locale su loopback, renderer HTML/CSS/JS locale, player HTML5 con HLS.js se disponibile; fallback al MPV già installato sul PC per codec/sorgenti compatibili. Nessuna pagina di host incorporata e nessun SDK pubblicitario. L'assenza di annunci nel video stesso non è garantibile.
