package de.royaldownloader.app.ui.queue

import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateIntAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.DeleteOutline
import androidx.compose.material.icons.rounded.Downloading
import androidx.compose.material.icons.rounded.HourglassTop
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.royaldownloader.app.data.remote.QueueItem
import de.royaldownloader.app.data.remote.SocketStatus
import de.royaldownloader.app.ui.components.*
import de.royaldownloader.app.ui.theme.*

@Composable
fun QueueScreen(viewModel: QueueViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var confirmCancel by remember { mutableStateOf(false) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(18.dp, 18.dp, 18.dp, 28.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            RoyalArchiveHeader(
                eyebrow = "LIVE PIPELINE",
                title = "Downloads",
                supportingText = "Warteschlange und laufende Übertragungen in Echtzeit.",
                trailing = {
                    RoyalIconButton(onClick = viewModel::refresh, enabled = !state.loading) {
                        Icon(Icons.Rounded.Refresh, contentDescription = "Queue aktualisieren")
                    }
                },
            )
        }
        item {
            QueuePipelineOverview(
                queued = state.snapshot.count,
                active = state.progress.size,
                finished = state.recentResults.count { it.successful },
                socketStatus = state.socketStatus,
            )
        }
        state.error?.let { item { RoyalConnectionBanner("Queue-Aktion fehlgeschlagen", it.message, tone = RoyalStatusTone.Error) } }
        if (state.progress.isNotEmpty()) {
            item { RoyalSectionHeader("Aktiv", label = "LIVE") }
            items(state.progress.values.sortedBy { it.label }, key = { it.label }) { progress ->
                RoyalDownloadProgress(
                    title = progress.label,
                    progress = ((progress.percent ?: 0.0) / 100.0).toFloat(),
                    detail = progress.message,
                    statusLabel = if (progress.percent == null) "Wird vorbereitet" else "Download läuft",
                    indeterminate = progress.percent == null,
                    modifier = Modifier.animateItem(),
                )
            }
        }
        if (state.recentResults.isNotEmpty()) {
            item { RoyalSectionHeader("Letzte Ergebnisse", label = "DIESE SITZUNG") }
            items(state.recentResults, key = { "${it.label}:${it.message}:${it.successful}" }) { result ->
                RoyalPanel(modifier = Modifier.fillMaxWidth().animateItem()) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(result.label, color = RoyalText, style = MaterialTheme.typography.titleMedium)
                            if (result.message.isNotBlank()) {
                                Text(result.message, color = RoyalTextMuted, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                        RoyalStatusChip(
                            if (result.successful) "Fertig" else "Fehler",
                            tone = if (result.successful) RoyalStatusTone.Success else RoyalStatusTone.Error,
                        )
                    }
                }
            }
        }
        if (state.loading && state.snapshot.count == 0) {
            item { RoyalLoadingState("Queue wird geladen …", Modifier.fillMaxWidth()) }
        } else if (state.snapshot.count == 0) {
            item { RoyalEmptyState("Queue ist leer", "Füge einen Film oder Episoden über Entdecken hinzu.") }
        } else {
            state.snapshot.groups.forEach { group ->
                item { RoyalSectionHeader(group.name, label = "${group.items.size} EINTRÄGE") }
                itemsIndexed(group.items, key = { _, item -> item.slug }) { index, queueItem ->
                    QueueWaitingCard(
                        item = queueItem,
                        position = index + 1,
                        enabled = !state.actionBusy,
                        onRemove = { viewModel.remove(queueItem.slug) },
                        modifier = Modifier.animateItem(),
                    )
                }
            }
            item {
                RoyalDangerButton(
                    onClick = { confirmCancel = true },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !state.actionBusy,
                ) { Text("Alle Downloads abbrechen") }
            }
        }
    }
    if (confirmCancel) AlertDialog(
        onDismissRequest = { confirmCancel = false },
        title = { Text("Alle Downloads abbrechen?") },
        text = { Text("Aktive und wartende Downloads werden serverseitig beendet.") },
        confirmButton = { TextButton(onClick = { confirmCancel = false; viewModel.cancelAll() }) { Text("Abbrechen") } },
        dismissButton = { TextButton(onClick = { confirmCancel = false }) { Text("Zurück") } },
    )
}

@Composable
private fun QueuePipelineOverview(
    queued: Int,
    active: Int,
    finished: Int,
    socketStatus: SocketStatus,
) {
    val motion = RoyalTheme.motion
    val queuedCount by animateIntAsState(
        targetValue = queued,
        animationSpec = tween(motion.standardMillis),
        label = "queued-count",
    )
    val activeCount by animateIntAsState(
        targetValue = active,
        animationSpec = tween(motion.standardMillis),
        label = "active-count",
    )
    val finishedCount by animateIntAsState(
        targetValue = finished,
        animationSpec = tween(motion.standardMillis),
        label = "finished-count",
    )
    RoyalPanel(
        modifier = Modifier.fillMaxWidth().animateContentSize(),
        variant = RoyalPanelVariant.Elevated,
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            LivePulse(connected = socketStatus == SocketStatus.Connected)
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    socketLabel(socketStatus),
                    color = RoyalText,
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    if (active > 0) "$active Übertragung(en) laufen" else "Bereit für den nächsten Auftrag",
                    color = RoyalTextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            RoyalStatusChip(
                if (socketStatus == SocketStatus.Connected) "LIVE" else "STATUS",
                tone = socketTone(socketStatus),
            )
        }
        Spacer(Modifier.height(18.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            PipelineStage(
                icon = { Icon(Icons.Rounded.HourglassTop, contentDescription = null) },
                value = queuedCount,
                label = "Wartend",
                tone = RoyalStatusTone.Warning,
                modifier = Modifier.weight(1f),
            )
            PipelineConnector(active = queued > 0 || active > 0)
            PipelineStage(
                icon = { Icon(Icons.Rounded.Downloading, contentDescription = null) },
                value = activeCount,
                label = "Aktiv",
                tone = RoyalStatusTone.Active,
                modifier = Modifier.weight(1f),
            )
            PipelineConnector(active = active > 0 || finished > 0)
            PipelineStage(
                icon = { Icon(Icons.Rounded.CheckCircle, contentDescription = null) },
                value = finishedCount,
                label = "Fertig",
                tone = RoyalStatusTone.Success,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun PipelineStage(
    icon: @Composable () -> Unit,
    value: Int,
    label: String,
    tone: RoyalStatusTone,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        Box(
            modifier = Modifier
                .size(42.dp)
                .clip(CircleShape)
                .background(
                    when (tone) {
                        RoyalStatusTone.Success -> RoyalSuccess.copy(alpha = 0.16f)
                        RoyalStatusTone.Active -> RoyalGold.copy(alpha = 0.17f)
                        else -> RoyalWarning.copy(alpha = 0.15f)
                    },
                ),
            contentAlignment = Alignment.Center,
        ) {
            CompositionLocalProvider(
                LocalContentColor provides when (tone) {
                    RoyalStatusTone.Success -> RoyalSuccess
                    RoyalStatusTone.Active -> RoyalGoldBright
                    else -> RoyalWarning
                },
                content = icon,
            )
        }
        Text(value.toString(), color = RoyalText, style = MaterialTheme.typography.titleLarge)
        Text(label, color = RoyalTextMuted, style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
private fun RowScope.PipelineConnector(active: Boolean) {
    Box(
        modifier = Modifier
            .weight(0.42f)
            .height(2.dp)
            .offset(y = (-22).dp)
            .clip(CircleShape)
            .background(if (active) RoyalGold else RoyalGoldBorder),
    )
}

@Composable
private fun LivePulse(connected: Boolean) {
    val motion = RoyalTheme.motion
    if (!connected || motion.reduceMotion) {
        Box(
            modifier = Modifier
                .size(12.dp)
                .clip(CircleShape)
                .background(if (connected) RoyalSuccess else RoyalWarning),
        )
        return
    }
    val transition = rememberInfiniteTransition(label = "live-pulse")
    val pulse by transition.animateFloat(
        initialValue = 0.45f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(850),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "live-pulse-alpha",
    )
    Box(
        modifier = Modifier
            .size(12.dp)
            .scale(0.82f + pulse * 0.18f)
            .alpha(pulse)
            .clip(CircleShape)
            .background(RoyalSuccess),
    )
}

@Composable
private fun QueueWaitingCard(
    item: QueueItem,
    position: Int,
    enabled: Boolean,
    onRemove: () -> Unit,
    modifier: Modifier = Modifier,
) {
    RoyalPanel(
        modifier = modifier.fillMaxWidth().animateContentSize(),
        contentPadding = PaddingValues(0.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(
                modifier = Modifier
                    .width(54.dp)
                    .heightIn(min = 96.dp)
                    .background(RoyalGold.copy(alpha = 0.12f))
                    .padding(vertical = 15.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    position.toString().padStart(2, '0'),
                    color = RoyalGoldBright,
                    style = RoyalDataStyle,
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Bold,
                )
                Spacer(Modifier.height(7.dp))
                Icon(
                    Icons.Rounded.HourglassTop,
                    contentDescription = null,
                    tint = RoyalTextMuted,
                    modifier = Modifier.size(18.dp),
                )
            }
            Column(
                modifier = Modifier.weight(1f).padding(horizontal = 13.dp, vertical = 13.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    item.title,
                    color = RoyalText,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(7.dp),
                    verticalArrangement = Arrangement.spacedBy(7.dp),
                ) {
                    RoyalStatusChip(item.contentLanguage.uppercase().ifBlank { "—" })
                    RoyalStatusChip(item.hosterLabel, tone = RoyalStatusTone.Active)
                    if (item.provider.isNotBlank()) RoyalStatusChip(item.provider)
                }
            }
            RoyalIconButton(
                onClick = onRemove,
                enabled = enabled,
                modifier = Modifier.align(Alignment.CenterVertically).padding(end = 10.dp),
            ) {
                Icon(Icons.Rounded.DeleteOutline, contentDescription = "Aus Queue entfernen")
            }
        }
    }
}

private fun socketLabel(status: SocketStatus): String = when (status) {
    SocketStatus.Connected -> "Live mit dem Server verbunden"
    SocketStatus.Connecting -> "Live-Verbindung wird aufgebaut"
    is SocketStatus.Reconnecting -> "Live-Verbindung wird erneuert"
    SocketStatus.Unauthorized -> "Live-Anmeldung abgelaufen"
    SocketStatus.Forbidden -> "Live-Zugriff verweigert"
    is SocketStatus.PolicyViolation -> "Live-Verbindung abgewiesen"
    SocketStatus.Stopped -> "Live-Aktualisierung pausiert"
}

private fun socketTone(status: SocketStatus): RoyalStatusTone = when (status) {
    SocketStatus.Connected -> RoyalStatusTone.Success
    SocketStatus.Unauthorized,
    SocketStatus.Forbidden,
    is SocketStatus.PolicyViolation -> RoyalStatusTone.Error
    else -> RoyalStatusTone.Warning
}
