package de.royaldownloader.app.data.local

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class AppPreferencesTest {
    @Test
    fun `normalization trims input lowercases host and adds trailing slash`() {
        assertEquals(
            "https://royal-downloader.de/",
            AppPreferences.normalizeServerUrl("  HTTPS://ROYAL-DOWNLOADER.DE  "),
        )
    }

    @Test
    fun `normalization keeps an explicit valid HTTPS port`() {
        assertEquals(
            "https://example.org:8443/",
            AppPreferences.normalizeServerUrl("https://Example.org:8443/"),
        )
    }

    @Test
    fun `HTTP and missing schemes are rejected`() {
        assertInvalid("http://royal-downloader.de")
        assertInvalid("royal-downloader.de")
        assertInvalid("//royal-downloader.de")
    }

    @Test
    fun `credentials query and fragment are rejected`() {
        assertInvalid("https://user:secret@example.org")
        assertInvalid("https://example.org?token=secret")
        assertInvalid("https://example.org#settings")
    }

    @Test
    fun `non-root paths are rejected instead of being silently discarded`() {
        assertInvalid("https://example.org/royal")
        assertInvalid("https://example.org/royal/")
    }

    @Test
    fun `ports outside the TCP range are rejected`() {
        assertInvalid("https://example.org:0")
        assertInvalid("https://example.org:65536")
    }

    private fun assertInvalid(value: String) {
        assertThrows(IllegalArgumentException::class.java) {
            AppPreferences.normalizeServerUrl(value)
        }
    }
}
