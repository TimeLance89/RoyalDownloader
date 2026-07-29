package de.royaldownloader.app.data

import de.royaldownloader.app.BuildConfig
import de.royaldownloader.app.data.local.AppPreferences
import de.royaldownloader.app.data.local.CredentialKind
import de.royaldownloader.app.data.local.SecureTokenStore
import de.royaldownloader.app.data.remote.*
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.util.concurrent.atomic.AtomicLong

enum class ApiMode { V1, LEGACY }

data class ConnectionInfo(
    val serverUrl: String,
    val apiMode: ApiMode,
    val apiVersion: String,
    val health: HealthResponse,
    val auth: AuthStatus,
    val capabilities: CapabilitiesResponse,
)

sealed interface ConnectionState {
    data object Checking : ConnectionState
    data class Connected(val info: ConnectionInfo) : ConnectionState
    data class LoginRequired(
        val serverUrl: String,
        val auth: AuthStatus,
        val reason: LoginReason = LoginReason.REQUIRED,
    ) : ConnectionState
    data class SetupRequired(val serverUrl: String) : ConnectionState
    data class AccountSetupRequired(val serverUrl: String) : ConnectionState
    data class Maintenance(val serverUrl: String, val status: String) : ConnectionState
    data class Incompatible(
        val serverUrl: String,
        val serverApiVersion: String,
        val supportedApiVersions: List<Int>,
        val details: String = "",
    ) : ConnectionState
    data class Offline(val serverUrl: String, val failure: RoyalFailure) : ConnectionState
}

enum class LoginReason { REQUIRED, EXPIRED }

enum class FailureKind {
    DEVICE_OFFLINE,
    DNS,
    SERVER_UNREACHABLE,
    TIMEOUT,
    TLS,
    CLOUDFLARE,
    AUTH,
    FORBIDDEN,
    NOT_FOUND,
    CONFLICT,
    RATE_LIMIT,
    MAINTENANCE,
    SERVER,
    INVALID_RESPONSE,
    UNKNOWN,
}

class RoyalFailure(
    val kind: FailureKind,
    override val message: String,
    val statusCode: Int? = null,
    val retryable: Boolean = false,
    val retryAfterSeconds: Long? = null,
    cause: Throwable? = null,
) : Exception(message, cause)

data class LiveProgress(val label: String, val message: String, val percent: Double?)
data class LiveResult(val label: String, val message: String, val successful: Boolean)

data class HomeSnapshot(
    val queue: QueueSnapshot,
    val watchlist: List<WatchlistItem>,
    val cinemaMovies: List<MovieSummary>,
    val newMovies: List<MovieSummary>,
    val topMovies: List<MovieSummary>,
    val series: List<SeriesSummary>,
    val anime: List<AnimeSummary>,
    val animeDisabledReason: String = "",
)

class RoyalRepository(
    private val appScope: CoroutineScope,
    private val preferences: AppPreferences,
    private val tokenStore: SecureTokenStore,
    private val connectivity: ConnectivityObserver,
    private val json: Json,
    private val artworkProxyState: ArtworkProxyState,
) {
    private val factory = NetworkClientFactory(tokenStore, json)
    private val configurationMutex = Mutex()
    @Volatile private var bundle = factory.create(BuildConfig.DEFAULT_SERVER_URL)
    @Volatile private var apiMode = ApiMode.LEGACY
    @Volatile private var activeServerUrl = BuildConfig.DEFAULT_SERVER_URL
    private var lastAuth = AuthStatus()
    private var activeFeatures: Map<String, Boolean> = emptyMap()
    private var activeCapabilities: CapabilitiesResponse? = null
    @Volatile private var appInForeground = true
    @Volatile private var configurationGeneration = 0

    private val webSocket = RoyalWebSocket(
        scope = appScope,
        json = json,
        tokenStore = tokenStore,
        networkAvailable = connectivity.connected,
    )

    private val _connection = MutableStateFlow<ConnectionState>(ConnectionState.Checking)
    val connection: StateFlow<ConnectionState> = _connection.asStateFlow()
    val networkAvailable: StateFlow<Boolean> = connectivity.connected
    val socketStatus: StateFlow<SocketStatus> = webSocket.status
    val socketEvents: SharedFlow<SocketEvent> = webSocket.events

    private val _queue = MutableStateFlow(QueueSnapshot())
    private val queueRevision = AtomicLong(0)
    val queue: StateFlow<QueueSnapshot> = _queue.asStateFlow()
    private val _watchlist = MutableStateFlow<List<WatchlistItem>>(emptyList())
    private val watchlistRevision = AtomicLong(0)
    val watchlist: StateFlow<List<WatchlistItem>> = _watchlist.asStateFlow()
    private val _progress = MutableStateFlow<Map<String, LiveProgress>>(emptyMap())
    val progress: StateFlow<Map<String, LiveProgress>> = _progress.asStateFlow()
    private val _recentResults = MutableStateFlow<List<LiveResult>>(emptyList())
    val recentResults: StateFlow<List<LiveResult>> = _recentResults.asStateFlow()

    init {
        appScope.launch {
            webSocket.events.collect { event ->
                event.queue?.let(::publishQueue)
                event.watchlist?.let(::publishWatchlist)
                when (event.type) {
                    "progress" -> if (event.label.isNotBlank()) {
                        _progress.update {
                            it + (event.label to LiveProgress(event.label, event.msg, event.pct))
                        }
                    }
                    "job_done" -> {
                        _progress.update { it - event.label }
                        _recentResults.update { previous ->
                            listOf(
                                LiveResult(
                                    label = event.label.ifBlank { event.slug },
                                    message = event.msg,
                                    successful = event.ok == true,
                                ),
                            ).plus(previous).take(12)
                        }
                        if (event.slug.isNotBlank()) removeQueueItemLocally(event.slug)
                        appScope.launch { runSuspendCatching { refreshQueue() } }
                    }
                    "queue_done" -> {
                        _progress.value = emptyMap()
                        publishQueue(QueueSnapshot())
                        appScope.launch { runSuspendCatching { refreshQueue() } }
                    }
                }
            }
        }
        appScope.launch {
            webSocket.status.collect { status ->
                if (status is SocketStatus.Reconnecting || status == SocketStatus.Forbidden ||
                    status is SocketStatus.PolicyViolation
                ) {
                    _progress.value = emptyMap()
                }
                if (status == SocketStatus.Connected) {
                    appScope.launch {
                        runSuspendCatching { refreshQueue() }
                        runSuspendCatching { refreshWatchlist() }
                    }
                }
                if (status == SocketStatus.Unauthorized && lastAuth.required) {
                    tokenStore.clear()
                    _connection.value = ConnectionState.LoginRequired(
                        activeServerUrl,
                        lastAuth.copy(authenticated = false),
                        LoginReason.EXPIRED,
                    )
                }
            }
        }
    }

    suspend fun bootstrap(): ConnectionState {
        _connection.value = ConnectionState.Checking
        var hadStoredSession = false
        return try {
            ensureConfigured()
            val bootstrapGeneration = configurationGeneration
            tokenStore.ensureLoaded()
            hadStoredSession = tokenStore.currentCredential() != null
            val (capabilities, probedLegacyAuth) = discoverCapabilities()
            val credentialBound = tokenStore.bindUnboundCredential(
                kind = if (apiMode == ApiMode.V1) CredentialKind.MOBILE_BEARER else CredentialKind.LEGACY_COOKIE,
                origin = activeServerUrl,
            )
            activeFeatures = capabilities.features
            artworkProxyState.update(
                activeServerUrl,
                versionedApi = apiMode == ApiMode.V1,
                enabled = apiMode == ApiMode.LEGACY || capabilities.features["cover_proxy"] == true,
            )
            val health = if (apiMode == ApiMode.V1) bundle.api.healthV1() else bundle.api.healthLegacy()
            val auth = probedLegacyAuth.takeUnless { credentialBound }
                ?: if (apiMode == ApiMode.V1) bundle.api.authStatusV1() else bundle.api.authStatusLegacy()
            if (bootstrapGeneration != configurationGeneration) {
                throw CancellationException("Server während Verbindungsprüfung gewechselt")
            }
            lastAuth = auth
            val result = when {
                apiMode == ApiMode.V1 && incompatibilityDetails(capabilities) != null -> ConnectionState.Incompatible(
                    activeServerUrl,
                    capabilities.apiVersion,
                    capabilities.supportedApiVersions,
                    incompatibilityDetails(capabilities).orEmpty(),
                )
                auth.setupRequired || !capabilities.initialized ||
                    (apiMode == ApiMode.LEGACY && !health.initialized) -> ConnectionState.SetupRequired(activeServerUrl)
                !health.status.equals("ok", ignoreCase = true) ->
                    ConnectionState.Maintenance(activeServerUrl, health.status)
                auth.promptSetup || (!auth.configured && !auth.required) ->
                    ConnectionState.AccountSetupRequired(activeServerUrl)
                auth.required && !auth.authenticated -> ConnectionState.LoginRequired(
                    activeServerUrl,
                    auth,
                    if (hadStoredSession) LoginReason.EXPIRED else LoginReason.REQUIRED,
                )
                else -> {
                    val info = ConnectionInfo(
                        serverUrl = activeServerUrl,
                        apiMode = apiMode,
                        apiVersion = capabilities.apiVersion,
                        health = health,
                        auth = auth,
                        capabilities = capabilities,
                    )
                    val refreshFailures = listOf(
                        runSuspendCatching { refreshQueue() }.exceptionOrNull(),
                        runSuspendCatching { refreshWatchlist() }.exceptionOrNull(),
                    ).filterNotNull()
                    if (refreshFailures.any { it is RoyalFailure && it.kind == FailureKind.AUTH }) {
                        ConnectionState.LoginRequired(
                            activeServerUrl,
                            auth.copy(authenticated = false),
                            LoginReason.EXPIRED,
                        )
                    } else {
                        activeCapabilities = capabilities
                        startLiveUpdates(capabilities)
                        ConnectionState.Connected(info)
                    }
                }
            }
            if (bootstrapGeneration != configurationGeneration) {
                throw CancellationException("Server während Verbindungsprüfung gewechselt")
            }
            _connection.value = result
            result
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            webSocket.stop()
            val failure = mapFailure(error)
            val failedState = if (failure.kind == FailureKind.AUTH) {
                ConnectionState.LoginRequired(
                    activeServerUrl,
                    lastAuth.copy(required = true, authenticated = false),
                    if (hadStoredSession) LoginReason.EXPIRED else LoginReason.REQUIRED,
                )
            } else {
                ConnectionState.Offline(activeServerUrl, failure)
            }
            failedState.also { _connection.value = it }
        }
    }

    suspend fun login(username: String, password: String, deviceName: String) {
        ensureConfigured()
        val request = LoginRequest(
            username = username.trim(),
            password = password,
            deviceName = deviceName.take(80),
            appVersion = BuildConfig.VERSION_NAME,
        )
        try {
            if (apiMode == ApiMode.V1) {
                val response = bundle.api.loginV1(request)
                if (!response.isSuccessful) throw HttpException(response)
                val body = response.body() ?: throw SerializationException("Login-Antwort fehlt")
                if (!body.tokenType.equals("bearer", ignoreCase = true)) {
                    throw SerializationException("token_type wird nicht unterstützt")
                }
                val expiresAt = body.expiresIn.takeIf { it > 0 }?.let { seconds ->
                    val now = System.currentTimeMillis()
                    val millis = seconds.coerceAtMost(MAX_TOKEN_TTL_SECONDS) * 1_000L
                    now + millis
                }
                tokenStore.setCredential(
                    token = body.accessToken,
                    kind = CredentialKind.MOBILE_BEARER,
                    origin = activeServerUrl,
                    expiresAtEpochMillis = expiresAt,
                )
            } else {
                val response = bundle.api.loginLegacy(request)
                if (!response.isSuccessful) throw HttpException(response)
                val token = response.headers().values("Set-Cookie")
                    .firstNotNullOfOrNull { header ->
                        header.split(';').firstOrNull { it.trim().startsWith("royal_session=") }
                            ?.substringAfter('=')
                    }
                    ?: throw SerializationException("Sitzungscookie fehlt")
                tokenStore.setCredential(
                    token = token,
                    kind = CredentialKind.LEGACY_COOKIE,
                    origin = activeServerUrl,
                )
            }
            bootstrap()
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            if (error is HttpException && error.code() == 401) {
                throw RoyalFailure(
                    FailureKind.AUTH,
                    parseErrorMessage(error) ?: "Benutzername oder Passwort ist falsch.",
                    401,
                )
            }
            throw mapFailure(error)
        }
    }

    suspend fun logout() {
        val token = tokenStore.currentToken()
        val mode = apiMode
        tokenStore.clear()
        webSocket.stop()
        _connection.value = ConnectionState.LoginRequired(
            activeServerUrl,
            lastAuth.copy(authenticated = false),
            LoginReason.REQUIRED,
        )
        try {
            if (!token.isNullOrBlank()) {
                withTimeout(8_000) {
                    if (mode == ApiMode.V1) {
                        bundle.api.logoutV1("Bearer $token")
                    } else {
                        bundle.api.logoutLegacy("royal_session=$token")
                    }
                }
            }
        } catch (error: CancellationException) {
            throw error
        } catch (_: Throwable) {
            // Lokales Abmelden hat Vorrang; der Server lässt das Token zusätzlich auslaufen.
        }
    }

    suspend fun changeServerUrl(value: String) {
        val normalized = try {
            AppPreferences.normalizeServerUrl(value)
        } catch (error: IllegalArgumentException) {
            throw RoyalFailure(
                FailureKind.UNKNOWN,
                error.message ?: "Die Serveradresse ist ungültig.",
                cause = error,
            )
        }
        tokenStore.clear()
        preferences.setServerUrl(normalized)
        configure(normalized)
        appScope.launch { bootstrap() }
    }

    suspend fun refreshHome(): HomeSnapshot {
        val queueAtStart = queueRevision.get()
        val watchlistAtStart = watchlistRevision.get()
        return request {
        coroutineScope {
            val queueTask = async { runSuspendCatching { fetchQueue() } }
            val watchTask = async { runSuspendCatching { fetchWatchlist() } }
            val newTask = async { runSuspendCatching { movies("new").results } }
            val topTask = async { runSuspendCatching { movies("top").results } }
            val seriesTask = async { runSuspendCatching { series("trending").items } }
            val animeTask = async { runSuspendCatching { anime("latest") } }
            val queueResult = queueTask.await()
            val watchResult = watchTask.await()
            val newResult = newTask.await()
            val topResult = topTask.await()
            val seriesResult = seriesTask.await()
            val animeResult = animeTask.await()
            val failures = listOf(
                queueResult.exceptionOrNull(),
                watchResult.exceptionOrNull(),
                newResult.exceptionOrNull(),
                topResult.exceptionOrNull(),
                seriesResult.exceptionOrNull(),
                animeResult.exceptionOrNull(),
            ).filterNotNull()
            if (failures.size == 6) throw failures.first()
            val q = queueResult.getOrDefault(QueueSnapshot())
            val w = watchResult.getOrDefault(emptyList())
            val a = animeResult.getOrDefault(AnimeCatalogResponse())
            val newMovies = newResult.getOrDefault(emptyList())
            val topMovies = topResult.getOrDefault(emptyList())
            HomeSnapshot(
                queue = q,
                watchlist = w,
                cinemaMovies = (newMovies + topMovies)
                    .distinctBy { it.slug }
                    .filter { it.inCinema },
                newMovies = newMovies,
                topMovies = topMovies,
                series = seriesResult.getOrDefault(emptyList()),
                anime = a.results,
                animeDisabledReason = a.disabledReason,
            )
        }
    }.also { snapshot ->
        applyQueueIfUnchanged(snapshot.queue, queueAtStart)
        applyWatchlistIfUnchanged(snapshot.watchlist, watchlistAtStart)
    }
    }

    suspend fun movies(mode: String, query: String = "", page: Int = 1): MovieCatalogResponse = request {
        requireFeature("movies", "Filme")
        val catalog = if (apiMode == ApiMode.V1) bundle.api.moviesV1(mode, query, page = page)
        else bundle.api.moviesLegacy(mode, query, page = page)
        enrichMovieArtwork(catalog)
    }

    suspend fun movieDetail(slug: String): MovieDetail = request {
        requireFeature("movies", "Filme")
        if (apiMode == ApiMode.V1) bundle.api.movieV1(slug) else bundle.api.movieLegacy(slug)
    }

    private suspend fun enrichMovieArtwork(catalog: MovieCatalogResponse): MovieCatalogResponse {
        if (catalog.results.isEmpty()) return catalog
        val body = MovieMetadataRequest(
            catalog.results.map { MovieMetadataItem(it.slug, it.title, it.year) },
        )
        val metadata = runSuspendCatching {
            if (apiMode == ApiMode.V1) bundle.api.movieMetadataV1(body)
            else bundle.api.movieMetadataLegacy(body)
        }.getOrNull()?.movies.orEmpty()
        if (metadata.isEmpty()) return catalog
        return catalog.copy(
            results = catalog.results.map { movie ->
                val enrichment = metadata[movie.slug] ?: return@map movie
                movie.copy(
                    coverUrl = enrichment.coverUrl.ifBlank { movie.coverUrl },
                    backdropUrl = enrichment.backdropUrl.ifBlank { movie.backdropUrl },
                    description = enrichment.description.ifBlank { movie.description },
                    rating = enrichment.rating ?: movie.rating,
                    releaseDate = enrichment.releaseDate.ifBlank { movie.releaseDate },
                    inCinema = enrichment.inCinema,
                )
            },
        )
    }

    suspend fun series(mode: String, query: String = "", page: Int = 1): SeriesCatalogResponse = request {
        requireFeature("series", "Serien")
        if (apiMode == ApiMode.V1) bundle.api.seriesV1(mode, query, page = page)
        else bundle.api.seriesLegacy(mode, query, page = page)
    }

    suspend fun seriesDetail(request: SeriesLoadRequest): SeriesDetail = request {
        requireFeature("series", "Serien")
        if (apiMode == ApiMode.V1) bundle.api.seriesDetailV1(request)
        else bundle.api.seriesDetailLegacy(request)
    }

    suspend fun anime(mode: String, query: String = "", page: Int = 1): AnimeCatalogResponse = request {
        requireFeature("anime", "Anime")
        if (apiMode == ApiMode.V1) bundle.api.animeV1(mode, query, page)
        else bundle.api.animeLegacy(mode, query, page)
    }

    suspend fun animeDetail(id: String, translation: String = "", page: Int = 1): AnimeDetail = request {
        requireFeature("anime", "Anime")
        if (apiMode == ApiMode.V1) bundle.api.animeDetailV1(id, translation, page)
        else bundle.api.animeDetailLegacy(id, translation, page)
    }

    suspend fun refreshQueue(): QueueSnapshot {
        val revision = queueRevision.get()
        val result = request { fetchQueue() }
        return applyQueueIfUnchanged(result, revision)
    }

    suspend fun addToQueue(slugs: List<String>): QueueResponse {
        val revision = queueRevision.get()
        val result = request {
            requireFeature("queue", "Die Download-Queue")
            val body = QueueSlugsRequest(slugs.distinct())
            if (apiMode == ApiMode.V1) bundle.api.addQueueV1(body) else bundle.api.addQueueLegacy(body)
        }
        applyQueueIfUnchanged(result.queue, revision)
        return result
    }

    suspend fun removeFromQueue(slug: String): QueueSnapshot {
        val revision = queueRevision.get()
        val result = request {
            requireFeature("queue", "Die Download-Queue")
            val body = QueueRemoveRequest(slug)
            val response = if (apiMode == ApiMode.V1) bundle.api.removeQueueV1(body) else bundle.api.removeQueueLegacy(body)
            response.queue
        }
        return applyQueueIfUnchanged(result, revision)
    }

    suspend fun cancelDownloads() {
        request {
        requireFeature("queue", "Die Download-Queue")
        if (apiMode == ApiMode.V1) bundle.api.cancelDownloadsV1() else bundle.api.cancelDownloadsLegacy()
        }
        refreshQueue()
    }

    suspend fun refreshWatchlist(): List<WatchlistItem> = updateWatchlistFromRequest { fetchWatchlist() }

    suspend fun addWatchlist(body: WatchlistAddRequest): List<WatchlistItem> = updateWatchlistFromRequest {
        requireFeature("watchlist", "Abonnements")
        val result = if (apiMode == ApiMode.V1) bundle.api.addWatchlistV1(body) else bundle.api.addWatchlistLegacy(body)
        result.watchlist
    }

    suspend fun updateWatchlistMode(body: WatchlistModeRequest): List<WatchlistItem> = updateWatchlistFromRequest {
        requireFeature("watchlist", "Abonnements")
        val result = if (apiMode == ApiMode.V1) bundle.api.watchlistModeV1(body) else bundle.api.watchlistModeLegacy(body)
        result.watchlist
    }

    suspend fun removeWatchlist(baseSlug: String): List<WatchlistItem> = updateWatchlistFromRequest {
        requireFeature("watchlist", "Abonnements")
        val body = WatchlistRemoveRequest(listOf(baseSlug))
        val result = if (apiMode == ApiMode.V1) bundle.api.removeWatchlistV1(body) else bundle.api.removeWatchlistLegacy(body)
        result.watchlist
    }

    suspend fun checkWatchlist(baseSlugs: List<String>? = null): List<WatchlistItem> = updateWatchlistFromRequest {
        requireFeature("watchlist", "Abonnements")
        val body = WatchlistCheckRequest(baseSlugs)
        val result = if (apiMode == ApiMode.V1) bundle.api.checkWatchlistV1(body) else bundle.api.checkWatchlistLegacy(body)
        result.watchlist
    }
    suspend fun openWatchlist(baseSlug: String): SeriesDetail {
        val detail = loadWatchlistArtwork(baseSlug)
        val subscriptions = runSuspendCatching { refreshWatchlist() }
            .getOrDefault(_watchlist.value)
        return detail.copy(
            subscription = subscriptions.firstOrNull { it.baseSlug == baseSlug },
        )
    }

    suspend fun loadWatchlistArtwork(baseSlug: String): SeriesDetail = request {
        requireFeature("watchlist", "Abonnements")
        val body = WatchlistOpenRequest(baseSlug)
        if (apiMode == ApiMode.V1) bundle.api.openWatchlistV1(body)
        else bundle.api.openWatchlistLegacy(body)
    }

    private suspend fun fetchQueue(): QueueSnapshot =
        (if (apiMode == ApiMode.V1) {
            requireFeature("queue", "Die Download-Queue")
            bundle.api.queueV1()
        } else bundle.api.queueLegacy()).queue

    private suspend fun fetchWatchlist(): List<WatchlistItem> =
        (if (apiMode == ApiMode.V1) {
            requireFeature("watchlist", "Abonnements")
            bundle.api.watchlistV1()
        } else bundle.api.watchlistLegacy()).watchlist

    private suspend fun updateWatchlistFromRequest(
        block: suspend () -> List<WatchlistItem>,
    ): List<WatchlistItem> {
        val revision = watchlistRevision.get()
        val result = request(block)
        return applyWatchlistIfUnchanged(result, revision)
    }

    private fun publishQueue(snapshot: QueueSnapshot) {
        queueRevision.incrementAndGet()
        _queue.value = snapshot
    }

    private fun applyQueueIfUnchanged(snapshot: QueueSnapshot, expectedRevision: Long): QueueSnapshot {
        if (queueRevision.compareAndSet(expectedRevision, expectedRevision + 1)) {
            _queue.value = snapshot
        }
        return _queue.value
    }

    private fun publishWatchlist(items: List<WatchlistItem>) {
        watchlistRevision.incrementAndGet()
        _watchlist.value = items
    }

    private fun applyWatchlistIfUnchanged(
        items: List<WatchlistItem>,
        expectedRevision: Long,
    ): List<WatchlistItem> {
        if (watchlistRevision.compareAndSet(expectedRevision, expectedRevision + 1)) {
            _watchlist.value = items
        }
        return _watchlist.value
    }

    private suspend fun ensureConfigured() {
        val savedUrl = preferences.settings.first().serverUrl
        if (savedUrl != activeServerUrl) configure(savedUrl)
    }

    private suspend fun configure(serverUrl: String) = configurationMutex.withLock {
        if (serverUrl == activeServerUrl) return@withLock
        webSocket.stop()
        val previousClient = bundle.client
        previousClient.dispatcher.cancelAll()
        previousClient.connectionPool.evictAll()
        previousClient.dispatcher.executorService.shutdown()
        bundle = factory.create(serverUrl)
        activeServerUrl = serverUrl
        selectApiMode(ApiMode.LEGACY)
        activeFeatures = emptyMap()
        activeCapabilities = null
        lastAuth = AuthStatus()
        configurationGeneration += 1
        publishQueue(QueueSnapshot())
        publishWatchlist(emptyList())
        _progress.value = emptyMap()
        _recentResults.value = emptyList()
    }

    private fun startLiveUpdates(capabilities: CapabilitiesResponse) {
        if (!appInForeground || capabilities.features["websocket"] == false) {
            webSocket.stop()
            return
        }
        val path = if (apiMode == ApiMode.V1) capabilities.websocket.path.ifBlank { "/api/v1/ws" } else "/ws"
        webSocket.start(
            bundle.client,
            activeServerUrl,
            path,
            authorizationHeader = apiMode == ApiMode.V1 && capabilities.websocket.authorizationHeader,
        )
    }

    fun onAppBackground() {
        appInForeground = false
        webSocket.stop()
    }

    fun onAppForeground() {
        appInForeground = true
        val state = _connection.value
        val capabilities = activeCapabilities
        if (state is ConnectionState.Connected && capabilities != null) {
            startLiveUpdates(capabilities)
            appScope.launch {
                runSuspendCatching { refreshQueue() }
                runSuspendCatching { refreshWatchlist() }
            }
        }
    }

    private suspend fun discoverCapabilities(): Pair<CapabilitiesResponse, AuthStatus?> {
        return try {
            selectApiMode(ApiMode.V1)
            bundle.api.capabilitiesV1() to null
        } catch (v1Error: HttpException) {
            if (v1Error.code() !in setOf(401, 403, 404)) throw v1Error
            val legacyAuth = try {
                bundle.api.authStatusLegacy()
            } catch (legacyError: HttpException) {
                if (legacyError.code() == 404) {
                    throw RoyalFailure(
                        FailureKind.NOT_FOUND,
                        "Dieser Server bietet weder die Mobile-API noch eine kompatible Legacy-API.",
                        404,
                    )
                }
                throw legacyError
            }
            selectApiMode(ApiMode.LEGACY)
            legacyCapabilities(legacyAuth) to legacyAuth
        }
    }

    private fun selectApiMode(mode: ApiMode) {
        apiMode = mode
        // A v1 server must advertise the additive endpoint before Coil starts using it.
        // Legacy RoyalDownloader versions have always exposed /api/cover.
        artworkProxyState.update(
            activeServerUrl,
            versionedApi = mode == ApiMode.V1,
            enabled = mode == ApiMode.LEGACY,
        )
    }

    private fun legacyCapabilities(auth: AuthStatus) = CapabilitiesResponse(
        apiVersion = "legacy",
        initialized = true,
        auth = CapabilityAuth(required = auth.required, configured = auth.configured),
        features = mapOf("movies" to true, "series" to true, "anime" to true, "queue" to true, "watchlist" to true),
        websocket = CapabilityWebSocket(path = "/ws", authorizationHeader = false),
    )

    private suspend fun <T> request(block: suspend () -> T): T {
        val generation = configurationGeneration
        val tokenAtStart = tokenStore.currentCredential()?.token
        try {
            val result = block()
            if (generation != configurationGeneration) throw CancellationException("Server gewechselt")
            return result
        } catch (error: Throwable) {
            if (error is CancellationException) throw error
            val failure = mapFailure(error)
            if (failure.kind == FailureKind.AUTH && tokenStore.currentCredential()?.token == tokenAtStart) {
                tokenStore.clear()
                webSocket.stop()
                _connection.value = ConnectionState.LoginRequired(
                    activeServerUrl,
                    lastAuth.copy(authenticated = false),
                    LoginReason.EXPIRED,
                )
            }
            throw failure
        }
    }

    private fun requireFeature(key: String, label: String) {
        if (apiMode == ApiMode.V1 && activeFeatures[key] != true) {
            throw RoyalFailure(
                FailureKind.FORBIDDEN,
                "$label ist auf diesem Server deaktiviert.",
            )
        }
    }

    private fun removeQueueItemLocally(slug: String) {
        val groups = _queue.value.groups.mapNotNull { group ->
            group.copy(items = group.items.filterNot { it.slug == slug })
                .takeIf { it.items.isNotEmpty() }
        }
        publishQueue(QueueSnapshot(
            count = groups.sumOf { it.items.size },
            groups = groups,
        ))
    }

    private fun mapFailure(error: Throwable): RoyalFailure {
        val serverMessage = (error as? HttpException)?.let(::parseErrorMessage)
        return FailureClassifier.classify(error, connectivity.connected.value, serverMessage)
    }

    private fun parseErrorMessage(error: HttpException): String? {
        val raw = runCatching { error.response()?.errorBody()?.string() }.getOrNull() ?: return null
        return runCatching {
            val payload = json.decodeFromString<ErrorPayload>(raw)
            (payload.detail ?: payload.error)?.take(240)
        }.getOrNull()
    }

    private fun incompatibilityDetails(capabilities: CapabilitiesResponse): String? {
        if (capabilities.minClientApi > SUPPORTED_API_VERSION ||
            SUPPORTED_API_VERSION !in capabilities.supportedApiVersions
        ) {
            return "Die unterstützte API-Version überschneidet sich nicht mit v$SUPPORTED_API_VERSION."
        }
        val missing = REQUIRED_FEATURE_KEYS.filterNot(capabilities.features::containsKey)
        if (missing.isNotEmpty()) {
            return "Pflichtangaben fehlen: ${missing.joinToString()}."
        }
        if (capabilities.websocket.eventSchemaVersion != SUPPORTED_EVENT_SCHEMA_VERSION) {
            return "WebSocket-Ereignisschema v${capabilities.websocket.eventSchemaVersion} wird nicht unterstützt."
        }
        if (!capabilities.websocket.authorizationHeader) {
            return "Die Mobile-WebSocket-Verbindung unterstützt keine Bearer-Authentifizierung."
        }
        return null
    }

    private companion object {
        const val SUPPORTED_API_VERSION = 1
        const val SUPPORTED_EVENT_SCHEMA_VERSION = 1
        const val MAX_TOKEN_TTL_SECONDS = 365L * 24 * 60 * 60
        val REQUIRED_FEATURE_KEYS = setOf("movies", "series", "anime", "queue", "watchlist", "websocket")
    }
}
