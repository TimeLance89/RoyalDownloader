package de.royaldownloader.app.data.remote

import de.royaldownloader.app.BuildConfig
import de.royaldownloader.app.data.local.CredentialKind
import de.royaldownloader.app.data.local.SecureTokenStore
import de.royaldownloader.app.data.local.SessionCredential
import de.royaldownloader.app.data.local.SessionCredentialProvider
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.io.EOFException
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.ProtocolException
import java.net.SocketException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLException

data class NetworkBundle(
    val api: RoyalApi,
    val client: OkHttpClient,
)

class NetworkClientFactory(
    private val tokenStore: SecureTokenStore,
    val json: Json,
) {
    fun create(baseUrl: String): NetworkBundle {
        val configuredOrigin = baseUrl.toHttpUrl().canonicalOrigin()
        val client = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(90, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .callTimeout(120, TimeUnit.SECONDS)
            .pingInterval(25, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .followRedirects(false)
            .followSslRedirects(false)
            .addInterceptor(AppAuthenticationInterceptor(tokenStore, configuredOrigin))
            .addInterceptor(SafeReadRetryInterceptor())
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()

        return NetworkBundle(retrofit.create(RoyalApi::class.java), client)
    }
}

/** A single transparent retry is limited to idempotent reads and transient transport failures. */
internal class SafeReadRetryInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        if (request.method != "GET" && request.method != "HEAD") {
            return chain.proceed(request)
        }
        return try {
            chain.proceed(request)
        } catch (first: IOException) {
            if (chain.call().isCanceled() || !isRetryable(first)) throw first
            chain.proceed(request)
        }
    }

    internal companion object {
        fun isRetryable(error: IOException): Boolean {
            val causes = generateSequence<Throwable>(error) { it.cause }.take(8).toList()
            if (causes.any { it is SSLException || it is UnknownHostException || it is ProtocolException }) {
                return false
            }
            return causes.any {
                it is SocketTimeoutException ||
                    it is ConnectException ||
                    it is NoRouteToHostException ||
                    it is SocketException ||
                    it is EOFException
            }
        }
    }
}

internal class AppAuthenticationInterceptor(
    private val credentialProvider: SessionCredentialProvider,
    private val configuredOrigin: String,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val builder = original.newBuilder()
            .header("Accept", "application/json")
            .header("User-Agent", "RoyalDownloader-Android/${BuildConfig.VERSION_NAME}")
            .header("X-Royal-App-Version", BuildConfig.VERSION_NAME)

        val requestOriginMatches = original.url.canonicalOrigin() == configuredOrigin
        val isWebSocket = original.header("Upgrade").equals("websocket", ignoreCase = true)
        val headers = when {
            !requestOriginMatches -> CredentialHeaders(suppressExistingCredentials = true)
            isWebSocket -> CredentialHeaders()
            else -> explicitLogoutCredentialHeaders(
                path = original.url.encodedPath,
                authorization = original.header("Authorization"),
                cookie = original.header("Cookie"),
            ) ?: restCredentialHeaders(
                credential = credentialProvider.currentCredential(),
                requestUrl = original.url,
                path = original.url.encodedPath,
            )
        }
        if (headers.suppressExistingCredentials) {
            builder.removeHeader("Authorization")
            builder.removeHeader("Cookie")
        }
        headers.authorization?.let { builder.header("Authorization", it) }
        headers.cookie?.let { builder.header("Cookie", it) }
        return chain.proceed(builder.build())
    }
}

internal data class CredentialHeaders(
    val authorization: String? = null,
    val cookie: String? = null,
    val suppressExistingCredentials: Boolean = false,
)

internal fun restCredentialHeaders(
    credential: SessionCredential?,
    requestUrl: HttpUrl,
    path: String,
    isWebSocket: Boolean = false,
    nowEpochMillis: Long = System.currentTimeMillis(),
): CredentialHeaders {
    if (isWebSocket) return CredentialHeaders()
    if (path in PUBLIC_UNAUTHENTICATED_PATHS) {
        return CredentialHeaders(suppressExistingCredentials = true)
    }
    val expectedKind = when {
        path.startsWith("/api/v1/") -> CredentialKind.MOBILE_BEARER
        path.startsWith("/api/") -> CredentialKind.LEGACY_COOKIE
        else -> return CredentialHeaders(suppressExistingCredentials = true)
    }
    if (credential == null || !credential.isUsableFor(requestUrl.canonicalOrigin(), expectedKind, nowEpochMillis)) {
        return CredentialHeaders(suppressExistingCredentials = true)
    }
    return when (expectedKind) {
        CredentialKind.MOBILE_BEARER -> CredentialHeaders(
            authorization = "Bearer ${credential.token}",
            suppressExistingCredentials = true,
        )
        CredentialKind.LEGACY_COOKIE -> CredentialHeaders(
            cookie = "royal_session=${credential.token}",
            suppressExistingCredentials = true,
        )
        CredentialKind.UNBOUND -> CredentialHeaders(suppressExistingCredentials = true)
    }
}

/**
 * Allows a captured credential only for the exact logout endpoint after local state was cleared.
 * Redirects are disabled on the client and the interceptor additionally enforces its configured
 * origin before this function is reached.
 */
internal fun explicitLogoutCredentialHeaders(
    path: String,
    authorization: String?,
    cookie: String?,
): CredentialHeaders? = when (path) {
    "/api/v1/auth/logout" -> {
        val bearer = authorization?.takeIf(::isSafeBearerHeader)
        CredentialHeaders(authorization = bearer, suppressExistingCredentials = true)
    }
    "/api/auth/logout" -> {
        val sessionCookie = cookie?.takeIf(::isSafeRoyalSessionCookie)
        CredentialHeaders(cookie = sessionCookie, suppressExistingCredentials = true)
    }
    else -> null
}

internal fun webSocketCredentialHeaders(
    credential: SessionCredential?,
    requestUrl: HttpUrl,
    authorizationHeader: Boolean,
    nowEpochMillis: Long = System.currentTimeMillis(),
): CredentialHeaders {
    val expectedKind = if (authorizationHeader) CredentialKind.MOBILE_BEARER else CredentialKind.LEGACY_COOKIE
    if (credential == null || !credential.isUsableFor(requestUrl.canonicalOrigin(), expectedKind, nowEpochMillis)) {
        return CredentialHeaders(suppressExistingCredentials = true)
    }
    return if (authorizationHeader) {
        CredentialHeaders(authorization = "Bearer ${credential.token}", suppressExistingCredentials = true)
    } else {
        CredentialHeaders(cookie = "royal_session=${credential.token}", suppressExistingCredentials = true)
    }
}

internal fun HttpUrl.canonicalOrigin(): String = newBuilder()
    .encodedPath("/")
    .query(null)
    .fragment(null)
    .build()
    .toString()
    .removeSuffix("/")

private val PUBLIC_UNAUTHENTICATED_PATHS = setOf(
    "/api/v1/capabilities",
    "/api/v1/auth/login",
    "/api/auth/login",
    "/api/v1/health",
    "/api/health",
)

private fun isSafeBearerHeader(value: String): Boolean {
    if (!value.startsWith("Bearer ", ignoreCase = false)) return false
    val token = value.removePrefix("Bearer ")
    return token.isNotBlank() && token.length <= 8_192 && token.none { it.isISOControl() || it.isWhitespace() }
}

private fun isSafeRoyalSessionCookie(value: String): Boolean {
    if (!value.startsWith("royal_session=", ignoreCase = false)) return false
    val token = value.removePrefix("royal_session=")
    return token.isNotBlank() &&
        token.length <= 8_192 &&
        token.none { it.isISOControl() || it.isWhitespace() || it == ';' || it == ',' }
}
