package de.royaldownloader.app.ui.theme

import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.geometry.Offset

/** Core palette inherited from the Royal Downloader web application's Obsidian & Gold theme. */
val RoyalVault = Color(0xFF08060D)
val RoyalObsidian = Color(0xFF120D1A)
val RoyalAmethyst = Color(0xFF1D1527)
val RoyalRaised = Color(0xFF251B31)

val RoyalGold = Color(0xFFD8B766)
val RoyalGoldBright = Color(0xFFF0D890)
val RoyalGoldPale = Color(0xFFF5E2A8)
val RoyalGoldBurnished = Color(0xFFB98F3E)
val RoyalGoldDim = Color(0xFF6D5528)
val RoyalGoldDeep = Color(0xFF3D2F14)

val RoyalText = Color(0xFFF3EEE3)
val RoyalTextMuted = Color(0xFFA99E91)
val RoyalTextFaint = Color(0xFF716A63)
val RoyalInk = Color(0xFF191106)

val RoyalSuccess = Color(0xFF93D49A)
val RoyalError = Color(0xFFE86F6F)
val RoyalWarning = Color(0xFFE8BD61)
val RoyalSelection = Color(0xFFC99AF2)
val RoyalAnime = Color(0xFF79D9E8)
val RoyalAnimeBright = Color(0xFFA8EDF5)
val RoyalCinemaRed = Color(0xFFE50914)

val RoyalGoldBorder = Color(0x24D8B766)
val RoyalGoldBorderStrong = Color(0x59D8B766)
val RoyalSurfaceSoft = Color(0xA6140E1D)
val RoyalSurfaceStrong = Color(0xF20F0A16)
val RoyalScrim = Color(0xD9040307)

object RoyalBrushes {
    val Gold: Brush = Brush.linearGradient(
        colors = listOf(
            RoyalGoldPale,
            RoyalGold,
            RoyalGoldBurnished,
            RoyalGoldBright,
        ),
        start = Offset.Zero,
        end = Offset(720f, 720f),
    )

    val GoldEdge: Brush = Brush.verticalGradient(
        colors = listOf(
            RoyalGoldBright,
            RoyalGold,
            RoyalGold.copy(alpha = 0.10f),
        ),
    )

    val Panel: Brush = Brush.linearGradient(
        colors = listOf(
            RoyalAmethyst.copy(alpha = 0.92f),
            RoyalObsidian.copy(alpha = 0.96f),
        ),
        start = Offset.Zero,
        end = Offset(900f, 700f),
    )

    val SelectedPanel: Brush = Brush.linearGradient(
        colors = listOf(
            RoyalGold.copy(alpha = 0.17f),
            RoyalAmethyst.copy(alpha = 0.94f),
        ),
        start = Offset.Zero,
        end = Offset(900f, 360f),
    )

    val PosterFallback: Brush = Brush.linearGradient(
        colors = listOf(
            RoyalGold.copy(alpha = 0.18f),
            RoyalAmethyst,
            RoyalObsidian,
        ),
        start = Offset.Zero,
        end = Offset(500f, 800f),
    )
}
