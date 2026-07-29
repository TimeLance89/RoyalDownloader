package de.royaldownloader.app.ui.discover

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.data.runSuspendCatching
import de.royaldownloader.app.data.remote.AnimeSummary
import de.royaldownloader.app.data.remote.MovieSummary
import de.royaldownloader.app.data.remote.SeriesSummary
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class MediaSection { MOVIES, SERIES, ANIME }

data class DiscoverState(
    val section: MediaSection = MediaSection.MOVIES,
    val query: String = "",
    val loading: Boolean = true,
    val loadingMore: Boolean = false,
    val page: Int = 1,
    val hasMore: Boolean = false,
    val movies: List<MovieSummary> = emptyList(),
    val series: List<SeriesSummary> = emptyList(),
    val anime: List<AnimeSummary> = emptyList(),
    val disabledReason: String = "",
    val error: RoyalFailure? = null,
)

class DiscoverViewModel(private val repository: RoyalRepository) : ViewModel() {
    private val _state = MutableStateFlow(DiscoverState())
    val state: StateFlow<DiscoverState> = _state.asStateFlow()
    private var searchJob: Job? = null
    private var requestGeneration = 0

    init { load(reset = true) }

    fun selectSection(section: MediaSection) {
        if (_state.value.section == section) return
        searchJob?.cancel()
        _state.value = DiscoverState(section = section)
        load(reset = true)
    }

    fun updateQuery(value: String) {
        requestGeneration += 1
        _state.update { it.copy(query = value) }
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(350)
            load(reset = true)
        }
    }

    fun submitSearch() {
        searchJob?.cancel()
        load(reset = true)
    }

    fun retry() = load(reset = true)
    fun loadMore() {
        val current = _state.value
        if (!current.hasMore || current.loading || current.loadingMore) return
        load(reset = false)
    }

    private fun load(reset: Boolean) {
        val generation = ++requestGeneration
        val requested = _state.value
        val requestedSection = requested.section
        val requestedQuery = requested.query.trim()
        viewModelScope.launch {
            val page = if (reset) 1 else requested.page + 1
            _state.update { current ->
                if (generation != requestGeneration || current.section != requestedSection ||
                    current.query.trim() != requestedQuery
                ) current else current.copy(
                    loading = reset,
                    loadingMore = !reset,
                    error = null,
                    page = if (reset) 1 else current.page,
                )
            }
            if (generation != requestGeneration) return@launch
            runSuspendCatching {
                when (requestedSection) {
                    MediaSection.MOVIES -> repository.movies(if (requestedQuery.isBlank()) "new" else "search", requestedQuery, page)
                    MediaSection.SERIES -> repository.series(if (requestedQuery.isBlank()) "trending" else "search", requestedQuery, page)
                    MediaSection.ANIME -> repository.anime(if (requestedQuery.isBlank()) "latest" else "search", requestedQuery, page)
                }
            }.onSuccess { response ->
                if (generation != requestGeneration) return@onSuccess
                _state.update { current -> when (response) {
                    is de.royaldownloader.app.data.remote.MovieCatalogResponse -> current.copy(
                        loading = false, loadingMore = false, page = page, hasMore = response.hasMore,
                        movies = if (reset) response.results else current.movies + response.results,
                    )
                    is de.royaldownloader.app.data.remote.SeriesCatalogResponse -> current.copy(
                        loading = false, loadingMore = false, page = page, hasMore = response.hasMore,
                        series = if (reset) response.items else current.series + response.items,
                    )
                    is de.royaldownloader.app.data.remote.AnimeCatalogResponse -> current.copy(
                        loading = false, loadingMore = false, page = page, hasMore = response.hasMore,
                        anime = if (reset) response.results else current.anime + response.results,
                        disabledReason = response.disabledReason,
                    )
                    else -> current.copy(loading = false, loadingMore = false)
                } }
            }.onFailure { error ->
                if (generation != requestGeneration) return@onFailure
                _state.update { it.copy(
                    loading = false,
                    loadingMore = false,
                    error = error as? RoyalFailure,
                ) }
            }
        }
    }
}
