package de.royaldownloader.app.ui.detail

import de.royaldownloader.app.data.remote.MovieTrailer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class YoutubeTrailerTest {
    @Test
    fun `accepts valid youtube trailer`() {
        assertEquals(
            "dQw4w9WgXcQ",
            youtubeVideoId(MovieTrailer(site = "YouTube", key = "dQw4w9WgXcQ")),
        )
    }

    @Test
    fun `rejects foreign sites and unsafe keys`() {
        assertNull(youtubeVideoId(MovieTrailer(site = "Vimeo", key = "dQw4w9WgXcQ")))
        assertNull(youtubeVideoId(MovieTrailer(site = "YouTube", key = "../watch?v=1")))
        assertNull(youtubeVideoId(null))
    }
}
