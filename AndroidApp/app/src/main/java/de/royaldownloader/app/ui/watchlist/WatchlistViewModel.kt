package de.royaldownloader.app.ui.watchlist

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.data.runSuspendCatching
import de.royaldownloader.app.data.remote.WatchlistItem
import de.royaldownloader.app.data.remote.WatchlistModeRequest
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class WatchlistUiState(
    val items: List<WatchlistItem> = emptyList(),
    val loading: Boolean = true,
    val checking: Boolean = false,
    val activeSlug: String? = null,
    val error: RoyalFailure? = null,
)

class WatchlistViewModel(private val repository: RoyalRepository) : ViewModel() {
    private val _state = MutableStateFlow(WatchlistUiState())
    val state: StateFlow<WatchlistUiState> = _state.asStateFlow()
    private val attemptedArtwork = mutableSetOf<String>()
    private var artworkJob: Job? = null

    init {
        viewModelScope.launch {
            repository.watchlist.collect { value ->
                _state.update { current ->
                    current.copy(
                        items = value.map { incoming ->
                            val existing = current.items.firstOrNull { it.baseSlug == incoming.baseSlug }
                            if (incoming.backdropUrl.isBlank() && incoming.coverUrl.isBlank() && existing != null) {
                                incoming.copy(
                                    backdropUrl = existing.backdropUrl,
                                    coverUrl = existing.coverUrl,
                                )
                            } else incoming
                        },
                        loading = false,
                    )
                }
                loadMissingArtwork()
            }
        }
        refresh()
    }

    fun refresh() {
        attemptedArtwork.clear()
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            runSuspendCatching { repository.refreshWatchlist() }
                .onFailure { error -> _state.update { it.copy(error = error as? RoyalFailure) } }
            _state.update { it.copy(loading = false) }
        }
    }

    fun checkAll() {
        if (_state.value.checking) return
        viewModelScope.launch {
            _state.update { it.copy(checking = true, error = null) }
            runSuspendCatching { repository.checkWatchlist() }
                .onFailure { error -> _state.update { it.copy(error = error as? RoyalFailure) } }
            _state.update { it.copy(checking = false) }
        }
    }

    fun updateMode(item: WatchlistItem, mode: String) = itemAction(item.baseSlug) {
        repository.updateWatchlistMode(WatchlistModeRequest(item.baseSlug, mode, item.cleanupMode))
    }

    fun remove(item: WatchlistItem) = itemAction(item.baseSlug) { repository.removeWatchlist(item.baseSlug) }

    private fun itemAction(slug: String, block: suspend () -> Unit) {
        if (_state.value.activeSlug != null) return
        viewModelScope.launch {
            _state.update { it.copy(activeSlug = slug, error = null) }
            runSuspendCatching { block() }
                .onFailure { error -> _state.update { it.copy(error = error as? RoyalFailure) } }
            _state.update { it.copy(activeSlug = null) }
        }
    }

    private fun loadMissingArtwork() {
        if (artworkJob?.isActive == true) return
        artworkJob = viewModelScope.launch {
            while (true) {
                val item = _state.value.items.firstOrNull {
                    it.backdropUrl.isBlank() && it.coverUrl.isBlank() &&
                        it.baseSlug !in attemptedArtwork
                } ?: break
                attemptedArtwork += item.baseSlug
                runSuspendCatching { repository.loadWatchlistArtwork(item.baseSlug) }
                    .onSuccess { detail ->
                        if (detail.backdropUrl.isNotBlank() || detail.coverUrl.isNotBlank()) {
                            _state.update { current ->
                                current.copy(
                                    items = current.items.map {
                                        if (it.baseSlug == item.baseSlug) {
                                            it.copy(
                                                backdropUrl = detail.backdropUrl,
                                                coverUrl = detail.coverUrl,
                                            )
                                        } else it
                                    },
                                )
                            }
                        }
                    }
            }
        }
    }
}
