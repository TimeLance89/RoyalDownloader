package org.jellyfin.androidtv.integration.royaldownloader

import io.kotest.core.spec.style.FunSpec
import io.kotest.matchers.shouldBe

class RoyalDownloadPolicyTests : FunSpec({
    test("series can queue only after a complete current library check") {
        RoyalDownloadPolicy.canQueueSeries(false, true, false, true, false) shouldBe true
        RoyalDownloadPolicy.canQueueSeries(false, true, false, false, false) shouldBe false
        RoyalDownloadPolicy.canQueueSeries(false, true, false, null, false) shouldBe false
        RoyalDownloadPolicy.canQueueSeries(false, true, true, true, false) shouldBe false
        RoyalDownloadPolicy.canQueueSeries(false, true, false, true, true) shouldBe false
        RoyalDownloadPolicy.canQueueSeries(true, true, false, true, false) shouldBe false
        RoyalDownloadPolicy.canQueueSeries(false, null, false, true, false) shouldBe false
    }
    test("an explicitly unconfigured RD library still permits released episodes") {
        RoyalDownloadPolicy.canQueueSeries(false, false, false, null, false) shouldBe true
        RoyalDownloadPolicy.canQueueSeries(true, false, false, null, false) shouldBe false
    }
    test("partly imported series remain discoverable while owned movies are hidden") {
        RoyalDownloadPolicy.hideSearchResult(false, true) shouldBe false
        RoyalDownloadPolicy.hideSearchResult(true, true) shouldBe true
        RoyalDownloadPolicy.hideSearchResult(true, false) shouldBe false
    }
})
