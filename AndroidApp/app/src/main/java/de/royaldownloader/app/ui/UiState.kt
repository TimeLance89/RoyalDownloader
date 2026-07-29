package de.royaldownloader.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import de.royaldownloader.app.data.RoyalFailure

data class LoadState<T>(
    val data: T? = null,
    val loading: Boolean = false,
    val error: RoyalFailure? = null,
)

fun <T : ViewModel> simpleViewModelFactory(create: () -> T): ViewModelProvider.Factory =
    object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <VM : ViewModel> create(modelClass: Class<VM>): VM = create() as VM
    }
