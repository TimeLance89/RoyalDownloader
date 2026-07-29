package de.royaldownloader.app.data

import okhttp3.Headers
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.net.ConnectException
import java.net.UnknownHostException

class FailureClassifierTest {
    @Test
    fun `401 is always an expired authentication failure`() {
        val failure = classifyHttp(401)
        assertEquals(FailureKind.AUTH, failure.kind)
        assertTrue(failure.message.contains("Sitzung abgelaufen"))
        assertFalse(failure.retryable)
    }

    @Test
    fun `403 and missing mobile API remain distinct`() {
        assertEquals(FailureKind.FORBIDDEN, classifyHttp(403).kind)
        assertEquals(FailureKind.NOT_FOUND, classifyHttp(404).kind)
    }

    @Test
    fun `cloudflare 52x is classified separately`() {
        val failure = classifyHttp(522)
        assertEquals(FailureKind.CLOUDFLARE, failure.kind)
        assertTrue(failure.retryable)
    }

    @Test
    fun `retry-after is preserved for rate limits and maintenance`() {
        val rateLimit = classifyHttp(429, retryAfter = "17")
        val maintenance = classifyHttp(503, retryAfter = "60")
        assertEquals(FailureKind.RATE_LIMIT, rateLimit.kind)
        assertEquals(17L, rateLimit.retryAfterSeconds)
        assertEquals(FailureKind.MAINTENANCE, maintenance.kind)
    }

    @Test
    fun `validated internet distinguishes DNS and origin reachability`() {
        assertEquals(
            FailureKind.DNS,
            FailureClassifier.classify(UnknownHostException(), internetAvailable = true).kind,
        )
        assertEquals(
            FailureKind.SERVER_UNREACHABLE,
            FailureClassifier.classify(ConnectException(), internetAvailable = true).kind,
        )
    }

    @Test
    fun `unvalidated network is device offline`() {
        assertEquals(
            FailureKind.DEVICE_OFFLINE,
            FailureClassifier.classify(UnknownHostException(), internetAvailable = false).kind,
        )
    }

    private fun classifyHttp(code: Int, retryAfter: String? = null): RoyalFailure {
        val headers = Headers.Builder().apply {
            retryAfter?.let { add("Retry-After", it) }
        }.build()
        val response = Response.error<String>(
            "{}".toResponseBody("application/json".toMediaType()),
            okhttp3.Response.Builder()
                .request(okhttp3.Request.Builder().url("https://royal.example/api/v1/health").build())
                .protocol(okhttp3.Protocol.HTTP_1_1)
                .code(code)
                .message("test")
                .headers(headers)
                .body("{}".toResponseBody("application/json".toMediaType()))
                .build(),
        )
        return FailureClassifier.classify(HttpException(response), internetAvailable = true)
    }
}
