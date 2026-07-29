package de.royaldownloader.app

import android.content.Context
import coil.ImageLoader
import de.royaldownloader.app.BuildConfig
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.data.local.AppPreferences
import de.royaldownloader.app.data.local.SecureTokenStore
import de.royaldownloader.app.data.remote.ArtworkProxyState
import de.royaldownloader.app.data.remote.ConnectivityObserver
import de.royaldownloader.app.data.remote.artworkHttpClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.serialization.json.Json

class AppContainer(context: Context) {
    private val applicationContext = context.applicationContext
    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        coerceInputValues = true
        explicitNulls = false
    }
    val preferences = AppPreferences(applicationContext)
    val tokenStore = SecureTokenStore(applicationContext)
    val connectivity = ConnectivityObserver(applicationContext)
    private val artworkProxyState = ArtworkProxyState(BuildConfig.DEFAULT_SERVER_URL)
    val imageLoader: ImageLoader by lazy {
        ImageLoader.Builder(applicationContext)
            .okHttpClient { artworkHttpClient(tokenStore, artworkProxyState) }
            .components { add(de.royaldownloader.app.data.remote.ArtworkStringMapper()) }
            // Poster are public provider artwork. Keep them in Coil's private app cache even though
            // authenticated API responses correctly carry Cache-Control: no-store.
            .respectCacheHeaders(false)
            .build()
    }
    val repository = RoyalRepository(
        appScope = appScope,
        preferences = preferences,
        tokenStore = tokenStore,
        connectivity = connectivity,
        json = json,
        artworkProxyState = artworkProxyState,
    )
}
