package de.royaldownloader.app.ui.queue

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import de.royaldownloader.app.data.LiveProgress
import de.royaldownloader.app.data.LiveResult
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.data.runSuspendCatching
import de.royaldownloader.app.data.remote.QueueSnapshot
import de.royaldownloader.app.data.remote.SocketStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class QueueUiState(
    val snapshot: QueueSnapshot = QueueSnapshot(),
    val progress: Map<String, LiveProgress> = emptyMap(),
    val recentResults: List<LiveResult> = emptyList(),
    val socketStatus: SocketStatus = SocketStatus.Stopped,
    val loading: Boolean = true,
    val actionBusy: Boolean = false,
    val error: RoyalFailure? = null,
)

class QueueViewModel(private val repository: RoyalRepository) : ViewModel() {
    private val _state = MutableStateFlow(QueueUiState())
    val state: StateFlow<QueueUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch { repository.queue.collect { value -> _state.update { it.copy(snapshot = value, loading = false) } } }
        viewModelScope.launch { repository.progress.collect { value -> _state.update { it.copy(progress = value) } } }
        viewModelScope.launch { repository.recentResults.collect { value -> _state.update { it.copy(recentResults = value) } } }
        viewModelScope.launch { repository.socketStatus.collect { value -> _state.update { it.copy(socketStatus = value) } } }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            runSuspendCatching { repository.refreshQueue() }
                .onFailure { error -> _state.update { it.copy(error = error as? RoyalFailure) } }
            _state.update { it.copy(loading = false) }
        }
    }

    fun remove(slug: String) = action { repository.removeFromQueue(slug) }
    fun cancelAll() = action { repository.cancelDownloads() }

    private fun action(block: suspend () -> Unit) {
        if (_state.value.actionBusy) return
        viewModelScope.launch {
            _state.update { it.copy(actionBusy = true, error = null) }
            runSuspendCatching { block() }
                .onFailure { error -> _state.update { it.copy(error = error as? RoyalFailure) } }
            _state.update { it.copy(actionBusy = false) }
        }
    }
}
