# Jellyfin-Bestandsindex

Royal Downloader speichert den letzten vollständigen Bestand an Filmen, Serien und Episoden in `jellyfin_inventory.sqlite3` im RD-Datenverzeichnis. SQLite aktualisiert den Bestand atomar und indiziert Episoden nach Serien-ID. Der Index enthält auch die von RD für Qualitätsvergleiche benötigten Film-Metadaten und Medienpfade. Benutzerbezogene Daten wie der Wiedergabestatus werden weiterhin separat geladen.

Ein Hintergrundprozess prüft standardmäßig alle 15 Sekunden die Anzahl und die zuletzt hinzugefügten Einträge. Einen vollständigen Abgleich führt RD beim Start, alle sechs Stunden und bei einer erkannten Änderung ohne passende Webhook-Aktualisierung durch. Die beiden Intervalle sind über `JELLYFIN_LIVE_POLL_SECONDS` und `JELLYFIN_INVENTORY_RECONCILE_SECONDS` einstellbar. Der letzte gespeicherte Bestand bleibt bei fehlgeschlagenen Abrufen sichtbar und eine nicht verifizierte Abwesenheit gibt keinen Download frei. Vor dem Einreihen einer fehlenden Folge einer bekannten Serie kann RD deren Episoden gezielt bei Jellyfin bestätigen.

## Änderungen per Webhook übernehmen

1. In RD `JELLYFIN_INVENTORY_WEBHOOK_SECRET` auf einen eigenen zufälligen Wert mit mindestens 32 Zeichen setzen und RD mit der neuen Umgebung starten.
2. In Jellyfin eine zu dessen Version passende Version des [offiziellen Webhook-Plugins](https://github.com/jellyfin/jellyfin-plugin-webhook) installieren. Das Plugin unterstützt `ItemDeleted` ab [Version 16](https://github.com/jellyfin/jellyfin-plugin-webhook/releases/tag/v16).
3. Im Plugin ein **Generic Destination** für **Item Added** und **Item Deleted** anlegen. Als Typen **Movie**, **Series** und **Episode** wählen. Die Zieladresse ist `http://<RD-Adresse>:8765/api/jellyfin/inventory/events`, erreichbar von Jellyfin aus. Als Request-Header `X-Royal-Jellyfin-Secret` mit dem in RD gesetzten Wert hinterlegen.
4. **Send All Properties** deaktiviert lassen und die folgende Vorlage eintragen.

```json
{
  "NotificationType": "{{NotificationType}}",
  "ItemType": "{{ItemType}}",
  "ItemId": "{{ItemId}}"
}
```

RD bestätigt die dauerhaft abgelegte Meldung mit HTTP 202. Anschließend prüft RD die betreffende Jellyfin-ID über dessen API. Mehrere Meldungen zur selben ID werden zusammengefasst. Das Entfernen eines Eintrags aus dem Index löscht keine Mediendatei. Der regelmäßige Vollabgleich findet auch Änderungen, zu denen das Plugin keine Meldung geliefert hat.

## Bestehende Lesewege und Diagnose

Plex verwendet weiterhin seine bisherigen Bestandsabrufe. Die Jellyfin-Merkliste lädt die Sicht des verknüpften Benutzers separat, weil der globale Index keine Bibliotheksberechtigungen, Abspielbarkeit oder Wiedergabestatus belegt. Für Filme in der Merkliste wird die Wiedergabe-Metadatenabfrage auf die betreffenden Jellyfin-IDs eingeschränkt.

Die Nachprüfung der Downloads läuft weiterhin nach 5, 15, 30, 60 und 120 Sekunden. Die globalen Prüfungen teilen sich die Bestandsaktualisierung. Benutzerbezogene Abfragen erfolgen weiterhin separat.

`media_scan_diagnostics().inventory_reads` exposes only counts of started,
joined, reused and failed reads, current in-flight reads and retained result
entries. Results are bounded to 16 entries and cleared on configuration changes.
URLs, credentials, item IDs and user IDs are not included in these diagnostics.
