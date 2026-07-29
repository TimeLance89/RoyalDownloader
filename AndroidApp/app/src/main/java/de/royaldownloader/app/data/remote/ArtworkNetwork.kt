package de.royaldownloader.app.data.remote

import coil.map.Mapper
import coil.request.Options
import de.royaldownloader.app.BuildConfig
import de.royaldownloader.app.data.local.SessionCredentialProvider
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import java.util.concurrent.TimeUnit

/**
 * Current server endpoint used by Coil. Provider artwork is fetched through RoyalDownloader so
 * hotlink protection, provider cookies, HTTP-only source URLs, and provider-specific referers stay
 * server-side. The configuration contains no credential and is safe to use as Coil's cache key.
 */
class ArtworkProxyState(
    initialServerUrl: String,
    initialVersionedApi: Boolean = false,
) {
    @Volatile
    private var configuration = ArtworkProxyConfiguration(
        baseUrl = initialServerUrl.toHttpUrl(),
        versionedApi = initialVersionedApi,
        enabled = true,
    )

    fun update(serverUrl: String, versionedApi: Boolean, enabled: Boolean = true) {
        configuration = ArtworkProxyConfiguration(serverUrl.toHttpUrl(), versionedApi, enabled)
    }

    internal fun resolve(source: HttpUrl): HttpUrl = resolveArtworkUrl(source, configuration)
}

internal data class ArtworkProxyConfiguration(
    val baseUrl: HttpUrl,
    val versionedApi: Boolean,
    val enabled: Boolean = true,
)

internal class ArtworkStringMapper : Mapper<String, HttpUrl> {
    override fun map(data: String, options: Options): HttpUrl? = normalizeArtworkSource(data)
}

internal fun normalizeArtworkSource(value: String): HttpUrl? {
    val candidate = value.trim().let { if (it.startsWith("//")) "https:$it" else it }
    val parsed = candidate.toHttpUrlOrNull() ?: return null
    if (
        parsed.scheme !in setOf("http", "https") ||
        parsed.username.isNotEmpty() ||
        parsed.password.isNotEmpty()
    ) {
        return null
    }
    return parsed
}

internal fun resolveArtworkUrl(
    source: HttpUrl,
    configuration: ArtworkProxyConfiguration,
): HttpUrl {
    val serverOrigin = configuration.baseUrl.canonicalOrigin()
    if (source.canonicalOrigin() == serverOrigin) return source
    if (!configuration.enabled) return source

    // TMDB is deliberately loaded directly, matching the web client. Its image CDN supports
    // native clients without provider cookies or referer spoofing.
    if (source.scheme == "https" && source.host.equals("image.tmdb.org", ignoreCase = true)) {
        return source
    }

    return configuration.baseUrl.newBuilder()
        .encodedPath(if (configuration.versionedApi) "/api/v1/cover" else "/api/cover")
        .query(null)
        .fragment(null)
        .addQueryParameter("url", source.toString())
        .build()
}

/** Adds a credential only after the final request URL has been resolved to the selected server. */
internal class ArtworkProxyInterceptor(
    private val credentialProvider: SessionCredentialProvider,
    private val proxyState: ArtworkProxyState,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val target = proxyState.resolve(original.url)
        val builder = original.newBuilder()
            .url(target)
            .removeHeader("Authorization")
            .removeHeader("Cookie")
            .header("Accept", "image/*")
            .header("User-Agent", "RoyalDownloader-Android/${BuildConfig.VERSION_NAME}")

        val credentialHeaders = restCredentialHeaders(
            credential = credentialProvider.currentCredential(),
            requestUrl = target,
            path = target.encodedPath,
        )
        credentialHeaders.authorization?.let { builder.header("Authorization", it) }
        credentialHeaders.cookie?.let { builder.header("Cookie", it) }
        return chain.proceed(builder.build())
    }
}

internal fun artworkHttpClient(
    credentialProvider: SessionCredentialProvider,
    proxyState: ArtworkProxyState,
): OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(15, TimeUnit.SECONDS)
    .readTimeout(30, TimeUnit.SECONDS)
    .callTimeout(45, TimeUnit.SECONDS)
    .retryOnConnectionFailure(false)
    // The RoyalDownloader cover endpoint returns image bytes directly. Disabling redirects keeps
    // credentials pinned to that exact origin even if a proxy is misconfigured.
    .followRedirects(false)
    .followSslRedirects(false)
    .addInterceptor(ArtworkProxyInterceptor(credentialProvider, proxyState))
    .addInterceptor(SafeReadRetryInterceptor())
    .build()
