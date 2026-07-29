package de.royaldownloader.app.data.remote

import de.royaldownloader.app.data.local.CredentialKind
import de.royaldownloader.app.data.local.SessionCredential
import de.royaldownloader.app.data.local.SessionCredentialProvider
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

class ArtworkNetworkTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() = server.shutdown()

    @Test
    fun `v1 proxies provider artwork and keeps tmdb direct`() {
        val configuration = ArtworkProxyConfiguration(
            baseUrl = "https://royal-downloader.de/".toHttpUrl(),
            versionedApi = true,
        )
        val provider = "http://poster.example/images/a b.webp?size=500".toHttpUrl()
        val proxied = resolveArtworkUrl(provider, configuration)

        assertEquals("https", proxied.scheme)
        assertEquals("royal-downloader.de", proxied.host)
        assertEquals("/api/v1/cover", proxied.encodedPath)
        assertEquals(provider.toString(), proxied.queryParameter("url"))

        val tmdb = "https://image.tmdb.org/t/p/w500/example.jpg".toHttpUrl()
        assertEquals(tmdb, resolveArtworkUrl(tmdb, configuration))
    }

    @Test
    fun `legacy uses legacy proxy and same-origin URLs are not wrapped`() {
        val configuration = ArtworkProxyConfiguration(
            baseUrl = "https://royal-downloader.de/".toHttpUrl(),
            versionedApi = false,
        )
        val provider = "https://cdn.example/poster.jpg".toHttpUrl()
        assertEquals(
            "/api/cover",
            resolveArtworkUrl(provider, configuration).encodedPath,
        )

        val sameOrigin = "https://royal-downloader.de/static/poster.jpg".toHttpUrl()
        assertEquals(sameOrigin, resolveArtworkUrl(sameOrigin, configuration))

        val disabled = configuration.copy(versionedApi = true, enabled = false)
        assertEquals(provider, resolveArtworkUrl(provider, disabled))
    }

    @Test
    fun `artwork source normalizes protocol relative and rejects credentials`() {
        assertEquals(
            "https://cdn.example/poster.webp",
            normalizeArtworkSource("//cdn.example/poster.webp").toString(),
        )
        assertNull(normalizeArtworkSource("https://user:password@cdn.example/poster.jpg"))
        assertNull(normalizeArtworkSource("/relative/poster.jpg"))
        assertNull(normalizeArtworkSource("javascript:alert(1)"))
    }

    @Test
    fun `image interceptor rewrites external artwork without inventing credentials`() {
        server.enqueue(MockResponse().setBody("image"))
        val origin = server.url("/").toString().removeSuffix("/")
        // Credentials intentionally use HTTPS in production. For this transport-only unit test,
        // use no credential and assert that the external request is still rewritten locally.
        val state = ArtworkProxyState(server.url("/").toString(), initialVersionedApi = true)
        val client = artworkHttpClient(SessionCredentialProvider { null }, state)

        client.newCall(
            okhttp3.Request.Builder().url("https://provider.example/poster.jpg").build(),
        ).execute().use { response -> assertEquals(200, response.code) }

        val request = server.takeRequest()
        assertEquals("/api/v1/cover", request.requestUrl?.encodedPath)
        assertEquals("https://provider.example/poster.jpg", request.requestUrl?.queryParameter("url"))
        assertNull(request.getHeader("Authorization"))
        assertNull(request.getHeader("Cookie"))
        assertEquals(server.url("/").host, origin.toHttpUrl().host)
    }

    @Test
    fun `credential selection for artwork never crosses session types`() {
        val origin = "https://royal-downloader.de"
        val v1 = "$origin/api/v1/cover?url=https%3A%2F%2Fprovider.example%2Fa.jpg".toHttpUrl()
        val legacy = "$origin/api/cover?url=https%3A%2F%2Fprovider.example%2Fa.jpg".toHttpUrl()
        val mobile = SessionCredential("mobile-token", CredentialKind.MOBILE_BEARER, origin)
        val web = SessionCredential("web-token", CredentialKind.LEGACY_COOKIE, origin)

        assertEquals("Bearer mobile-token", restCredentialHeaders(mobile, v1, v1.encodedPath).authorization)
        assertNull(restCredentialHeaders(web, v1, v1.encodedPath).cookie)
        assertEquals("royal_session=web-token", restCredentialHeaders(web, legacy, legacy.encodedPath).cookie)
        assertNull(restCredentialHeaders(mobile, legacy, legacy.encodedPath).authorization)
    }
}
