package de.royaldownloader.app.ui.watchlist

import de.royaldownloader.app.data.remote.WatchlistItem
import de.royaldownloader.app.ui.components.RoyalStatusTone
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

internal fun watchModeLabel(mode: String): String = when (mode) {
    "all" -> "Alles Fehlende"
    "latest_season" -> "Neueste Staffel"
    "next_season" -> "Nächste Staffel nach Sehfortschritt"
    else -> mode
}

internal fun watchModeTitle(mode: String): String = when (mode) {
    "all" -> "Das Abo hält die komplette Serie vollständig"
    "latest_season" -> "Die neueste Staffel bleibt im Fokus"
    "next_season" -> "Das Abo folgt deinem Sehfortschritt"
    else -> "Individuelle Downloadregel"
}

internal fun watchModeExplanation(mode: String): String = when (mode) {
    "all" ->
        "Royal prüft sofort alle Staffeln und danach regelmäßig weiter. Fehlende Episoden landen je nach Automatik in der Queue oder im Abo-Postfach."
    "latest_season" ->
        "Royal überwacht die höchste Staffel. Sobald eine neue Staffel erscheint, wird sie automatisch zum neuen Ziel."
    "next_season" ->
        "Royal folgt dem Sehfortschritt des gewählten Jellyfin-Benutzers. Die nächste Staffel wird erst nach der vollständig gesehenen vorherigen Staffel freigegeben."
    else -> "Royal prüft die Serie regelmäßig nach der gespeicherten Regel."
}

internal fun cleanupModeLabel(mode: String): String = when (mode) {
    "keep" -> "Gesehene Inhalte behalten"
    "watched_seasons" -> "Gesehene Staffeln löschen"
    "watched_episodes" -> "Gesehene Episoden löschen"
    else -> mode
}

internal fun cleanupModeExplanation(mode: String): String = when (mode) {
    "watched_seasons" ->
        "Vollständig gesehene Staffeln dürfen nach dem Jellyfin-Abgleich automatisch entfernt werden."
    "watched_episodes" ->
        "Als gesehen markierte Episoden dürfen nach dem Jellyfin-Abgleich automatisch entfernt werden."
    else -> "Bereits geladene Inhalte bleiben erhalten."
}

internal fun statusLabel(item: WatchlistItem): String = when (item.status) {
    "current" -> "Aktuell"
    "queued" -> "Eingeplant"
    "missing" -> "Episoden fehlen"
    "waiting_window" -> "Wartet auf Zeitfenster"
    "failed" -> "Fehlgeschlagen"
    "blocked" -> "Pausiert"
    else -> item.status
}

internal fun statusTone(item: WatchlistItem): RoyalStatusTone = when (item.status) {
    "current" -> RoyalStatusTone.Success
    "queued" -> RoyalStatusTone.Queued
    "failed", "blocked" -> RoyalStatusTone.Error
    else -> RoyalStatusTone.Warning
}

internal fun checkedAtLabel(epochSeconds: Double): String {
    if (epochSeconds <= 0) return "Noch nicht geprüft"
    return runCatching {
        CHECKED_AT_FORMAT.format(
            Instant.ofEpochSecond(epochSeconds.toLong()).atZone(ZoneId.systemDefault()),
        )
    }.getOrDefault("Prüfzeit unbekannt")
}

private val CHECKED_AT_FORMAT = DateTimeFormatter.ofPattern("'Geprüft am' dd.MM.yyyy 'um' HH:mm")
