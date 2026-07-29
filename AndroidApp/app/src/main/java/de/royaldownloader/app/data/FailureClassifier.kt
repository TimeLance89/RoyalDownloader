package de.royaldownloader.app.data

import kotlinx.serialization.SerializationException
import retrofit2.HttpException
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.ProtocolException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException

internal object FailureClassifier {
    fun classify(
        error: Throwable,
        internetAvailable: Boolean,
        serverMessage: String? = null,
    ): RoyalFailure {
        if (error is RoyalFailure) return error
        return when (error) {
            is HttpException -> classifyHttp(error, serverMessage)
            is SocketTimeoutException -> RoyalFailure(
                FailureKind.TIMEOUT,
                "Royal Downloader hat nicht rechtzeitig geantwortet.",
                retryable = true,
                cause = error,
            )
            is SSLException -> RoyalFailure(
                FailureKind.TLS,
                "Die sichere TLS-Verbindung zu Royal Downloader konnte nicht hergestellt werden.",
                cause = error,
            )
            is UnknownHostException -> if (internetAvailable) {
                RoyalFailure(
                    FailureKind.DNS,
                    "Die Serveradresse konnte nicht über DNS aufgelöst werden.",
                    retryable = true,
                    cause = error,
                )
            } else {
                deviceOffline(error)
            }
            is ConnectException, is NoRouteToHostException -> if (internetAvailable) {
                RoyalFailure(
                    FailureKind.SERVER_UNREACHABLE,
                    "Internet ist verfügbar, aber Royal Downloader ist nicht erreichbar.",
                    retryable = true,
                    cause = error,
                )
            } else {
                deviceOffline(error)
            }
            is ProtocolException, is SerializationException -> RoyalFailure(
                FailureKind.INVALID_RESPONSE,
                "Der Server hat eine inkompatible Antwort gesendet.",
                cause = error,
            )
            is IOException -> if (internetAvailable) {
                RoyalFailure(
                    FailureKind.SERVER_UNREACHABLE,
                    "Die Verbindung zu Royal Downloader wurde unterbrochen.",
                    retryable = true,
                    cause = error,
                )
            } else {
                deviceOffline(error)
            }
            else -> RoyalFailure(
                FailureKind.UNKNOWN,
                "Die Aktion konnte nicht abgeschlossen werden.",
                cause = error,
            )
        }
    }

    private fun classifyHttp(error: HttpException, serverMessage: String?): RoyalFailure {
        val code = error.code()
        val retryAfter = error.response()?.headers()?.get("Retry-After")?.toLongOrNull()
        return when (code) {
            401 -> RoyalFailure(
                FailureKind.AUTH,
                "Sitzung abgelaufen. Bitte melde dich erneut bei Royal Downloader an.",
                code,
            )
            403 -> RoyalFailure(
                FailureKind.FORBIDDEN,
                serverMessage ?: "Der Server hat den Zugriff verweigert.",
                code,
            )
            404 -> RoyalFailure(
                FailureKind.NOT_FOUND,
                serverMessage ?: "Die angeforderte Mobile-API oder Ressource wurde nicht gefunden.",
                code,
            )
            409 -> RoyalFailure(
                FailureKind.CONFLICT,
                serverMessage ?: "Die Aktion kollidiert mit dem aktuellen Serverzustand.",
                code,
            )
            429 -> RoyalFailure(
                FailureKind.RATE_LIMIT,
                serverMessage ?: retryAfter?.let { "Zu viele Anfragen. Versuche es in $it Sekunden erneut." }
                    ?: "Zu viele Anfragen. Bitte kurz warten.",
                code,
                retryable = true,
                retryAfterSeconds = retryAfter,
            )
            in 520..527 -> RoyalFailure(
                FailureKind.CLOUDFLARE,
                "Cloudflare kann Royal Downloader derzeit nicht erreichen (HTTP $code).",
                code,
                retryable = true,
            )
            503 -> if (looksLikeMaintenance(serverMessage, retryAfter)) {
                RoyalFailure(
                    FailureKind.MAINTENANCE,
                    serverMessage ?: "Royal Downloader befindet sich vorübergehend im Wartungs- oder Updatezustand.",
                    code,
                    retryable = true,
                    retryAfterSeconds = retryAfter,
                )
            } else {
                serverFailure(code, error)
            }
            in 500..599 -> serverFailure(code, error)
            else -> RoyalFailure(
                FailureKind.UNKNOWN,
                serverMessage ?: "Die Anfrage ist mit HTTP $code fehlgeschlagen.",
                code,
            )
        }
    }

    private fun looksLikeMaintenance(message: String?, retryAfter: Long?): Boolean {
        if (retryAfter != null) return true
        val normalized = message?.lowercase().orEmpty()
        return listOf("wartung", "maintenance", "update", "temporarily unavailable")
            .any(normalized::contains)
    }

    private fun serverFailure(code: Int, cause: Throwable) = RoyalFailure(
        FailureKind.SERVER,
        "Royal Downloader hat einen Serverfehler gemeldet (HTTP $code).",
        code,
        retryable = true,
        cause = cause,
    )

    private fun deviceOffline(cause: Throwable) = RoyalFailure(
        FailureKind.DEVICE_OFFLINE,
        "Dieses Gerät hat derzeit keine bestätigte Internetverbindung.",
        retryable = true,
        cause = cause,
    )
}
