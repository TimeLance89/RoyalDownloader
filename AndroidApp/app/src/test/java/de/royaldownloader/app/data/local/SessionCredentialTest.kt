package de.royaldownloader.app.data.local

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionCredentialTest {
    @Test
    fun `origin normalization keeps only canonical HTTPS origin`() {
        assertEquals(
            "https://example.org",
            normalizeCredentialOrigin("https://EXAMPLE.org:443/a/path?query=ignored#fragment"),
        )
        assertEquals(
            "https://example.org:8443",
            normalizeCredentialOrigin("https://example.org:8443/"),
        )
        assertNull(normalizeCredentialOrigin("http://example.org"))
        assertNull(normalizeCredentialOrigin("https://user:secret@example.org"))
    }

    @Test
    fun `credential requires matching kind origin and non-expired lifetime`() {
        val credential = SessionCredential(
            token = "opaque",
            kind = CredentialKind.MOBILE_BEARER,
            origin = "https://royal-downloader.de",
            expiresAtEpochMillis = 2_000,
        )

        assertTrue(
            credential.isUsableFor(
                "https://royal-downloader.de/",
                CredentialKind.MOBILE_BEARER,
                nowEpochMillis = 1_999,
            ),
        )
        assertFalse(
            credential.isUsableFor(
                "https://other.example/",
                CredentialKind.MOBILE_BEARER,
                nowEpochMillis = 1_999,
            ),
        )
        assertFalse(
            credential.isUsableFor(
                "https://royal-downloader.de/",
                CredentialKind.LEGACY_COOKIE,
                nowEpochMillis = 1_999,
            ),
        )
        assertFalse(
            credential.isUsableFor(
                "https://royal-downloader.de/",
                CredentialKind.MOBILE_BEARER,
                nowEpochMillis = 2_000,
            ),
        )
    }

    @Test
    fun `unbound migrated credential cannot be used for any request`() {
        val credential = SessionCredential("legacy-opaque", CredentialKind.UNBOUND, origin = "")

        assertFalse(
            credential.isUsableFor(
                "https://royal-downloader.de",
                CredentialKind.MOBILE_BEARER,
            ),
        )
        assertFalse(
            credential.isUsableFor(
                "https://royal-downloader.de",
                CredentialKind.LEGACY_COOKIE,
            ),
        )
    }
}
