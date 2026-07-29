package de.royaldownloader.app.ui.auth

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CloudOff
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.OpenInBrowser
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import de.royaldownloader.app.ui.components.*
import de.royaldownloader.app.data.FailureKind
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.ui.theme.RoyalError
import de.royaldownloader.app.ui.theme.RoyalGold
import de.royaldownloader.app.ui.theme.RoyalText
import de.royaldownloader.app.ui.theme.RoyalTextMuted
import de.royaldownloader.app.ui.theme.RoyalTheme

@Composable
private fun ConnectionFrame(content: @Composable ColumnScope.() -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .systemBarsPadding()
            .padding(RoyalTheme.spacing.lg),
        contentAlignment = Alignment.Center,
    ) {
        RoyalPanel(
            modifier = Modifier.widthIn(max = 480.dp),
            variant = RoyalPanelVariant.Elevated,
            contentPadding = PaddingValues(RoyalTheme.spacing.lg),
        ) {
            RoyalWordmark()
            Spacer(Modifier.height(RoyalTheme.spacing.xl))
            content()
        }
    }
}

@Composable
fun LoginScreen(
    serverUrl: String,
    usernameHint: String,
    sessionExpired: Boolean,
    busy: Boolean,
    errorMessage: String?,
    onLogin: (String, String) -> Unit,
    onServerChange: (String) -> Unit,
    onClearError: () -> Unit,
) {
    var username by remember(usernameHint) { mutableStateOf(usernameHint) }
    var password by remember { mutableStateOf("") }
    var passwordVisible by remember { mutableStateOf(false) }
    var editingServer by remember { mutableStateOf(false) }

    ConnectionFrame {
        RoyalArchiveHeader(
            eyebrow = if (sessionExpired) "Anmeldung erforderlich" else "Sicherer Zugang",
            title = if (sessionExpired) "Sitzung abgelaufen" else "Bei deiner Sammlung anmelden",
            supportingText = serverUrl.removeSuffix("/"),
        )
        if (sessionExpired) {
            Spacer(Modifier.height(RoyalTheme.spacing.md))
            RoyalConnectionBanner(
                title = "Bitte erneut anmelden",
                message = "Deine App-Sitzung ist nicht mehr gültig. Melde dich erneut bei Royal Downloader an.",
                tone = RoyalStatusTone.Warning,
            )
        }
        Spacer(Modifier.height(RoyalTheme.spacing.lg))
        OutlinedTextField(
            value = username,
            onValueChange = { username = it; onClearError() },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Benutzername") },
            singleLine = true,
            enabled = !busy,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
        )
        Spacer(Modifier.height(RoyalTheme.spacing.sm))
        OutlinedTextField(
            value = password,
            onValueChange = { password = it; onClearError() },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Passwort") },
            singleLine = true,
            enabled = !busy,
            visualTransformation = if (passwordVisible) VisualTransformation.None else PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
            trailingIcon = {
                IconButton(onClick = { passwordVisible = !passwordVisible }) {
                    Icon(
                        if (passwordVisible) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility,
                        contentDescription = if (passwordVisible) "Passwort verbergen" else "Passwort anzeigen",
                    )
                }
            },
        )
        errorMessage?.let {
            Spacer(Modifier.height(RoyalTheme.spacing.sm))
            Text(it, color = RoyalError, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(RoyalTheme.spacing.lg))
        RoyalPrimaryButton(
            onClick = { onLogin(username, password) },
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy && username.isNotBlank() && password.isNotBlank(),
        ) {
            if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = Color.Black)
            else Icon(Icons.Rounded.Lock, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text(
                if (busy) "Anmeldung läuft"
                else if (sessionExpired) "Erneut anmelden"
                else "Anmelden",
            )
        }
        TextButton(onClick = { editingServer = true }, modifier = Modifier.align(Alignment.CenterHorizontally)) {
            Text("Anderen Server verwenden")
        }
    }
    if (editingServer) ServerAddressDialog(
        initialValue = serverUrl,
        onDismiss = { editingServer = false },
        onConfirm = { editingServer = false; onServerChange(it) },
    )
}

@Composable
fun ConnectionScreen(
    serverUrl: String,
    title: String? = null,
    message: String? = null,
    failure: RoyalFailure? = null,
    networkAvailable: Boolean,
    busy: Boolean,
    validationMessage: String?,
    onRetry: () -> Unit,
    onServerChange: (String) -> Unit,
) {
    var editingServer by remember { mutableStateOf(false) }
    val resolvedTitle = title ?: failure?.kind?.connectionTitle() ?: "Verbindung fehlgeschlagen"
    val resolvedMessage = message ?: failure?.message ?: "Die Verbindung konnte nicht hergestellt werden."
    val statusText = failure?.kind?.statusLabel(networkAvailable)
        ?: if (networkAvailable) "Internet verfügbar" else "Gerät offline"
    val statusTone = if (failure?.kind == FailureKind.DEVICE_OFFLINE || failure?.kind == FailureKind.TLS) {
        RoyalStatusTone.Error
    } else {
        RoyalStatusTone.Warning
    }
    ConnectionFrame {
        Icon(Icons.Rounded.CloudOff, contentDescription = null, tint = RoyalGold, modifier = Modifier.size(42.dp))
        Spacer(Modifier.height(RoyalTheme.spacing.md))
        Text(resolvedTitle, modifier = Modifier.semantics { heading() }, color = RoyalText, style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(RoyalTheme.spacing.xs))
        Text(resolvedMessage, color = RoyalTextMuted, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(RoyalTheme.spacing.sm))
        RoyalStatusChip(
            text = statusText,
            tone = statusTone,
        )
        validationMessage?.let { Text(it, color = RoyalError, style = MaterialTheme.typography.bodySmall) }
        Spacer(Modifier.height(RoyalTheme.spacing.lg))
        RoyalPrimaryButton(onClick = onRetry, modifier = Modifier.fillMaxWidth(), enabled = !busy) { Text("Erneut verbinden") }
        Spacer(Modifier.height(RoyalTheme.spacing.xs))
        RoyalSecondaryButton(onClick = { editingServer = true }, modifier = Modifier.fillMaxWidth(), enabled = !busy) { Text("Serveradresse ändern") }
    }
    if (editingServer) ServerAddressDialog(
        initialValue = serverUrl,
        onDismiss = { editingServer = false },
        onConfirm = { editingServer = false; onServerChange(it) },
    )
}

private fun FailureKind.connectionTitle(): String = when (this) {
    FailureKind.DEVICE_OFFLINE -> "Gerät offline"
    FailureKind.DNS -> "DNS-Auflösung fehlgeschlagen"
    FailureKind.SERVER_UNREACHABLE -> "Royal Downloader nicht erreichbar"
    FailureKind.TIMEOUT -> "Zeitüberschreitung"
    FailureKind.TLS -> "Sichere Verbindung fehlgeschlagen"
    FailureKind.CLOUDFLARE -> "Cloudflare-Verbindung gestört"
    FailureKind.AUTH -> "Sitzung abgelaufen"
    FailureKind.FORBIDDEN -> "Zugriff verweigert"
    FailureKind.NOT_FOUND -> "Mobile-API nicht gefunden"
    FailureKind.CONFLICT -> "Serverzustand geändert"
    FailureKind.RATE_LIMIT -> "Zu viele Anfragen"
    FailureKind.MAINTENANCE -> "Wartung oder Update"
    FailureKind.SERVER -> "Serverfehler"
    FailureKind.INVALID_RESPONSE -> "Serverversion nicht kompatibel"
    FailureKind.UNKNOWN -> "Verbindung fehlgeschlagen"
}

private fun FailureKind.statusLabel(networkAvailable: Boolean): String = when (this) {
    FailureKind.DEVICE_OFFLINE -> "Gerät offline"
    FailureKind.DNS -> "Internet verfügbar · DNS-Fehler"
    FailureKind.SERVER_UNREACHABLE -> "Internet verfügbar · Server nicht erreichbar"
    FailureKind.TIMEOUT -> "Internet verfügbar · Server antwortet nicht"
    FailureKind.TLS -> "Internet verfügbar · TLS-Fehler"
    FailureKind.CLOUDFLARE -> "Internet verfügbar · Cloudflare 52x"
    FailureKind.AUTH -> "Server erreichbar · Anmeldung erforderlich"
    FailureKind.FORBIDDEN -> "Server erreichbar · Zugriff verweigert"
    FailureKind.NOT_FOUND -> "Server erreichbar · API fehlt"
    FailureKind.CONFLICT -> "Server erreichbar · Konflikt"
    FailureKind.RATE_LIMIT -> "Server erreichbar · Rate-Limit"
    FailureKind.MAINTENANCE -> "Server erreichbar · Wartung"
    FailureKind.SERVER -> "Server erreichbar · HTTP 5xx"
    FailureKind.INVALID_RESPONSE -> "Server erreichbar · Antwort inkompatibel"
    FailureKind.UNKNOWN -> if (networkAvailable) "Internet verfügbar" else "Netzwerk nicht bestätigt"
}

@Composable
fun SetupRequiredScreen(
    serverUrl: String,
    securitySetup: Boolean = false,
    busy: Boolean = false,
    errorMessage: String? = null,
    onOpenWebSetup: () -> Unit,
    onRetry: () -> Unit,
    onServerChange: (String) -> Unit,
) {
    var editingServer by remember { mutableStateOf(false) }
    ConnectionFrame {
        RoyalArchiveHeader(
            eyebrow = if (securitySetup) "Sicherheitssetup" else "Ersteinrichtung",
            title = if (securitySetup) "Zugangsschutz erforderlich" else "Server zuerst im Browser einrichten",
            supportingText = if (securitySetup) {
                "Der Server ist derzeit ohne Anmeldung erreichbar. Richte zuerst ein Konto in der Weboberfläche ein."
            } else {
                "Der Einrichtungsassistent bleibt bewusst in der Weboberfläche. Danach übernimmt die App den mobilen Betrieb."
            },
        )
        Spacer(Modifier.height(RoyalTheme.spacing.lg))
        errorMessage?.let {
            Text(it, color = RoyalError, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(RoyalTheme.spacing.sm))
        }
        RoyalPrimaryButton(onClick = onOpenWebSetup, modifier = Modifier.fillMaxWidth(), enabled = !busy) {
            Icon(Icons.Rounded.OpenInBrowser, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text(if (securitySetup) "Kontoschutz einrichten" else "Einrichtung öffnen")
        }
        Spacer(Modifier.height(RoyalTheme.spacing.xs))
        RoyalSecondaryButton(onClick = onRetry, modifier = Modifier.fillMaxWidth(), enabled = !busy) { Text("Status erneut prüfen") }
        TextButton(
            onClick = { editingServer = true },
            modifier = Modifier.align(Alignment.CenterHorizontally),
            enabled = !busy,
        ) { Text("Server ändern") }
    }
    if (editingServer) ServerAddressDialog(
        initialValue = serverUrl,
        onDismiss = { editingServer = false },
        onConfirm = { editingServer = false; onServerChange(it) },
    )
}

@Composable
fun ServerAddressDialog(
    initialValue: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var value by remember(initialValue) { mutableStateOf(initialValue) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Serveradresse") },
        text = {
            Column {
                Text("Nur HTTPS-Adressen werden akzeptiert.", color = RoyalTextMuted)
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = value,
                    onValueChange = { value = it },
                    label = { Text("https://…") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                )
            }
        },
        confirmButton = { TextButton(onClick = { onConfirm(value) }) { Text("Verbinden") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Abbrechen") } },
    )
}
