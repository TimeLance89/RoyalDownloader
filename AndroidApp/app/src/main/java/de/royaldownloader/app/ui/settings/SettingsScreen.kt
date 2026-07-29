package de.royaldownloader.app.ui.settings

import android.content.Intent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Logout
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.net.toUri
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import de.royaldownloader.app.ui.auth.ServerAddressDialog
import de.royaldownloader.app.ui.components.*
import de.royaldownloader.app.ui.theme.*

@Composable
fun SettingsScreen(viewModel: SettingsViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var editServer by remember { mutableStateOf(false) }
    var confirmLogout by remember { mutableStateOf(false) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(18.dp, 18.dp, 18.dp, 28.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            RoyalArchiveHeader(
                eyebrow = "APP & VERBINDUNG",
                title = "Einstellungen",
                supportingText = "Seltene Serveroptionen bleiben übersichtlich in der Weboberfläche.",
            )
        }
        item {
            RoyalPanel(modifier = Modifier.fillMaxWidth(), variant = RoyalPanelVariant.Elevated) {
                RoyalArchiveLabel("SERVER")
                Spacer(Modifier.height(6.dp))
                Text(state.serverUrl.removeSuffix("/"), color = RoyalText, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    RoyalStatusChip("HTTPS", tone = RoyalStatusTone.Success)
                    RoyalStatusChip("API ${state.apiVersion}", tone = RoyalStatusTone.Active)
                }
                Spacer(Modifier.height(14.dp))
                RoyalSecondaryButton(onClick = { editServer = true }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Rounded.Dns, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Server wechseln")
                }
                state.errorMessage?.let { Text(it, color = RoyalError, style = MaterialTheme.typography.bodySmall) }
            }
        }
        item {
            RoyalPanel(modifier = Modifier.fillMaxWidth()) {
                RoyalArchiveLabel("KONTO")
                Spacer(Modifier.height(6.dp))
                Text(state.username.ifBlank { "Legacy-Zugang ohne Konto" }, color = RoyalText, style = MaterialTheme.typography.titleMedium)
                Text("Sitzung verschlüsselt über Android Keystore gespeichert", color = RoyalTextMuted, style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(14.dp))
                RoyalDangerButton(onClick = { confirmLogout = true }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.AutoMirrored.Rounded.Logout, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Abmelden")
                }
            }
        }
        item {
            RoyalPanel(modifier = Modifier.fillMaxWidth()) {
                RoyalArchiveLabel("WEB-VERWALTUNG")
                Spacer(Modifier.height(6.dp))
                Text("Provider, Jellyfin, TMDB, Speicherpfade und Automatisierung werden weiterhin zentral auf dem Server verwaltet.", color = RoyalTextMuted)
                Spacer(Modifier.height(14.dp))
                RoyalPrimaryButton(
                    onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, state.serverUrl.toUri())) },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Icon(Icons.Rounded.OpenInBrowser, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("Weboberfläche öffnen")
                }
            }
        }
        item {
            RoyalConnectionBanner(
                title = "Keine Secrets in der App",
                message = "Cloudflare-, Provider-, TMDB- und Jellyfin-Zugangsdaten bleiben ausschließlich auf deinem RoyalDownloader-Server.",
                tone = RoyalStatusTone.Success,
            )
        }
    }
    if (editServer) ServerAddressDialog(
        initialValue = state.serverUrl,
        onDismiss = { editServer = false },
        onConfirm = { editServer = false; viewModel.saveServer(it) },
    )
    if (confirmLogout) AlertDialog(
        onDismissRequest = { confirmLogout = false },
        title = { Text("Abmelden?") },
        text = { Text("Das sichere App-Token wird auf diesem Gerät gelöscht.") },
        confirmButton = { TextButton(onClick = { confirmLogout = false; viewModel.logout() }) { Text("Abmelden") } },
        dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text("Abbrechen") } },
    )
}
