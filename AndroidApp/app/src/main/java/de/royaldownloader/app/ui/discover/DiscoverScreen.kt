package de.royaldownloader.app.ui.discover

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.royaldownloader.app.ui.components.*
import de.royaldownloader.app.ui.theme.RoyalTheme

@Composable
fun DiscoverScreen(
    viewModel: DiscoverViewModel,
    onMovie: (String) -> Unit,
    onSeries: (String, String) -> Unit,
    onAnime: (String) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val gridState = rememberLazyGridState()
    val prefetchNextPage by remember {
        derivedStateOf {
            val layout = gridState.layoutInfo
            val lastVisible = layout.visibleItemsInfo.lastOrNull()?.index ?: -1
            layout.totalItemsCount > 0 && lastVisible >= layout.totalItemsCount - 6
        }
    }
    LaunchedEffect(
        prefetchNextPage,
        state.hasMore,
        state.loading,
        state.loadingMore,
        state.page,
        state.section,
    ) {
        if (prefetchNextPage && state.hasMore && !state.loading && !state.loadingMore) {
            viewModel.loadMore()
        }
    }
    LaunchedEffect(state.section, state.query) {
        gridState.scrollToItem(0)
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp),
    ) {
        Spacer(Modifier.height(16.dp))
        RoyalArchiveHeader(
            eyebrow = "DISCOVERY",
            title = "Entdecken",
            supportingText = "Filme, Serien und Anime aus deinen aktiven Quellen.",
        )
        Spacer(Modifier.height(RoyalTheme.spacing.md))
        RoyalSearchField(
            query = state.query,
            onQueryChange = viewModel::updateQuery,
            placeholder = when (state.section) {
                MediaSection.MOVIES -> "Film suchen"
                MediaSection.SERIES -> "Serie suchen"
                MediaSection.ANIME -> "Anime suchen"
            },
            onSearch = viewModel::submitSearch,
            clearContentDescription = "Suche löschen",
        )
        Spacer(Modifier.height(RoyalTheme.spacing.sm))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            RoyalFilterChip(state.section == MediaSection.MOVIES, { viewModel.selectSection(MediaSection.MOVIES) }, "Filme")
            RoyalFilterChip(state.section == MediaSection.SERIES, { viewModel.selectSection(MediaSection.SERIES) }, "Serien")
            RoyalFilterChip(state.section == MediaSection.ANIME, { viewModel.selectSection(MediaSection.ANIME) }, "Anime")
        }
        Spacer(Modifier.height(RoyalTheme.spacing.md))
        when {
            state.loading -> RoyalLoadingState("Katalog wird geladen …", Modifier.fillMaxSize())
            state.error != null -> RoyalErrorState(
                "Katalog nicht verfügbar",
                state.error?.message.orEmpty(),
                "Erneut laden",
                viewModel::retry,
                Modifier.fillMaxSize(),
            )
            state.disabledReason.isNotBlank() && state.section == MediaSection.ANIME -> RoyalEmptyState(
                "Anime ist pausiert",
                state.disabledReason,
                Modifier.fillMaxSize(),
            )
            itemCount(state) == 0 -> RoyalEmptyState(
                if (state.query.isBlank()) "Noch keine Inhalte" else "Keine Treffer",
                if (state.query.isBlank()) "Aktiviere eine passende Quelle in der Weboberfläche." else "Versuche einen anderen oder kürzeren Titel.",
                Modifier.fillMaxSize(),
            )
            else -> LazyVerticalGrid(
                columns = GridCells.Adaptive(148.dp),
                state = gridState,
                modifier = Modifier.fillMaxSize(),
                horizontalArrangement = Arrangement.spacedBy(14.dp),
                verticalArrangement = Arrangement.spacedBy(20.dp),
                contentPadding = PaddingValues(bottom = 28.dp),
            ) {
                when (state.section) {
                    MediaSection.MOVIES -> items(state.movies, key = { it.slug }) { item ->
                        RoyalPosterCard(
                            item.title, item.coverUrl, { onMovie(item.slug) },
                            subtitle = item.year,
                            metadata = if (item.tmdbId != null) "TMDB-Auswahl" else item.contentLanguage.uppercase(),
                            statusLabel = if (item.inJellyfin == true) "In Jellyfin" else null,
                            statusTone = RoyalStatusTone.Success,
                            statusProminent = item.inJellyfin == true,
                        )
                    }
                    MediaSection.SERIES -> items(
                        state.series,
                        key = { listOf(it.baseSlug, it.sampleSlug, it.sampleUrl, it.provider, it.title).joinToString("|") },
                    ) { item ->
                        RoyalPosterCard(
                            item.title, item.coverUrl,
                            { onSeries(item.baseSlug, item.sampleSlug.ifBlank { item.sampleUrl }) },
                            subtitle = item.year,
                            metadata = item.providerLabel,
                        )
                    }
                    MediaSection.ANIME -> items(state.anime, key = { it.id }) { item ->
                        RoyalPosterCard(
                            item.title, item.coverUrl, { onAnime(item.id) },
                            subtitle = item.year,
                            metadata = "${item.episodeCount} Episoden",
                            statusLabel = item.translations.keys.joinToString(" / ").uppercase().ifBlank { null },
                            statusTone = RoyalStatusTone.Anime,
                        )
                    }
                }
            }
        }
    }
}

private fun itemCount(state: DiscoverState): Int = when (state.section) {
    MediaSection.MOVIES -> state.movies.size
    MediaSection.SERIES -> state.series.size
    MediaSection.ANIME -> state.anime.size
}
