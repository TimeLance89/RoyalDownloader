package de.royaldownloader.app.data.local

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import de.royaldownloader.app.BuildConfig
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import java.io.IOException
import java.net.URI

data class AppSettings(
    val serverUrl: String = BuildConfig.DEFAULT_SERVER_URL,
)

class AppPreferences(private val context: Context) {
    private object Keys {
        val serverUrl = stringPreferencesKey("server_url")
    }

    val settings: Flow<AppSettings> = context.royalDataStore.data
        .catch { error ->
            if (error is IOException) emit(androidx.datastore.preferences.core.emptyPreferences())
            else throw error
        }
        .map { preferences ->
            AppSettings(
                serverUrl = normalizeServerUrl(
                    preferences[Keys.serverUrl] ?: BuildConfig.DEFAULT_SERVER_URL,
                ),
            )
        }

    suspend fun setServerUrl(value: String) {
        val normalized = normalizeServerUrl(value)
        context.royalDataStore.edit { it[Keys.serverUrl] = normalized }
    }

    companion object {
        fun normalizeServerUrl(value: String): String {
            val candidate = value.trim().let { if (it.endsWith('/')) it else "$it/" }
            val uri = runCatching { URI(candidate) }.getOrNull()
                ?: throw IllegalArgumentException("Die Serveradresse ist ungültig.")
            require(uri.scheme.equals("https", ignoreCase = true)) {
                "Royal Downloader benötigt eine HTTPS-Adresse."
            }
            require(!uri.host.isNullOrBlank() && uri.userInfo == null && uri.query == null && uri.fragment == null) {
                "Bitte eine vollständige Serveradresse ohne Pfad oder Zugangsdaten eingeben."
            }
            require(uri.rawPath.isNullOrEmpty() || uri.rawPath == "/") {
                "Die Serveradresse darf keinen zusätzlichen Pfad enthalten."
            }
            require(uri.port == -1 || uri.port in 1..65535) {
                "Der Serverport ist ungültig."
            }
            val port = if (uri.port == -1) "" else ":${uri.port}"
            return "https://${uri.host.lowercase()}$port/"
        }
    }
}
