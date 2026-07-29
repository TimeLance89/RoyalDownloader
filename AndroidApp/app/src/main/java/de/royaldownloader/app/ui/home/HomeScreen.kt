package de.royaldownloader.app.ui.home

import androidx.compose.animation.Crossfade
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import de.royaldownloader.app.data.HomeSnapshot
import de.royaldownloader.app.data.remote.*
import de.royaldownloader.app.ui.components.*
import de.royaldownloader.app.ui.theme.*
import kotlinx.coroutines.delay
import java.time.LocalDate
import java.time.format.DateTimeFormatter

@Composable
fun HomeScreen(
    viewModel: HomeViewModel,
    onMovie: (String) -> Unit,
    onSeries: (String, String) -> Unit,
    onAnime: (String) -> Unit,
    onOpenQueue: () -> Unit,
    onOpenWatchlist: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    when {
        state.data == null && state.loading -> RoyalLoadingState("Deine Sammlung wird vorbereitet …", Modifier.fillMaxSize())
        state.data == null && state.error != null -> RoyalErrorState(
            title = "Home konnte nicht geladen werden",
            message = state.error?.message.orEmpty(),
            retryLabel = "Erneut laden",
            onRetry = viewModel::refresh,
            modifier = Modifier.fillMaxSize(),
        )
        else -> state.data?.let { snapshot ->
            HomeContent(snapshot, state.loading, viewModel::refresh, onMovie, onSeries, onAnime, onOpenQueue, onOpenWatchlist)
        }
    }
}

@Composable
private fun HomeContent(
    snapshot: HomeSnapshot,
    refreshing: Boolean,
    onRefresh: () -> Unit,
    onMovie: (String) -> Unit,
    onSeries: (String, String) -> Unit,
    onAnime: (String) -> Unit,
    onOpenQueue: () -> Unit,
    onOpenWatchlist: () -> Unit,
) {
    val fallbackFeatured = snapshot.newMovies.firstOrNull { it.backdropUrl.isNotBlank() }
        ?: snapshot.topMovies.firstOrNull { it.backdropUrl.isNotBlank() }
        ?: snapshot.newMovies.firstOrNull()
        ?: snapshot.topMovies.firstOrNull()
    val cinemaFeatures = snapshot.cinemaMovies
        .filter { it.backdropUrl.isNotBlank() }
        .take(6)
        .ifEmpty { listOfNotNull(fallbackFeatured) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(bottom = 32.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp),
    ) {
        item {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 18.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                RoyalWordmark(compact = true, modifier = Modifier.weight(1f))
                RoyalIconButton(onClick = onRefresh, enabled = !refreshing) {
                    Icon(Icons.Rounded.Refresh, contentDescription = "Aktualisieren")
                }
            }
        }
        if (cinemaFeatures.isNotEmpty()) {
            item {
                FeaturedCinemaBanner(
                    movies = cinemaFeatures,
                    onMovie = onMovie,
                )
            }
        }
        item {
            Row(
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 18.dp),
            ) {
                SummaryTile("QUEUE", snapshot.queue.count.toString(), "offen", Modifier.weight(1f), onOpenQueue)
                SummaryTile("ABOS", snapshot.watchlist.size.toString(), "Serien", Modifier.weight(1f), onOpenWatchlist)
                SummaryTile("NEU", snapshot.watchlist.sumOf { it.newCount }.toString(), "Episoden", Modifier.weight(1f), onOpenWatchlist)
            }
        }
        if (snapshot.queue.count > 0) {
            item {
                RoyalConnectionBanner(
                    title = "${snapshot.queue.count} Downloads eingeplant",
                    message = "Die Queue läuft serverseitig weiter – auch wenn die App geschlossen ist.",
                    tone = RoyalStatusTone.Active,
                    actionLabel = "Queue öffnen",
                    onAction = onOpenQueue,
                    modifier = Modifier.padding(horizontal = 18.dp),
                )
            }
        }
        if (snapshot.newMovies.isNotEmpty()) {
            item { CinemaRailHeader("Neu im Katalog", "FILME", Modifier.padding(horizontal = 18.dp)) }
            item { MovieRail(snapshot.newMovies, onMovie) }
        }
        if (snapshot.topMovies.isNotEmpty()) {
            item { CinemaRailHeader("Top 10 heute", "TRENDING", Modifier.padding(horizontal = 18.dp)) }
            item { RankedMovieRail(snapshot.topMovies.take(10), onMovie) }
        }
        if (snapshot.series.isNotEmpty()) {
            item { CinemaRailHeader("Serien entdecken", "SERIEN", Modifier.padding(horizontal = 18.dp)) }
            item {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp), contentPadding = PaddingValues(horizontal = 18.dp)) {
                    items(
                        snapshot.series,
                        key = { listOf(it.baseSlug, it.sampleSlug, it.sampleUrl, it.provider, it.title).joinToString("|") },
                    ) { series ->
                        RoyalPosterCard(
                            title = series.title,
                            subtitle = listOf(series.year, series.providerLabel).filter { it.isNotBlank() }.joinToString(" · "),
                            metadata = series.languageLabel.ifBlank { series.contentLanguage.uppercase() },
                            imageModel = series.coverUrl,
                            onClick = { onSeries(series.baseSlug, series.sampleSlug.ifBlank { series.sampleUrl }) },
                            modifier = Modifier.width(148.dp),
                        )
                    }
                }
            }
        }
        if (snapshot.anime.isNotEmpty()) {
            item { CinemaRailHeader("Anime", "ANIME", Modifier.padding(horizontal = 18.dp)) }
            item {
                LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp), contentPadding = PaddingValues(horizontal = 18.dp)) {
                    items(snapshot.anime, key = { it.id }) { anime ->
                        RoyalPosterCard(
                            title = anime.title,
                            subtitle = anime.year,
                            metadata = "${anime.episodeCount} Episoden",
                            imageModel = anime.coverUrl,
                            onClick = { onAnime(anime.id) },
                            modifier = Modifier.width(148.dp),
                            statusLabel = anime.translations.keys.joinToString(" / ").uppercase().ifBlank { null },
                            statusTone = RoyalStatusTone.Anime,
                        )
                    }
                }
            }
        } else if (snapshot.animeDisabledReason.isNotBlank()) {
            item {
                RoyalConnectionBanner(
                    "Anime ist deaktiviert",
                    snapshot.animeDisabledReason,
                    tone = RoyalStatusTone.Anime,
                    modifier = Modifier.padding(horizontal = 18.dp),
                )
            }
        }
    }
}

@Composable
private fun FeaturedCinemaBanner(
    movies: List<MovieSummary>,
    onMovie: (String) -> Unit,
) {
    var index by remember(movies.map { it.slug }) { mutableIntStateOf(0) }
    LaunchedEffect(movies) {
        while (movies.size > 1) {
            delay(7_500)
            index = (index + 1) % movies.size
        }
    }
    val safeIndex = index.coerceIn(movies.indices)
    Crossfade(targetState = safeIndex, label = "Kinofilmwechsel") { position ->
        FeaturedMovie(
            movie = movies[position],
            position = position,
            total = movies.size,
            onClick = { onMovie(movies[position].slug) },
        )
    }
}

@Composable
private fun FeaturedMovie(
    movie: MovieSummary,
    position: Int,
    total: Int,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(480.dp),
    ) {
        AsyncImage(
            model = movie.backdropUrl.ifBlank { movie.coverUrl },
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop,
        )
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        0f to RoyalVault.copy(alpha = 0.06f),
                        0.50f to RoyalVault.copy(alpha = 0.30f),
                        1f to RoyalVault,
                    ),
                ),
        )
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.horizontalGradient(
                        listOf(RoyalVault.copy(alpha = 0.88f), RoyalVault.copy(alpha = 0.12f)),
                    ),
                ),
        )
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth(0.92f)
                .padding(horizontal = 22.dp, vertical = 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.width(4.dp).height(18.dp).background(RoyalCinemaRed))
                RoyalArchiveLabel(
                    if (movie.inCinema) "JETZT IM KINO" else "HEUTE IM FOKUS",
                    color = RoyalText,
                )
            }
            Text(
                movie.title,
                color = androidx.compose.ui.graphics.Color.White,
                style = MaterialTheme.typography.displaySmall.copy(
                    fontFamily = Outfit,
                    fontWeight = FontWeight.Black,
                ),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (movie.releaseDate.isNotBlank()) {
                    RoyalStatusChip(
                        "${if (movie.inCinema) "Kinostart" else "Start"} ${formatCinemaDate(movie.releaseDate)}",
                        tone = RoyalStatusTone.Active,
                    )
                } else if (movie.year.isNotBlank()) {
                    RoyalStatusChip(movie.year)
                }
                movie.rating?.takeIf { it > 0 }?.let {
                    RoyalStatusChip("★ %.1f".format(it), tone = RoyalStatusTone.Success)
                }
                if (movie.contentLanguage.isNotBlank()) {
                    RoyalStatusChip(movie.contentLanguage.uppercase(), tone = RoyalStatusTone.Success)
                }
            }
            if (movie.description.isNotBlank()) {
                Text(
                    movie.description,
                    color = RoyalText.copy(alpha = 0.88f),
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Button(
                onClick = onClick,
                modifier = Modifier.widthIn(min = 166.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = androidx.compose.ui.graphics.Color.White,
                    contentColor = androidx.compose.ui.graphics.Color.Black,
                ),
            ) {
                Icon(Icons.Rounded.Info, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Details ansehen", fontWeight = FontWeight.Bold)
            }
        }
        if (total > 1) {
            Row(
                modifier = Modifier.align(Alignment.BottomEnd).padding(end = 22.dp, bottom = 26.dp),
                horizontalArrangement = Arrangement.spacedBy(5.dp),
            ) {
                repeat(total) { dot ->
                    Box(
                        Modifier
                            .width(if (dot == position) 18.dp else 6.dp)
                            .height(4.dp)
                            .clip(MaterialTheme.shapes.extraSmall)
                            .background(
                                if (dot == position) RoyalCinemaRed
                                else androidx.compose.ui.graphics.Color.White.copy(alpha = 0.44f),
                            ),
                    )
                }
            }
        }
    }
}

private fun formatCinemaDate(value: String): String = runCatching {
    LocalDate.parse(value).format(DateTimeFormatter.ofPattern("dd.MM.yyyy"))
}.getOrDefault(value)

@Composable
private fun CinemaRailHeader(title: String, label: String, modifier: Modifier = Modifier) {
    Row(modifier = modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(3.dp).height(28.dp).background(RoyalCinemaRed))
        Spacer(Modifier.width(10.dp))
        Column {
            RoyalArchiveLabel(label, color = RoyalTextMuted)
            Text(title, color = RoyalText, style = MaterialTheme.typography.titleLarge)
        }
    }
}

@Composable
private fun SummaryTile(label: String, value: String, caption: String, modifier: Modifier, onClick: () -> Unit) {
    RoyalPanel(modifier = modifier, onClick = onClick, contentPadding = PaddingValues(12.dp)) {
        RoyalArchiveLabel(label)
        Text(value, color = RoyalText, style = MaterialTheme.typography.headlineMedium)
        Text(caption, color = RoyalTextMuted, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun MovieRail(movies: List<MovieSummary>, onMovie: (String) -> Unit) {
    LazyRow(horizontalArrangement = Arrangement.spacedBy(12.dp), contentPadding = PaddingValues(horizontal = 18.dp)) {
        items(movies, key = { it.slug }) { movie ->
            RoyalPosterCard(
                title = movie.title,
                subtitle = movie.year,
                metadata = movie.contentLanguage.uppercase(),
                imageModel = movie.coverUrl,
                onClick = { onMovie(movie.slug) },
                modifier = Modifier.width(148.dp),
                statusLabel = if (movie.inJellyfin == true) "In Jellyfin" else null,
                statusTone = RoyalStatusTone.Success,
                statusProminent = movie.inJellyfin == true,
            )
        }
    }
}

@Composable
private fun RankedMovieRail(movies: List<MovieSummary>, onMovie: (String) -> Unit) {
    LazyRow(
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        contentPadding = PaddingValues(horizontal = 18.dp),
    ) {
        itemsIndexed(movies, key = { _, movie -> movie.slug }) { index, movie ->
            RankedMovieCard(index + 1, movie, onClick = { onMovie(movie.slug) })
        }
    }
}

@Composable
private fun RankedMovieCard(rank: Int, movie: MovieSummary, onClick: () -> Unit) {
    Box(modifier = Modifier.width(246.dp).height(352.dp)) {
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .width(194.dp)
                .height(330.dp)
                .clip(MaterialTheme.shapes.large)
                .background(RoyalObsidian)
                .border(1.dp, RoyalGoldBorderStrong, MaterialTheme.shapes.large)
                .clickable(role = Role.Button, onClick = onClick),
        ) {
            AsyncImage(
                model = movie.coverUrl,
                contentDescription = "Platz $rank: ${movie.title}",
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
            )
            Box(
                Modifier
                    .fillMaxSize()
                    .background(
                        Brush.verticalGradient(
                            0f to androidx.compose.ui.graphics.Color.Transparent,
                            0.52f to RoyalVault.copy(alpha = 0.08f),
                            1f to RoyalVault.copy(alpha = 0.98f),
                        ),
                    ),
            )
            if (movie.inJellyfin == true) {
                RoyalStatusChip(
                    "In Jellyfin",
                    tone = RoyalStatusTone.Success,
                    prominent = true,
                    modifier = Modifier.align(Alignment.TopEnd).padding(10.dp),
                )
            }
            Column(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .fillMaxWidth()
                    .padding(13.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(
                    movie.title,
                    color = RoyalText,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    if (movie.year.isNotBlank()) {
                        Text(movie.year, color = RoyalTextMuted, style = MaterialTheme.typography.labelMedium)
                    }
                    movie.rating?.takeIf { it > 0 }?.let {
                        Text("★ %.1f".format(it), color = RoyalGoldBright, style = MaterialTheme.typography.labelMedium)
                    }
                }
                if (movie.description.isNotBlank()) {
                    Text(
                        movie.description,
                        color = RoyalTextMuted,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
        val rankModifier = Modifier
            .align(Alignment.BottomStart)
            .offset(x = (-4).dp, y = (-4).dp)
            .zIndex(3f)
        Text(
            text = rank.toString(),
            modifier = rankModifier,
            color = RoyalVault.copy(alpha = 0.94f),
            fontFamily = Outfit,
            fontWeight = FontWeight.Black,
            fontSize = 150.sp,
            lineHeight = 150.sp,
        )
        Text(
            text = rank.toString(),
            modifier = rankModifier,
            color = androidx.compose.ui.graphics.Color.White.copy(alpha = 0.96f),
            fontFamily = Outfit,
            fontWeight = FontWeight.Black,
            fontSize = 150.sp,
            lineHeight = 150.sp,
            style = MaterialTheme.typography.displayLarge.copy(
                drawStyle = Stroke(width = 5f),
            ),
        )
    }
}
