package org.jellyfin.androidtv.ui.search

import io.kotest.core.spec.style.FunSpec
import io.kotest.matchers.shouldBe
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.jellyfin.sdk.model.api.BaseItemDto

@OptIn(ExperimentalCoroutinesApi::class)
class RoyalSearchViewModelTests : FunSpec({
    test("RD submission retries the same query after an empty result") {
        runTest {
            val dispatcher = StandardTestDispatcher(testScheduler)
            Dispatchers.setMain(dispatcher)
            try {
                val queries = mutableListOf<String>()
                val model = RoyalSearchViewModel(
                    find = { queries.add(it); emptyList() },
                    prompt = { BaseItemDto(id = java.util.UUID.randomUUID(), type = org.jellyfin.sdk.model.api.BaseItemKind.FOLDER, name = "prompt") },
                    status = { name, _ -> BaseItemDto(id = java.util.UUID.randomUUID(), type = org.jellyfin.sdk.model.api.BaseItemKind.FOLDER, name = name) },
                    ioDispatcher = dispatcher,
                )
                model.searchImmediately("  Dark  ")
                advanceUntilIdle()
                model.searchResultsFlow.value.single().items.single().name shouldBe "Keine RD-Treffer"
                model.searchImmediately("Dark")
                advanceUntilIdle()
                queries shouldBe listOf("Dark", "Dark")
            } finally { Dispatchers.resetMain() }
        }
    }
    test("a new query cancels obsolete results and exposes the loading state") {
        runTest {
            val dispatcher = StandardTestDispatcher(testScheduler)
            Dispatchers.setMain(dispatcher)
            try {
                val model = RoyalSearchViewModel(
                    find = { delay(1000); listOf(BaseItemDto(id = java.util.UUID.randomUUID(), type = org.jellyfin.sdk.model.api.BaseItemKind.FOLDER, name = it)) },
                    prompt = { BaseItemDto(id = java.util.UUID.randomUUID(), type = org.jellyfin.sdk.model.api.BaseItemKind.FOLDER, name = "prompt") },
                    status = { name, _ -> BaseItemDto(id = java.util.UUID.randomUUID(), type = org.jellyfin.sdk.model.api.BaseItemKind.FOLDER, name = name) },
                    ioDispatcher = dispatcher,
                )
                model.searchImmediately("old")
                runCurrent()
                model.searchResultsFlow.value.single().items.single().name shouldBe "RD durchsuchen …"
                model.searchImmediately("new")
                advanceUntilIdle()
                model.searchResultsFlow.value.single().items.single().name shouldBe "new"
                model.searchImmediately(" ")
                model.searchResultsFlow.value.single().items.single().name shouldBe "prompt"
            } finally { Dispatchers.resetMain() }
        }
    }
})
