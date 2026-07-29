package de.royaldownloader.app.ui.detail

import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import de.royaldownloader.app.data.remote.*
import de.royaldownloader.app.ui.components.*
import de.royaldownloader.app.ui.theme.*
import de.royaldownloader.app.ui.watchlist.checkedAtLabel
import de.royaldownloader.app.ui.watchlist.cleanupModeExplanation
import de.royaldownloader.app.ui.watchlist.cleanupModeLabel
import de.royaldownloader.app.ui.watchlist.statusLabel
import de.royaldownloader.app.ui.watchlist.statusTone
import de.royaldownloader.app.ui.watchlist.watchModeExplanation
import de.royaldownloader.app.ui.watchlist.watchModeLabel
import de.royaldownloader.app.ui.watchlist.watchModeTitle
import java.text.NumberFormat
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable
fun DetailScreen(
    viewModel: DetailViewModel,
    kind: DetailKind,
    onBack: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    val context = LocalContext.current
    var editSubscription by remember { mutableStateOf(false) }
    LaunchedEffect(state.message) {
        state.message?.let { snackbar.showSnackbar(it); viewModel.clearMessage() }
    }
    LaunchedEffect(state.actionError) {
        state.actionError?.let { snackbar.showSnackbar(it.message); viewModel.clearActionError() }
    }
    Scaffold(
        containerColor = androidx.compose.ui.graphics.Color.Transparent,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (!state.loading && state.error == null) {
                DetailActions(state, kind, viewModel)
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize()) {
            when {
                state.loading -> RoyalLoadingState("Details werden geladen …", Modifier.fillMaxSize())
                state.error != null -> RoyalErrorState(
                    "Details nicht verfügbar",
                    state.error?.message.orEmpty(),
                    "Erneut laden",
                    viewModel::retry,
                    Modifier.fillMaxSize(),
                )
                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(bottom = padding.calculateBottomPadding() + 24.dp),
                ) {
                    item {
                        when (kind) {
                            DetailKind.MOVIE -> state.movie?.let { movie ->
                                MovieHero(
                                    movie = movie,
                                    onPlayTrailer = {
                                        youtubeVideoId(movie.trailer)?.let { videoId ->
                                            context.startActivity(
                                                TrailerPlayerActivity.intent(
                                                    context,
                                                    videoId,
                                                    movie.trailer?.name.orEmpty(),
                                                ),
                                            )
                                        }
                                    },
                                )
                            }
                            DetailKind.SERIES -> state.series?.let { series ->
                                SeriesHero(
                                    series = series,
                                    onPlayTrailer = {
                                        youtubeVideoId(series.trailer)?.let { videoId ->
                                            context.startActivity(
                                                TrailerPlayerActivity.intent(
                                                    context,
                                                    videoId,
                                                    series.trailer?.name.orEmpty(),
                                                ),
                                            )
                                        }
                                    },
                                    onSubscription = { editSubscription = true },
                                )
                            }
                            DetailKind.ANIME -> state.anime?.let { MediaHero(it.bannerUrl, it.coverUrl, it.title, it.year, it.mediaType, "EN", anime = true) }
                        }
                    }
                    item { Spacer(Modifier.height(18.dp)) }
                    when (kind) {
                        DetailKind.MOVIE -> state.movie?.let { movieContent(it) }
                        DetailKind.SERIES -> state.series?.let { series ->
                            seriesContent(
                                series,
                                state.selectedEpisodes,
                                viewModel::toggleEpisode,
                                onEditSubscription = { editSubscription = true },
                            )
                        }
                        DetailKind.ANIME -> state.anime?.let {
                            animeContent(
                                it,
                                state.selectedTranslation,
                                state.selectedEpisodes,
                                viewModel::selectTranslation,
                                viewModel::toggleEpisode,
                                viewModel::previousAnimePage,
                                viewModel::nextAnimePage,
                            )
                        }
                    }
                }
            }
            RoyalIconButton(
                onClick = onBack,
                modifier = Modifier
                    .statusBarsPadding()
                    .padding(12.dp)
                    .align(Alignment.TopStart),
            ) { Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Zurück") }
        }
    }
    if (editSubscription) {
        state.series?.let { series ->
            SubscriptionSettingsDialog(
                series = series,
                busy = state.actionBusy,
                onDismiss = { if (!state.actionBusy) editSubscription = false },
                onSave = { downloadMode, cleanupMode ->
                    viewModel.saveSeriesSubscription(downloadMode, cleanupMode)
                    editSubscription = false
                },
            )
        }
    }
}

@Composable
private fun DetailActions(state: DetailState, kind: DetailKind, viewModel: DetailViewModel) {
    Surface(color = RoyalVault.copy(alpha = 0.98f), shadowElevation = 12.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            when (kind) {
                DetailKind.MOVIE -> RoyalPrimaryButton(
                    viewModel::queueMovie,
                    Modifier.fillMaxWidth(),
                    enabled = !state.actionBusy,
                ) {
                    Icon(Icons.Rounded.Download, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(if (state.actionBusy) "Wird eingeplant …" else "Film herunterladen")
                }
                DetailKind.SERIES, DetailKind.ANIME -> RoyalPrimaryButton(
                    viewModel::queueSelected,
                    Modifier.fillMaxWidth(),
                    enabled = !state.actionBusy && state.selectedEpisodes.isNotEmpty(),
                ) {
                    Icon(Icons.Rounded.Download, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        if (state.selectedEpisodes.isEmpty()) "Episoden auswählen"
                        else "${state.selectedEpisodes.size} herunterladen",
                    )
                }
            }
        }
    }
}

@Composable
private fun MediaHero(
    backdrop: String,
    cover: String,
    title: String,
    year: String,
    source: String,
    language: String,
    anime: Boolean = false,
) {
    Box(modifier = Modifier.fillMaxWidth().height(330.dp)) {
        AsyncImage(
            model = backdrop.ifBlank { cover },
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop,
            alpha = 0.58f,
        )
        Box(
            Modifier.fillMaxSize().background(
                androidx.compose.ui.graphics.Brush.verticalGradient(
                    listOf(androidx.compose.ui.graphics.Color.Transparent, RoyalVault),
                ),
            ),
        )
        Row(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth()
                .padding(horizontal = 18.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            AsyncImage(
                model = cover,
                contentDescription = "Poster zu $title",
                modifier = Modifier
                    .width(108.dp)
                    .aspectRatio(2f / 3f)
                    .clip(MaterialTheme.shapes.medium),
                contentScale = ContentScale.Crop,
            )
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                RoyalArchiveLabel(if (anime) "ANIME ARCHIVE" else "ROYAL COLLECTION")
                Text(title, color = RoyalText, style = MaterialTheme.typography.headlineMedium, maxLines = 3, overflow = TextOverflow.Ellipsis)
                Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    if (year.isNotBlank()) RoyalStatusChip(year)
                    if (source.isNotBlank()) RoyalStatusChip(source, tone = if (anime) RoyalStatusTone.Anime else RoyalStatusTone.Neutral)
                    if (language.isNotBlank()) RoyalStatusChip(language.uppercase(), tone = RoyalStatusTone.Active)
                }
            }
        }
    }
}

@Composable
private fun SeriesHero(
    series: SeriesDetail,
    onPlayTrailer: () -> Unit,
    onSubscription: () -> Unit,
) {
    val seasonCount = series.seasons.size
    val episodeCount = series.episodeCount.takeIf { it > 0 }
        ?: series.seasons.sumOf { it.episodes.size }
    Box(modifier = Modifier.fillMaxWidth().height(560.dp)) {
        AsyncImage(
            model = series.backdropUrl.ifBlank { series.coverUrl },
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop,
        )
        Box(
            Modifier.fillMaxSize().background(
                androidx.compose.ui.graphics.Brush.verticalGradient(
                    0f to RoyalVault.copy(alpha = 0.03f),
                    0.42f to RoyalVault.copy(alpha = 0.28f),
                    0.72f to RoyalVault.copy(alpha = 0.82f),
                    1f to RoyalVault,
                ),
            ),
        )
        Box(
            Modifier.fillMaxSize().background(
                androidx.compose.ui.graphics.Brush.horizontalGradient(
                    listOf(RoyalVault.copy(alpha = 0.70f), RoyalVault.copy(alpha = 0.02f)),
                ),
            ),
        )
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 22.dp),
            verticalArrangement = Arrangement.spacedBy(11.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Box(Modifier.width(4.dp).height(20.dp).background(RoyalCinemaRed))
                RoyalArchiveLabel(
                    if (series.watchlisted) "ROYAL ORIGINAL · ABONNIERT" else "ROYAL SERIE",
                    color = RoyalText,
                )
            }
            Text(
                series.title,
                color = androidx.compose.ui.graphics.Color.White,
                style = MaterialTheme.typography.displaySmall.copy(
                    fontFamily = Outfit,
                    fontWeight = FontWeight.Black,
                ),
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(9.dp),
                verticalArrangement = Arrangement.spacedBy(7.dp),
            ) {
                series.rating?.takeIf { it > 0 }?.let {
                    Text(
                        "★ %.1f".format(it),
                        color = RoyalSuccess,
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
                if (series.year.isNotBlank()) {
                    Text(series.year, color = RoyalText, style = MaterialTheme.typography.labelLarge)
                }
                Text(
                    "$seasonCount ${if (seasonCount == 1) "Staffel" else "Staffeln"}",
                    color = RoyalText,
                    style = MaterialTheme.typography.labelLarge,
                )
                Text(
                    "$episodeCount Episoden",
                    color = RoyalText,
                    style = MaterialTheme.typography.labelLarge,
                )
                if (series.runtime.isNotBlank()) {
                    Text(series.runtime, color = RoyalText, style = MaterialTheme.typography.labelLarge)
                }
            }
            Text(
                series.description.ifBlank { "Alle Staffeln, Episoden und Abo-Regeln auf einen Blick." },
                color = RoyalText.copy(alpha = 0.88f),
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (youtubeVideoId(series.trailer) != null) {
                    Button(
                        onClick = onPlayTrailer,
                        modifier = Modifier.weight(1f),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = androidx.compose.ui.graphics.Color.White,
                            contentColor = androidx.compose.ui.graphics.Color.Black,
                        ),
                    ) {
                        Icon(Icons.Rounded.PlayArrow, contentDescription = null)
                        Spacer(Modifier.width(7.dp))
                        Text("Trailer", fontWeight = FontWeight.Bold)
                    }
                }
                Button(
                    onClick = onSubscription,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = RoyalRaised.copy(alpha = 0.92f),
                        contentColor = RoyalText,
                    ),
                ) {
                    Icon(
                        if (series.watchlisted) Icons.Rounded.Tune else Icons.Rounded.Add,
                        contentDescription = null,
                    )
                    Spacer(Modifier.width(7.dp))
                    Text(if (series.watchlisted) "Abo verwalten" else "Abonnieren")
                }
            }
        }
    }
}

@Composable
private fun MovieHero(
    movie: MovieDetail,
    onPlayTrailer: () -> Unit,
) {
    Box(modifier = Modifier.fillMaxWidth().height(510.dp)) {
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
                    androidx.compose.ui.graphics.Brush.verticalGradient(
                        0f to RoyalVault.copy(alpha = 0.04f),
                        0.52f to RoyalVault.copy(alpha = 0.38f),
                        1f to RoyalVault,
                    ),
                ),
        )
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    androidx.compose.ui.graphics.Brush.horizontalGradient(
                        listOf(RoyalVault.copy(alpha = 0.82f), RoyalVault.copy(alpha = 0.06f)),
                    ),
                ),
        )
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 22.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.width(4.dp).height(20.dp).background(RoyalCinemaRed))
                RoyalArchiveLabel("ROYAL FEATURE", color = RoyalText)
            }
            Text(
                movie.title,
                color = RoyalText,
                style = MaterialTheme.typography.displaySmall,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
            )
            if (movie.tagline.isNotBlank()) {
                Text(
                    movie.tagline,
                    color = RoyalText.copy(alpha = 0.86f),
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (movie.year.isNotBlank()) RoyalStatusChip(movie.year)
                movie.rating?.takeIf { it > 0 }?.let {
                    RoyalStatusChip("★ %.1f".format(it), tone = RoyalStatusTone.Active)
                }
                if (movie.certification.isNotBlank()) {
                    RoyalStatusChip(
                        if (movie.certificationCountry == "DE") "FSK ${movie.certification}" else movie.certification,
                    )
                }
                if (movie.runtime.isNotBlank()) RoyalStatusChip(movie.runtime)
            }
            if (youtubeVideoId(movie.trailer) != null) {
                RoyalSecondaryButton(onClick = onPlayTrailer, modifier = Modifier.widthIn(min = 178.dp)) {
                    Icon(Icons.Rounded.PlayArrow, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Trailer")
                }
            }
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.movieContent(movie: MovieDetail) {
    item {
        DetailSection("HANDLUNG", "Die Geschichte") {
            if (movie.tagline.isNotBlank()) {
                Text(
                    "„${movie.tagline}“",
                    color = RoyalGoldBright,
                    style = MaterialTheme.typography.titleMedium,
                )
                Spacer(Modifier.height(4.dp))
            }
            Text(
                movie.description.ifBlank { "Keine Beschreibung verfügbar." },
                color = RoyalText,
                style = MaterialTheme.typography.bodyLarge,
            )
        }
    }
    item {
        DetailSection("AUF EINEN BLICK", "Filmdaten") {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(
                    movie.runtime,
                    movie.releaseDate.takeIf { it.isNotBlank() }?.let(::formatMovieDate),
                    movie.certification.takeIf { it.isNotBlank() }?.let {
                        if (movie.certificationCountry == "DE") "FSK $it" else it
                    },
                    movie.rating?.let { "★ %.1f · %s Stimmen".format(it, formatCompactNumber(movie.voteCount ?: 0)) },
                    movie.status,
                    movie.metadataSource,
                )
                    .filterNotNull().filter { it.isNotBlank() }.forEach { RoyalStatusChip(it) }
                movie.genres.forEach { RoyalStatusChip(it, tone = RoyalStatusTone.Selected) }
            }
            if (movie.originalTitle.isNotBlank() && movie.originalTitle != movie.title) {
                Spacer(Modifier.height(8.dp))
                DetailKeyValue("Originaltitel", movie.originalTitle)
            }
        }
    }
    if (movie.hosters.isNotEmpty() || movie.sourceProviders.isNotEmpty()) {
        item {
            DetailSection(
                "VERFÜGBARKEIT",
                if (movie.providerCount > 0) {
                    "${movie.providerCount} Anbieter · ${movie.hosterTotal} Hoster"
                } else {
                    "${movie.hosters.size} Streaming-Quellen"
                },
            ) {
                if (movie.sourceProviders.isNotEmpty()) {
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        movie.sourceProviders.forEach { source ->
                            RoyalStatusChip(
                                "${source.label} · ${source.hosterCount} Hoster",
                                tone = RoyalStatusTone.Active,
                            )
                        }
                    }
                    Spacer(Modifier.height(10.dp))
                }
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    movie.hosters.forEach { hoster ->
                        RoyalStatusChip(
                            listOf(hoster.name, hoster.quality, hoster.language.uppercase())
                                .filter { it.isNotBlank() }
                                .joinToString(" · "),
                            tone = RoyalStatusTone.Success,
                        )
                    }
                }
                Spacer(Modifier.height(10.dp))
                DetailKeyValue(
                    "Anbieter-Reihenfolge",
                    movie.providerRoute.ifBlank { movie.hosterRoute.ifBlank { movie.hosterLabel } },
                )
                movie.hosterScore?.let { DetailKeyValue("Qualitätswert", "${it.toInt()} / 100") }
                if (movie.providerFallbackCount > 0 || movie.hosterFallbackCount > 0) {
                    DetailKeyValue(
                        "Fallbacks",
                        "${movie.providerFallbackCount} Anbieter · ${movie.hosterFallbackCount} Hoster",
                    )
                }
            }
        }
    }
    if (movie.cast.isNotEmpty()) {
        item {
            Column(
                modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                RoyalSectionHeader(
                    "Besetzung",
                    label = "CAST",
                    modifier = Modifier.padding(horizontal = 18.dp),
                )
                LazyRow(
                    contentPadding = PaddingValues(horizontal = 18.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(movie.cast.take(12), key = { "${it.name}:${it.character}" }) { member ->
                        CastCard(member)
                    }
                }
            }
        }
    }
    if (movie.directors.isNotEmpty() || movie.writers.isNotEmpty() || movie.productionCompanies.isNotEmpty()) {
        item {
            DetailSection("HINTER DER KAMERA", "Stab & Produktion") {
                if (movie.directors.isNotEmpty()) DetailKeyValue("Regie", movie.directors.joinToString())
                if (movie.writers.isNotEmpty()) DetailKeyValue("Drehbuch", movie.writers.joinToString())
                if (movie.productionCompanies.isNotEmpty()) {
                    DetailKeyValue("Studios", movie.productionCompanies.joinToString())
                }
                if (movie.collection.isNotBlank()) DetailKeyValue("Reihe", movie.collection)
            }
        }
    }
    if (movie.keywords.isNotEmpty()) {
        item {
            DetailSection("THEMEN", "Schlagwörter") {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    movie.keywords.forEach { RoyalStatusChip(it, tone = RoyalStatusTone.Selected) }
                }
            }
        }
    }
    if (
        movie.countries.isNotEmpty() || movie.spokenLanguages.isNotEmpty() ||
        movie.budget > 0 || movie.revenue > 0
    ) {
        item {
            DetailSection("PRODUKTION", "Veröffentlichung & Zahlen") {
                if (movie.countries.isNotEmpty()) DetailKeyValue("Länder", movie.countries.joinToString())
                if (movie.spokenLanguages.isNotEmpty()) {
                    DetailKeyValue("Sprachen", movie.spokenLanguages.joinToString())
                }
                if (movie.budget > 0) DetailKeyValue("Budget", formatMovieMoney(movie.budget))
                if (movie.revenue > 0) DetailKeyValue("Einspielergebnis", formatMovieMoney(movie.revenue))
            }
        }
    }
}

@Composable
private fun CastCard(member: CastMember) {
    RoyalInsetPanel(
        modifier = Modifier.width(132.dp),
        contentPadding = PaddingValues(0.dp),
    ) {
        AsyncImage(
            model = member.profileUrl,
            contentDescription = member.name,
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(3f / 4f)
                .clip(MaterialTheme.shapes.medium),
            contentScale = ContentScale.Crop,
        )
        Column(
            modifier = Modifier.padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Text(
                member.name,
                color = RoyalText,
                style = MaterialTheme.typography.labelLarge,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                member.character.ifBlank { "Besetzung" },
                color = RoyalTextMuted,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun DetailKeyValue(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            label.uppercase(),
            modifier = Modifier.width(104.dp),
            color = RoyalTextFaint,
            style = MaterialTheme.typography.labelSmall,
        )
        Text(
            value,
            modifier = Modifier.weight(1f),
            color = RoyalText,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

private fun formatMovieDate(value: String): String = runCatching {
    LocalDate.parse(value).format(DateTimeFormatter.ofPattern("dd.MM.yyyy"))
}.getOrDefault(value)

private fun formatCompactNumber(value: Int): String = when {
    value >= 1_000_000 -> "%.1f Mio.".format(value / 1_000_000.0)
    value >= 1_000 -> "%.1f Tsd.".format(value / 1_000.0)
    value > 0 -> value.toString()
    else -> "–"
}

private fun formatMovieMoney(value: Long): String =
    NumberFormat.getCurrencyInstance(Locale.US).format(value)

internal fun youtubeVideoId(trailer: MovieTrailer?): String? {
    if (!trailer?.site.equals("YouTube", ignoreCase = true)) return null
    return trailer?.key?.takeIf { YOUTUBE_VIDEO_ID.matches(it) }
}

private val YOUTUBE_VIDEO_ID = Regex("^[A-Za-z0-9_-]{6,20}$")

private fun androidx.compose.foundation.lazy.LazyListScope.seriesContent(
    series: SeriesDetail,
    selected: Set<String>,
    onToggle: (String) -> Unit,
    onEditSubscription: () -> Unit,
) {
    item {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            RoyalSectionHeader("Über ${series.title}", label = "DIE SERIE")
            Text(
                series.description.ifBlank { "Keine Beschreibung verfügbar." },
                color = RoyalText,
                style = MaterialTheme.typography.bodyLarge,
            )
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                series.genres.forEach { RoyalStatusChip(it, tone = RoyalStatusTone.Selected) }
                if (series.status.isNotBlank()) RoyalStatusChip(series.status)
                if (series.providerLabel.isNotBlank()) RoyalStatusChip(series.providerLabel)
                if (series.contentLanguage.isNotBlank()) {
                    RoyalStatusChip(series.contentLanguage.uppercase(), tone = RoyalStatusTone.Active)
                }
            }
            if (series.originalTitle.isNotBlank() && series.originalTitle != series.title) {
                DetailKeyValue("Originaltitel", series.originalTitle)
            }
        }
    }
    item {
        SeriesFacts(series)
    }
    if (series.watchlisted) {
        item {
            SubscriptionSection(series, onEditSubscription)
        }
    }
    if (series.availabilityPending || series.availabilityError.isNotBlank() || series.jellyfinAvailable == false) {
        item {
            val message = when {
                series.availabilityError.isNotBlank() -> series.availabilityError
                series.jellyfinAvailable == false ->
                    "Jellyfin konnte nicht eindeutig abgeglichen werden. Die Episodenauswahl ist vorsorglich eingeschränkt."
                else -> "Bestand, Veröffentlichungen und Metadaten werden noch geprüft."
            }
            RoyalConnectionBanner(
                title = "Verfügbarkeitsprüfung",
                message = message,
                tone = if (series.availabilityError.isNotBlank()) RoyalStatusTone.Error else RoyalStatusTone.Warning,
                modifier = Modifier.padding(horizontal = 18.dp, vertical = 6.dp),
            )
        }
    }
    item {
        SeriesEpisodeBrowser(series, selected, onToggle)
    }
}

@Composable
private fun SeriesFacts(series: SeriesDetail) {
    val episodeCount = series.episodeCount.takeIf { it > 0 }
        ?: series.seasons.sumOf { it.episodes.size }
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        SeriesFact(
            value = series.seasons.size.toString(),
            label = if (series.seasons.size == 1) "Staffel" else "Staffeln",
            modifier = Modifier.weight(1f),
        )
        SeriesFact(
            value = episodeCount.toString(),
            label = "Episoden",
            modifier = Modifier.weight(1f),
        )
        SeriesFact(
            value = series.rating?.takeIf { it > 0 }?.let { "%.1f".format(it) } ?: "–",
            label = "TMDB-Wertung",
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun SeriesFact(value: String, label: String, modifier: Modifier = Modifier) {
    RoyalInsetPanel(
        modifier = modifier,
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 14.dp),
    ) {
        Text(
            value,
            color = RoyalGoldBright,
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        Text(
            label.uppercase(),
            color = RoyalTextFaint,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
    }
}

@Composable
private fun SeriesEpisodeBrowser(
    series: SeriesDetail,
    selected: Set<String>,
    onToggle: (String) -> Unit,
) {
    val initialSeason = series.seasons.firstOrNull()?.season ?: 0
    var selectedSeason by remember(series.baseSlug, series.seasons) {
        mutableIntStateOf(initialSeason)
    }
    val season = series.seasons.firstOrNull { it.season == selectedSeason }
        ?: series.seasons.firstOrNull()
    Column(
        modifier = Modifier.fillMaxWidth().padding(top = 14.dp, bottom = 6.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            RoyalSectionHeader(
                title = "Episoden",
                label = "JETZT ANSEHEN",
                modifier = Modifier.weight(1f),
            )
            Text(
                "${selected.size} ausgewählt",
                color = if (selected.isEmpty()) RoyalTextFaint else RoyalGoldBright,
                style = MaterialTheme.typography.labelMedium,
            )
        }
        LazyRow(
            contentPadding = PaddingValues(horizontal = 18.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(series.seasons, key = { it.season }) { item ->
                RoyalFilterChip(
                    selected = item.season == season?.season,
                    onClick = { selectedSeason = item.season },
                    label = "Staffel ${item.season}",
                )
            }
        }
        AnimatedContent(
            targetState = season,
            label = "Staffelwechsel",
        ) { activeSeason ->
            Column(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp),
                verticalArrangement = Arrangement.spacedBy(9.dp),
            ) {
                activeSeason?.episodes.orEmpty().forEach { episode ->
                    SeriesEpisodeRow(
                        episode = episode,
                        selected = episode.slug in selected,
                        onClick = { onToggle(episode.slug) },
                    )
                }
            }
        }
    }
}

@Composable
private fun SeriesEpisodeRow(
    episode: Episode,
    selected: Boolean,
    onClick: () -> Unit,
) {
    val status = when {
        episode.inJellyfin -> "In Jellyfin"
        episode.downloaded -> "Geladen"
        episode.queued -> "In Queue"
        episode.unreleased -> "Noch nicht erschienen"
        else -> "Zum Download verfügbar"
    }
    val disabled = episode.queued || episode.downloaded || episode.inJellyfin || episode.unreleased
    val shape = MaterialTheme.shapes.medium
    Surface(
        onClick = onClick,
        enabled = !disabled,
        modifier = Modifier
            .fillMaxWidth()
            .border(
                width = if (selected) 2.dp else 1.dp,
                color = if (selected) RoyalGold else RoyalGoldBorder,
                shape = shape,
            ),
        shape = shape,
        color = if (selected) RoyalRaised else RoyalObsidian,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 13.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(13.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(46.dp)
                    .clip(MaterialTheme.shapes.small)
                    .background(if (selected) RoyalGold else RoyalAmethyst),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    episode.episode.toString(),
                    color = if (selected) RoyalInk else RoyalText,
                    style = MaterialTheme.typography.titleLarge,
                )
            }
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    "Episode ${episode.episode}",
                    color = RoyalText,
                    style = MaterialTheme.typography.titleMedium,
                )
                Text(
                    status,
                    color = when {
                        episode.inJellyfin || episode.downloaded -> RoyalSuccess
                        episode.queued -> RoyalWarning
                        episode.unreleased -> RoyalTextFaint
                        else -> RoyalTextMuted
                    },
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            if (!disabled) {
                Icon(
                    if (selected) Icons.Rounded.CheckCircle else Icons.Rounded.AddCircleOutline,
                    contentDescription = if (selected) "Auswahl entfernen" else "Episode auswählen",
                    tint = if (selected) RoyalGoldBright else RoyalTextMuted,
                )
            } else {
                Icon(
                    Icons.Rounded.Lock,
                    contentDescription = status,
                    tint = RoyalTextFaint,
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}

@Composable
private fun SubscriptionSection(series: SeriesDetail, onEdit: () -> Unit) {
    val subscription = series.subscription
    val mode = subscription?.downloadMode ?: series.watchMode
    val cleanup = subscription?.cleanupMode ?: series.cleanupMode
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        RoyalSectionHeader("Dein Serien-Abo", label = "WEITERSEHEN")
        RoyalPanel(
            modifier = Modifier.fillMaxWidth(),
            variant = RoyalPanelVariant.Selected,
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Icon(Icons.Rounded.Bookmark, contentDescription = null, tint = RoyalGoldBright)
                Column(modifier = Modifier.weight(1f)) {
                    Text(watchModeLabel(mode), color = RoyalText, style = MaterialTheme.typography.titleMedium)
                    Text("Royal prüft diese Serie automatisch", color = RoyalTextMuted, style = MaterialTheme.typography.bodySmall)
                }
            }
            Spacer(Modifier.height(12.dp))
            if (subscription != null) {
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    RoyalStatusChip(statusLabel(subscription), tone = statusTone(subscription))
                    if (subscription.newCount > 0) RoyalStatusChip("${subscription.newCount} offen", tone = RoyalStatusTone.Active)
                    if (subscription.queuedCount > 0) RoyalStatusChip("${subscription.queuedCount} in Queue", tone = RoyalStatusTone.Queued)
                    if (subscription.failedCount > 0) RoyalStatusChip("${subscription.failedCount} Fehler", tone = RoyalStatusTone.Error)
                }
                Spacer(Modifier.height(10.dp))
            } else {
                RoyalStatusChip("Abonniert", tone = RoyalStatusTone.Success)
                Spacer(Modifier.height(10.dp))
            }
            Text(watchModeTitle(mode), color = RoyalText, style = MaterialTheme.typography.titleMedium)
            Text(watchModeExplanation(mode), color = RoyalTextMuted, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(9.dp))
            Text(cleanupModeLabel(cleanup), color = RoyalText, style = MaterialTheme.typography.titleSmall)
            Text(cleanupModeExplanation(cleanup), color = RoyalTextMuted, style = MaterialTheme.typography.bodyMedium)
            subscription?.let {
                Spacer(Modifier.height(9.dp))
                Text(checkedAtLabel(it.lastChecked), color = RoyalTextMuted, style = MaterialTheme.typography.labelMedium)
                if (it.lastError.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(it.lastError, color = RoyalError, style = MaterialTheme.typography.bodySmall)
                }
            }
            Spacer(Modifier.height(12.dp))
            RoyalSecondaryButton(onClick = onEdit, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Rounded.Tune, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Abo-Regel ändern")
            }
        }
    }
}

@Composable
private fun SubscriptionSettingsDialog(
    series: SeriesDetail,
    busy: Boolean,
    onDismiss: () -> Unit,
    onSave: (downloadMode: String, cleanupMode: String) -> Unit,
) {
    var downloadMode by remember(series.baseSlug, series.watchMode) {
        mutableStateOf(series.watchMode.ifBlank { "latest_season" })
    }
    var cleanupMode by remember(series.baseSlug, series.cleanupMode) {
        mutableStateOf(series.cleanupMode.ifBlank { "keep" })
    }
    val jellyfinRulesAvailable =
        series.jellyfinConfigured && series.jellyfinAvailable != false
    LaunchedEffect(jellyfinRulesAvailable) {
        if (!jellyfinRulesAvailable) {
            if (downloadMode == "next_season") downloadMode = "latest_season"
            if (cleanupMode != "keep") cleanupMode = "keep"
        }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            usePlatformDefaultWidth = false,
            decorFitsSystemWindows = false,
        ),
    ) {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = RoyalVault,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .statusBarsPadding()
                    .navigationBarsPadding()
                    .imePadding(),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "Abo-Einstellung",
                        modifier = Modifier.weight(1f),
                        color = RoyalGoldBright,
                        style = MaterialTheme.typography.headlineSmall,
                    )
                    RoyalIconButton(onClick = onDismiss, enabled = !busy) {
                        Icon(Icons.Rounded.Close, contentDescription = "Abo-Einstellung schließen")
                    }
                }
                HorizontalDivider(color = RoyalGoldBorder)
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(horizontal = 18.dp, vertical = 20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    item {
                        RoyalArchiveLabel("DOWNLOADUMFANG")
                        Spacer(Modifier.height(5.dp))
                        Text(
                            series.title,
                            color = RoyalText,
                            style = MaterialTheme.typography.headlineMedium,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "Lege fest, welche fehlenden Folgen zu diesem Abo gehören. Die Regel gilt sofort und bei jeder späteren Prüfung.",
                            color = RoyalTextMuted,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Spacer(Modifier.height(10.dp))
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(9.dp),
                            verticalAlignment = Alignment.Top,
                        ) {
                            Icon(
                                Icons.Rounded.CheckCircle,
                                contentDescription = null,
                                tint = RoyalSuccess,
                                modifier = Modifier.size(20.dp),
                            )
                            Text(
                                "Bereits in Jellyfin oder im Serienordner vorhandene Folgen werden übersprungen.",
                                color = RoyalText,
                                style = MaterialTheme.typography.bodySmall,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }
                    item {
                        SubscriptionOptionCard(
                            selected = downloadMode == "all",
                            glyph = "S1 · S2 · …",
                            title = "Alles Fehlende",
                            tag = "KOMPLETT",
                            description = "Berücksichtigt Lücken in allen verfügbaren Staffeln.",
                            example = "Bei S1–S4 werden fehlende Folgen aus jeder Staffel geladen.",
                            onClick = { downloadMode = "all" },
                        )
                    }
                    item {
                        SubscriptionOptionCard(
                            selected = downloadMode == "latest_season",
                            glyph = "– · – · MAX",
                            title = "Nur neueste Staffel",
                            tag = "AKTUELL",
                            description = "Berücksichtigt nur Lücken in der aktuell höchsten Staffel.",
                            example = "Bei S1–S4 wird S4 vervollständigt. Später rückt S5 nach.",
                            onClick = { downloadMode = "latest_season" },
                        )
                    }
                    item {
                        SubscriptionOptionCard(
                            selected = downloadMode == "next_season",
                            enabled = jellyfinRulesAvailable,
                            glyph = "✓  →  +1",
                            title = "Nach Gesehen-Status",
                            tag = "JELLYFIN",
                            description = "Gibt immer nur die nächste noch nicht vollständig gesehene Staffel frei.",
                            example = "S1 vollständig gesehen → S2 laden. Danach wartet das Abo.",
                            onClick = { downloadMode = "next_season" },
                        )
                    }
                    item {
                        RoyalInsetPanel(
                            modifier = Modifier.fillMaxWidth(),
                            borderColor = RoyalGoldBorderStrong,
                        ) {
                            Row(horizontalArrangement = Arrangement.spacedBy(11.dp)) {
                                Box(
                                    modifier = Modifier
                                        .size(40.dp)
                                        .clip(MaterialTheme.shapes.small)
                                        .background(RoyalGold.copy(alpha = 0.12f)),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Icon(Icons.Rounded.Info, contentDescription = null, tint = RoyalGoldBright)
                                }
                                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                                    RoyalArchiveLabel("WAS DANACH PASSIERT")
                                    Text(
                                        watchModeTitle(downloadMode),
                                        color = RoyalText,
                                        style = MaterialTheme.typography.titleMedium,
                                    )
                                    Text(
                                        watchModeExplanation(downloadMode),
                                        color = RoyalTextMuted,
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                }
                            }
                        }
                    }
                    item {
                        Spacer(Modifier.height(4.dp))
                        HorizontalDivider(color = RoyalGoldBorder)
                        Spacer(Modifier.height(18.dp))
                        RoyalArchiveLabel("NACH DEM ANSEHEN")
                        Spacer(Modifier.height(5.dp))
                        Text(
                            "Speicher automatisch freigeben",
                            color = RoyalText,
                            style = MaterialTheme.typography.headlineSmall,
                        )
                        Text(
                            "Du kannst für diese Serie festlegen, was nach dem Jellyfin-Abgleich passiert.",
                            color = RoyalTextMuted,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    item {
                        SubscriptionOptionCard(
                            selected = cleanupMode == "keep",
                            glyph = "◆",
                            title = "Behalten",
                            tag = "SICHER",
                            description = "Gesehene Episoden und Staffeln bleiben in Jellyfin.",
                            example = "Es werden keine Mediendateien automatisch gelöscht.",
                            onClick = { cleanupMode = "keep" },
                        )
                    }
                    item {
                        SubscriptionOptionCard(
                            selected = cleanupMode == "watched_seasons",
                            enabled = jellyfinRulesAvailable,
                            glyph = "S✓",
                            title = "Staffel komplett gesehen → löschen",
                            tag = "JELLYFIN",
                            description = "Eine Staffel wird erst nach der letzten regulären Folge freigegeben.",
                            example = "Nur vollständig gesehene Staffeln werden beim nächsten Check entfernt.",
                            onClick = { cleanupMode = "watched_seasons" },
                        )
                    }
                    item {
                        SubscriptionOptionCard(
                            selected = cleanupMode == "watched_episodes",
                            enabled = jellyfinRulesAvailable,
                            glyph = "E✓",
                            title = "Episode gesehen → löschen",
                            tag = "JELLYFIN",
                            description = "Jede als gesehen markierte Episode wird einzeln freigegeben.",
                            example = "Die Datei wird beim nächsten Abo-Check entfernt.",
                            onClick = { cleanupMode = "watched_episodes" },
                        )
                    }
                    if (!jellyfinRulesAvailable) {
                        item {
                            RoyalConnectionBanner(
                                title = "Jellyfin-Regeln nicht verfügbar",
                                message = "Gesehen-Status und automatisches Löschen benötigen einen erreichbaren Jellyfin-Benutzer.",
                                tone = RoyalStatusTone.Warning,
                            )
                        }
                    } else if (cleanupMode != "keep") {
                        item {
                            RoyalConnectionBanner(
                                title = "Dauerhafte Aktion",
                                message = "Jellyfin kann dabei die zugehörige Mediendatei löschen. Eine Löschberechtigung ist erforderlich.",
                                tone = RoyalStatusTone.Error,
                            )
                        }
                    }
                }
                HorizontalDivider(color = RoyalGoldBorder)
                Row(
                    modifier = Modifier.fillMaxWidth().padding(14.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    RoyalSecondaryButton(
                        onClick = onDismiss,
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                    ) {
                        Text("Abbrechen")
                    }
                    RoyalPrimaryButton(
                        onClick = { onSave(downloadMode, cleanupMode) },
                        modifier = Modifier.weight(1f),
                        enabled = !busy,
                    ) {
                        Text(if (busy) "Speichert …" else "Abo speichern")
                    }
                }
            }
        }
    }
}

@Composable
private fun SubscriptionOptionCard(
    selected: Boolean,
    glyph: String,
    title: String,
    tag: String,
    description: String,
    example: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
) {
    val outerShape = MaterialTheme.shapes.large
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (selected) {
                    Modifier
                        .border(3.dp, RoyalGold, outerShape)
                        .padding(4.dp)
                } else {
                    Modifier
                },
            ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(outerShape)
                .background(
                    if (selected) RoyalGold.copy(alpha = 0.10f)
                    else RoyalObsidian.copy(alpha = 0.92f),
                )
                .border(
                    1.dp,
                    if (selected) RoyalGoldBright else RoyalGoldBorder,
                    outerShape,
                )
                .clickable(enabled = enabled, role = Role.RadioButton, onClick = onClick)
                .padding(16.dp)
                .alpha(if (enabled) 1f else 0.48f),
            horizontalArrangement = Arrangement.spacedBy(13.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .widthIn(min = 58.dp)
                    .clip(MaterialTheme.shapes.small)
                    .background(RoyalGold.copy(alpha = 0.08f))
                    .border(1.dp, RoyalGoldBorderStrong, MaterialTheme.shapes.small)
                    .padding(horizontal = 9.dp, vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    glyph,
                    color = RoyalGoldBright,
                    style = RoyalDataStyle,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                )
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(7.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        title,
                        modifier = Modifier.weight(1f, fill = false),
                        color = RoyalText,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                    )
                    RoyalArchiveLabel(tag, color = RoyalGold)
                }
                Text(description, color = RoyalTextMuted, style = MaterialTheme.typography.bodySmall)
                Text(
                    "Beispiel: $example",
                    color = RoyalTextMuted.copy(alpha = 0.86f),
                    style = MaterialTheme.typography.labelSmall,
                )
            }
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .background(if (selected) RoyalGold else androidx.compose.ui.graphics.Color.Transparent)
                    .border(
                        1.dp,
                        if (selected) RoyalGoldBright else RoyalGoldBorderStrong,
                        CircleShape,
                    ),
                contentAlignment = Alignment.Center,
            ) {
                if (selected) {
                    Icon(
                        Icons.Rounded.Check,
                        contentDescription = "Ausgewählt",
                        tint = RoyalInk,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.animeContent(
    anime: AnimeDetail,
    translation: String,
    selected: Set<String>,
    onTranslation: (String) -> Unit,
    onToggle: (String) -> Unit,
    onPreviousPage: () -> Unit,
    onNextPage: () -> Unit,
) {
    item {
        DetailSection("ANIME", "${anime.total} Episoden") {
            Text(anime.description.ifBlank { "Keine Beschreibung verfügbar." }, color = RoyalTextMuted)
            Spacer(Modifier.height(14.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                anime.translations.keys.forEach { track ->
                    RoyalFilterChip(
                        selected = track == translation,
                        onClick = { onTranslation(track) },
                        label = anime.translationLabels[track] ?: track.uppercase(),
                    )
                }
            }
        }
    }
    item {
        DetailSection("EPISODEN", "Spur ${translation.uppercase()}") {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                anime.episodes.forEach { episode ->
                    EpisodeChip(
                        label = episode.number.toString(),
                        selected = episode.slug in selected,
                        disabled = episode.queued || episode.downloaded,
                        status = if (episode.downloaded) "Geladen" else if (episode.queued) "Queue" else null,
                        onClick = { onToggle(episode.slug) },
                    )
                }
            }
            if (anime.pageCount > 1) {
                Spacer(Modifier.height(14.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    RoyalSecondaryButton(
                        onClick = onPreviousPage,
                        modifier = Modifier.weight(1f),
                        enabled = anime.page > 1,
                    ) { Text("Zurück") }
                    Text(
                        "${anime.page} / ${anime.pageCount}",
                        color = RoyalTextMuted,
                        style = MaterialTheme.typography.labelLarge,
                    )
                    RoyalSecondaryButton(
                        onClick = onNextPage,
                        modifier = Modifier.weight(1f),
                        enabled = anime.page < anime.pageCount,
                    ) { Text("Weiter") }
                }
            }
        }
    }
}

@Composable
private fun DetailSection(label: String, title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        RoyalSectionHeader(title, label = label)
        RoyalPanel(modifier = Modifier.fillMaxWidth(), content = content)
    }
}

@Composable
private fun EpisodeChip(
    label: String,
    selected: Boolean,
    disabled: Boolean,
    status: String?,
    onClick: () -> Unit,
) {
    Column(
        modifier = Modifier
            .clip(MaterialTheme.shapes.small)
            .background(if (selected) RoyalSelection else RoyalAmethyst.copy(alpha = 0.5f))
            .clickable(enabled = !disabled, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(label, color = if (selected) RoyalInk else if (disabled) RoyalTextMuted else RoyalText, style = MaterialTheme.typography.labelLarge)
        status?.let { Text(it, color = if (selected) RoyalInk else RoyalTextMuted, style = MaterialTheme.typography.labelSmall) }
    }
}
