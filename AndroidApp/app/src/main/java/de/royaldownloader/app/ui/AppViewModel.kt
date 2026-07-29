package de.royaldownloader.app.ui

import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import de.royaldownloader.app.data.ConnectionState
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.data.runSuspendCatching
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AuthActionState(
    val busy: Boolean = false,
    val error: RoyalFailure? = null,
)

class AppViewModel(private val repository: RoyalRepository) : ViewModel() {
    val connection: StateFlow<ConnectionState> = repository.connection
    val networkAvailable: StateFlow<Boolean> = repository.networkAvailable
    private val _authAction = MutableStateFlow(AuthActionState())
    val authAction: StateFlow<AuthActionState> = _authAction.asStateFlow()

    init {
        retryConnection()
        viewModelScope.launch {
            networkAvailable.drop(1).filter { it }.collect {
                if (connection.value is ConnectionState.Offline) retryConnection()
            }
        }
    }

    fun retryConnection() {
        if (_authAction.value.busy) return
        viewModelScope.launch {
            _authAction.value = AuthActionState(busy = true)
            try {
                repository.bootstrap()
            } finally {
                _authAction.value = AuthActionState()
            }
        }
    }

    fun login(username: String, password: String) {
        if (_authAction.value.busy) return
        viewModelScope.launch {
            _authAction.value = AuthActionState(busy = true)
            runSuspendCatching {
                repository.login(username, password, "${Build.MANUFACTURER} ${Build.MODEL}")
            }.onSuccess {
                _authAction.value = AuthActionState()
            }.onFailure { error ->
                _authAction.value = AuthActionState(error = error as? RoyalFailure)
            }
        }
    }

    fun clearAuthError() {
        _authAction.update { it.copy(error = null) }
    }

    fun changeServer(value: String) {
        if (_authAction.value.busy) return
        viewModelScope.launch {
            _authAction.value = AuthActionState(busy = true)
            runSuspendCatching { repository.changeServerUrl(value) }
                .onSuccess { _authAction.value = AuthActionState() }
                .onFailure { error ->
                    _authAction.value = AuthActionState(error = error as? RoyalFailure)
                }
        }
    }
}
