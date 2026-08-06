# Persistente Download-Jobs

Die Warteschlange speichert aktive Jobs und die letzten 500 terminalen Jobs in
`data/FilmeDownloader/download_queue.json`. Im Container liegt diese Datei
damit unter dem bestehenden persistenten Mount `/app/data`; Medienziele bleiben
unverändert. Jeder Ausführungsversuch erhält ein eigenes Staging-Verzeichnis.

Jeder Inhalt erhält genau eine stabile `job_id`. Jeder Start oder Benutzer-Retry
erhält zusätzlich eine eindeutige `attempt_id`. Provider- und Hoster-Fallbacks
innerhalb desselben Versuchs behalten beide IDs; ein neuer Retry behält die
`job_id`, verwendet aber eine neue `attempt_id`. Der Medien-Slug bleibt als
fachliche Zuordnung für Watchlist, Telegram und Seerr erhalten.

## Zustände

Aktiv sind `queued`, `preparing`, `waiting_provider`, `downloading`, `paused`
und `cancelling`; terminal sind `completed`, `failed` und `cancelled`. Beim
Abbruch wird zuerst `cancelling` persistent gespeichert. Ein Retry bleibt
gesperrt, bis der physische Worker beendet und der Job als `cancelled` in die
Historie verschoben wurde. Fortschritts- und Abschluss-Callbacks werden nur
akzeptiert, wenn `job_id` und `attempt_id` dem aktuellen Versuch entsprechen.

Nach einem
Prozess- oder Containerneustart werden zuvor laufende Vorbereitungen und
Downloads mit derselben ID sicher als `queued` wiederhergestellt. Dadurch wird
kein halbfertiger In-Memory-Zustand als weiterlaufender Download ausgegeben.

Die aktuelle Engine kann einen laufenden yt-dlp-/HTTP-Transfer nicht über alle
Hoster hinweg zuverlässig pausieren und fortsetzen. Die API lehnt eine solche
Pause deshalb ausdrücklich ab. Wartende Provider-Jobs können dagegen erneut
angestoßen werden.

## Migration und Schreibsicherheit

Die frühere JSON-Liste aus Slugs wird beim ersten Laden verlustfrei in das neue
Dokument migriert. Bis der erste Schreibvorgang erfolgreich war, ist die
abgeleitete Migrations-ID deterministisch; dadurch bleibt sie auch nach einem
Schreibfehler und Neustart stabil. Slugs und damit Telegram-, Seerr- und
Watchlist-Zuordnungen ändern sich nicht.

Jeder Snapshot wird in eine temporäre Datei geschrieben, geflusht, per `fsync`
gesichert und anschließend atomar ersetzt. Persistenzfehler bleiben über den
bestehenden Queue-Persistenzstatus sichtbar und werden bei API-Transaktionen als
`503 state_persistence_failed` zurückgegeben.

## Kompatibilität

`GET /api/queue`, die Slug-basierten Add-/Remove-/Clear-Routen und alle
`/api/v1`-Aliasse bleiben erhalten. Neue Job- und Historienfelder sind additiv.
Der versionierte WebSocket-Snapshot enthält den vollständigen Queue-Jobzustand;
Fortschritts- und Abschlussereignisse tragen zusätzlich `job_id` und
`attempt_id`.
