package de.royaldownloader.app.data.local

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import java.security.KeyStore
import java.util.concurrent.atomic.AtomicReference
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

enum class CredentialKind {
    MOBILE_BEARER,
    LEGACY_COOKIE,
    /** A safely quarantined credential migrated from the former token-only format. */
    UNBOUND,
}

data class SessionCredential(
    val token: String,
    val kind: CredentialKind,
    /** Canonical HTTPS origin without a trailing slash, or empty only while UNBOUND. */
    val origin: String,
    val expiresAtEpochMillis: Long? = null,
) {
    fun isExpired(nowEpochMillis: Long = System.currentTimeMillis()): Boolean =
        expiresAtEpochMillis?.let { it <= nowEpochMillis } == true

    fun isUsableFor(
        requestOrigin: String,
        expectedKind: CredentialKind,
        nowEpochMillis: Long = System.currentTimeMillis(),
    ): Boolean = kind == expectedKind &&
        !isExpired(nowEpochMillis) &&
        origin.isNotBlank() &&
        origin == normalizeCredentialOrigin(requestOrigin)
}

fun interface SessionCredentialProvider {
    fun currentCredential(): SessionCredential?
}

/**
 * Stores only AES-GCM ciphertext in DataStore; the key never leaves Android Keystore.
 *
 * All DataStore and Keystore access is serialized and dispatched off the main thread. A token
 * migrated from the old token-only payload remains UNBOUND and is never sent until the repository
 * explicitly binds it to the selected server and authentication mechanism.
 */
class SecureTokenStore(private val context: Context) : SessionCredentialProvider {
    private object Keys {
        val ciphertext = stringPreferencesKey("session_ciphertext")
        val iv = stringPreferencesKey("session_iv")
    }

    private val cachedCredential = AtomicReference<SessionCredential?>(null)
    private val operationMutex = Mutex()
    @Volatile private var loaded = false

    override fun currentCredential(): SessionCredential? = cachedCredential.get()

    /** Compatibility accessor. Expired credentials are deliberately not exposed for requests. */
    fun currentToken(): String? = currentCredential()?.takeUnless { it.isExpired() }?.token

    suspend fun ensureLoaded() {
        if (loaded) return
        operationMutex.withLock {
            ensureLoadedLocked()
        }
    }

    suspend fun setCredential(
        token: String,
        kind: CredentialKind,
        origin: String,
        expiresAtEpochMillis: Long? = null,
    ) {
        val credential = validatedCredential(token, kind, origin, expiresAtEpochMillis)
        operationMutex.withLock {
            ensureLoadedLocked()
            persistCredentialLocked(credential)
            cachedCredential.set(credential)
            loaded = true
        }
    }

    /**
     * Compatibility bridge for callers compiled against the old API. The credential stays
     * quarantined until [bindUnboundCredential] is called with the verified server and API mode.
     */
    suspend fun setToken(token: String) {
        setCredential(token, CredentialKind.UNBOUND, origin = "")
    }

    suspend fun bindUnboundCredential(kind: CredentialKind, origin: String): Boolean {
        require(kind != CredentialKind.UNBOUND) { "Eine Bindung benötigt einen konkreten Credential-Typ." }
        val normalizedOrigin = requireNotNull(normalizeCredentialOrigin(origin)) {
            "Credential-Origin muss eine gültige HTTPS-Adresse sein."
        }
        return operationMutex.withLock {
            ensureLoadedLocked()
            val current = cachedCredential.get() ?: return@withLock false
            if (current.kind != CredentialKind.UNBOUND || current.isExpired()) return@withLock false
            val bound = current.copy(kind = kind, origin = normalizedOrigin)
            persistCredentialLocked(bound)
            cachedCredential.set(bound)
            true
        }
    }

    suspend fun clear() {
        operationMutex.withLock {
            withContext(Dispatchers.IO) {
                context.royalDataStore.edit(::removeStoredCredential)
            }
            cachedCredential.set(null)
            loaded = true
        }
    }

    private suspend fun ensureLoadedLocked() {
        if (loaded) return
        val loadResult = withContext(Dispatchers.IO) {
            val preferences = context.royalDataStore.data.first()
            loadCredential(preferences[Keys.ciphertext], preferences[Keys.iv])
        }
        when (loadResult) {
            LoadResult.Empty -> cachedCredential.set(null)
            LoadResult.Invalid -> {
                withContext(Dispatchers.IO) {
                    context.royalDataStore.edit(::removeStoredCredential)
                    deleteKey()
                }
                cachedCredential.set(null)
            }
            is LoadResult.Valid -> {
                cachedCredential.set(loadResult.credential)
                if (loadResult.requiresRewrite) {
                    persistCredentialLocked(loadResult.credential)
                }
            }
        }
        loaded = true
    }

    private suspend fun persistCredentialLocked(credential: SessionCredential) {
        val stored = StoredCredential(
            token = credential.token,
            kind = credential.kind,
            origin = credential.origin,
            expiresAtEpochMillis = credential.expiresAtEpochMillis,
        )
        val plaintext = credentialJson.encodeToString(StoredCredential.serializer(), stored)
        val encrypted = withContext(Dispatchers.IO) { encrypt(plaintext) }
        withContext(Dispatchers.IO) {
            context.royalDataStore.edit { preferences ->
                preferences[Keys.ciphertext] = encrypted.first
                preferences[Keys.iv] = encrypted.second
            }
        }
    }

    private fun loadCredential(ciphertext: String?, iv: String?): LoadResult {
        if (ciphertext.isNullOrBlank() && iv.isNullOrBlank()) return LoadResult.Empty
        if (ciphertext.isNullOrBlank() || iv.isNullOrBlank()) return LoadResult.Invalid
        val plaintext = decrypt(ciphertext, iv) ?: return LoadResult.Invalid
        val stored = runCatching {
            credentialJson.decodeFromString(StoredCredential.serializer(), plaintext)
        }.getOrNull()
        if (stored != null) {
            val credential = runCatching {
                validatedCredential(
                    token = stored.token,
                    kind = stored.kind,
                    origin = stored.origin,
                    expiresAtEpochMillis = stored.expiresAtEpochMillis,
                )
            }.getOrNull() ?: return LoadResult.Invalid
            return LoadResult.Valid(credential, requiresRewrite = stored.version != STORAGE_VERSION)
        }

        // Version 1 stored the raw opaque token as plaintext inside the AES-GCM envelope. A
        // structured but invalid payload must fail closed instead of being mistaken for a token.
        if (plaintext.trimStart().startsWith('{')) return LoadResult.Invalid
        val migrated = runCatching {
            validatedCredential(plaintext, CredentialKind.UNBOUND, origin = "", expiresAtEpochMillis = null)
        }.getOrNull() ?: return LoadResult.Invalid
        return LoadResult.Valid(migrated, requiresRewrite = true)
    }

    private fun encrypt(value: String): Pair<String, String> {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(encrypted, Base64.NO_WRAP) to
            Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
    }

    private fun decrypt(ciphertext: String, iv: String): String? = runCatching {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(
            Cipher.DECRYPT_MODE,
            getOrCreateKey(),
            GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
        )
        String(cipher.doFinal(Base64.decode(ciphertext, Base64.NO_WRAP)), Charsets.UTF_8)
    }.getOrNull()

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    private fun deleteKey() {
        runCatching {
            KeyStore.getInstance(KEYSTORE).apply { load(null) }.deleteEntry(KEY_ALIAS)
        }
    }

    private fun removeStoredCredential(preferences: MutablePreferences) {
        preferences.remove(Keys.ciphertext)
        preferences.remove(Keys.iv)
    }

    private sealed interface LoadResult {
        data object Empty : LoadResult
        data object Invalid : LoadResult
        data class Valid(val credential: SessionCredential, val requiresRewrite: Boolean) : LoadResult
    }

    @Serializable
    private data class StoredCredential(
        val version: Int = STORAGE_VERSION,
        val token: String,
        val kind: CredentialKind,
        val origin: String,
        @SerialName("expires_at_epoch_millis") val expiresAtEpochMillis: Long? = null,
    )

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "royal_downloader_session_v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val STORAGE_VERSION = 2
        const val MAX_TOKEN_LENGTH = 8_192
        val credentialJson = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }

        fun validatedCredential(
            token: String,
            kind: CredentialKind,
            origin: String,
            expiresAtEpochMillis: Long?,
        ): SessionCredential {
            require(
                token.isNotBlank() &&
                    token.length <= MAX_TOKEN_LENGTH &&
                    token.none { it.isISOControl() || it.isWhitespace() || it == ';' || it == ',' },
            ) {
                "Das Sitzungs-Credential ist ungültig."
            }
            require(expiresAtEpochMillis == null || expiresAtEpochMillis > 0) {
                "Der Ablaufzeitpunkt ist ungültig."
            }
            val normalizedOrigin = if (kind == CredentialKind.UNBOUND) {
                require(origin.isBlank()) { "Ein ungebundenes Credential darf keinen Origin besitzen." }
                ""
            } else {
                requireNotNull(normalizeCredentialOrigin(origin)) {
                    "Credential-Origin muss eine gültige HTTPS-Adresse sein."
                }
            }
            return SessionCredential(token, kind, normalizedOrigin, expiresAtEpochMillis)
        }
    }
}

internal fun normalizeCredentialOrigin(value: String): String? {
    val url = value.toHttpUrlOrNull() ?: return null
    if (!url.isHttps || url.username.isNotEmpty() || url.password.isNotEmpty()) return null
    return url.newBuilder()
        .encodedPath("/")
        .query(null)
        .fragment(null)
        .build()
        .toString()
        .removeSuffix("/")
}
