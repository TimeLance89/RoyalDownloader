package de.royaldownloader.app.ui.theme

import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

private val RoyalColorScheme = darkColorScheme(
    primary = RoyalGold,
    onPrimary = RoyalInk,
    primaryContainer = RoyalGoldDeep,
    onPrimaryContainer = RoyalGoldPale,
    inversePrimary = RoyalGoldBurnished,
    secondary = RoyalSelection,
    onSecondary = RoyalVault,
    secondaryContainer = Color(0xFF382447),
    onSecondaryContainer = Color(0xFFEAD8F8),
    tertiary = RoyalAnime,
    onTertiary = Color(0xFF061216),
    tertiaryContainer = Color(0xFF12343B),
    onTertiaryContainer = RoyalAnimeBright,
    background = RoyalVault,
    onBackground = RoyalText,
    surface = RoyalObsidian,
    onSurface = RoyalText,
    surfaceVariant = RoyalAmethyst,
    onSurfaceVariant = RoyalTextMuted,
    surfaceTint = RoyalGold,
    inverseSurface = RoyalText,
    inverseOnSurface = RoyalVault,
    error = RoyalError,
    onError = RoyalVault,
    errorContainer = Color(0xFF4A2024),
    onErrorContainer = Color(0xFFFFDAD8),
    outline = RoyalGoldBorderStrong,
    outlineVariant = RoyalGoldBorder,
    scrim = RoyalScrim,
)

@Immutable
data class RoyalSpacing(
    val hairline: Dp = 1.dp,
    val xxs: Dp = 4.dp,
    val xs: Dp = 8.dp,
    val sm: Dp = 12.dp,
    val md: Dp = 16.dp,
    val lg: Dp = 24.dp,
    val xl: Dp = 32.dp,
    val xxl: Dp = 48.dp,
)

@Immutable
data class RoyalMotion(
    val reduceMotion: Boolean,
    val quickMillis: Int,
    val standardMillis: Int,
    val deliberateMillis: Int,
)

private val LocalRoyalSpacing = compositionLocalOf { RoyalSpacing() }
private val LocalRoyalMotion = compositionLocalOf {
    RoyalMotion(
        reduceMotion = false,
        quickMillis = 140,
        standardMillis = 260,
        deliberateMillis = 420,
    )
}

object RoyalTheme {
    val spacing: RoyalSpacing
        @Composable
        @ReadOnlyComposable
        get() = LocalRoyalSpacing.current

    val motion: RoyalMotion
        @Composable
        @ReadOnlyComposable
        get() = LocalRoyalMotion.current
}

@Composable
fun rememberSystemReducedMotion(): Boolean {
    val context = LocalContext.current
    val resolver = context.contentResolver

    fun readScale(): Float = runCatching {
        Settings.Global.getFloat(
            resolver,
            Settings.Global.ANIMATOR_DURATION_SCALE,
            1f,
        )
    }.getOrDefault(1f)

    var durationScale by remember(resolver) { mutableFloatStateOf(readScale()) }

    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) {
                durationScale = readScale()
            }
        }
        val uri = Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE)
        resolver.registerContentObserver(uri, false, observer)
        onDispose { resolver.unregisterContentObserver(observer) }
    }

    return durationScale == 0f
}

@Composable
fun RoyalDownloaderTheme(
    reducedMotion: Boolean = rememberSystemReducedMotion(),
    content: @Composable () -> Unit,
) {
    val motion = remember(reducedMotion) {
        if (reducedMotion) {
            RoyalMotion(
                reduceMotion = true,
                quickMillis = 0,
                standardMillis = 0,
                deliberateMillis = 0,
            )
        } else {
            RoyalMotion(
                reduceMotion = false,
                quickMillis = 140,
                standardMillis = 260,
                deliberateMillis = 420,
            )
        }
    }

    androidx.compose.runtime.CompositionLocalProvider(
        LocalRoyalSpacing provides RoyalSpacing(),
        LocalRoyalMotion provides motion,
    ) {
        MaterialTheme(
            colorScheme = RoyalColorScheme,
            typography = RoyalTypography,
            shapes = RoyalShapes,
            content = content,
        )
    }
}
