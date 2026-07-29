package de.royaldownloader.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import de.royaldownloader.app.ui.theme.RoyalError
import de.royaldownloader.app.ui.theme.RoyalGold
import de.royaldownloader.app.ui.theme.RoyalText
import de.royaldownloader.app.ui.theme.RoyalTextMuted
import de.royaldownloader.app.ui.theme.RoyalTheme

@Composable
fun RoyalEmptyState(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
    icon: (@Composable () -> Unit)? = null,
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = RoyalTheme.spacing.lg, vertical = RoyalTheme.spacing.xl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Box(
            modifier = Modifier
                .size(64.dp)
                .clip(CircleShape)
                .background(RoyalGold.copy(alpha = 0.08f)),
            contentAlignment = Alignment.Center,
        ) {
            if (icon != null) {
                icon()
            } else {
                RoyalCrownMark(size = 42.dp)
            }
        }
        Spacer(Modifier.height(16.dp))
        Text(
            text = title,
            modifier = Modifier.semantics { heading() },
            color = RoyalText,
            style = MaterialTheme.typography.headlineSmall,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            text = message,
            color = RoyalTextMuted,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
        )
        if (actionLabel != null && onAction != null) {
            Spacer(Modifier.height(20.dp))
            RoyalPrimaryButton(onClick = onAction) {
                Text(actionLabel)
            }
        }
    }
}

@Composable
fun RoyalErrorState(
    title: String,
    message: String,
    retryLabel: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    RoyalEmptyState(
        title = title,
        message = message,
        modifier = modifier,
        actionLabel = retryLabel,
        onAction = onRetry,
        icon = {
            Icon(
                imageVector = Icons.Rounded.ErrorOutline,
                contentDescription = null,
                modifier = Modifier.size(32.dp),
                tint = RoyalError,
            )
        },
    )
}

@Composable
fun RoyalLoadingState(
    label: String,
    modifier: Modifier = Modifier,
) {
    val reducedMotion = RoyalTheme.motion.reduceMotion
    Column(
        modifier = modifier
            .semantics { liveRegion = LiveRegionMode.Polite }
            .padding(RoyalTheme.spacing.lg),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (reducedMotion) {
            RoyalCrownMark(size = 34.dp)
        } else {
            androidx.compose.material3.CircularProgressIndicator(
                modifier = Modifier.size(32.dp),
                color = RoyalGold,
                trackColor = Color.Transparent,
                strokeWidth = 2.dp,
            )
        }
        Text(
            text = label,
            color = RoyalTextMuted,
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
    }
}
