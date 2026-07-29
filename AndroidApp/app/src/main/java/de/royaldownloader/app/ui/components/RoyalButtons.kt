package de.royaldownloader.app.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import de.royaldownloader.app.ui.theme.RoyalAmethyst
import de.royaldownloader.app.ui.theme.RoyalBrushes
import de.royaldownloader.app.ui.theme.RoyalError
import de.royaldownloader.app.ui.theme.RoyalGoldBorderStrong
import de.royaldownloader.app.ui.theme.RoyalGoldDeep
import de.royaldownloader.app.ui.theme.RoyalInk
import de.royaldownloader.app.ui.theme.RoyalText
import de.royaldownloader.app.ui.theme.RoyalTextMuted

@Composable
fun RoyalPrimaryButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    content: @Composable RowScope.() -> Unit,
) {
    val shape = MaterialTheme.shapes.medium
    val background = if (enabled) {
        Modifier.background(RoyalBrushes.Gold, shape)
    } else {
        Modifier.background(RoyalGoldDeep.copy(alpha = 0.62f), shape)
    }

    Button(
        onClick = onClick,
        modifier = modifier
            .defaultMinSize(minHeight = 48.dp)
            .clip(shape)
            .then(background),
        enabled = enabled,
        shape = shape,
        colors = ButtonDefaults.buttonColors(
            containerColor = Color.Transparent,
            contentColor = RoyalInk,
            disabledContainerColor = Color.Transparent,
            disabledContentColor = RoyalTextMuted.copy(alpha = 0.70f),
        ),
        elevation = ButtonDefaults.buttonElevation(
            defaultElevation = 0.dp,
            pressedElevation = 0.dp,
            focusedElevation = 0.dp,
            hoveredElevation = 0.dp,
            disabledElevation = 0.dp,
        ),
        content = content,
    )
}

@Composable
fun RoyalSecondaryButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    content: @Composable RowScope.() -> Unit,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.defaultMinSize(minHeight = 48.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.medium,
        border = BorderStroke(1.dp, RoyalGoldBorderStrong),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = RoyalAmethyst.copy(alpha = 0.56f),
            contentColor = RoyalText,
            disabledContentColor = RoyalTextMuted.copy(alpha = 0.55f),
        ),
        content = content,
    )
}

@Composable
fun RoyalDangerButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    content: @Composable RowScope.() -> Unit,
) {
    OutlinedButton(
        onClick = onClick,
        modifier = modifier.defaultMinSize(minHeight = 48.dp),
        enabled = enabled,
        shape = MaterialTheme.shapes.medium,
        border = BorderStroke(1.dp, RoyalError.copy(alpha = 0.55f)),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = RoyalError.copy(alpha = 0.08f),
            contentColor = RoyalError,
            disabledContentColor = RoyalTextMuted.copy(alpha = 0.55f),
        ),
        content = content,
    )
}

@Composable
fun RoyalIconButton(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    content: @Composable () -> Unit,
) {
    IconButton(
        onClick = onClick,
        modifier = modifier.sizeIn(minWidth = 48.dp, minHeight = 48.dp),
        enabled = enabled,
        colors = IconButtonDefaults.iconButtonColors(
            containerColor = RoyalAmethyst.copy(alpha = 0.72f),
            contentColor = RoyalText,
            disabledContainerColor = RoyalAmethyst.copy(alpha = 0.30f),
            disabledContentColor = RoyalTextMuted.copy(alpha = 0.45f),
        ),
        content = content,
    )
}
