package de.royaldownloader.app.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.progressSemantics
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import de.royaldownloader.app.ui.theme.RoyalAnime
import de.royaldownloader.app.ui.theme.RoyalDataStyle
import de.royaldownloader.app.ui.theme.RoyalError
import de.royaldownloader.app.ui.theme.RoyalGold
import de.royaldownloader.app.ui.theme.RoyalSelection
import de.royaldownloader.app.ui.theme.RoyalSuccess
import de.royaldownloader.app.ui.theme.RoyalText
import de.royaldownloader.app.ui.theme.RoyalTextMuted
import de.royaldownloader.app.ui.theme.RoyalTheme
import de.royaldownloader.app.ui.theme.RoyalVault
import de.royaldownloader.app.ui.theme.RoyalWarning

enum class RoyalStatusTone {
    Neutral,
    Active,
    Success,
    Warning,
    Error,
    Queued,
    Selected,
    Anime,
}

private data class StatusColors(
    val foreground: Color,
    val background: Color,
    val border: Color,
)

private fun RoyalStatusTone.colors(): StatusColors {
    val foreground = when (this) {
        RoyalStatusTone.Neutral -> RoyalTextMuted
        RoyalStatusTone.Active -> RoyalGold
        RoyalStatusTone.Success -> RoyalSuccess
        RoyalStatusTone.Warning -> RoyalWarning
        RoyalStatusTone.Error -> RoyalError
        RoyalStatusTone.Queued -> RoyalGold
        RoyalStatusTone.Selected -> RoyalSelection
        RoyalStatusTone.Anime -> RoyalAnime
    }
    return StatusColors(
        foreground = foreground,
        background = foreground.copy(alpha = 0.09f),
        border = foreground.copy(alpha = 0.32f),
    )
}

@Composable
fun RoyalStatusChip(
    text: String,
    modifier: Modifier = Modifier,
    tone: RoyalStatusTone = RoyalStatusTone.Neutral,
    icon: (@Composable () -> Unit)? = null,
    prominent: Boolean = false,
) {
    val baseColors = tone.colors()
    val colors = if (prominent) {
        StatusColors(
            foreground = RoyalVault,
            background = baseColors.foreground,
            border = Color.White.copy(alpha = 0.85f),
        )
    } else {
        baseColors
    }
    val shape = RoundedCornerShape(999.dp)
    Row(
        modifier = modifier
            .then(if (prominent) Modifier.shadow(9.dp, shape) else Modifier)
            .clip(shape)
            .background(colors.background)
            .border(if (prominent) 2.dp else 1.dp, colors.border, shape)
            .padding(
                horizontal = if (prominent) 12.dp else 10.dp,
                vertical = if (prominent) 7.dp else 6.dp,
            ),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        CompositionLocalProvider(LocalContentColor provides colors.foreground) {
            if (icon != null) {
                Box(Modifier.size(14.dp), contentAlignment = Alignment.Center) { icon() }
            } else {
                Canvas(Modifier.size(7.dp)) {
                    drawCircle(color = colors.foreground)
                }
            }
            Text(
                text = text,
                color = colors.foreground,
                style = if (prominent) MaterialTheme.typography.labelMedium else MaterialTheme.typography.labelSmall,
                fontWeight = if (prominent) FontWeight.ExtraBold else FontWeight.Normal,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
fun RoyalDownloadProgress(
    title: String,
    progress: Float,
    modifier: Modifier = Modifier,
    detail: String? = null,
    tone: RoyalStatusTone = RoyalStatusTone.Active,
    statusLabel: String? = null,
    indeterminate: Boolean = false,
) {
    val normalizedProgress = progress.coerceIn(0f, 1f)
    val motion = RoyalTheme.motion
    val animatedProgress by animateFloatAsState(
        targetValue = normalizedProgress,
        animationSpec = tween(durationMillis = motion.standardMillis),
        label = "download-progress",
    )
    val colors = tone.colors()
    RoyalInsetPanel(modifier = modifier) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(36.dp)
                    .clip(CircleShape)
                    .background(colors.background),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "↓",
                    color = colors.foreground,
                    style = MaterialTheme.typography.titleMedium,
                )
            }
            Spacer(Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    color = RoyalText,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                detail?.let {
                    Text(
                        text = it,
                        color = RoyalTextMuted,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Spacer(Modifier.width(8.dp))
            Text(
                text = if (indeterminate) "…" else "${(animatedProgress * 100).toInt()}%",
                color = colors.foreground,
                style = RoyalDataStyle,
            )
        }
        Spacer(Modifier.height(10.dp))
        if (indeterminate) {
            LinearProgressIndicator(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(7.dp)
                    .clip(RoundedCornerShape(999.dp)),
                color = colors.foreground,
                trackColor = RoyalVault.copy(alpha = 0.82f),
            )
        } else {
            LinearProgressIndicator(
                progress = { animatedProgress },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(7.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .progressSemantics(animatedProgress),
                color = colors.foreground,
                trackColor = RoyalVault.copy(alpha = 0.82f),
            )
        }
        statusLabel?.let {
            Spacer(Modifier.height(8.dp))
            RoyalStatusChip(text = it, tone = tone)
        }
    }
}

@Composable
fun RoyalConnectionBanner(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    tone: RoyalStatusTone = RoyalStatusTone.Warning,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    val colors = tone.colors()
    RoyalPanel(
        modifier = modifier.semantics { liveRegion = LiveRegionMode.Polite },
        variant = when (tone) {
            RoyalStatusTone.Error -> RoyalPanelVariant.Error
            RoyalStatusTone.Anime -> RoyalPanelVariant.Anime
            else -> RoyalPanelVariant.Elevated
        },
        contentPadding = androidx.compose.foundation.layout.PaddingValues(14.dp),
    ) {
        Row(
            verticalAlignment = Alignment.Top,
            horizontalArrangement = Arrangement.spacedBy(11.dp),
        ) {
            Box(
                modifier = Modifier
                    .padding(top = 4.dp)
                    .size(9.dp)
                    .clip(CircleShape)
                    .background(colors.foreground),
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    color = RoyalText,
                    style = MaterialTheme.typography.titleSmall,
                )
                Text(
                    text = message,
                    color = RoyalTextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
                if (actionLabel != null && onAction != null) {
                    Spacer(Modifier.height(8.dp))
                    RoyalSecondaryButton(onClick = onAction) {
                        Text(actionLabel)
                    }
                }
            }
        }
    }
}
