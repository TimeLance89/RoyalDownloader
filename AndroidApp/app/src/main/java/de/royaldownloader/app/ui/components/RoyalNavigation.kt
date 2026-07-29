package de.royaldownloader.app.ui.components

import androidx.compose.foundation.layout.size
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import de.royaldownloader.app.ui.theme.RoyalAmethyst
import de.royaldownloader.app.ui.theme.RoyalGold
import de.royaldownloader.app.ui.theme.RoyalInk
import de.royaldownloader.app.ui.theme.RoyalText
import de.royaldownloader.app.ui.theme.RoyalTextMuted
import de.royaldownloader.app.ui.theme.RoyalVault

@Immutable
data class RoyalNavigationDestination(
    val key: String,
    val label: String,
    val icon: ImageVector,
    val selectedIcon: ImageVector = icon,
    val badgeCount: Int? = null,
)

@Composable
fun RoyalNavigationBar(
    destinations: List<RoyalNavigationDestination>,
    selectedKey: String,
    onDestinationSelected: (RoyalNavigationDestination) -> Unit,
    modifier: Modifier = Modifier,
) {
    NavigationBar(
        modifier = modifier,
        containerColor = RoyalVault.copy(alpha = 0.98f),
        contentColor = RoyalText,
        tonalElevation = 0.dp,
    ) {
        destinations.forEach { destination ->
            val selected = destination.key == selectedKey
            NavigationBarItem(
                selected = selected,
                onClick = { onDestinationSelected(destination) },
                icon = {
                    BadgedBox(
                        badge = {
                            destination.badgeCount
                                ?.takeIf { it > 0 }
                                ?.let { count ->
                                    Badge(
                                        containerColor = RoyalGold,
                                        contentColor = RoyalInk,
                                    ) {
                                        Text(if (count > 99) "99+" else count.toString())
                                    }
                                }
                        },
                    ) {
                        Icon(
                            imageVector = if (selected) destination.selectedIcon else destination.icon,
                            contentDescription = null,
                            modifier = Modifier.size(23.dp),
                        )
                    }
                },
                label = {
                    Text(
                        text = destination.label,
                        style = MaterialTheme.typography.labelSmall,
                    )
                },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = RoyalGold,
                    selectedTextColor = RoyalGold,
                    indicatorColor = RoyalAmethyst,
                    unselectedIconColor = RoyalTextMuted,
                    unselectedTextColor = RoyalTextMuted,
                    disabledIconColor = RoyalTextMuted.copy(alpha = 0.35f),
                    disabledTextColor = RoyalTextMuted.copy(alpha = 0.35f),
                ),
            )
        }
    }
}
