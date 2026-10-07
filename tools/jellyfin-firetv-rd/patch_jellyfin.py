#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "jellyfin")

bridge_path = root / "app/src/main/java/org/jellyfin/androidtv/integration/royaldownloader/RoyalDownloaderBridge.kt"
bridge_path.parent.mkdir(parents=True, exist_ok=True)
bridge_path.write_text(r'''package org.jellyfin.androidtv.integration.royaldownloader

import android.app.AlertDialog
import android.content.Context
import android.text.InputType
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.jellyfin.sdk.model.api.BaseItemDto
import org.jellyfin.sdk.model.api.BaseItemKind
import org.json.JSONArray
import org.json.JSONObject
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URI
import java.net.URLEncoder
import java.net.UnknownHostException
import java.nio.charset.StandardCharsets
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLHandshakeException

object RoyalDownloaderBridge {
    private const val PREFS = "royal_downloader"
    private const val KEY_URL = "url"
    private const val KEY_USER = "username"
    private const val KEY_PASSWORD = "password"
    private const val KEY_TOKEN = "token"

    private lateinit var appContext: Context
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mappedItems = ConcurrentHashMap<UUID, RoyalItem>()

    private enum class Kind { CONFIG, ERROR, MOVIE, SERIES }

    private data class RoyalItem(
        val kind: Kind,
        val title: String,
        val year: String = "",
        val slug: String = "",
        val baseSlug: String = "",
        val sampleSlug: String = "",
        val detail: String = "",
    )

    private class RoyalHttpException(val status: Int, message: String) : RuntimeException(message)

    fun initialize(context: Context) {
        appContext = context.applicationContext
    }

    fun isRoyal(item: BaseItemDto?): Boolean {
        val id = item?.id ?: return false
        return mappedItems.containsKey(id)
    }

    fun search(query: String): List<BaseItemDto> {
        if (!::appContext.isInitialized) return emptyList()
        mappedItems.clear()
        if (!isConfigured()) {
            return listOf(toBaseItem(RoyalItem(Kind.CONFIG, "Royal Downloader verbinden", detail = "Einmal RD-Adresse und Zugangsdaten hinterlegen")))
        }

        return try {
            // Fail fast on connection/authentication before provider searches. This
            // keeps network/login errors distinguishable from a slow provider.
            probeApi()
            ensureToken()

            val encoded = URLEncoder.encode(query, StandardCharsets.UTF_8.toString())
            val executor = Executors.newFixedThreadPool(2)
            val movieFuture = executor.submit<JSONObject> {
                authorizedRequest("GET", "/api/v1/movies?mode=search&query=$encoded", readTimeoutMs = 35_000)
            }
            val seriesFuture = executor.submit<JSONObject> {
                authorizedRequest("GET", "/api/v1/series?mode=search&query=$encoded", readTimeoutMs = 35_000)
            }

            val hits = mutableListOf<RoyalItem>()
            var firstSearchError: Throwable? = null
            try {
                try {
                    val movieResults = movieFuture.get(40, TimeUnit.SECONDS).optJSONArray("results") ?: JSONArray()
                    for (index in 0 until movieResults.length()) {
                        val item = movieResults.optJSONObject(index) ?: continue
                        val slug = item.optString("slug")
                        val title = item.optString("title")
                        if (slug.isBlank() || title.isBlank()) continue
                        hits += RoyalItem(
                            kind = Kind.MOVIE,
                            title = title,
                            year = item.optString("year"),
                            slug = slug,
                            detail = "Film • über Royal Downloader verfügbar",
                        )
                    }
                } catch (error: Throwable) {
                    firstSearchError = unwrapFutureError(error)
                }

                try {
                    val seriesResults = seriesFuture.get(40, TimeUnit.SECONDS).optJSONArray("results") ?: JSONArray()
                    for (index in 0 until seriesResults.length()) {
                        val item = seriesResults.optJSONObject(index) ?: continue
                        val baseSlug = item.optString("base_slug")
                        val sampleSlug = item.optString("sample_slug")
                        val title = item.optString("title")
                        if (baseSlug.isBlank() || title.isBlank()) continue
                        hits += RoyalItem(
                            kind = Kind.SERIES,
                            title = title,
                            year = item.optString("year"),
                            baseSlug = baseSlug,
                            sampleSlug = sampleSlug,
                            detail = "Serie • fehlende Episoden über Royal Downloader",
                        )
                    }
                } catch (error: Throwable) {
                    if (firstSearchError == null) firstSearchError = unwrapFutureError(error)
                }
            } finally {
                executor.shutdownNow()
            }

            if (hits.isEmpty() && firstSearchError != null) throw firstSearchError as Throwable

            val unique = hits.distinctBy { Triple(it.kind, it.title.lowercase(), it.year) }.take(24)
            val missing = try {
                filterOwned(unique).take(12)
            } catch (_: Exception) {
                // A temporary Jellyfin ownership check must not hide otherwise
                // valid RoyalDownloader provider results.
                unique.take(12)
            }
            missing.map(::toBaseItem)
        } catch (error: Throwable) {
            val diagnosed = diagnose(error)
            listOf(toBaseItem(RoyalItem(
                Kind.ERROR,
                diagnosed.first,
                detail = diagnosed.second,
            )))
        }
    }

    fun handleClick(context: Context, item: BaseItemDto?): Boolean {
        val id = item?.id ?: return false
        val royal = mappedItems[id] ?: return false
        when (royal.kind) {
            Kind.CONFIG, Kind.ERROR -> showConfigurationDialog(context)
            Kind.MOVIE, Kind.SERIES -> scope.launch {
                val message = try {
                    requestDownload(royal)
                } catch (error: Exception) {
                    "Royal Downloader: ${error.message ?: "Anfrage fehlgeschlagen"}"
                }
                withContext(Dispatchers.Main) {
                    Toast.makeText(context, message, Toast.LENGTH_LONG).show()
                }
            }
        }
        return true
    }

    private fun isConfigured(): Boolean {
        val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return prefs.getString(KEY_URL, "").orEmpty().isNotBlank()
            && prefs.getString(KEY_USER, "").orEmpty().isNotBlank()
            && prefs.getString(KEY_PASSWORD, "").orEmpty().isNotBlank()
    }

    private fun showConfigurationDialog(context: Context) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val layout = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (24 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad / 2, pad, 0)
        }
        val url = EditText(context).apply {
            hint = "RD-Adresse, z. B. https://royal-downloader.de"
            setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setText(prefs.getString(KEY_URL, ""))
        }
        val user = EditText(context).apply {
            hint = "Benutzername"
            setSingleLine(true)
            setText(prefs.getString(KEY_USER, ""))
        }
        val password = EditText(context).apply {
            hint = "Passwort"
            setSingleLine(true)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(prefs.getString(KEY_PASSWORD, ""))
        }
        layout.addView(url)
        layout.addView(user)
        layout.addView(password)

        AlertDialog.Builder(context)
            .setTitle("Royal Downloader")
            .setMessage("Verbindung für die Jellyfin-Suche einrichten")
            .setView(layout)
            .setNegativeButton("Abbrechen", null)
            .setPositiveButton("Speichern & testen") { _, _ ->
                val rawUrl = url.text.toString().trim()
                val normalizedUrl = when {
                    rawUrl.startsWith("http://", ignoreCase = true) || rawUrl.startsWith("https://", ignoreCase = true) -> rawUrl
                    rawUrl.isNotBlank() -> "https://$rawUrl"
                    else -> rawUrl
                }.trimEnd('/')
                prefs.edit()
                    .putString(KEY_URL, normalizedUrl)
                    .putString(KEY_USER, user.text.toString().trim())
                    .putString(KEY_PASSWORD, password.text.toString())
                    .remove(KEY_TOKEN)
                    .apply()

                scope.launch {
                    val message = try {
                        probeApi()
                        ensureToken()
                        "Royal Downloader: Verbindung und Anmeldung OK"
                    } catch (error: Throwable) {
                        val diagnosed = diagnose(error)
                        "${diagnosed.first}: ${diagnosed.second}"
                    }
                    withContext(Dispatchers.Main) {
                        Toast.makeText(context, message, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .show()
    }

    private fun filterOwned(items: List<RoyalItem>): List<RoyalItem> {
        if (items.isEmpty()) return emptyList()
        val payloadItems = JSONArray()
        for (item in items) {
            val key = if (item.kind == Kind.MOVIE) item.slug else item.baseSlug
            payloadItems.put(JSONObject()
                .put("slug", key)
                .put("title", item.title)
                .put("year", item.year)
                .put("media_type", if (item.kind == Kind.MOVIE) "movie" else "series"))
        }
        val response = authorizedRequest("POST", "/api/v1/jellyfin/matches", JSONObject().put("items", payloadItems))
        val matches = response.optJSONObject("matches") ?: return items
        return items.filter { item ->
            val key = if (item.kind == Kind.MOVIE) item.slug else item.baseSlug
            !matches.optBoolean(key, false)
        }
    }

    private fun requestDownload(item: RoyalItem): String = when (item.kind) {
        Kind.MOVIE -> {
            val response = authorizedRequest(
                "POST",
                "/api/v1/queue/add",
                JSONObject().put("slugs", JSONArray().put(item.slug)),
            )
            val added = response.optInt("added", 0)
            if (added > 0) "${item.title}: Download an Royal Downloader übergeben"
            else "${item.title}: bereits vorhanden, geplant oder nicht verfügbar"
        }
        Kind.SERIES -> requestSeries(item)
        else -> "Keine Download-Aktion"
    }

    private fun requestSeries(item: RoyalItem): String {
        val detail = authorizedRequest(
            "POST",
            "/api/v1/series/load",
            JSONObject()
                .put("sample_slug", item.sampleSlug)
                .put("base_slug", item.baseSlug)
                .put("refresh_jellyfin", true)
                .put("defer_checks", false),
        )
        val slugs = JSONArray()
        val seasons = detail.optJSONArray("seasons") ?: JSONArray()
        for (seasonIndex in 0 until seasons.length()) {
            val episodes = seasons.optJSONObject(seasonIndex)?.optJSONArray("episodes") ?: continue
            for (episodeIndex in 0 until episodes.length()) {
                val episode = episodes.optJSONObject(episodeIndex) ?: continue
                if (episode.optBoolean("unreleased", false)) continue
                if (episode.optBoolean("queued", false)) continue
                if (episode.optBoolean("downloaded", false)) continue
                if (episode.optBoolean("in_jellyfin", false)) continue
                val slug = episode.optString("slug")
                if (slug.isNotBlank()) slugs.put(slug)
            }
        }
        if (slugs.length() == 0) return "${item.title}: keine fehlenden veröffentlichten Episoden"
        val response = authorizedRequest("POST", "/api/v1/queue/add", JSONObject().put("slugs", slugs))
        val added = response.optInt("added", 0)
        return "${item.title}: $added Episode(n) an Royal Downloader übergeben"
    }

    private fun toBaseItem(item: RoyalItem): BaseItemDto {
        val id = UUID.randomUUID()
        mappedItems[id] = item
        val displayName = if (item.year.isBlank()) item.title else "${item.title} (${item.year})"
        return BaseItemDto(
            id = id,
            type = when (item.kind) {
                Kind.MOVIE -> BaseItemKind.MOVIE
                Kind.SERIES -> BaseItemKind.SERIES
                else -> BaseItemKind.FOLDER
            },
            name = displayName,
            overview = item.detail,
        )
    }

    private fun probeApi() {
        val response = rawRequest("GET", "/api/v1/health", null, null, readTimeoutMs = 8_000)
        if (response.optString("status") != "ok") {
            throw IllegalStateException("RD-Healthcheck antwortet unerwartet")
        }
    }

    private fun ensureToken(): String {
        val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs.getString(KEY_TOKEN, "").orEmpty().takeIf { it.isNotBlank() }?.let { return it }
        val login = JSONObject()
            .put("username", prefs.getString(KEY_USER, "").orEmpty())
            .put("password", prefs.getString(KEY_PASSWORD, "").orEmpty())
            .put("device_label", "Jellyfin Fire TV")
        val response = rawRequest("POST", "/api/v1/auth/login", login, null, readTimeoutMs = 20_000)
        val token = response.optString("access_token")
        if (token.isBlank()) throw IllegalStateException("RD-Anmeldung lieferte kein Token")
        prefs.edit().putString(KEY_TOKEN, token).apply()
        return token
    }

    private fun authorizedRequest(
        method: String,
        path: String,
        body: JSONObject? = null,
        readTimeoutMs: Int = 30_000,
    ): JSONObject {
        var token = ensureToken()
        return try {
            rawRequest(method, path, body, token, readTimeoutMs)
        } catch (error: RoyalHttpException) {
            if (error.status != 401) throw error
            appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(KEY_TOKEN).apply()
            token = ensureToken()
            rawRequest(method, path, body, token, readTimeoutMs)
        }
    }

    private fun unwrapFutureError(error: Throwable): Throwable {
        return error.cause ?: error
    }

    private fun diagnose(error: Throwable): Pair<String, String> {
        val root = generateSequence(error) { it.cause }.last()
        return when (root) {
            is RoyalHttpException -> {
                val message = root.message.orEmpty()
                when {
                    root.status == 401 -> "RD: Anmeldung fehlgeschlagen" to message
                    root.status == 400 && message.contains("Host", ignoreCase = true) ->
                        "RD: Host nicht erlaubt" to "ROYAL_ALLOWED_HOSTS blockiert diese Adresse. $message"
                    else -> "RD: HTTP ${root.status}" to message
                }
            }
            is UnknownHostException -> "RD: Domain nicht auflösbar" to (root.message ?: "DNS-Fehler")
            is ConnectException -> "RD: Server nicht erreichbar" to (root.message ?: "Verbindungsfehler")
            is SocketTimeoutException -> "RD: Zeitüberschreitung" to "Der Server antwortet, aber die Anfrage dauert zu lange."
            is SSLHandshakeException -> "RD: HTTPS-Zertifikat abgewiesen" to (root.message ?: "TLS-Handshake fehlgeschlagen")
            else -> "RD: Fehler" to (root.message ?: error.message ?: error.javaClass.simpleName)
        }
    }

    private fun rawRequest(
        method: String,
        path: String,
        body: JSONObject?,
        token: String?,
        readTimeoutMs: Int = 30_000,
    ): JSONObject {
        val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val base = prefs.getString(KEY_URL, "").orEmpty().trim().trimEnd('/')
        if (base.isBlank()) throw IllegalStateException("RD-Adresse fehlt")
        val uri = URI.create(base + path)
        val connection = uri.toURL().openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.instanceFollowRedirects = true
        connection.connectTimeout = 8_000
        connection.readTimeout = readTimeoutMs
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("User-Agent", "Jellyfin-RD-FireTV/0.2")
        connection.setRequestProperty("Connection", "close")
        if (!token.isNullOrBlank()) connection.setRequestProperty("Authorization", "Bearer $token")
        if (body != null) {
            val bytes = body.toString().toByteArray(StandardCharsets.UTF_8)
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.setFixedLengthStreamingMode(bytes.size)
            connection.outputStream.use { it.write(bytes) }
        }
        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val text = stream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() }.orEmpty()
        connection.disconnect()
        if (status !in 200..299) {
            var detail = text
            var code = ""
            try {
                val payload = JSONObject(text)
                detail = payload.optString("detail").ifBlank { text }
                code = payload.optString("code")
            } catch (_: Exception) {
                // Keep raw response text.
            }
            val suffix = buildString {
                if (detail.isNotBlank()) append(": ").append(detail)
                if (code.isNotBlank()) append(" [").append(code).append("]")
            }
            throw RoyalHttpException(status, "HTTP $status$suffix")
        }
        return if (text.isBlank()) JSONObject() else JSONObject(text)
    }
}
''', encoding="utf-8")

# SearchFragment: initialize bridge when fragment attaches.
path = root / "app/src/main/java/org/jellyfin/androidtv/ui/search/SearchFragment.kt"
text = path.read_text(encoding="utf-8")
text = text.replace("import android.os.Bundle\n", "import android.content.Context\nimport android.os.Bundle\n")
text = text.replace(
    "import org.jellyfin.androidtv.ui.base.JellyfinTheme\n",
    "import org.jellyfin.androidtv.integration.royaldownloader.RoyalDownloaderBridge\nimport org.jellyfin.androidtv.ui.base.JellyfinTheme\n",
)
needle = "class SearchFragment : Fragment() {\n\tcompanion object {"
replacement = "class SearchFragment : Fragment() {\n\toverride fun onAttach(context: Context) {\n\t\tsuper.onAttach(context)\n\t\tRoyalDownloaderBridge.initialize(context)\n\t}\n\n\tcompanion object {"
if needle not in text:
    raise SystemExit("SearchFragment patch anchor not found")
text = text.replace(needle, replacement, 1)
path.write_text(text, encoding="utf-8")

# SearchViewModel: run RD search in parallel and append it as a row.
path = root / "app/src/main/java/org/jellyfin/androidtv/ui/search/SearchViewModel.kt"
text = path.read_text(encoding="utf-8")
text = text.replace("import kotlinx.coroutines.Job\n", "import kotlinx.coroutines.Dispatchers\nimport kotlinx.coroutines.Job\n")
text = text.replace(
    "import org.jellyfin.androidtv.R\n",
    "import org.jellyfin.androidtv.R\nimport org.jellyfin.androidtv.integration.royaldownloader.RoyalDownloaderBridge\n",
)
old = '''\t\tsearchJob = viewModelScope.launch {\n\t\t\tdelay(debounce)\n\n\t\t\t_searchResultsFlow.value = groups.map { (stringRes, itemKinds) ->\n\t\t\t\tasync {\n\t\t\t\t\tval result = searchRepository.search(trimmed, itemKinds)\n\t\t\t\t\tval items = result.getOrNull().orEmpty()\n\n\t\t\t\t\tSearchResultGroup(stringRes, items)\n\t\t\t\t}\n\t\t\t}.awaitAll()\n\t\t}\n'''
new = '''\t\tsearchJob = viewModelScope.launch {\n\t\t\tdelay(debounce)\n\n\t\t\tval royalSearch = async(Dispatchers.IO) { RoyalDownloaderBridge.search(trimmed) }\n\t\t\tval jellyfinGroups = groups.map { (stringRes, itemKinds) ->\n\t\t\t\tasync {\n\t\t\t\t\tval result = searchRepository.search(trimmed, itemKinds)\n\t\t\t\t\tval items = result.getOrNull().orEmpty()\n\n\t\t\t\t\tSearchResultGroup(stringRes, items)\n\t\t\t\t}\n\t\t\t}.awaitAll()\n\t\t\tval royalItems = royalSearch.await()\n\t\t\t_searchResultsFlow.value = buildList {\n\t\t\t\taddAll(jellyfinGroups)\n\t\t\t\tif (royalItems.isNotEmpty()) add(SearchResultGroup(R.string.lbl_royal_downloader, royalItems))\n\t\t\t}\n\t\t}\n'''
if old not in text:
    raise SystemExit("SearchViewModel patch anchor not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

# SearchFragmentDelegate: intercept RD fake items and don't ask Jellyfin for their backdrops.
path = root / "app/src/main/java/org/jellyfin/androidtv/ui/search/SearchFragmentDelegate.kt"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "import org.jellyfin.androidtv.data.service.BackgroundService\n",
    "import org.jellyfin.androidtv.data.service.BackgroundService\nimport org.jellyfin.androidtv.integration.royaldownloader.RoyalDownloaderBridge\n",
)
old = '''\tval onItemViewClickedListener = OnItemViewClickedListener { _, item, _, row ->\n\t\tif (item !is BaseRowItem) return@OnItemViewClickedListener\n\t\trow as ListRow\n\t\tval adapter = row.adapter as ItemRowAdapter\n\t\titemLauncher.launch(item as BaseRowItem?, adapter, context)\n\t}\n'''
new = '''\tval onItemViewClickedListener = OnItemViewClickedListener { _, item, _, row ->\n\t\tif (item !is BaseRowItem) return@OnItemViewClickedListener\n\t\tif (RoyalDownloaderBridge.handleClick(context, item.baseItem)) return@OnItemViewClickedListener\n\t\trow as ListRow\n\t\tval adapter = row.adapter as ItemRowAdapter\n\t\titemLauncher.launch(item as BaseRowItem?, adapter, context)\n\t}\n'''
if old not in text:
    raise SystemExit("SearchFragmentDelegate click anchor not found")
text = text.replace(old, new, 1)
old = '''\tval onItemViewSelectedListener = OnItemViewSelectedListener { _, item, _, _ ->\n\t\tval baseItem = item?.let { (item as BaseRowItem).baseItem }\n\t\tif (baseItem != null) {\n\t\t\tbackgroundService.setBackground(baseItem)\n\t\t} else {\n\t\t\tbackgroundService.clearBackgrounds()\n\t\t}\n\t}\n'''
new = '''\tval onItemViewSelectedListener = OnItemViewSelectedListener { _, item, _, _ ->\n\t\tval baseItem = item?.let { (item as BaseRowItem).baseItem }\n\t\tif (baseItem != null && !RoyalDownloaderBridge.isRoyal(baseItem)) {\n\t\t\tbackgroundService.setBackground(baseItem)\n\t\t} else {\n\t\t\tbackgroundService.clearBackgrounds()\n\t\t}\n\t}\n'''
if old not in text:
    raise SystemExit("SearchFragmentDelegate selection anchor not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

# Add base strings; translations fall back to base resources.
path = root / "app/src/main/res/values/strings.xml"
text = path.read_text(encoding="utf-8")
if 'name="lbl_royal_downloader"' not in text:
    text = text.replace(
        '<string name="app_name_debug" translatable="false" tools:ignore="UnusedResources">Jellyfin Debug</string>',
        '<string name="app_name_debug" translatable="false" tools:ignore="UnusedResources">Jellyfin RD 0.4</string>\n    <string name="lbl_royal_downloader" translatable="false">Royal Downloader</string>',
        1,
    )
path.write_text(text, encoding="utf-8")

from patch_watchlist import patch_watchlist
patch_watchlist(root)
print("RoyalDownloader Fire TV search and personal watchlist patch applied")
