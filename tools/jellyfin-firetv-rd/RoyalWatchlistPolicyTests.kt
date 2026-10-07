package org.jellyfin.androidtv.ui.home

import org.jellyfin.sdk.model.api.BaseItemDto
import org.jellyfin.sdk.model.api.BaseItemKind
import io.kotest.core.spec.style.FunSpec
import io.kotest.matchers.shouldBe
import io.kotest.matchers.shouldNotBe
import java.util.UUID

class RoyalWatchlistPolicyTests : FunSpec({
    test("lists are scoped to the active Jellyfin user") {
        val first = UUID.fromString("00000000-0000-0000-0000-000000000001")
        val second = UUID.fromString("00000000-0000-0000-0000-000000000002")
        RoyalWatchlistPolicy.playlistName(first) shouldBe "RD-Merkliste · 00000000000000000000000000000001"
        RoyalWatchlistPolicy.playlistName(first) shouldNotBe RoyalWatchlistPolicy.playlistName(second)
    }

    test("episodes collapse into one series card and movies stay distinct") {
        val movie = UUID.randomUUID()
        val series = UUID.randomUUID()
        val items = listOf(
            BaseItemDto(id = movie, type = BaseItemKind.MOVIE),
            BaseItemDto(id = UUID.randomUUID(), type = BaseItemKind.EPISODE, seriesId = series),
            BaseItemDto(id = UUID.randomUUID(), type = BaseItemKind.EPISODE, seriesId = series),
            BaseItemDto(id = UUID.randomUUID(), type = BaseItemKind.EPISODE),
            BaseItemDto(id = UUID.randomUUID(), type = BaseItemKind.AUDIO),
        )
        RoyalWatchlistPolicy.cardIds(items) shouldBe listOf(movie, series)
    }

    test("newest matching generation wins without selecting another profile") {
        val user = UUID.randomUUID()
        val foreign = BaseItemDto(id = UUID.randomUUID(), type = BaseItemKind.PLAYLIST,
            name = RoyalWatchlistPolicy.playlistName(UUID.randomUUID()))
        val newest = BaseItemDto(id = UUID.randomUUID(), type = BaseItemKind.PLAYLIST,
            name = RoyalWatchlistPolicy.playlistName(user))
        val old = newest.copy(id = UUID.randomUUID())
        RoyalWatchlistPolicy.playlist(listOf(foreign, newest, old), user) shouldBe newest
        RoyalWatchlistPolicy.playlist(listOf(foreign), user) shouldBe null
    }

    test("native playlist UI hides the routing suffix without changing identity") {
        val playlist = BaseItemDto(id = UUID.randomUUID(), type = BaseItemKind.PLAYLIST,
            name = RoyalWatchlistPolicy.playlistName(UUID.randomUUID()))
        RoyalWatchlistPolicy.displayItem(playlist).name shouldBe "RD-Merkliste"
        RoyalWatchlistPolicy.displayItem(playlist).id shouldBe playlist.id
        val movie = playlist.copy(type = BaseItemKind.MOVIE)
        RoyalWatchlistPolicy.displayItem(movie) shouldBe movie
        val ordinary = playlist.copy(name = "Meine Filme")
        RoyalWatchlistPolicy.displayItem(ordinary) shouldBe ordinary
    }
})
