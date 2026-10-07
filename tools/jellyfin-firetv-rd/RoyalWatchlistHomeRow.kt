package org.jellyfin.androidtv.ui.home

import android.content.Context
import androidx.leanback.widget.HeaderItem
import androidx.leanback.widget.ListRow
import androidx.leanback.widget.Row
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.jellyfin.androidtv.auth.repository.UserRepository
import org.jellyfin.androidtv.data.repository.ItemRepository
import org.jellyfin.androidtv.ui.itemhandling.BaseItemDtoBaseRowItem
import org.jellyfin.androidtv.ui.presentation.CardPresenter
import org.jellyfin.androidtv.ui.presentation.MutableObjectAdapter
import org.jellyfin.sdk.api.client.ApiClient
import org.jellyfin.sdk.api.client.extensions.itemsApi
import org.jellyfin.sdk.api.client.extensions.playlistsApi
import org.jellyfin.sdk.model.api.BaseItemDto
import org.jellyfin.sdk.model.api.BaseItemKind
import timber.log.Timber
import java.util.UUID

internal object RoyalWatchlistPolicy {
    fun playlistName(user: UUID): String = "RD-Merkliste · " + user.toString().replace("-", "")

    fun cardIds(items: List<BaseItemDto>): List<UUID> = items.mapNotNull { item ->
        when (item.type) {
            BaseItemKind.MOVIE -> item.id
            BaseItemKind.EPISODE -> item.seriesId
            else -> null
        }
    }.distinct()
}

/** Native Jellyfin items only: no RD account/session, synthetic items or downloads. */
class RoyalWatchlistHomeRow(
    private val owner: LifecycleOwner,
    private val api: ApiClient,
    private val users: UserRepository,
) : HomeFragmentRow {
    private var rows: MutableObjectAdapter<Row>? = null
    private var cards: MutableObjectAdapter<BaseItemDtoBaseRowItem>? = null
    private var row: ListRow? = null
    private var attached = false
    private var displayedUser: UUID? = null
    private val refreshRevision = MutableStateFlow(0L)

    fun refresh() { refreshRevision.update { it + 1 } }

    override fun addToRowsAdapter(context: Context, cardPresenter: CardPresenter, rowsAdapter: MutableObjectAdapter<Row>) {
        if (attached) return
        attached = true
        rows = rowsAdapter
        cards = MutableObjectAdapter(cardPresenter)
        row = ListRow(HeaderItem("RD-Merkliste"), cards)
        owner.lifecycleScope.launch {
            owner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(users.currentUser, refreshRevision) { user, _ -> user }
                    .collectLatest { user ->
                        // Clear synchronously before any network work on profile changes.
                        if (displayedUser != user?.id) {
                            clear()
                            displayedUser = user?.id
                        }
                        if (user == null) return@collectLatest
                        while (isActive) {
                            try {
                                val items = withContext(Dispatchers.IO) { load(user.id) }
                                if (users.currentUser.value?.id == user.id) display(items)
                            } catch (error: CancellationException) {
                                throw error
                            } catch (error: Exception) {
                                clear()
                                Timber.w(error, "RD watchlist unavailable")
                            }
                            delay(30_000)
                        }
                    }
            }
        }
    }

    private fun clear() {
        cards?.clear()
        row?.let { rows?.remove(it) }
    }

    private fun display(items: List<BaseItemDto>) {
        cards?.replaceAll(items.map { BaseItemDtoBaseRowItem(it) })
        val current = row ?: return
        val target = rows ?: return
        if (items.isEmpty()) target.remove(current)
        else if (target.indexOf(current) < 0) target.add(0, current)
    }

    private suspend fun load(userId: UUID): List<BaseItemDto> {
        val playlists = api.itemsApi.getItems(
            userId = userId, recursive = true,
            includeItemTypes = setOf(BaseItemKind.PLAYLIST),
            searchTerm = "RD-Merkliste", limit = 1000,
        ).content.items.filter { it.name == RoyalWatchlistPolicy.playlistName(userId) }
        if (playlists.isEmpty()) return emptyList()
        check(playlists.size == 1) { "Ambiguous RD playlist" }
        val items = mutableListOf<BaseItemDto>()
        var start = 0
        while (true) {
            val page = api.playlistsApi.getPlaylistItems(
                playlistId = playlists.single().id, userId = userId,
                startIndex = start, limit = 500, fields = ItemRepository.itemFields,
            ).content
            items.addAll(page.items)
            start += page.items.size
            if (page.items.isEmpty() || start >= page.totalRecordCount) break
            check(start < 100_000) { "RD playlist exceeds bounded read limit" }
        }
        val ids = RoyalWatchlistPolicy.cardIds(items)
        val details = ids.chunked(100).flatMap { batch ->
            api.itemsApi.getItems(userId = userId, ids = batch, recursive = true,
                fields = ItemRepository.itemFields, limit = batch.size).content.items
        }.associateBy { it.id }
        return ids.mapNotNull { details[it] }
            .filter { it.type == BaseItemKind.MOVIE || it.type == BaseItemKind.SERIES }
    }
}
