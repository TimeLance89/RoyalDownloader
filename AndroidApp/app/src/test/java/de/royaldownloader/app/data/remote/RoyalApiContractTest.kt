package de.royaldownloader.app.data.remote

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

class RoyalApiContractTest {
    private lateinit var server: MockWebServer
    private lateinit var api: RoyalApi

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
        api = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .addConverterFactory(json.asConverterFactory(JSON_MEDIA_TYPE.toMediaType()))
            .build()
            .create(RoyalApi::class.java)
    }

    @After fun tearDown() = server.shutdown()

    @Test
    fun loginUsesVersionedContractAndDecodesBearer() = runBlocking {
        server.enqueue(jsonResponse("""{"access_token":"opaque","token_type":"Bearer","expires_in":3600}"""))

        val response = api.loginV1(LoginRequest("admin", "geheim", "Pixel", "1.0"))

        assertEquals("opaque", response.body()?.accessToken)
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/api/v1/auth/login", request.path)
        val body = json.parseToJsonElement(request.body.readUtf8()).jsonObject
        assertEquals("admin", body.getValue("username").jsonPrimitive.content)
        assertEquals("geheim", body.getValue("password").jsonPrimitive.content)
        assertEquals("Pixel", body.getValue("device_label").jsonPrimitive.content)
    }

    @Test
    fun queueAndWatchlistMutationsUseCanonicalBodies() = runBlocking {
        server.enqueue(jsonResponse("""{"queue":{"count":0,"groups":[]}}"""))
        api.addQueueV1(QueueSlugsRequest(listOf("film:1", "film:2")))
        val queueRequest = server.takeRequest()
        assertEquals("/api/v1/queue/add", queueRequest.path)
        assertEquals(
            2,
            json.parseToJsonElement(queueRequest.body.readUtf8())
                .jsonObject.getValue("slugs").toString().let { json.decodeFromString<List<String>>(it) }.size,
        )

        server.enqueue(jsonResponse("""{"watchlist":[]}"""))
        api.watchlistModeV1(WatchlistModeRequest("serie:1", "latest_season", "keep"))
        val watchlistRequest = server.takeRequest()
        assertEquals("/api/v1/watchlist/mode", watchlistRequest.path)
        val body = json.parseToJsonElement(watchlistRequest.body.readUtf8()).jsonObject
        assertEquals("serie:1", body.getValue("base_slug").jsonPrimitive.content)
        assertEquals("latest_season", body.getValue("download_mode").jsonPrimitive.content)
    }

    @Test
    fun movieMetadataUsesVersionedBatchEndpoint() = runBlocking {
        server.enqueue(jsonResponse(
            """{"movies":{"film:1":{"cover_url":"https://image.tmdb.org/t/p/w500/film.jpg"}}}""",
        ))

        val response = api.movieMetadataV1(
            MovieMetadataRequest(listOf(MovieMetadataItem("film:1", "Film", "2026"))),
        )

        assertEquals(
            "https://image.tmdb.org/t/p/w500/film.jpg",
            response.movies.getValue("film:1").coverUrl,
        )
        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/api/v1/tmdb/movies", request.path)
        val item = json.parseToJsonElement(request.body.readUtf8())
            .jsonObject.getValue("items").jsonArray.single().jsonObject
        assertEquals("film:1", item.getValue("slug").jsonPrimitive.content)
        assertEquals("Film", item.getValue("title").jsonPrimitive.content)
        assertEquals("2026", item.getValue("year").jsonPrimitive.content)
    }

    @Test
    fun unauthorizedQueueResponseRemainsMachineDetectable() {
        server.enqueue(jsonResponse("""{"detail":"Anmeldung erforderlich.","code":"auth_required"}""", 401))

        val error = assertThrows(HttpException::class.java) {
            runBlocking { api.queueV1() }
        }

        assertEquals(401, error.code())
    }

    @Test
    fun malformedRequiredMovieFieldFailsClosed() {
        server.enqueue(jsonResponse("""{"results":[{"slug":"ohne-titel"}]}"""))

        assertThrows(SerializationException::class.java) {
            runBlocking { api.moviesV1("new") }
        }
    }

    @Test
    fun idempotentReadRetriesOneTransientDisconnect() {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        server.enqueue(jsonResponse("""{"status":"ok"}"""))
        val client = OkHttpClient.Builder()
            .retryOnConnectionFailure(false)
            .addInterceptor(SafeReadRetryInterceptor())
            .build()

        client.newCall(Request.Builder().url(server.url("/health")).build()).execute().use { response ->
            assertEquals(200, response.code)
        }
        assertEquals(2, server.requestCount)
    }

    @Test
    fun mutationIsNeverRetriedAfterTransientDisconnect() {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        server.enqueue(jsonResponse("""{"ok":true}"""))
        val client = OkHttpClient.Builder()
            .retryOnConnectionFailure(false)
            .addInterceptor(SafeReadRetryInterceptor())
            .build()
        val request = Request.Builder()
            .url(server.url("/mutation"))
            .post("{}".toRequestBody(JSON_MEDIA_TYPE.toMediaType()))
            .build()

        assertThrows(java.io.IOException::class.java) {
            client.newCall(request).execute()
        }
        assertEquals(1, server.requestCount)
    }

    private fun jsonResponse(body: String, code: Int = 200) = MockResponse()
        .setResponseCode(code)
        .addHeader("Content-Type", "application/json")
        .setBody(body)

    private companion object {
        const val JSON_MEDIA_TYPE = "application/json"
        val json = Json {
            ignoreUnknownKeys = true
            coerceInputValues = true
            explicitNulls = false
        }
    }
}
