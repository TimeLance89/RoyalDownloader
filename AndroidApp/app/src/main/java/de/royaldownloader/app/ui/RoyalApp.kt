package de.royaldownloader.app.ui

import android.content.Intent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import de.royaldownloader.app.AppContainer
import de.royaldownloader.app.data.ConnectionState
import de.royaldownloader.app.data.LoginReason
import de.royaldownloader.app.ui.auth.ConnectionScreen
import de.royaldownloader.app.ui.auth.LoginScreen
import de.royaldownloader.app.ui.auth.SetupRequiredScreen
import de.royaldownloader.app.ui.components.RoyalBackground
import de.royaldownloader.app.ui.components.RoyalLoadingState
import de.royaldownloader.app.ui.navigation.RoyalMainShell

@Composable
fun RoyalApp(container: AppContainer) {
    val appViewModel: AppViewModel = viewModel(
        factory = simpleViewModelFactory { AppViewModel(container.repository) },
    )
    val connection by appViewModel.connection.collectAsStateWithLifecycle()
    val authAction by appViewModel.authAction.collectAsStateWithLifecycle()
    val networkAvailable by appViewModel.networkAvailable.collectAsStateWithLifecycle()
    val context = LocalContext.current

    RoyalBackground {
        Box(Modifier.fillMaxSize()) {
            when (val state = connection) {
                ConnectionState.Checking -> RoyalLoadingState(
                    label = "Verbindung zu Royal Downloader wird geprüft …",
                    modifier = Modifier.fillMaxSize(),
                )
                is ConnectionState.LoginRequired -> LoginScreen(
                    serverUrl = state.serverUrl,
                    usernameHint = state.auth.username,
                    sessionExpired = state.reason == LoginReason.EXPIRED,
                    busy = authAction.busy,
                    errorMessage = authAction.error?.message,
                    onLogin = appViewModel::login,
                    onServerChange = appViewModel::changeServer,
                    onClearError = appViewModel::clearAuthError,
                )
                is ConnectionState.SetupRequired -> SetupRequiredScreen(
                    serverUrl = state.serverUrl,
                    busy = authAction.busy,
                    errorMessage = authAction.error?.message,
                    onOpenWebSetup = {
                        context.startActivity(Intent(Intent.ACTION_VIEW, state.serverUrl.toUri()))
                    },
                    onRetry = appViewModel::retryConnection,
                    onServerChange = appViewModel::changeServer,
                )
                is ConnectionState.AccountSetupRequired -> SetupRequiredScreen(
                    serverUrl = state.serverUrl,
                    securitySetup = true,
                    busy = authAction.busy,
                    errorMessage = authAction.error?.message,
                    onOpenWebSetup = {
                        context.startActivity(Intent(Intent.ACTION_VIEW, state.serverUrl.toUri()))
                    },
                    onRetry = appViewModel::retryConnection,
                    onServerChange = appViewModel::changeServer,
                )
                is ConnectionState.Maintenance -> ConnectionScreen(
                    serverUrl = state.serverUrl,
                    title = "Wartungsmodus",
                    message = "Der Server meldet den Status „${state.status}“. Versuche es später erneut.",
                    networkAvailable = networkAvailable,
                    busy = authAction.busy,
                    validationMessage = authAction.error?.message,
                    onRetry = appViewModel::retryConnection,
                    onServerChange = appViewModel::changeServer,
                )
                is ConnectionState.Incompatible -> ConnectionScreen(
                    serverUrl = state.serverUrl,
                    title = "API nicht kompatibel",
                    message = buildString {
                        append("Der Server bietet Mobile-API v${state.serverApiVersion} (${state.supportedApiVersions.joinToString()}). Diese App unterstützt v1.")
                        if (state.details.isNotBlank()) append(" ${state.details}")
                    },
                    networkAvailable = networkAvailable,
                    busy = authAction.busy,
                    validationMessage = authAction.error?.message,
                    onRetry = appViewModel::retryConnection,
                    onServerChange = appViewModel::changeServer,
                )
                is ConnectionState.Offline -> ConnectionScreen(
                    serverUrl = state.serverUrl,
                    failure = state.failure,
                    networkAvailable = networkAvailable,
                    busy = authAction.busy,
                    validationMessage = authAction.error?.message,
                    onRetry = appViewModel::retryConnection,
                    onServerChange = appViewModel::changeServer,
                )
                is ConnectionState.Connected -> RoyalMainShell(
                    repository = container.repository,
                )
            }
        }
    }
}
