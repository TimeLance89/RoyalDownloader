package de.royaldownloader.app.ui.detail

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.data.runSuspendCatching
import de.royaldownloader.app.data.remote.*
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

enum class DetailKind { MOVIE, SERIES, ANIME }

data class DetailState(
    val loading: Boolean = true,
    val actionBusy: Boolean = false,
    val movie: MovieDetail? = null,
    val movieSlug: String = "",
    val series: SeriesDetail? = null,
    val anime: AnimeDetail? = null,
    val selectedTranslation: String = "",
    val selectedEpisodes: Set<String> = emptySet(),
    val message: String? = null,
    val error: RoyalFailure? = null,
    val actionError: RoyalFailure? = null,
)

class DetailViewModel(
    private val repository: RoyalRepository,
    private val kind: DetailKind,
    private val id: String,
    private val sampleSlug: String = "",
    private val fromWatchlist: Boolean = false,
) : ViewModel() {
    private val _state = MutableStateFlow(DetailState())
    val state: StateFlow<DetailState> = _state.asStateFlow()
    private var loadJob: Job? = null

    init { load() }

    fun retry() = load()

    private fun load(
        translation: String = _state.value.selectedTranslation,
        page: Int = _state.value.anime?.page ?: 1,
    ) {
        loadJob?.cancel()
        loadJob = viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = null)
            runSuspendCatching {
                when (kind) {
                    DetailKind.MOVIE -> repository.movieDetail(id)
                    DetailKind.SERIES -> if (fromWatchlist) {
                        repository.openWatchlist(id)
                    } else {
                        repository.seriesDetail(
                            SeriesLoadRequest(
                                sampleSlug = sampleSlug.ifBlank { id },
                                baseSlug = id,
                                deferChecks = false,
                            ),
                        )
                    }
                    DetailKind.ANIME -> repository.animeDetail(id, translation, page)
                }
            }.onSuccess { detail ->
                _state.value = when (detail) {
                    is MovieDetail -> DetailState(movie = detail, movieSlug = id, loading = false)
                    is SeriesDetail -> {
                        val selectable = detail.seasons
                            .flatMap { it.episodes }
                            .filterNot {
                                it.queued || it.downloaded || it.inJellyfin || it.unreleased
                            }
                            .mapTo(mutableSetOf()) { it.slug }
                        DetailState(
                            series = detail,
                            selectedEpisodes = detail.preselectSlugs
                                .filterTo(mutableSetOf()) { it in selectable },
                            loading = false,
                        )
                    }
                    is AnimeDetail -> DetailState(
                        anime = detail,
                        selectedTranslation = detail.translation,
                        selectedEpisodes = _state.value.selectedEpisodes,
                        loading = false,
                    )
                    else -> DetailState(loading = false)
                }
            }.onFailure { error ->
                if (error is CancellationException) throw error
                _state.value = _state.value.copy(loading = false, error = error as? RoyalFailure)
            }
        }
    }

    fun selectTranslation(value: String) {
        if (value == _state.value.selectedTranslation) return
        _state.value = _state.value.copy(selectedTranslation = value, selectedEpisodes = emptySet())
        load(value, 1)
    }

    fun previousAnimePage() {
        val anime = _state.value.anime ?: return
        if (anime.page > 1) load(page = anime.page - 1)
    }

    fun nextAnimePage() {
        val anime = _state.value.anime ?: return
        if (anime.page < anime.pageCount) load(page = anime.page + 1)
    }

    fun toggleEpisode(slug: String) {
        val selected = _state.value.selectedEpisodes
        _state.value = _state.value.copy(
            selectedEpisodes = if (slug in selected) selected - slug else selected + slug,
        )
    }

    fun toggleSeason(seasonNumber: Int) {
        val season = _state.value.series?.seasons
            ?.firstOrNull { it.season == seasonNumber } ?: return
        val selectable = season.episodes
            .filterNot { it.queued || it.downloaded || it.inJellyfin || it.unreleased }
            .mapTo(mutableSetOf()) { it.slug }
        if (selectable.isEmpty()) return
        val selected = _state.value.selectedEpisodes
        _state.value = _state.value.copy(
            selectedEpisodes = if (selectable.all { it in selected }) {
                selected - selectable
            } else {
                selected + selectable
            },
        )
    }

    fun queueMovie() = queue(listOf(_state.value.movieSlug))
    fun queueSelected() = queue(_state.value.selectedEpisodes.toList())

    private fun queue(slugs: List<String>) {
        if (slugs.isEmpty() || _state.value.actionBusy) return
        viewModelScope.launch {
            _state.value = _state.value.copy(actionBusy = true, actionError = null, message = null)
            runSuspendCatching { repository.addToQueue(slugs) }
                .onSuccess { result ->
                    val queuedSlugs = result.queue.groups
                        .flatMap { it.items }
                        .mapTo(mutableSetOf()) { it.slug }
                    val reason = result.skippedDetails.values.distinct().take(2).joinToString(" · ")
                    val message = when {
                        result.added > 0 && result.skipped > 0 ->
                            "${result.added} eingeplant, ${result.skipped} übersprungen${reason.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()}"
                        result.added > 0 -> if (result.added == 1) "Zur Warteschlange hinzugefügt" else "${result.added} Episoden eingeplant"
                        else -> "Nicht eingeplant${reason.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()}"
                    }
                    _state.value = markQueued(_state.value, queuedSlugs).copy(
                        actionBusy = false,
                        selectedEpisodes = emptySet(),
                        message = message,
                    )
                }
                .onFailure { error ->
                    if (error is CancellationException) throw error
                    _state.value = _state.value.copy(actionBusy = false, actionError = error as? RoyalFailure)
                }
        }
    }

    fun saveSeriesSubscription(downloadMode: String, cleanupMode: String) {
        val detail = _state.value.series ?: return
        if (_state.value.actionBusy) return
        viewModelScope.launch {
            _state.value = _state.value.copy(actionBusy = true, actionError = null)
            val request = WatchlistAddRequest(
                baseSlug = detail.baseSlug,
                title = detail.title,
                sampleUrl = detail.url,
                knownSlugs = detail.seasons.flatMap { season -> season.episodes.map { it.slug } },
                downloadMode = downloadMode,
                cleanupMode = cleanupMode,
                tmdbId = detail.tmdbId,
                aliases = detail.aliases,
                seasonEpisodeCounts = detail.seasonEpisodeCounts,
                seasonCountsCheckedAt = detail.seasonCountsCheckedAt,
            )
            runSuspendCatching {
                if (detail.watchlisted) {
                    repository.updateWatchlistMode(
                        WatchlistModeRequest(detail.baseSlug, downloadMode, cleanupMode),
                    )
                } else {
                    repository.addWatchlist(request)
                }
            }
                .onSuccess { subscriptions ->
                    val subscription = subscriptions.firstOrNull { it.baseSlug == detail.baseSlug }
                    _state.value = _state.value.copy(
                        actionBusy = false,
                        series = detail.copy(
                            watchlisted = true,
                            watchMode = downloadMode,
                            cleanupMode = cleanupMode,
                            subscription = subscription,
                        ),
                        message = if (detail.watchlisted) "Abo-Regel aktualisiert" else "Serie abonniert",
                    )
                }
                .onFailure { error ->
                    if (error is CancellationException) throw error
                    _state.value = _state.value.copy(actionBusy = false, actionError = error as? RoyalFailure)
                }
        }
    }

    fun clearMessage() { _state.value = _state.value.copy(message = null) }
    fun clearActionError() { _state.value = _state.value.copy(actionError = null) }

    private fun markQueued(state: DetailState, queuedSlugs: Set<String>): DetailState = state.copy(
        series = state.series?.let { series ->
            series.copy(
                seasons = series.seasons.map { season ->
                    season.copy(
                        episodes = season.episodes.map { episode ->
                            episode.copy(queued = episode.queued || episode.slug in queuedSlugs)
                        },
                    )
                },
            )
        },
        anime = state.anime?.let { anime ->
            anime.copy(
                episodes = anime.episodes.map { episode ->
                    episode.copy(queued = episode.queued || episode.slug in queuedSlugs)
                },
            )
        },
    )
}
