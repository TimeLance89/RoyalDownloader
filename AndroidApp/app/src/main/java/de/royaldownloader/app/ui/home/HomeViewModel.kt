package de.royaldownloader.app.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import de.royaldownloader.app.data.HomeSnapshot
import de.royaldownloader.app.data.RoyalFailure
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.data.runSuspendCatching
import de.royaldownloader.app.ui.LoadState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class HomeViewModel(private val repository: RoyalRepository) : ViewModel() {
    private val _state = MutableStateFlow(LoadState<HomeSnapshot>(loading = true))
    val state: StateFlow<LoadState<HomeSnapshot>> = _state.asStateFlow()

    init { refresh() }

    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            runSuspendCatching { repository.refreshHome() }
                .onSuccess { _state.value = LoadState(data = it) }
                .onFailure { error -> _state.update { it.copy(loading = false, error = error as? RoyalFailure) } }
        }
    }
}
