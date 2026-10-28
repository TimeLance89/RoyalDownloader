# Jellyfin und Plex

Unter **Einstellungen → Dienste → Dein Mediencenter** ist genau ein Mediencenter aktiv. Vorhandene Jellyfin-Einstellungen werden ohne Migration weiterverwendet. Der Einrichtungsassistent bietet den Wechsel zur Alternative an; die aktive Verbindung lässt sich über **Verwalten** ändern.

## Plex verbinden

1. Plex Media Server installieren, anmelden und Film-/Serienbibliotheken anlegen.
2. **Zu Plex wechseln** öffnen. Die Serveradresse muss vom Royal-Server aus erreichbar sein.
3. Serveradresse und `X-Plex-Token` eintragen, anschließend **Verbindung prüfen**.
4. Die tatsächlich verfügbaren Film-/Serienbibliotheken und das Wiedergabeprofil wählen.
5. Auswahl prüfen und den Wechsel bestätigen.

Wenn Royal nativ auf demselben Windows-Rechner läuft, ist `http://127.0.0.1:32400` möglich. In Docker bezeichnet `127.0.0.1` den Container: dort die erreichbare Rechneradresse verwenden.

Token-Hilfe: [Plex: Authentication Token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/). API-Grundlage: [Plex Media Server API](https://developer.plex.tv/pms/).

Der Token wird als Header zum Plex-Server gesendet. Er wird weder in URL-Parametern noch in API-Antworten ausgegeben. Die bestehende geschützte lokale Einstellungsdatei speichert ihn wie andere Integrationszugänge. Leere Zugangsfelder behalten einen gespeicherten Schlüssel nur bei identischer Serveradresse und identischem Dienst bei.

## Verhalten

- Bibliotheksabgleich für Filme, Serien und Folgen einschließlich TMDB-Identität, Videohöhe und Dateipfad; vollständige paginierte Abfragen.
- Katalog-/Detailanzeigen und Download-Prüfungen verwenden den aktiven Dienst. Bestehende API-Feldnamen mit `jellyfin` bleiben aus Kompatibilitätsgründen erhalten.
- Gesehen-Status und die Staffel-Automatik verwenden das ausgewählte Profil. Unbekannter Status wird nicht als ungesehen interpretiert.
- Neue Downloads können Plex-Bibliotheksscans auslösen. Wiedergabeprüfung für Bandbreitendrosselung und Speicher-Autopilot berücksichtigt Plex.
- Persönliche Royal-Profile erhalten eigene, servergebundene Plex-Zuordnungen. Jellyfin-Zuordnungen bleiben für den Rückwechsel erhalten.
- RD-Merklisten werden als konto-private Plex-Playlists synchronisiert. Gesehene Inhalte fließen für verknüpfte Royal-Profile in das lokale Geschmacksprofil ein.
- Jellyfin-Empfehlungscollections werden nicht als Plex-Collections exportiert. Lokale Royal-Empfehlungen nutzen weiterhin das Geschmacksprofil.
- Moonfin bleibt eine Jellyfin-Erweiterung; bei aktivem Plex wird keine Moonfin-Konfiguration an Plex gesendet. Der unabhängige Seerr-Abgleich und Bibliotheksscan nutzen weiter den aktiven Dienst.

## Grenzen und Wechsel-Sicherheit

Plex stellt Gesehen-Daten im Kontext des authentifizierten Tokens bereit. Deshalb bietet Royal nur **Plex-Konto dieser Verbindung** an. Andere Plex-Home-Konten werden nicht durch bloße Übergabe einer Benutzer-ID abgefragt. Eine universelle Plex-Home-Anmeldung mit eigenen Zugangstoken je Haushaltprofil ist nicht Bestandteil dieser Anbindung.

Automatische Löschregeln sind für Plex gesperrt, auch wenn ein älteres Jellyfin-Abo eine solche Regel besitzt. Medienlöschung ist im Plex-Adapter deaktiviert. Der Wechsel setzt die Standard-Löschregel auf **Behalten**.

Die Zielverbindung wird beim Speichern erneut geprüft. Die Auswahl von Bibliotheken und Profil muss weiterhin gültig sein. Eine Generationsprüfung verhindert, dass eine zweite Sitzung inzwischen geänderte Verbindungen überschreibt. Bei fehlgeschlagener Prüfung oder Speicherung bleibt die bisherige Verbindung aktiv. Beide Dienste behalten getrennte Zugangsdaten; Caches werden beim Wechsel verworfen.

## Lokale Verifikation am 28.10.2026

- Echte Royal-Anmeldung und authentifizierter Probe-Aufruf gegen den installierten Windows-Plex-Server erfolgreich.
- Die anfängliche Aktivierung ohne Bibliotheken wurde korrekt abgelehnt. Nach dem Anlegen der Bibliothek **Filme** wurde Plex in einem separaten temporären Royal-Datenverzeichnis erfolgreich aktiviert; die bestehende Royal-Verbindung blieb unverändert.
- Ein echter Testfilm wurde mit TMDB-ID, Videohöhe, Dateipfad und Gesehen-Status gelesen. Royal meldet den Film sowohl über Titel/Jahr als auch unabhängig vom Titel über seine TMDB-ID als vorhanden. Eine absichtlich falsche TMDB-ID meldet Royal als fehlend.
- Live-Snapshot, Profil-Endpunkt, erneutes Laden der gespeicherten Auswahl und Plex-Scan wurden erfolgreich geprüft. Der Gesehen-Status wurde bei der Prüfung nicht verändert.
- Serien-/Folgenzuordnung und Pagination werden weiterhin mit kontrollierten Testdaten geprüft; ein echter Serientest benötigt eine Serienbibliothek.
- Desktop-/Mobil-Browsertests und vorhandene Jellyfin-/Setup-Regressionstests. Die Browser-Screenshots verwenden kontrollierte Beispieldaten; private Serveradressen und Mediendateipfade werden nicht veröffentlicht.

## Ansichten mit Beispieldaten

- [Einstellungen: vorhandenes Jellyfin](assets/screenshots/media-center/settings-desktop.png)
- [Wechsel zu Plex](assets/screenshots/media-center/switch-desktop.png)
- [Bibliothekswahl auf Mobilgeräten](assets/screenshots/media-center/libraries-mobile.png)
- [Aktiviertes Plex mit Rückwechsel](assets/screenshots/media-center/plex-active-mobile.png)
