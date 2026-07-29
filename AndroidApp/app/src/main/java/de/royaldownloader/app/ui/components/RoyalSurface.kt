package de.royaldownloader.app.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import de.royaldownloader.app.ui.theme.RoyalAnime
import de.royaldownloader.app.ui.theme.RoyalBrushes
import de.royaldownloader.app.ui.theme.RoyalError
import de.royaldownloader.app.ui.theme.RoyalGoldBorder
import de.royaldownloader.app.ui.theme.RoyalGoldBorderStrong
import de.royaldownloader.app.ui.theme.RoyalSelection
import de.royaldownloader.app.ui.theme.RoyalTheme

enum class RoyalPanelVariant {
    Default,
    Elevated,
    Selected,
    Anime,
    Error,
}

@Composable
fun RoyalPanel(
    modifier: Modifier = Modifier,
    variant: RoyalPanelVariant = RoyalPanelVariant.Default,
    shape: Shape = MaterialTheme.shapes.large,
    contentPadding: PaddingValues = PaddingValues(RoyalTheme.spacing.md),
    onClick: (() -> Unit)? = null,
    enabled: Boolean = true,
    content: @Composable ColumnScope.() -> Unit,
) {
    val (background, borderColor) = when (variant) {
        RoyalPanelVariant.Default -> RoyalBrushes.Panel to RoyalGoldBorder
        RoyalPanelVariant.Elevated -> RoyalBrushes.Panel to RoyalGoldBorderStrong
        RoyalPanelVariant.Selected -> RoyalBrushes.SelectedPanel to RoyalSelection.copy(alpha = 0.62f)
        RoyalPanelVariant.Anime -> RoyalBrushes.Panel to RoyalAnime.copy(alpha = 0.42f)
        RoyalPanelVariant.Error -> RoyalBrushes.Panel to RoyalError.copy(alpha = 0.50f)
    }
    val clickModifier = if (onClick != null) {
        Modifier
            .sizeIn(minHeight = 48.dp)
            .clickable(
                enabled = enabled,
                role = Role.Button,
                onClick = onClick,
            )
    } else {
        Modifier
    }

    Column(
        modifier = modifier
            .clip(shape)
            .background(background)
            .border(BorderStroke(1.dp, borderColor), shape)
            .then(clickModifier)
            .padding(contentPadding),
        content = content,
    )
}

@Composable
fun RoyalInsetPanel(
    modifier: Modifier = Modifier,
    borderColor: Color = RoyalGoldBorder,
    background: Brush = Brush.linearGradient(
        listOf(
            Color(0xA608060D),
            Color(0xA6120D1A),
        ),
    ),
    shape: Shape = MaterialTheme.shapes.medium,
    contentPadding: PaddingValues = PaddingValues(RoyalTheme.spacing.sm),
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = modifier
            .clip(shape)
            .background(background)
            .border(1.dp, borderColor, shape)
            .padding(contentPadding),
        content = content,
    )
}
