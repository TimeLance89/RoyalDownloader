# Updater-Prüfung, 8. Oktober 2026

Geprüfte Basis: `overnight`, Commit `292f7da`. Umfang: Versionsprüfung,
Freigaben, Kanalwechsel, automatische Installation, Archivverarbeitung,
Runtime-Aktivierung, Queue-Neustart, Rollback und Einstellungsoberfläche.

## Bewertung

Die Docker/NAS-Basis ist zeitgemäß: Der Updater lädt einen konkreten Commit,
prüft CI und Commit-Signatur und bereitet Quellcode sowie Abhängigkeiten in
einem separaten Release vor. Smoke-Prüfungen laufen vor der atomaren Aktivierung;
das vorherige Release bleibt für einen manuellen Rollback erhalten.
Downloads werden vor dem Neustart persistent gesichert.

Die Prüfung hat Fehler in Freigaben, Nebenläufigkeit und Fehlerzuständen
aufgedeckt. Diese Änderungen ersetzen keine Prüfung auf dem tatsächlichen NAS.

## Behobene Fehler

| Stelle | Auslöser und bisheriges Verhalten | Änderung |
|---|---|---|
| Installations-API | Ein bestätigter Rückwechsel zu Stable konnte trotz fehlgeschlagener CI, ungültiger Signatur oder Prüfungsfehler starten. | Beide Freigaben müssen ausdrücklich vorliegen; die Bestätigung erlaubt ausschließlich den Wechsel der Versionshistorie. |
| GitHub-Prüfung | Ein früherer grüner `verify`-Lauf konnte einen neueren fehlgeschlagenen oder laufenden Check überdecken. | Die neueste Check-ID entscheidet, unabhängig von der Reihenfolge der Antwort. |
| Prüfungs-Cache | Eine laufende oder noch fehlende CI-Prüfung konnte zehn Minuten zwischengespeichert werden. | Diese Ergebnisse werden nach höchstens 15 Sekunden erneut geprüft. |
| Installation/Kanalwechsel | Während einer GitHub-Prüfung konnte sich der Kanal ändern; die alte Revision konnte anschließend automatisch installiert werden. | Speichern und Installationszulassung verwenden denselben Konfigurations-Lock. Der geprüfte Kanal und bei Automatik zusätzlich der Modus werden unmittelbar vor dem Start erneut geprüft. |
| Oberfläche | Eine ältere Statusantwort konnte einen neueren Check oder eine laufende Installation überschreiben. | Antworten überholter Prüfungen werden verworfen. |
| Neustart-Erkennung | Alle drei Sekunden wurde erneut die vollständige GitHub-Prüfung angestoßen. | Die Oberfläche fragt ausschließlich lokale Capabilities ab. Die vollständige Revision wird beim Prozessstart festgehalten; ausgetauschte Dateien gelten nicht bereits als erfolgreicher Neustart. Ältere Builds werden über ihren zwölfstelligen Fingerabdruck erkannt. |
| Restart/Rollback | Fehler im Restart-Callback bzw. Restart-Thread ließen den Installer dauerhaft aktiv. Beim Rollback blieb die Zielrevision des letzten Updates stehen. | Restart-Fehler werden als terminaler Fehler veröffentlicht; Rollbacks melden den Commit des wiederhergestellten Releases. |
| Archiv | HTTP-Verbindungen wurden nicht zuverlässig geschlossen; alle Archiv-Header wurden vor dem Dateilimit eingelesen. | Verbindungen werden auch bei Fehlern geschlossen. Das Dateilimit greift während des Einlesens; Transferlänge und Zeitbudget zwischen Empfangsblöcken werden geprüft. Bestehende Connect-/Read-Timeouts bleiben wirksam. |
| Dateiziele | Verzeichnisse konnten vor der Prüfung des Zielpfads angelegt werden. | Die Pfadgrenze wird vor dem Anlegen geprüft; Laufwerkspfade werden aus Manifest-Einträgen ausgeschlossen. |

Die UI zeigt fehlende CI- und Signaturfreigaben für beide Kanäle an.
Die Beschreibung der Automatik entspricht dem tatsächlichen Ablauf:
Downloads laufen während der Vorbereitung weiter und werden zum Neustart gesichert.

## Verbleibende Grenzen

1. **Kein automatischer Rollback nach einem gescheiterten tatsächlichen
   Serverstart beim In-App-Update.** Die Vorabprüfung kompiliert und importiert
   den Server, führt jedoch nicht dessen vollständigen Lifespan aus. Scheitert
   erst dieser Start, erkennt die Oberfläche den fehlenden Zielprozess, kann
   aber bei unerreichbarem RD keinen API-Rollback auslösen. Ein unabhängiger
   Bootstrap-Wächter mit Health-Prüfung und begrenztem Rollback-Versuch wäre
   die nächste größere Ausbaustufe. Der externe NAS-Paketinstaller besitzt
   bereits eine eigene Startprüfung und Wiederherstellung.
2. Der Installerstatus lebt im Prozessspeicher. Ein Installationsjournal für
   Abstürze/Stromausfall und die Bereinigung verwaister Staging-Verzeichnisse
   fehlen. Die atomare Release-Verknüpfung und das vorherige Release bleiben
   die vorhandenen Wiederherstellungspunkte.
3. Die Legacy-Installation ohne versionierte Runtime ersetzt Dateien einzeln.
   Sie bietet bei einem Stromausfall keine atomare Gesamtaktivierung und
   akzeptiert absichtlich keine Änderung des Dependency-Lockfiles.
4. Die Archivfrist wird zwischen Empfangsblöcken geprüft; sie ist kein
   unabhängiger Prozess-Watchdog gegen eine beliebig langsam tröpfelnde
   Verbindung.

> **Follow-up in Overnight, 2026-10-10:** The self-healing Docker guard
> addresses the first two limitations above for versioned Docker installations:
> the image-owned bootstrap supervises actual startup and keeps a durable update
> journal. This audit remains the historical baseline, and the external NAS
> deployment still requires a freshly built Docker image before the guard is active.
> See [Self-healing Docker updater](SELF_HEALING_UPDATER.md) for verification,
> recovery boundaries and what still requires a NAS field test.

## Verifikation

Regressionen decken gesperrte Stable-Rückwechsel, neuere rote/laufende CI,
Kanal- und Modusänderungen während der Prüfung, Restart-Fehler, Rollback-Ziele,
Archivgrenzen und lokale Neustart-Erkennung ab. Bestehende Updater-, Runtime-
und Frontend-Tests werden zusätzlich ausgeführt. Linux-spezifische
Symlink-/Docker-Prüfungen müssen unter Linux bzw. in CI laufen.

Lokales Ergebnis: 1.514 Python-Tests bestanden, elf plattformbedingte
Überspringungen und zwei ausgeschlossene Windows-unverträgliche Bestandstests
(`test_setup_bootstrap_is_private_one_time_and_not_returned`,
`test_only_media_locations_join_smart_scan`). 246 Frontend-Tests und der
Browser-Smoke-Test bestanden. Syntax, Ruff, Security-Scan, Bandit und die
bestehenden Coverage-Grenzen bestanden ebenfalls. Docker/NAS-Laufzeit wurde
hier nicht ausgeführt.

Implementierung: `updates/update_checker.py`, `core/security_runtime.py`,
`updates/self_updater.py`, `application_services/updater.py`,
`api/api_administration_router.py`, `server.py`,
`web/js/features/settings/updater.js`.
