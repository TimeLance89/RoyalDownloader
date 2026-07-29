package de.royaldownloader.app.ui.watchlist

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.DeleteOutline
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import de.royaldownloader.app.data.remote.WatchlistItem
import de.royaldownloader.app.ui.components.*
import de.royaldownloader.app.ui.theme.*

@Composable
fun WatchlistScreen(
    viewModel: WatchlistViewModel,
    onOpenSeries: (String) -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var deleteItem by remember { mutableStateOf<WatchlistItem?>(null) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(18.dp, 18.dp, 18.dp, 28.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            RoyalArchiveHeader(
                eyebrow = "SERIEN-AUTOMATIK",
                title = "Abonnements",
                supportingText = "Neue Episoden finden und automatisch einplanen.",
                trailing = {
                    RoyalIconButton(onClick = viewModel::checkAll, enabled = !state.checking) {
                        Icon(Icons.Rounded.Refresh, contentDescription = "Alle Abos prüfen")
                    }
                },
            )
        }
        state.error?.let { item { RoyalConnectionBanner("Abo-Aktion fehlgeschlagen", it.message, tone = RoyalStatusTone.Error) } }
        if (state.loading) {
            item { RoyalLoadingState("Abos werden geladen …", Modifier.fillMaxWidth()) }
        } else if (state.items.isEmpty()) {
            item { RoyalEmptyState("Noch keine Abos", "Öffne eine Serie und aktiviere dort das Abonnement.") }
        } else {
            items(state.items, key = { it.baseSlug }) { item ->
                SubscriptionBackdropCard(
                    item = item,
                    enabled = state.activeSlug == null,
                    onClick = { onOpenSeries(item.baseSlug) },
                    onDelete = { deleteItem = item },
                    onModeChange = { viewModel.updateMode(item, it) },
                )
            }
        }
    }
    deleteItem?.let { item ->
        AlertDialog(
            onDismissRequest = { deleteItem = null },
            title = { Text("Abo entfernen?") },
            text = { Text("„${item.title}“ wird nicht mehr automatisch geprüft.") },
            confirmButton = { TextButton(onClick = { deleteItem = null; viewModel.remove(item) }) { Text("Entfernen") } },
            dismissButton = { TextButton(onClick = { deleteItem = null }) { Text("Abbrechen") } },
        )
    }
}

@Composable
private fun SubscriptionBackdropCard(
    item: WatchlistItem,
    enabled: Boolean,
    onClick: () -> Unit,
    onDelete: () -> Unit,
    onModeChange: (String) -> Unit,
) {
    val shape = RoundedCornerShape(22.dp)
    val imageUrl = item.backdropUrl.ifBlank { item.coverUrl }
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (item.newCount > 0) Modifier.border(1.dp, RoyalGoldBorderStrong, shape)
                else Modifier
            ),
        onClick = onClick,
        shape = shape,
        color = RoyalObsidian,
    ) {
        Column {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(218.dp)
                    .background(
                        Brush.linearGradient(
                            listOf(RoyalAmethyst, RoyalVault),
                        ),
                    ),
            ) {
                if (imageUrl.isNotBlank()) {
                    AsyncImage(
                        model = imageUrl,
                        contentDescription = "Wallpaper von ${item.title}",
                        modifier = Modifier.fillMaxSize(),
                        contentScale = ContentScale.Crop,
                    )
                }
                Box(
                    Modifier
                        .fillMaxSize()
                        .background(
                            Brush.verticalGradient(
                                0f to Color.Black.copy(alpha = 0.16f),
                                0.48f to Color.Black.copy(alpha = 0.20f),
                                1f to RoyalObsidian,
                            ),
                        ),
                )
                Box(
                    Modifier
                        .fillMaxSize()
                        .background(
                            Brush.horizontalGradient(
                                listOf(Color.Black.copy(alpha = 0.58f), Color.Transparent),
                            ),
                        ),
                )
                Column(
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(14.dp),
                ) {
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(7.dp),
                        verticalArrangement = Arrangement.spacedBy(7.dp),
                    ) {
                        RoyalStatusChip(statusLabel(item), tone = statusTone(item))
                        if (item.newCount > 0) {
                            RoyalStatusChip("${item.newCount} neu", tone = RoyalStatusTone.Active)
                        }
                        if (item.queuedCount > 0) {
                            RoyalStatusChip("${item.queuedCount} in Queue", tone = RoyalStatusTone.Queued)
                        }
                        if (item.failedCount > 0) {
                            RoyalStatusChip("${item.failedCount} Fehler", tone = RoyalStatusTone.Error)
                        }
                    }
                }
                Box(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(10.dp)
                        .clip(RoundedCornerShape(50))
                        .background(Color.Black.copy(alpha = 0.62f)),
                ) {
                    RoyalIconButton(onClick = onDelete, enabled = enabled) {
                        Icon(Icons.Rounded.DeleteOutline, contentDescription = "Abo entfernen")
                    }
                }
                Column(
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .fillMaxWidth()
                        .padding(horizontal = 18.dp, vertical = 16.dp),
                ) {
                    Text(
                        item.title,
                        color = Color.White,
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Black,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        watchModeTitle(item.downloadMode),
                        color = RoyalGoldBright,
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            }
            Column(
                modifier = Modifier.padding(start = 18.dp, end = 18.dp, top = 4.dp, bottom = 18.dp),
            ) {
                Text(
                    watchModeExplanation(item.downloadMode),
                    color = RoyalTextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(Modifier.height(12.dp))
                Text("DOWNLOADREGEL", color = RoyalTextFaint, style = MaterialTheme.typography.labelSmall)
                Spacer(Modifier.height(6.dp))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(7.dp),
                    verticalArrangement = Arrangement.spacedBy(7.dp),
                ) {
                    listOf(
                        "all" to "Alle fehlenden",
                        "latest_season" to "Neueste Staffel",
                        "next_season" to "Nächste Staffel",
                    ).forEach { (mode, label) ->
                        RoyalFilterChip(
                            selected = item.downloadMode == mode,
                            onClick = { onModeChange(mode) },
                            label = label,
                            enabled = enabled,
                        )
                    }
                }
                Spacer(Modifier.height(12.dp))
                HorizontalDivider(color = RoyalGoldBorder)
                Spacer(Modifier.height(10.dp))
                Text(
                    cleanupModeLabel(item.cleanupMode),
                    color = RoyalText,
                    style = MaterialTheme.typography.labelLarge,
                )
                Text(
                    "${cleanupModeExplanation(item.cleanupMode)} · ${checkedAtLabel(item.lastChecked)}",
                    color = RoyalTextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
                if (item.lastError.isNotBlank()) {
                    Spacer(Modifier.height(10.dp))
                    Text(item.lastError, color = RoyalError, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
