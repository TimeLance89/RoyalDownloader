package de.royaldownloader.app.data.remote

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.Build
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.concurrent.atomic.AtomicBoolean

/** Tracks whether Android has a validated, usable default internet connection. */
class ConnectivityObserver(context: Context) : AutoCloseable {
    private val manager = context.getSystemService(ConnectivityManager::class.java)
    private val closed = AtomicBoolean(false)
    private val _connected = MutableStateFlow(currentlyConnected())
    val connected: StateFlow<Boolean> = _connected.asStateFlow()

    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) = update()
        override fun onLost(network: Network) = update()
        override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) = update()
        override fun onBlockedStatusChanged(network: Network, blocked: Boolean) = update()
    }

    init {
        manager.registerDefaultNetworkCallback(callback)
    }

    override fun close() {
        if (closed.compareAndSet(false, true)) {
            runCatching { manager.unregisterNetworkCallback(callback) }
        }
    }

    private fun update() {
        if (!closed.get()) _connected.value = currentlyConnected()
    }

    private fun currentlyConnected(): Boolean {
        val network = manager.activeNetwork ?: return false
        val capabilities = manager.getNetworkCapabilities(network) ?: return false
        return hasValidatedInternet(capabilities)
    }

    internal companion object {
        fun hasValidatedInternet(capabilities: NetworkCapabilities): Boolean {
            if (!capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) return false
            if (!capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) return false
            if (capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_CAPTIVE_PORTAL)) return false
            return Build.VERSION.SDK_INT < Build.VERSION_CODES.P ||
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_SUSPENDED)
        }
    }
}
