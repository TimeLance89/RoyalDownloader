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
})
