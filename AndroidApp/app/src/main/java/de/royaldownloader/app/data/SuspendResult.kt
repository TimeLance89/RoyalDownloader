package de.royaldownloader.app.data

import kotlinx.coroutines.CancellationException

/** Equivalent to runCatching, but never turns structured-concurrency cancellation into an app error. */
suspend fun <T> runSuspendCatching(block: suspend () -> T): Result<T> = try {
    Result.success(block())
} catch (error: CancellationException) {
    throw error
} catch (error: Throwable) {
    Result.failure(error)
}
