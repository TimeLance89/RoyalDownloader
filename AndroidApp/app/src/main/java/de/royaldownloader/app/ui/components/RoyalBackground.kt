package de.royaldownloader.app.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import de.royaldownloader.app.ui.theme.RoyalGold
import de.royaldownloader.app.ui.theme.RoyalSelection
import de.royaldownloader.app.ui.theme.RoyalVault
import kotlin.math.max

/** Static, GPU-cheap interpretation of the web UI's aurora background. */
@Composable
fun RoyalBackground(
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .drawWithCache {
                val longestSide = max(size.width, size.height)
                val goldAurora = Brush.radialGradient(
                    colors = listOf(
                        RoyalGold.copy(alpha = 0.15f),
                        RoyalGold.copy(alpha = 0.035f),
                        RoyalGold.copy(alpha = 0f),
                    ),
                    center = Offset(size.width * 0.08f, size.height * 0.04f),
                    radius = longestSide * 0.74f,
                )
                val violetAurora = Brush.radialGradient(
                    colors = listOf(
                        RoyalSelection.copy(alpha = 0.10f),
                        RoyalSelection.copy(alpha = 0.025f),
                        RoyalSelection.copy(alpha = 0f),
                    ),
                    center = Offset(size.width * 0.94f, size.height * 0.90f),
                    radius = longestSide * 0.68f,
                )

                onDrawBehind {
                    drawRect(color = RoyalVault)
                    drawRect(goldAurora)
                    drawRect(violetAurora)
                }
            },
        content = content,
    )
}
