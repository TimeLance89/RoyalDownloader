package de.royaldownloader.app.data.remote

import de.royaldownloader.app.data.local.CredentialKind
import de.royaldownloader.app.data.local.SessionCredential
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.EOFException
import java.io.IOException
import java.net.ProtocolException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException

class NetworkSecurityTest {
    private val origin = "https://royal-downloader.de"
    private val mobile = SessionCredential("mobile-token", CredentialKind.MOBILE_BEARER, origin)
    private val legacy = SessionCredential("legacy-token", CredentialKind.LEGACY_COOKIE, origin)

    @Test
    fun `v1 receives only bound mobile bearer and legacy receives only cookie`() {
        val v1Url = "$origin/api/v1/queue".toHttpUrl()
        val legacyUrl = "$origin/api/queue".toHttpUrl()

        val v1 = restCredentialHeaders(mobile, v1Url, v1Url.encodedPath)
        assertEquals("Bearer mobile-token", v1.authorization)
        assertNull(v1.cookie)

        val wrongV1 = restCredentialHeaders(legacy, v1Url, v1Url.encodedPath)
        assertNull(wrongV1.authorization)
        assertNull(wrongV1.cookie)

        val oldApi = restCredentialHeaders(legacy, legacyUrl, legacyUrl.encodedPath)
        assertNull(oldApi.authorization)
        assertEquals("royal_session=legacy-token", oldApi.cookie)

        val wrongLegacy = restCredentialHeaders(mobile, legacyUrl, legacyUrl.encodedPath)
        assertNull(wrongLegacy.authorization)
        assertNull(wrongLegacy.cookie)
    }

    @Test
    fun `login capabilities health websocket and foreign origins receive no rest credential`() {
        listOf(
            "/api/v1/capabilities",
            "/api/v1/auth/login",
            "/api/auth/login",
            "/api/v1/health",
            "/api/health",
        ).forEach { path ->
            val url = "$origin$path".toHttpUrl()
            val headers = restCredentialHeaders(mobile, url, path)
            assertNull(path, headers.authorization)
            assertNull(path, headers.cookie)
            assertTrue(path, headers.suppressExistingCredentials)
        }

        val queueUrl = "https://attacker.example/api/v1/queue".toHttpUrl()
        assertNull(restCredentialHeaders(mobile, queueUrl, queueUrl.encodedPath).authorization)

        val socketUrl = "$origin/api/v1/ws".toHttpUrl()
        assertNull(
            restCredentialHeaders(mobile, socketUrl, socketUrl.encodedPath, isWebSocket = true).authorization,
        )
    }

    @Test
    fun `websocket honors explicit advertised authentication method`() {
        val url = buildWebSocketRequestUrl("$origin/", "/api/v1/ws")

        assertEquals("https", url.scheme)
        assertEquals("/api/v1/ws", url.encodedPath)

        val bearer = webSocketCredentialHeaders(mobile, url, authorizationHeader = true)
        assertEquals("Bearer mobile-token", bearer.authorization)
        assertNull(bearer.cookie)

        val cookie = webSocketCredentialHeaders(legacy, url, authorizationHeader = false)
        assertNull(cookie.authorization)
        assertEquals("royal_session=legacy-token", cookie.cookie)

        assertNull(webSocketCredentialHeaders(legacy, url, authorizationHeader = true).authorization)
        assertNull(webSocketCredentialHeaders(mobile, url, authorizationHeader = false).cookie)
    }

    @Test
    fun `only exact logout routes retain a safe explicit revocation credential`() {
        val v1 = explicitLogoutCredentialHeaders(
            path = "/api/v1/auth/logout",
            authorization = "Bearer captured-mobile",
            cookie = "royal_session=must-not-cross",
        )
        assertEquals("Bearer captured-mobile", v1?.authorization)
        assertNull(v1?.cookie)

        val legacyLogout = explicitLogoutCredentialHeaders(
            path = "/api/auth/logout",
            authorization = "Bearer must-not-cross",
            cookie = "royal_session=captured-legacy",
        )
        assertNull(legacyLogout?.authorization)
        assertEquals("royal_session=captured-legacy", legacyLogout?.cookie)

        assertNull(
            explicitLogoutCredentialHeaders(
                path = "/api/v1/queue/add",
                authorization = "Bearer captured-mobile",
                cookie = null,
            ),
        )
        assertNull(
            explicitLogoutCredentialHeaders(
                path = "/api/v1/auth/logout",
                authorization = "Bearer bad token with spaces",
                cookie = null,
            )?.authorization,
        )
    }

    @Test
    fun `retry excludes DNS TLS and protocol failures`() {
        assertFalse(SafeReadRetryInterceptor.isRetryable(UnknownHostException("dns")))
        assertFalse(SafeReadRetryInterceptor.isRetryable(SSLHandshakeException("tls")))
        assertFalse(SafeReadRetryInterceptor.isRetryable(ProtocolException("protocol")))
        assertTrue(SafeReadRetryInterceptor.isRetryable(SocketTimeoutException("timeout")))
        assertTrue(
            SafeReadRetryInterceptor.isRetryable(
                IOException("unexpected end of stream", EOFException("closed")),
            ),
        )
    }
}
