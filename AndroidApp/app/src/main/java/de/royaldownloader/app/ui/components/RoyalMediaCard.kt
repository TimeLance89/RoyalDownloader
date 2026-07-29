package de.royaldownloader.app.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import de.royaldownloader.app.R
import de.royaldownloader.app.ui.theme.RoyalBrushes
import de.royaldownloader.app.ui.theme.RoyalGold
import de.royaldownloader.app.ui.theme.RoyalGoldBorder
import de.royaldownloader.app.ui.theme.RoyalGoldBorderStrong
import de.royaldownloader.app.ui.theme.RoyalInk
import de.royaldownloader.app.ui.theme.RoyalSelection
import de.royaldownloader.app.ui.theme.RoyalText
import de.royaldownloader.app.ui.theme.RoyalTextMuted

@Composable
fun RoyalPosterCard(
    title: String,
    imageModel: Any?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    metadata: String? = null,
    posterContentDescription: String? = null,
    archiveCode: String? = null,
    statusLabel: String? = null,
    statusTone: RoyalStatusTone = RoyalStatusTone.Neutral,
    statusProminent: Boolean = false,
    selected: Boolean = false,
) {
    val posterShape = MaterialTheme.shapes.medium
    Column(
        modifier = modifier
            .widthIn(min = 132.dp)
            .semantics { this.selected = selected }
            .clickable(role = Role.Button, onClick = onClick),
        verticalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(2f / 3f)
                .sizeIn(minHeight = 180.dp)
                .clip(posterShape)
                .background(RoyalBrushes.PosterFallback)
                .border(
                    width = if (selected) 2.dp else 1.dp,
                    color = if (selected) RoyalSelection else RoyalGoldBorderStrong,
                    shape = posterShape,
                ),
        ) {
            Image(
                painter = painterResource(R.drawable.ic_crown_splash),
                contentDescription = null,
                modifier = Modifier
                    .size(66.dp)
                    .align(Alignment.Center),
                alpha = 0.34f,
            )
            AsyncImage(
                model = imageModel,
                contentDescription = posterContentDescription,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
            )
            archiveCode?.let {
                Box(
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(9.dp)
                        .clip(MaterialTheme.shapes.extraSmall)
                        .background(RoyalGold)
                        .padding(horizontal = 7.dp, vertical = 5.dp),
                ) {
                    RoyalArchiveLabel(text = it, color = RoyalInk)
                }
            }
            if (selected) {
                Box(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(9.dp)
                        .size(32.dp)
                        .clip(CircleShape)
                        .background(RoyalSelection),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = "✓",
                        color = RoyalInk,
                        style = MaterialTheme.typography.labelLarge,
                    )
                }
            }
            statusLabel?.let {
                RoyalStatusChip(
                    text = it,
                    tone = statusTone,
                    prominent = statusProminent,
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .padding(9.dp),
                )
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(
                text = title,
                color = RoyalText,
                style = MaterialTheme.typography.titleSmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            subtitle?.let {
                Text(
                    text = it,
                    color = RoyalTextMuted,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            metadata?.let {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(4.dp)
                            .clip(CircleShape)
                            .background(RoyalGold),
                    )
                    Text(
                        text = it,
                        color = RoyalTextMuted,
                        style = MaterialTheme.typography.labelSmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
fun RoyalPosterPlaceholder(
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
) {
    Box(
        modifier = modifier
            .clip(MaterialTheme.shapes.medium)
            .background(RoyalBrushes.PosterFallback)
            .border(1.dp, RoyalGoldBorder, MaterialTheme.shapes.medium),
        contentAlignment = Alignment.Center,
    ) {
        Image(
            painter = painterResource(R.drawable.ic_crown_splash),
            contentDescription = contentDescription,
            modifier = Modifier.size(64.dp),
            alpha = 0.40f,
        )
    }
}
