package de.royaldownloader.app.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import de.royaldownloader.app.data.ConnectionState
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.data.runSuspendCatching
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val serverUrl: String = "",
    val username: String = "",
    val apiVersion: String = "",
    val saving: Boolean = false,
    val errorMessage: String? = null,
)

class SettingsViewModel(private val repository: RoyalRepository) : ViewModel() {
    private val _state = MutableStateFlow(SettingsUiState())
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            repository.connection.collect { connection ->
                if (connection is ConnectionState.Connected) {
                    _state.update { current -> current.copy(
                        serverUrl = connection.info.serverUrl,
                        username = connection.info.auth.username,
                        apiVersion = connection.info.apiVersion,
                    ) }
                }
            }
        }
    }

    fun saveServer(value: String) {
        if (_state.value.saving) return
        viewModelScope.launch {
            _state.update { it.copy(saving = true, errorMessage = null) }
            runSuspendCatching { repository.changeServerUrl(value) }
                .onFailure { error ->
                    _state.update { it.copy(
                        errorMessage = (error as? RoyalFailure)?.message ?: error.message,
                    ) }
                }
            _state.update { it.copy(saving = false) }
        }
    }

    fun logout() {
        viewModelScope.launch { repository.logout() }
    }
}
