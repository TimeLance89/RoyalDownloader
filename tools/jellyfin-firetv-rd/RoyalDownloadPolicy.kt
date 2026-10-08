package org.jellyfin.androidtv.integration.royaldownloader

/** Keep unknown library state separate from confirmed missing episodes. */
internal object RoyalDownloadPolicy {
    fun canQueueSeries(
        availabilityPending: Boolean,
        jellyfinConfigured: Boolean?,
        jellyfinPending: Boolean,
        jellyfinAvailable: Boolean?,
        jellyfinStale: Boolean,
    ): Boolean = !availabilityPending && jellyfinConfigured != null &&
        (jellyfinConfigured == false ||
            (!jellyfinPending && jellyfinAvailable == true && !jellyfinStale))

    // A series match only proves that some episodes exist, not completeness.
    fun hideSearchResult(isMovie: Boolean, owned: Boolean): Boolean = isMovie && owned
}
