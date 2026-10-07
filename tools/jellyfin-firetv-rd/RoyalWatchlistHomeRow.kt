package org.jellyfin.androidtv.ui.home

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.ViewGroup
import android.widget.TextView
import androidx.leanback.widget.ClassPresenterSelector
import androidx.leanback.widget.Presenter
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
import org.jellyfin.sdk.model.api.ItemSortBy
import org.jellyfin.sdk.model.api.SortOrder
import timber.log.Timber
import java.util.UUID

internal object RoyalWatchlistPolicy {
    fun playlistName(user: UUID): String = "RD-Merkliste · " + user.toString().replace("-", "")

    fun displayItem(item: BaseItemDto): BaseItemDto =
        if (item.type == BaseItemKind.PLAYLIST &&
            Regex("^RD-Merkliste · [0-9a-fA-F]{32}$").matches(item.name.orEmpty()))
            item.copy(name = "RD-Merkliste") else item

    // Jellyfin supplies newest-first ordering. Old empty generations must not
    // suppress the newly published list or leak removed titles back into it.
    fun playlist(items: List<BaseItemDto>, user: UUID): BaseItemDto? =
        items.firstOrNull { it.type == BaseItemKind.PLAYLIST && it.name == playlistName(user) }

    fun cardIds(items: List<BaseItemDto>): List<UUID> = items.mapNotNull { item ->
        when (item.type) {
            BaseItemKind.MOVIE -> item.id
            BaseItemKind.EPISODE -> item.seriesId
            else -> null
        }
    }.distinct()
}

internal data class RoyalWatchlistStatus(val message: String)

private class RoyalWatchlistStatusPresenter : Presenter() {
    override fun onCreateViewHolder(parent: ViewGroup): ViewHolder {
        val density = parent.resources.displayMetrics.density
        val view = TextView(parent.context).apply {
            layoutParams = ViewGroup.LayoutParams((520 * density).toInt(), (145 * density).toInt())
            setPadding((24 * density).toInt(), (20 * density).toInt(), (24 * density).toInt(), (20 * density).toInt())
            textSize = 18f
            setTextColor(Color.WHITE)
            gravity = android.view.Gravity.CENTER_VERTICAL
            isFocusable = true
            isFocusableInTouchMode = true
            setOnFocusChangeListener { _, focused ->
                background = GradientDrawable().apply {
                    cornerRadius = 12 * density
                    setColor(Color.parseColor(if (focused) "#234575" else "#202733"))
                    setStroke((2 * density).toInt(), Color.parseColor(if (focused) "#8FBFFF" else "#354052"))
                }
            }
            background = GradientDrawable().apply {
                cornerRadius = 12 * density
                setColor(Color.parseColor("#202733"))
            }
        }
        return ViewHolder(view)
    }

    override fun onBindViewHolder(viewHolder: ViewHolder, item: Any?) {
        (viewHolder.view as TextView).text = (item as RoyalWatchlistStatus).message
    }
    override fun onUnbindViewHolder(viewHolder: ViewHolder) {
        (viewHolder.view as TextView).text = ""
    }
}

/** Native Jellyfin items only: no RD account/session, synthetic items or downloads. */
class RoyalWatchlistHomeRow(
    private val owner: LifecycleOwner,
    private val api: ApiClient,
    private val users: UserRepository,
) : HomeFragmentRow {
    private var rows: MutableObjectAdapter<Row>? = null
    private var cards: MutableObjectAdapter<Any>? = null
    private var row: ListRow? = null
    private var attached = false
    private var displayedUser: UUID? = null
    private val refreshRevision = MutableStateFlow(0L)

    fun refresh() { refreshRevision.update { it + 1 } }
    fun onItemClicked(item: Any?) { if (item is RoyalWatchlistStatus) refresh() }

    override fun addToRowsAdapter(context: Context, cardPresenter: CardPresenter, rowsAdapter: MutableObjectAdapter<Row>) {
        if (attached) return
        attached = true
        rows = rowsAdapter
        cards = MutableObjectAdapter(ClassPresenterSelector()
            .addClassPresenter(BaseItemDtoBaseRowItem::class.java, cardPresenter)
            .addClassPresenter(RoyalWatchlistStatus::class.java, RoyalWatchlistStatusPresenter()))
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
                        if (cards?.size() == 0) status("Merkliste wird geladen …")
                        while (isActive) {
                            try {
                                val items = withContext(Dispatchers.IO) { load(user.id) }
                                if (users.currentUser.value?.id == user.id) display(items)
                            } catch (error: CancellationException) {
                                throw error
                            } catch (error: Exception) {
                                status("Merkliste konnte nicht geladen werden.\nOK drücken, um erneut zu prüfen.")
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
        if (items.isEmpty()) {
            status("Merke Filme und Serien in RoyalDownloader.\nSie erscheinen hier, sobald sie in Jellyfin verfügbar sind.\nOK: erneut prüfen")
            return
        }
        cards?.replaceAll(items.map { BaseItemDtoBaseRowItem(it) })
        val current = row ?: return
        val target = rows ?: return
        if (target.indexOf(current) < 0) target.add(0, current)
    }

    private fun status(message: String) {
        cards?.replaceAll(listOf(RoyalWatchlistStatus(message)))
        val current = row ?: return
        val target = rows ?: return
        if (target.indexOf(current) < 0) target.add(0, current)
    }

    private suspend fun load(userId: UUID): List<BaseItemDto> {
        val playlists = api.itemsApi.getItems(
            userId = userId, recursive = true,
            includeItemTypes = setOf(BaseItemKind.PLAYLIST),
            searchTerm = "RD-Merkliste", limit = 1000,
            sortBy = setOf(ItemSortBy.DATE_CREATED), sortOrder = setOf(SortOrder.DESCENDING),
        ).content.items
        val playlist = RoyalWatchlistPolicy.playlist(playlists, userId) ?: return emptyList()
        val items = mutableListOf<BaseItemDto>()
        var start = 0
        while (true) {
            val page = api.playlistsApi.getPlaylistItems(
                playlistId = playlist.id, userId = userId,
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
