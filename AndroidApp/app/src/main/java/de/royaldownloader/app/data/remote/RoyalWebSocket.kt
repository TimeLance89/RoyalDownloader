package de.royaldownloader.app.data.remote

import de.royaldownloader.app.data.local.SecureTokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.io.IOException
import kotlin.math.min
import kotlin.random.Random

sealed interface SocketStatus {
    data object Stopped : SocketStatus
    data object Connecting : SocketStatus
    data object Connected : SocketStatus
    data class Reconnecting(val attempt: Int) : SocketStatus
    data object Unauthorized : SocketStatus
    data object Forbidden : SocketStatus
    data class PolicyViolation(val reason: String) : SocketStatus
}

class RoyalWebSocket(
    private val scope: CoroutineScope,
    private val json: Json,
    private val tokenStore: SecureTokenStore,
    private val networkAvailable: StateFlow<Boolean>,
) {
    private val incomingEvents = Channel<QueuedSocketEvent>(EVENT_BUFFER_CAPACITY)
    private val _events = MutableSharedFlow<SocketEvent>(extraBufferCapacity = 1)
    val events: SharedFlow<SocketEvent> = _events.asSharedFlow()
    private val _status = MutableStateFlow<SocketStatus>(SocketStatus.Stopped)
    val status: StateFlow<SocketStatus> = _status.asStateFlow()

    private val stateLock = Any()
    private var socket: WebSocket? = null
    private var connectJob: Job? = null
    private var reconnectJob: Job? = null
    private var client: OkHttpClient? = null
    private var baseUrl: String = ""
    private var path: String = "/ws"
    private var authorizationHeader = false
    private var enabled = false
    private var generation = 0
    private var reconnectAttempt = 0

    init {
        // WebSocket callbacks are synchronous. A single coroutine preserves event order and uses
        // suspending SharedFlow delivery instead of silently dropping queue completion events.
        scope.launch {
            for (queued in incomingEvents) {
                if (isCurrent(queued.generation)) _events.emit(queued.event)
            }
        }
    }

    /** Compatibility overload; new callers should pass the advertised authentication capability. */
    fun start(client: OkHttpClient, baseUrl: String, path: String) {
        start(client, baseUrl, path, authorizationHeader = path.startsWith("/api/v1/"))
    }

    fun start(
        client: OkHttpClient,
        baseUrl: String,
        path: String,
        authorizationHeader: Boolean,
    ) {
        stop()
        val expectedGeneration = synchronized(stateLock) {
            this.client = client
            this.baseUrl = baseUrl
            this.path = path.ifBlank { "/ws" }
            this.authorizationHeader = authorizationHeader
            enabled = true
            generation += 1
            reconnectAttempt = 0
            generation
        }
        connect(expectedGeneration)
    }

    fun stop() {
        val previous = synchronized(stateLock) {
            enabled = false
            generation += 1
            val state = PendingResources(connectJob, reconnectJob, socket)
            connectJob = null
            reconnectJob = null
            socket = null
            state
        }
        previous.connectJob?.cancel()
        previous.reconnectJob?.cancel()
        previous.socket?.close(1000, "Client beendet")
        _status.value = SocketStatus.Stopped
    }

    private fun connect(expectedGeneration: Int) {
        lateinit var newJob: Job
        newJob = scope.launch(start = CoroutineStart.LAZY) {
            try {
                networkAvailable.first { it }
                val config = synchronized(stateLock) {
                    if (!enabled || expectedGeneration != generation) return@launch
                    val selectedClient = client ?: return@launch
                    SocketConfiguration(
                        client = selectedClient,
                        baseUrl = baseUrl,
                        path = path,
                        authorizationHeader = authorizationHeader,
                    )
                }
                val socketUrl = buildWebSocketRequestUrl(config.baseUrl, config.path)
                val headers = webSocketCredentialHeaders(
                    credential = tokenStore.currentCredential(),
                    requestUrl = socketUrl,
                    authorizationHeader = config.authorizationHeader,
                )
                val requestBuilder = Request.Builder().url(socketUrl)
                    .removeHeader("Authorization")
                    .removeHeader("Cookie")
                headers.authorization?.let { requestBuilder.header("Authorization", it) }
                headers.cookie?.let { requestBuilder.header("Cookie", it) }

                val created = config.client.newWebSocket(
                    requestBuilder.build(),
                    listener(expectedGeneration),
                )
                val accepted = synchronized(stateLock) {
                    if (enabled && expectedGeneration == generation) {
                        socket = created
                        true
                    } else {
                        false
                    }
                }
                if (!accepted) created.cancel()
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: IOException) {
                scheduleReconnect(expectedGeneration)
            } catch (_: IllegalArgumentException) {
                scheduleReconnect(expectedGeneration)
            } finally {
                synchronized(stateLock) {
                    if (connectJob === newJob) connectJob = null
                }
            }
        }

        val previous = synchronized(stateLock) {
            if (!enabled || expectedGeneration != generation) return
            val old = connectJob
            connectJob = newJob
            _status.value = if (reconnectAttempt == 0) {
                SocketStatus.Connecting
            } else {
                SocketStatus.Reconnecting(reconnectAttempt)
            }
            old
        }
        previous?.cancel()
        newJob.start()
    }

    private fun listener(expectedGeneration: Int) = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            val accepted = synchronized(stateLock) {
                if (!enabled || expectedGeneration != generation) {
                    false
                } else {
                    socket = webSocket
                    reconnectAttempt = 0
                    true
                }
            }
            if (!accepted) {
                webSocket.cancel()
                return
            }
            _status.value = SocketStatus.Connected
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (!isCurrent(expectedGeneration)) return
            runCatching { json.decodeFromString<SocketEvent>(text) }
                .onSuccess {
                    if (incomingEvents.trySend(QueuedSocketEvent(expectedGeneration, it)).isFailure) {
                        // Bound memory under event floods. Reconnecting yields a fresh v1 snapshot,
                        // so structural queue state is recovered instead of being silently stale.
                        webSocket.cancel()
                        scheduleReconnect(expectedGeneration)
                    }
                }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code, null)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            clearSocket(webSocket, expectedGeneration)
            if (!isCurrent(expectedGeneration)) return
            if (code == POLICY_VIOLATION_CODE) {
                if (isAuthenticationPolicyViolation(reason)) {
                    finishTerminal(expectedGeneration, SocketStatus.Unauthorized)
                } else {
                    finishTerminal(
                        expectedGeneration,
                        SocketStatus.PolicyViolation(reason.take(MAX_REASON_LENGTH)),
                    )
                }
                return
            }
            scheduleReconnect(expectedGeneration)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val statusCode = response?.code
            response?.close()
            clearSocket(webSocket, expectedGeneration)
            if (!isCurrent(expectedGeneration)) return
            when (statusCode) {
                401 -> finishTerminal(expectedGeneration, SocketStatus.Unauthorized)
                403 -> finishTerminal(expectedGeneration, SocketStatus.Forbidden)
                else -> scheduleReconnect(expectedGeneration)
            }
        }
    }

    private fun finishTerminal(expectedGeneration: Int, terminalStatus: SocketStatus) {
        val pendingReconnect = synchronized(stateLock) {
            if (!enabled || expectedGeneration != generation) return
            enabled = false
            val pending = reconnectJob
            reconnectJob = null
            pending
        }
        pendingReconnect?.cancel()
        _status.value = terminalStatus
    }

    private fun clearSocket(webSocket: WebSocket, expectedGeneration: Int) {
        synchronized(stateLock) {
            if (expectedGeneration == generation && socket === webSocket) socket = null
        }
    }

    private fun isCurrent(expectedGeneration: Int): Boolean = synchronized(stateLock) {
        enabled && expectedGeneration == generation
    }

    private fun scheduleReconnect(expectedGeneration: Int) {
        lateinit var scheduled: Job
        val shouldStart = synchronized(stateLock) {
            if (!enabled || expectedGeneration != generation || reconnectJob?.isActive == true) {
                false
            } else {
                reconnectAttempt += 1
                val attempt = reconnectAttempt
                val delayMillis = reconnectDelayMillis(attempt)
                scheduled = scope.launch(start = CoroutineStart.LAZY) {
                    delay(delayMillis)
                    val shouldConnect = synchronized(stateLock) {
                        if (
                            enabled &&
                            expectedGeneration == generation &&
                            reconnectJob === scheduled
                        ) {
                            reconnectJob = null
                            true
                        } else {
                            false
                        }
                    }
                    if (shouldConnect) connect(expectedGeneration)
                }
                reconnectJob = scheduled
                _status.value = SocketStatus.Reconnecting(attempt)
                true
            }
        }
        if (shouldStart) scheduled.start()
    }

    private data class PendingResources(
        val connectJob: Job?,
        val reconnectJob: Job?,
        val socket: WebSocket?,
    )

    private data class SocketConfiguration(
        val client: OkHttpClient,
        val baseUrl: String,
        val path: String,
        val authorizationHeader: Boolean,
    )

    private data class QueuedSocketEvent(
        val generation: Int,
        val event: SocketEvent,
    )

    companion object {
        private const val POLICY_VIOLATION_CODE = 1008
        private const val MAX_REASON_LENGTH = 160
        private const val EVENT_BUFFER_CAPACITY = 256

        internal fun reconnectDelayMillis(attempt: Int, jitter: Double = Random.nextDouble()): Long {
            val exponent = 1L shl min((attempt - 1).coerceAtLeast(0), 5)
            val base = min(30_000L, 1_000L * exponent)
            return (base * (0.8 + jitter * 0.4)).toLong()
        }

        internal fun isAuthenticationPolicyViolation(reason: String): Boolean {
            val normalized = reason.trim().lowercase()
            return listOf("auth", "token", "anmeld", "sitzung", "session", "unauthor")
                .any(normalized::contains)
        }
    }
}

/** OkHttp performs the WebSocket upgrade on an HTTP(S) request URL. */
internal fun buildWebSocketRequestUrl(baseUrl: String, path: String): HttpUrl = baseUrl.toHttpUrl()
    .newBuilder()
    .encodedPath(if (path.startsWith('/')) path else "/$path")
    .query(null)
    .fragment(null)
    .build()
