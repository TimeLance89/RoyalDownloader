package de.royaldownloader.app.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import de.royaldownloader.app.R
import de.royaldownloader.app.ui.theme.CormorantGaramond
import de.royaldownloader.app.ui.theme.Outfit
import de.royaldownloader.app.ui.theme.RoyalArchiveLabelStyle
import de.royaldownloader.app.ui.theme.RoyalBrushes
import de.royaldownloader.app.ui.theme.RoyalGold
import de.royaldownloader.app.ui.theme.RoyalGoldBright
import de.royaldownloader.app.ui.theme.RoyalText
import de.royaldownloader.app.ui.theme.RoyalTextMuted
import de.royaldownloader.app.ui.theme.RoyalTheme
import java.util.Locale

@Composable
fun RoyalCrownMark(
    modifier: Modifier = Modifier,
    size: Dp = 40.dp,
    contentDescription: String? = null,
    painter: Painter = painterResource(R.drawable.ic_crown_splash),
) {
    Image(
        painter = painter,
        contentDescription = contentDescription,
        modifier = modifier.size(size),
    )
}

@Composable
fun RoyalWordmark(
    modifier: Modifier = Modifier,
    compact: Boolean = false,
    contentDescription: String = "Royal Downloader",
) {
    Row(
        modifier = modifier.clearAndSetSemantics {
            this.contentDescription = contentDescription
        },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(if (compact) 7.dp else 10.dp),
    ) {
        RoyalCrownMark(size = if (compact) 30.dp else 38.dp)
        Column(verticalArrangement = Arrangement.spacedBy(0.dp)) {
            Text(
                text = "ROYAL",
                color = RoyalGoldBright,
                fontFamily = CormorantGaramond,
                fontWeight = FontWeight.Bold,
                fontSize = if (compact) 21.sp else 27.sp,
                lineHeight = if (compact) 22.sp else 28.sp,
                letterSpacing = if (compact) 3.1.sp else 4.2.sp,
            )
            Text(
                text = "DOWNLOADER",
                color = RoyalTextMuted,
                fontFamily = Outfit,
                fontWeight = FontWeight.Medium,
                fontSize = if (compact) 10.sp else 11.sp,
                lineHeight = 13.sp,
                letterSpacing = if (compact) 1.8.sp else 2.3.sp,
            )
        }
    }
}

@Composable
fun RoyalArchiveLabel(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = RoyalGold,
) {
    Text(
        text = text.uppercase(Locale.ROOT),
        modifier = modifier,
        color = color,
        style = RoyalArchiveLabelStyle,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

/**
 * The signature Royal archive edge: a precise gold spine that ties headings to the
 * product's crown-and-archive language without reproducing the desktop layout.
 */
@Composable
fun RoyalArchiveHeader(
    title: String,
    modifier: Modifier = Modifier,
    eyebrow: String? = null,
    supportingText: String? = null,
    trailing: @Composable (RowScope.() -> Unit)? = null,
) {
    Row(
        modifier = modifier.height(IntrinsicSize.Min),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .width(4.dp)
                .fillMaxHeight()
                .background(RoyalBrushes.GoldEdge, MaterialTheme.shapes.extraSmall),
        )
        Spacer(Modifier.width(RoyalTheme.spacing.sm))
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            eyebrow?.let { RoyalArchiveLabel(text = it) }
            Text(
                text = title,
                modifier = Modifier.semantics { heading() },
                color = RoyalText,
                style = MaterialTheme.typography.headlineSmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            supportingText?.let {
                Text(
                    text = it,
                    color = RoyalTextMuted,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        trailing?.let {
            Spacer(Modifier.width(RoyalTheme.spacing.sm))
            it()
        }
    }
}

@Composable
fun RoyalSectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    label: String? = null,
    action: @Composable (RowScope.() -> Unit)? = null,
) {
    Row(
        modifier = modifier.padding(vertical = RoyalTheme.spacing.xs),
        verticalAlignment = Alignment.Bottom,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            label?.let { RoyalArchiveLabel(it) }
            Text(
                text = title,
                modifier = Modifier.semantics { heading() },
                color = RoyalText,
                style = MaterialTheme.typography.headlineSmall,
            )
        }
        action?.invoke(this)
    }
}
