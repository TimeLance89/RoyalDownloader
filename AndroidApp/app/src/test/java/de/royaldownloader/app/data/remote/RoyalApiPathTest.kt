package de.royaldownloader.app.data.remote

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

class RoyalApiPathTest {
    private lateinit var server: MockWebServer
    private lateinit var api: RoyalApi

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        api = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .addConverterFactory(
                json.asConverterFactory("application/json".toMediaType()),
            )
            .build()
            .create(RoyalApi::class.java)
    }

    @After fun tearDown() = server.shutdown()

    @Test
    fun movieProviderUrlIsKeptInsidePath() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"title":"Test"}""").addHeader("Content-Type", "application/json"))

        api.movieLegacy("https://provider.example/movie/royal?lang=de")

        val requestPath = server.takeRequest().path.orEmpty()
        assertTrue(requestPath, requestPath.startsWith("/api/movie/"))
        assertTrue(
            requestPath,
            requestPath.contains("https:%2F%2Fprovider.example%2Fmovie%2Froyal%3Flang=de"),
        )
        assertFalse(requestPath, requestPath.contains("?lang=de"))
    }

    private companion object {
        val json = Json { ignoreUnknownKeys = true }
    }
}
