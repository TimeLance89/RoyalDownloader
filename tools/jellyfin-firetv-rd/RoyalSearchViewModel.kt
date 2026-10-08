package org.jellyfin.androidtv.ui.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import org.jellyfin.androidtv.R
import org.jellyfin.androidtv.integration.royaldownloader.RoyalDownloaderBridge
import org.jellyfin.sdk.model.api.BaseItemDto

/** RD results never pass through the Jellyfin search repository. */
class RoyalSearchViewModel(
    private val find: suspend (String) -> List<BaseItemDto> = { RoyalDownloaderBridge.search(it) },
    private val prompt: () -> BaseItemDto = { RoyalDownloaderBridge.searchPrompt() },
    private val status: (String, String) -> BaseItemDto = RoyalDownloaderBridge::statusItem,
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {
    private var searchJob: Job? = null
    private var previousQuery = ""
    private val requests = Semaphore(1)
    private val results = MutableStateFlow<Collection<SearchResultGroup>>(emptyList())
    val searchResultsFlow = results.asStateFlow()

    fun searchImmediately(query: String) = search(query, 0, force = true)
    fun searchDebounced(query: String) = search(query, 600, force = false)
    fun refresh() = searchImmediately(previousQuery)

    private fun search(query: String, debounce: Long, force: Boolean) {
        val trimmed = query.trim()
        if (!force && trimmed == previousQuery) return
        previousQuery = trimmed
        searchJob?.cancel()
        if (trimmed.isBlank()) {
            show(listOf(prompt()))
            return
        }
        searchJob = viewModelScope.launch {
            delay(debounce)
            show(listOf(status("RD durchsuchen …", "")))
            val items = withContext(ioDispatcher) {
                requests.withPermit { find(trimmed) }
            }
            show(items.ifEmpty {
                listOf(status("Keine RD-Treffer", "Anderen Titel versuchen; bereits vorhandene Filme werden ausgeblendet."))
            })
        }
    }

    private fun show(items: List<BaseItemDto>) {
        results.value = listOf(SearchResultGroup(R.string.lbl_royal_downloader, items))
    }
}
