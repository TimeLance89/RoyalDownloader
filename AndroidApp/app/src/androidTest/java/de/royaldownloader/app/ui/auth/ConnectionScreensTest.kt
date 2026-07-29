package de.royaldownloader.app.ui.auth

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import de.royaldownloader.app.data.FailureKind
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.ui.theme.RoyalDownloaderTheme
import org.junit.Rule
import org.junit.Test

class ConnectionScreensTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun expiredSessionShowsLoginInsteadOfOfflineCopy() {
        composeRule.setContent {
            RoyalDownloaderTheme {
                LoginScreen(
                    serverUrl = "https://royal.example/",
                    usernameHint = "",
                    sessionExpired = true,
                    busy = false,
                    errorMessage = null,
                    onLogin = { _, _ -> },
                    onServerChange = {},
                    onClearError = {},
                )
            }
        }

        composeRule.onNodeWithText("Sitzung abgelaufen").assertIsDisplayed()
        composeRule.onNodeWithText("Erneut anmelden").assertIsDisplayed()
        composeRule.onNodeWithText("Server nicht erreichbar").assertDoesNotExist()
        composeRule.onNodeWithText("Gerät offline").assertDoesNotExist()
    }

    @Test
    fun dnsFailureIsNotPresentedAsDeviceOffline() {
        composeRule.setContent {
            RoyalDownloaderTheme {
                ConnectionScreen(
                    serverUrl = "https://royal.example/",
                    failure = RoyalFailure(
                        FailureKind.DNS,
                        "Die Serveradresse konnte nicht über DNS aufgelöst werden.",
                        retryable = true,
                    ),
                    networkAvailable = true,
                    busy = false,
                    validationMessage = null,
                    onRetry = {},
                    onServerChange = {},
                )
            }
        }

        composeRule.onNodeWithText("DNS-Auflösung fehlgeschlagen").assertIsDisplayed()
        composeRule.onNodeWithText("Internet verfügbar · DNS-Fehler").assertIsDisplayed()
        composeRule.onNodeWithText("Gerät offline").assertDoesNotExist()
    }
}
