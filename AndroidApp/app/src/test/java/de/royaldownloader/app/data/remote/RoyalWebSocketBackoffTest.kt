package de.royaldownloader.app.data.remote

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RoyalWebSocketBackoffTest {
    @Test
    fun `backoff doubles from one second with deterministic midpoint jitter`() {
        val delays = (1..6).map { attempt ->
            RoyalWebSocket.reconnectDelayMillis(attempt, jitter = 0.5)
        }

        assertEquals(listOf(1_000L, 2_000L, 4_000L, 8_000L, 16_000L, 30_000L), delays)
    }

    @Test
    fun `backoff base remains capped after the sixth attempt`() {
        assertEquals(30_000L, RoyalWebSocket.reconnectDelayMillis(6, jitter = 0.5))
        assertEquals(30_000L, RoyalWebSocket.reconnectDelayMillis(20, jitter = 0.5))
        assertEquals(30_000L, RoyalWebSocket.reconnectDelayMillis(Int.MAX_VALUE, jitter = 0.5))
    }

    @Test
    fun `jitter spans eighty to one hundred twenty percent`() {
        assertEquals(800L, RoyalWebSocket.reconnectDelayMillis(1, jitter = 0.0))
        assertEquals(1_000L, RoyalWebSocket.reconnectDelayMillis(1, jitter = 0.5))
        assertEquals(1_200L, RoyalWebSocket.reconnectDelayMillis(1, jitter = 1.0))
        assertEquals(24_000L, RoyalWebSocket.reconnectDelayMillis(8, jitter = 0.0))
        assertEquals(36_000L, RoyalWebSocket.reconnectDelayMillis(8, jitter = 1.0))
    }

    @Test
    fun `non-positive attempts defensively use the first delay`() {
        assertEquals(1_000L, RoyalWebSocket.reconnectDelayMillis(0, jitter = 0.5))
        assertEquals(1_000L, RoyalWebSocket.reconnectDelayMillis(-10, jitter = 0.5))
    }

    @Test
    fun `only explicit authentication policy reasons expire a session`() {
        assertTrue(RoyalWebSocket.isAuthenticationPolicyViolation("Anmeldung erforderlich"))
        assertTrue(RoyalWebSocket.isAuthenticationPolicyViolation("Sitzung abgelaufen"))
        assertTrue(RoyalWebSocket.isAuthenticationPolicyViolation("invalid auth token"))
        assertFalse(RoyalWebSocket.isAuthenticationPolicyViolation("Nachricht zu groß"))
        assertFalse(RoyalWebSocket.isAuthenticationPolicyViolation("Rate limit"))
    }
}
