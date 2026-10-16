# RoyalDownloader – konsolidiertes Stability Lab

Stand: 11.10.2026; Basis: `overnight` nach PR #505 (ursprünglich `b4ec9a56da1a4d6bc8555c82ed6041975e08b08d`).

## Umfang und Grenzen

Dieser PR ist **nur Testinfrastruktur, Testfixture und Regressionstests**, nicht die zweite Integration der bereits gemergten Audit-Fixes #502–#506. Keine Änderung an UI, Providern, Queue-Scheduler, Download-Lifecycle, Authentifizierung oder produktiver Laufzeitkonfiguration.

Die vollständige Python-Suite kann in einem Offline-Container oder modulweise mit separaten, hart begrenzten Testprozessen ausgeführt werden. Netzwerkzugang ist im Container mit `--network none` abgeschaltet; zusätzlicher Python-/curl-Schutz verhindert unbemerkte reale Provider-Requests. Baseline und Kandidat werden auf demselben Runner gemessen. Ein fehlgeschlagener Test, ein Timeout oder eine unvollständige Messung darf keinen grünen Vergleich ergeben.

Test- und Messbereiche: 650, 1.000 und 5.000 synthetische Queue-Aufträge; Wiederherstellung und doppelte Claims; CPU/RAM/Threads und persistente Operationen; parallel geplante Health-/Queue-Antworten; Prozessgruppen-Cleanup bei Timeout; Browser-Testfixture-Freigabe nach Fehlern; sichere JUnit-Verarbeitung. Messungen beziehen sich auf CI, **nicht** auf Live-Mediendownloads oder NAS-Dauerlast.

## Konsolidierungsherkunft

- PR #500: isolierte Python-Module und gepaarte Queue-/Speicherleistungsmessungen, deren Ziel hier durch einen einzigen Offline-Runner mit wählbarem Modulmodus übernommen wird. Keine zweite parallele Workflow-Suite.
- PR #507: Offline-Docker, Lastmatrix, Messbudgets und ursprüngliche Audit-Ergebnisse; historische Messwerte bleiben Dokumentation der alten Basis und werden **nicht** als neue aktuelle Zahlen ausgegeben.
- PR #508: Prozess-/Netzwerkschutz, fail-closed Regressionen, Testfixture-Bereinigung und Metrikvergleich auf aktuellem `overnight`.

Der historische Ausgangsbranch `backup/overnight-pre-audit-fixes-20261011` bleibt unberührt.

## Sicherheits- und Freigabekriterien

- Bestehende Quality- und CodeQL-Checks müssen vollständig grün bleiben; keine Deaktivierung von Tests.
- Der neue Stability-Workflow muss ebenfalls erfolgreich sein. In der PR-Ansicht seinen tatsächlichen Head und die Resultate überprüfen.
- Keine automatische Übernahme nach `overnight` oder `main`, kein NAS-Deployment.
- Die **zusätzliche Queue-Serialisierung** aus dem alten PR #508 (ein `CapacityLimiter(1)`) ist bewusst **nicht** enthalten. Ein Performance-Nutzen oder eine nötige Korrektur dafür muss separat begründet und getestet werden.
- Nach erfolgreicher Validierung erst über das Schließen der duplizierten PRs #500/#507 entscheiden.

## Bekannte Grenzen

Beim Vergleich mit Stable vor der Queue-Backup-Einführung veröffentlicht die
Baseline eine Datei (zwei fsync-Aufrufe, ein Austausch), der Kandidat dagegen
Primärdatei und geprüftes Backup (vier fsync-Aufrufe, zwei Austausche).
Nur bei einer durchgehend gemessenen alten Baseline wird die Speicherdauer des
Kandidaten pro veröffentlichter Datei verglichen. Rohdauer und Vergleichswert
stehen beide im Bericht. Der Kandidat muss weiterhin beide Dateien dauerhaft
schreiben; gemischte Baselines und fehlende Backup-Operationen bleiben Fehler.
Vergleiche zwischen zwei Backup-Versionen und alle anderen Leistungsbudgets
behalten ihre bisherigen Grenzwerte.

Die Quality-Suite testet Integration, Container-Start und Upgrade-/Rollback-Pfade; das Offline-Labor ergänzt gezielte Last-/Ressourcentests. Beide ersetzen weder 24-/72-Stunden-Leak-Soaks noch echte NAS-Mount-/EIO-/Datenträgerfehler-Tests.
