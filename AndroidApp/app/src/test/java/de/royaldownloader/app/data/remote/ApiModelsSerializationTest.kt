package de.royaldownloader.app.data.remote

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiModelsSerializationTest {
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        coerceInputValues = true
        explicitNulls = false
    }

    @Test
    fun `current v1 capabilities fixture accepts numeric API version and additive fields`() {
        val capabilities = json.decodeFromString<CapabilitiesResponse>(V1_CAPABILITIES)

        assertEquals("1", capabilities.apiVersion)
        assertEquals(listOf(1), capabilities.supportedApiVersions)
        assertEquals(1, capabilities.minClientApi)
        assertTrue(capabilities.initialized)
        assertTrue(capabilities.auth.configured)
        assertTrue(capabilities.auth.required)
        assertEquals(listOf("bearer"), capabilities.auth.methods)
        assertTrue(capabilities.features.getValue("watchlist"))
        assertEquals("/api/v1/ws", capabilities.websocket.path)
        assertTrue(capabilities.websocket.authorizationHeader)
    }

    @Test
    fun `legacy compatibility capabilities fixture accepts string API version`() {
        val capabilities = json.decodeFromString<CapabilitiesResponse>(LEGACY_CAPABILITIES)

        assertEquals("legacy", capabilities.apiVersion)
        assertEquals("/ws", capabilities.websocket.path)
        assertFalse(capabilities.websocket.authorizationHeader)
        assertTrue(capabilities.features.getValue("movies"))
    }

    @Test
    fun `live legacy and v1 health fixtures use safe defaults for omitted counters`() {
        val legacy = json.decodeFromString<HealthResponse>(LEGACY_HEALTH)
        val v1 = json.decodeFromString<HealthResponse>(V1_HEALTH)

        assertTrue(legacy.initialized)
        assertEquals(0, legacy.queueActive)
        assertEquals(0, legacy.queuePending)
        assertFalse(v1.initialized)
        assertEquals(0, v1.queueActive)
        assertEquals(0, v1.queuePending)
    }

    @Test
    fun `live legacy auth fixture decodes unauthenticated setup state`() {
        val auth = json.decodeFromString<AuthStatus>(LEGACY_AUTH_STATUS)

        assertFalse(auth.configured)
        assertFalse(auth.required)
        assertTrue(auth.authenticated)
        assertTrue(auth.promptSetup)
        assertEquals(8, auth.minPasswordLength)
        assertEquals(3, auth.minUsernameLength)
    }

    @Test
    fun `v1 movie catalog and detail fixtures decode real optional metadata`() {
        val catalog = json.decodeFromString<MovieCatalogResponse>(V1_MOVIES)
        val detail = json.decodeFromString<MovieDetail>(V1_MOVIE_DETAIL)
        val metadata = json.decodeFromString<MovieMetadataResponse>(
            """{"movies":{"filmpalast:dune-part-two":{"cover_url":"https://image.tmdb.org/t/p/w500/list.jpg","backdrop_url":"https://image.tmdb.org/t/p/w1280/list.jpg","description":"Wüstenkrieg","rating":8.2}}}""",
        )

        assertEquals("top", catalog.category)
        assertEquals(2, catalog.page)
        assertTrue(catalog.hasMore)
        assertEquals(1, catalog.results.size)
        assertEquals("Dune: Part Two", catalog.results.single().title)
        assertEquals(true, catalog.results.single().inJellyfin)
        assertEquals("de", catalog.sources.single().contentLanguage)
        assertEquals(693134, detail.tmdbId)
        assertEquals(8.2, detail.rating!!, 0.0)
        assertEquals("Denis Villeneuve", detail.directors.single())
        assertEquals("Paul Atreides", detail.cast.single().character)
        assertEquals("VOE", detail.hosterLabel)
        assertEquals("YouTube", detail.trailer?.site)
        assertEquals("example", detail.trailer?.key)
        assertEquals("Dune: Part Two", detail.originalTitle)
        assertEquals(listOf("English", "Deutsch"), detail.spokenLanguages)
        assertEquals(listOf("Legendary Pictures"), detail.productionCompanies)
        assertEquals(190_000_000L, detail.budget)
        assertEquals(714_000_000L, detail.revenue)
        assertEquals(
            "https://image.tmdb.org/t/p/w500/list.jpg",
            metadata.movies.getValue("filmpalast:dune-part-two").coverUrl,
        )
        assertEquals(
            "https://image.tmdb.org/t/p/w1280/list.jpg",
            metadata.movies.getValue("filmpalast:dune-part-two").backdropUrl,
        )
        assertEquals("Wüstenkrieg", metadata.movies.getValue("filmpalast:dune-part-two").description)
    }

    @Test
    fun `legacy empty movie catalog preserves nullable category and empty lists`() {
        val catalog = json.decodeFromString<MovieCatalogResponse>(LEGACY_EMPTY_MOVIES)

        assertTrue(catalog.results.isEmpty())
        assertNull(catalog.category)
        assertEquals(1, catalog.page)
        assertFalse(catalog.hasMore)
        assertTrue(catalog.sources.isEmpty())
    }

    @Test
    fun `v1 series catalog and detail fixtures tolerate server enrichment fields`() {
        val catalog = json.decodeFromString<SeriesCatalogResponse>(V1_SERIES)
        val detail = json.decodeFromString<SeriesDetail>(V1_SERIES_DETAIL)

        assertEquals("trending", catalog.mode)
        assertEquals("Dark", catalog.items.single().title)
        assertEquals("serienstream:dark", catalog.items.single().baseSlug)
        assertEquals(2, detail.seasons.single().episodes.size)
        assertTrue(detail.seasons.single().episodes.first().downloaded)
        assertTrue(detail.seasons.single().episodes.last().unreleased)
        assertEquals(mapOf("1" to 10, "2" to 8), detail.seasonEpisodeCounts)
        assertEquals(70523, detail.tmdbId)
        assertEquals("seriesTrailer01", detail.trailer?.key)
        assertEquals("https://image.tmdb.org/t/p/w1280/dark-backdrop.jpg", detail.backdropUrl)
        assertEquals(8.7, detail.rating!!, 0.0)
        assertEquals(listOf("dark-s01e02"), detail.preselectSlugs)
    }

    @Test
    fun `older legacy series entries field remains usable through items`() {
        val catalog = json.decodeFromString<SeriesCatalogResponse>(LEGACY_SERIES_ENTRIES)

        assertTrue(catalog.results.isEmpty())
        assertEquals("The Office", catalog.items.single().title)
        assertEquals("the-office", catalog.items.single().baseSlug)
    }

    @Test
    fun `queue fixtures cover empty and populated snapshots`() {
        val empty = json.decodeFromString<QueueResponse>(EMPTY_QUEUE)
        val populated = json.decodeFromString<QueueResponse>(POPULATED_QUEUE)

        assertEquals(0, empty.queue.count)
        assertTrue(empty.queue.groups.isEmpty())
        assertEquals(2, populated.queue.count)
        assertEquals("Serien", populated.queue.groups.single().name)
        assertEquals(2, populated.queue.groups.single().items.size)
        assertFalse(populated.queue.groups.single().items.first().done)
        assertTrue(populated.queue.groups.single().items.last().done)
    }

    @Test
    fun `watchlist fixtures cover empty and derived server state`() {
        val empty = json.decodeFromString<WatchlistResponse>(EMPTY_WATCHLIST)
        val populated = json.decodeFromString<WatchlistResponse>(POPULATED_WATCHLIST)

        assertTrue(empty.watchlist.isEmpty())
        val item = populated.watchlist.single()
        assertEquals("Silo", item.title)
        assertEquals("latest_season", item.downloadMode)
        assertEquals("watched_episodes", item.cleanupMode)
        assertEquals(2, item.newCount)
        assertEquals(1, item.queuedCount)
        assertEquals(1, item.failedCount)
        assertEquals("failed", item.status)
        assertEquals(mapOf("1" to 10, "2" to 10), item.seasonEpisodeCounts)
        assertEquals(listOf("Silo", "Wool"), item.aliases)
    }

    @Test
    fun `series queue and watchlist requests encode canonical snake case fields`() {
        val series = json.encodeToJsonElement(
            SeriesLoadRequest.serializer(),
            SeriesLoadRequest(
                sampleSlug = "serienstream:dark-s01e01",
                baseSlug = "serienstream:dark",
                refreshJellyfin = true,
                deferChecks = true,
            ),
        ).jsonObject
        val queue = json.encodeToJsonElement(
            QueueSlugsRequest.serializer(),
            QueueSlugsRequest(listOf("dark-s01e01", "dark-s01e02")),
        ).jsonObject
        val watchlist = json.encodeToJsonElement(
            WatchlistModeRequest.serializer(),
            WatchlistModeRequest(
                baseSlug = "serienstream:dark",
                downloadMode = "latest_season",
                cleanupMode = "keep",
            ),
        ).jsonObject

        assertEquals("serienstream:dark-s01e01", series.getValue("sample_slug").jsonPrimitive.content)
        assertTrue(series.getValue("refresh_jellyfin").jsonPrimitive.content.toBoolean())
        assertTrue(series.getValue("defer_checks").jsonPrimitive.content.toBoolean())
        assertEquals(2, queue.getValue("slugs").jsonArray.size)
        assertEquals("serienstream:dark", watchlist.getValue("base_slug").jsonPrimitive.content)
        assertEquals("latest_season", watchlist.getValue("download_mode").jsonPrimitive.content)
        assertEquals("keep", watchlist.getValue("cleanup_mode").jsonPrimitive.content)
    }

    @Test
    fun `socket snapshot fixture decodes queue and watchlist while ignoring v1 envelope fields`() {
        val event = json.decodeFromString<SocketEvent>(V1_SOCKET_SNAPSHOT)

        assertEquals("snapshot", event.type)
        assertEquals(2, event.queue?.count)
        assertEquals("Silo", event.watchlist?.single()?.title)
    }

    @Test
    fun `documented error payload variants and empty payload decode safely`() {
        val auth = json.decodeFromString<ErrorPayload>(AUTH_ERROR)
        val legacy = json.decodeFromString<ErrorPayload>(LEGACY_ERROR)
        val empty = json.decodeFromString<ErrorPayload>("{}")

        assertEquals("Anmeldung erforderlich.", auth.detail)
        assertEquals("auth_required", auth.code)
        assertEquals("Provider vorübergehend nicht erreichbar", legacy.error)
        assertNull(empty.detail)
        assertNull(empty.error)
        assertNull(empty.code)
    }

    @Test
    fun `empty envelopes produce stable disconnected and empty collection defaults`() {
        val capabilities = json.decodeFromString<CapabilitiesResponse>("{}")
        val movies = json.decodeFromString<MovieCatalogResponse>("{}")
        val series = json.decodeFromString<SeriesCatalogResponse>("{}")
        val queue = json.decodeFromString<QueueResponse>("{}")
        val watchlist = json.decodeFromString<WatchlistResponse>("{}")
        val event = json.decodeFromString<SocketEvent>("{}")

        assertEquals("legacy", capabilities.apiVersion)
        assertFalse(capabilities.initialized)
        assertTrue(movies.results.isEmpty())
        assertTrue(series.items.isEmpty())
        assertEquals(0, queue.queue.count)
        assertTrue(watchlist.watchlist.isEmpty())
        assertEquals("unknown", event.type)
    }

    @Test
    fun `structurally invalid required fields fail instead of creating corrupt models`() {
        assertThrows(SerializationException::class.java) {
            json.decodeFromString<MovieCatalogResponse>(
                """{"results":[{"slug":"ohne-titel"}]}""",
            )
        }
        assertThrows(SerializationException::class.java) {
            json.decodeFromString<QueueResponse>(
                """{"queue":{"groups":[{"name":"Filme","items":[{"title":"Ohne Slug"}]}]}}""",
            )
        }
    }

    private companion object {
        val V1_CAPABILITIES = """
            {
              "name": "Royal Downloader",
              "api_version": 1,
              "supported_api_versions": [1],
              "minimum_api_version": 1,
              "build": null,
              "initialized": true,
              "setup_required": false,
              "authentication": {
                "configured": true,
                "required": true,
                "methods": ["bearer"],
                "legacy_methods": ["cookie", "basic"],
                "token_ttl_seconds": 2592000,
                "token_idle_timeout_seconds": 1209600
              },
              "features": {
                "movies": true,
                "series": true,
                "anime": true,
                "queue": true,
                "watchlist": true,
                "jellyfin_matching": true,
                "tmdb_metadata": true,
                "websocket": true
              },
              "websocket": {
                "path": "/api/v1/ws",
                "legacy_path": "/ws",
                "event_schema_version": 1,
                "initial_snapshot": true,
                "authentication": ["bearer", "cookie", "basic"]
              }
            }
        """.trimIndent()

        val LEGACY_CAPABILITIES = """
            {
              "api_version": "legacy",
              "initialized": true,
              "authentication": {"configured": true, "required": false, "methods": ["cookie"]},
              "features": {"movies": true, "series": true, "queue": true, "watchlist": true},
              "websocket": {"path": "/ws", "authorization_header": false}
            }
        """.trimIndent()

        val LEGACY_HEALTH = """
            {"status":"ok","initialized":true,"queue_active":0,"queue_pending":0}
        """.trimIndent()

        val V1_HEALTH = """{"status":"ok","api_version":1}"""

        val LEGACY_AUTH_STATUS = """
            {
              "configured": false,
              "required": false,
              "authenticated": true,
              "username": "",
              "source": "none",
              "setup_required": false,
              "prompt_setup": true,
              "min_password_length": 8,
              "min_username_length": 3
            }
        """.trimIndent()

        val V1_MOVIES = """
            {
              "results": [{
                "title": "Dune: Part Two",
                "slug": "filmpalast:dune-part-two",
                "url": "https://example.invalid/dune-part-two",
                "year": "2024",
                "is_movie": true,
                "provider": "filmpalast",
                "content_language": "de",
                "cover_url": "https://image.tmdb.org/t/p/w500/example.jpg",
                "in_jellyfin": true
              }],
              "category": "top",
              "page": 2,
              "has_more": true,
              "last_page_full": true,
              "sources": [{
                "key": "filmpalast",
                "label": "Filmpalast",
                "content_language": "de",
                "language_label": "Deutsch",
                "count": 1
              }]
            }
        """.trimIndent()

        val V1_MOVIE_DETAIL = """
            {
              "title": "Dune: Part Two",
              "url": "https://example.invalid/dune-part-two",
              "year": "2024",
              "runtime": "167 min",
              "cover_url": "https://image.tmdb.org/t/p/w500/example.jpg",
              "backdrop_url": "https://image.tmdb.org/t/p/original/example.jpg",
              "description": "Paul stellt sich seiner Zukunft.",
              "genres": ["Science-Fiction", "Abenteuer"],
              "provider": "filmpalast",
              "provider_label": "Filmpalast",
              "content_language": "de",
              "language_label": "Deutsch",
              "hosters": [{"name":"VOE","url":"https://voe.example/e/1","language":"de","quality":"1080p"}],
              "hoster_label": "VOE",
              "hoster_route": "VOE direkt",
              "hoster_score": 91,
              "hoster_fallback_count": 0,
              "metadata_source": "TMDB",
              "rating": 8.2,
              "vote_count": 6100,
              "tagline": "Lang lebe die Kämpfer.",
              "certification": "12",
              "certification_country": "DE",
              "status": "Released",
              "original_title": "Dune: Part Two",
              "release_date": "2024-02-27",
              "original_language": "en",
              "spoken_languages": ["English", "Deutsch"],
              "countries": ["United States of America"],
              "directors": ["Denis Villeneuve"],
              "writers": ["Denis Villeneuve", "Jon Spaihts"],
              "cast": [{"name":"Timothée Chalamet","character":"Paul Atreides","profile_url":"https://image.tmdb.org/example.jpg"}],
              "production_companies": ["Legendary Pictures"],
              "keywords": ["desert", "prophecy"],
              "collection": "Dune Collection",
              "budget": 190000000,
              "revenue": 714000000,
              "trailer": {"site":"YouTube","key":"example","name":"Offizieller Trailer","official":true},
              "tmdb_url": "https://www.themoviedb.org/movie/693134",
              "tmdb_id": 693134
            }
        """.trimIndent()

        val LEGACY_EMPTY_MOVIES = """
            {"results":[],"category":null,"page":1,"has_more":false,"sources":[]}
        """.trimIndent()

        val V1_SERIES = """
            {
              "results": [{
                "title": "Dark",
                "base_slug": "serienstream:dark",
                "sample_slug": "serienstream:dark-s01e01",
                "sample_url": "https://example.invalid/serie/dark",
                "year": "2017",
                "cover_url": "https://example.invalid/dark.jpg",
                "provider": "serienstream",
                "provider_label": "Serienstream",
                "content_language": "de",
                "language_label": "Deutsch",
                "sources": [{"key":"serienstream","label":"Serienstream","content_language":"de"}]
              }],
              "direct_series": null,
              "mode": "trending",
              "page": 1,
              "has_more": false,
              "last_page_full": false,
              "sources": [{"key":"serienstream","label":"Serienstream","content_language":"de","language_label":"Deutsch","count":1}]
            }
        """.trimIndent()

        val LEGACY_SERIES_ENTRIES = """
            {
              "entries": [{
                "title": "The Office",
                "base_slug": "the-office",
                "sample_slug": "the-office-s01e01",
                "sample_url": "https://example.invalid/serie/the-office"
              }],
              "mode": "search",
              "page": 1,
              "has_more": false,
              "sources": []
            }
        """.trimIndent()

        val V1_SERIES_DETAIL = """
            {
              "title": "Dark",
              "base_slug": "serienstream:dark",
              "url": "https://example.invalid/serie/dark",
              "cover_url": "https://example.invalid/dark.jpg",
              "backdrop_url": "https://image.tmdb.org/t/p/w1280/dark-backdrop.jpg",
              "description": "Eine Kleinstadt und ein Zeitreise-Rätsel.",
              "genres": ["Drama", "Mystery"],
              "provider": "serienstream",
              "provider_label": "Serienstream",
              "content_language": "de",
              "language_label": "Deutsch",
              "episode_count": 2,
              "watchlisted": true,
              "availability_pending": false,
              "enrichment_pending": false,
              "jellyfin_configured": true,
              "jellyfin_pending": false,
              "jellyfin_available": true,
              "watch_mode": "all",
              "cleanup_mode": "keep",
              "metadata_source": "TMDB",
              "year": "2017",
              "first_air_date": "2017-12-01",
              "runtime": "60 min",
              "original_title": "Dark",
              "rating": 8.7,
              "vote_count": 41000,
              "status": "Ended",
              "trailer": {"site":"YouTube","key":"seriesTrailer01","name":"Deutscher Trailer","official":true},
              "tmdb_id": 70523,
              "aliases": ["Dark"],
              "season_episode_counts": {"1":10,"2":8},
              "season_counts_checked_at": 1785250000.5,
              "preselect_slugs": ["dark-s01e02"],
              "seasons": [{
                "season": 1,
                "episodes": [
                  {"season":1,"episode":1,"slug":"dark-s01e01","url":"https://example.invalid/1","release_name":"Dark S01E01","queued":false,"downloaded":true,"in_jellyfin":true,"unreleased":false},
                  {"season":1,"episode":2,"slug":"dark-s01e02","url":"https://example.invalid/2","release_name":"Dark S01E02","queued":false,"downloaded":false,"in_jellyfin":false,"unreleased":true}
                ]
              }]
            }
        """.trimIndent()

        val EMPTY_QUEUE = """{"queue":{"count":0,"groups":[]}}"""

        val POPULATED_QUEUE = """
            {
              "queue": {
                "count": 2,
                "groups": [{
                  "name": "Serien",
                  "items": [
                    {"slug":"dark-s01e01","title":"Dark S01E01","hoster_label":"VOE","provider":"serienstream","content_language":"de","done":false},
                    {"slug":"dark-s01e02","title":"Dark S01E02","hoster_label":"—","provider":"serienstream","content_language":"de","done":true}
                  ]
                }]
              }
            }
        """.trimIndent()

        val EMPTY_WATCHLIST = """{"watchlist":[]}"""

        val POPULATED_WATCHLIST = """
            {
              "watchlist": [{
                "base_slug": "serienstream:silo",
                "title": "Silo",
                "sample_url": "https://example.invalid/serie/silo",
                "known_slugs": ["silo-s01e01", "silo-s01e02"],
                "download_mode": "latest_season",
                "download_mode_label": "Neueste Staffel",
                "download_mode_ready": true,
                "cleanup_mode": "watched_episodes",
                "cleanup_mode_label": "Gesehene Episoden",
                "cleanup_mode_ready": true,
                "last_error": "",
                "last_checked": 1785250100.25,
                "failed_downloads": {"silo-s01e02":{"message":"Hoster nicht erreichbar","attempts":2,"next_retry":1785250400.0}},
                "tmdb_id": 125988,
                "aliases": ["Silo", "Wool"],
                "season_episode_counts": {"1":10,"2":10},
                "season_counts_checked_at": 1785250000.5,
                "new_count": 2,
                "queued_count": 1,
                "failed_count": 1,
                "status": "failed"
              }]
            }
        """.trimIndent()

        val V1_SOCKET_SNAPSHOT = """
            {
              "type": "snapshot",
              "api_version": 1,
              "event_schema_version": 1,
              "queue": {"count":2,"groups":[]},
              "watchlist": [{"base_slug":"serienstream:silo","title":"Silo"}],
              "download": {"active":1,"pending":1}
            }
        """.trimIndent()

        val AUTH_ERROR = """{"detail":"Anmeldung erforderlich.","code":"auth_required"}"""
        val LEGACY_ERROR = """{"error":"Provider vorübergehend nicht erreichbar"}"""
    }
}
