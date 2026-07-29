package de.royaldownloader.app.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.KSerializer
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.jsonPrimitive

object FlexibleStringSerializer : KSerializer<String> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("FlexibleString", PrimitiveKind.STRING)
    override fun serialize(encoder: Encoder, value: String) = encoder.encodeString(value)
    override fun deserialize(decoder: Decoder): String = when (decoder) {
        is JsonDecoder -> decoder.decodeJsonElement().jsonPrimitive.content
        else -> decoder.decodeString()
    }
}

@Serializable
data class HealthResponse(
    val status: String = "unknown",
    val initialized: Boolean = false,
    @SerialName("queue_active") val queueActive: Int = 0,
    @SerialName("queue_pending") val queuePending: Int = 0,
)

@Serializable
data class AuthStatus(
    val configured: Boolean = false,
    val required: Boolean = false,
    val authenticated: Boolean = false,
    val username: String = "",
    val source: String = "none",
    @SerialName("setup_required") val setupRequired: Boolean = false,
    @SerialName("prompt_setup") val promptSetup: Boolean = false,
    @SerialName("min_password_length") val minPasswordLength: Int = 8,
    @SerialName("min_username_length") val minUsernameLength: Int = 3,
)

@Serializable
data class CapabilitiesResponse(
    @SerialName("api_version") @Serializable(with = FlexibleStringSerializer::class) val apiVersion: String = "legacy",
    @SerialName("supported_api_versions") val supportedApiVersions: List<Int> = listOf(1),
    @SerialName("minimum_api_version") val minClientApi: Int = 1,
    val initialized: Boolean = false,
    @SerialName("authentication") val auth: CapabilityAuth = CapabilityAuth(),
    val features: Map<String, Boolean> = emptyMap(),
    val websocket: CapabilityWebSocket = CapabilityWebSocket(),
)

@Serializable
data class CapabilityAuth(
    val configured: Boolean = false,
    val required: Boolean = false,
    val methods: List<String> = emptyList(),
)

@Serializable
data class CapabilityWebSocket(
    val path: String = "/ws",
    @SerialName("authorization_header") val authorizationHeader: Boolean = true,
    @SerialName("event_schema_version") val eventSchemaVersion: Int = 1,
)

@Serializable data class LoginRequest(
    val username: String,
    val password: String,
    @SerialName("device_label") val deviceName: String = "Android",
    @SerialName("app_version") val appVersion: String = "",
)

@Serializable
data class MobileLoginResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("token_type") val tokenType: String = "bearer",
    @SerialName("expires_in") val expiresIn: Long = 0,
    val username: String = "",
)

@Serializable data class OkResponse(val ok: Boolean = true)

@Serializable
data class MovieCatalogResponse(
    val results: List<MovieSummary> = emptyList(),
    val category: String? = null,
    val page: Int = 1,
    @SerialName("has_more") val hasMore: Boolean = false,
    val sources: List<ProviderSource> = emptyList(),
)

@Serializable
data class ProviderSource(
    val key: String = "",
    val label: String = "",
    @SerialName("content_language") val contentLanguage: String = "",
    @SerialName("language_label") val languageLabel: String = "",
    val count: Int? = null,
)

@Serializable
data class MovieSummary(
    val title: String,
    val slug: String,
    val url: String = "",
    val year: String = "",
    @SerialName("is_movie") val isMovie: Boolean = true,
    val provider: String = "",
    @SerialName("content_language") val contentLanguage: String = "",
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("backdrop_url") val backdropUrl: String = "",
    val description: String = "",
    val rating: Double? = null,
    @SerialName("release_date") val releaseDate: String = "",
    @SerialName("in_cinema") val inCinema: Boolean = false,
    @SerialName("in_jellyfin") val inJellyfin: Boolean? = null,
    @SerialName("tmdb_id") val tmdbId: Int? = null,
)

@Serializable
data class MovieMetadataItem(
    val slug: String,
    val title: String,
    val year: String = "",
)

@Serializable
data class MovieMetadataRequest(
    val items: List<MovieMetadataItem>,
)

@Serializable
data class MovieMetadataResponse(
    val movies: Map<String, MovieListMetadata> = emptyMap(),
)

@Serializable
data class MovieListMetadata(
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("backdrop_url") val backdropUrl: String = "",
    val description: String = "",
    val rating: Double? = null,
    @SerialName("release_date") val releaseDate: String = "",
    @SerialName("in_cinema") val inCinema: Boolean = false,
)

@Serializable
data class MovieDetail(
    val title: String,
    val url: String = "",
    val year: String = "",
    val runtime: String = "",
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("backdrop_url") val backdropUrl: String = "",
    val description: String = "",
    val genres: List<String> = emptyList(),
    val provider: String = "",
    @SerialName("provider_label") val providerLabel: String = "",
    @SerialName("content_language") val contentLanguage: String = "",
    @SerialName("language_label") val languageLabel: String = "",
    val hosters: List<Hoster> = emptyList(),
    @SerialName("hoster_label") val hosterLabel: String = "",
    @SerialName("hoster_route") val hosterRoute: String = "",
    val rating: Double? = null,
    @SerialName("vote_count") val voteCount: Int? = null,
    val tagline: String = "",
    val certification: String = "",
    @SerialName("certification_country") val certificationCountry: String = "",
    val status: String = "",
    @SerialName("original_title") val originalTitle: String = "",
    @SerialName("release_date") val releaseDate: String = "",
    @SerialName("original_language") val originalLanguage: String = "",
    @SerialName("spoken_languages") val spokenLanguages: List<String> = emptyList(),
    val countries: List<String> = emptyList(),
    val directors: List<String> = emptyList(),
    val writers: List<String> = emptyList(),
    val cast: List<CastMember> = emptyList(),
    @SerialName("production_companies") val productionCompanies: List<String> = emptyList(),
    val keywords: List<String> = emptyList(),
    val collection: String = "",
    val budget: Long = 0,
    val revenue: Long = 0,
    val trailer: MovieTrailer? = null,
    @SerialName("tmdb_url") val tmdbUrl: String = "",
    @SerialName("metadata_source") val metadataSource: String = "",
    @SerialName("hoster_score") val hosterScore: Double? = null,
    @SerialName("hoster_fallback_count") val hosterFallbackCount: Int = 0,
    @SerialName("source_providers") val sourceProviders: List<MovieSource> = emptyList(),
    @SerialName("provider_count") val providerCount: Int = 0,
    @SerialName("provider_fallback_count") val providerFallbackCount: Int = 0,
    @SerialName("hoster_total") val hosterTotal: Int = 0,
    @SerialName("provider_route") val providerRoute: String = "",
    @SerialName("tmdb_id") val tmdbId: Int? = null,
)

@Serializable
data class MovieSource(
    val key: String = "",
    val label: String = "",
    @SerialName("content_language") val contentLanguage: String = "",
    @SerialName("hoster_count") val hosterCount: Int = 0,
    val hosters: List<Hoster> = emptyList(),
)

@Serializable data class MovieTrailer(
    val site: String = "",
    val key: String = "",
    val name: String = "",
    val official: Boolean = false,
)

@Serializable data class CastMember(
    val name: String = "",
    val character: String = "",
    @SerialName("profile_url") val profileUrl: String = "",
)

@Serializable data class Hoster(
    val name: String = "",
    val url: String = "",
    val language: String = "",
    val quality: String = "",
)

@Serializable
data class SeriesCatalogResponse(
    val results: List<SeriesSummary> = emptyList(),
    val entries: List<SeriesSummary> = emptyList(),
    val mode: String = "",
    val page: Int = 1,
    @SerialName("has_more") val hasMore: Boolean = false,
    val sources: List<ProviderSource> = emptyList(),
) {
    val items: List<SeriesSummary> get() = if (results.isNotEmpty()) results else entries
}

@Serializable
data class SeriesSummary(
    val title: String,
    @SerialName("base_slug") val baseSlug: String = "",
    @SerialName("sample_slug") val sampleSlug: String = "",
    @SerialName("sample_url") val sampleUrl: String = "",
    val year: String = "",
    @SerialName("cover_url") val coverUrl: String = "",
    val provider: String = "",
    @SerialName("provider_label") val providerLabel: String = "",
    @SerialName("content_language") val contentLanguage: String = "",
    @SerialName("language_label") val languageLabel: String = "",
)

@Serializable data class SeriesLoadRequest(
    @SerialName("sample_slug") val sampleSlug: String,
    @SerialName("base_slug") val baseSlug: String = "",
    @SerialName("refresh_jellyfin") val refreshJellyfin: Boolean = false,
    @SerialName("defer_checks") val deferChecks: Boolean = false,
)

@Serializable
data class SeriesDetail(
    val title: String,
    @SerialName("base_slug") val baseSlug: String,
    val url: String = "",
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("backdrop_url") val backdropUrl: String = "",
    val description: String = "",
    val genres: List<String> = emptyList(),
    val seasons: List<Season> = emptyList(),
    val provider: String = "",
    @SerialName("provider_label") val providerLabel: String = "",
    @SerialName("content_language") val contentLanguage: String = "",
    @SerialName("language_label") val languageLabel: String = "",
    @SerialName("episode_count") val episodeCount: Int = 0,
    val watchlisted: Boolean = false,
    @SerialName("availability_pending") val availabilityPending: Boolean = false,
    @SerialName("availability_error") val availabilityError: String = "",
    @SerialName("enrichment_pending") val enrichmentPending: Boolean = false,
    @SerialName("jellyfin_configured") val jellyfinConfigured: Boolean = false,
    @SerialName("jellyfin_pending") val jellyfinPending: Boolean = false,
    @SerialName("jellyfin_available") val jellyfinAvailable: Boolean? = null,
    @SerialName("watch_mode") val watchMode: String = "all",
    @SerialName("cleanup_mode") val cleanupMode: String = "keep",
    @SerialName("metadata_source") val metadataSource: String = "",
    val year: String = "",
    @SerialName("first_air_date") val firstAirDate: String = "",
    val runtime: String = "",
    @SerialName("original_title") val originalTitle: String = "",
    val rating: Double? = null,
    @SerialName("vote_count") val voteCount: Int? = null,
    val status: String = "",
    val cast: List<CastMember> = emptyList(),
    val creators: List<String> = emptyList(),
    val networks: List<String> = emptyList(),
    val trailer: MovieTrailer? = null,
    @SerialName("tmdb_id") val tmdbId: Int? = null,
    val aliases: List<String> = emptyList(),
    @SerialName("season_episode_counts") val seasonEpisodeCounts: Map<String, Int> = emptyMap(),
    @SerialName("season_counts_checked_at") val seasonCountsCheckedAt: Double = 0.0,
    @SerialName("preselect_slugs") val preselectSlugs: List<String> = emptyList(),
    val subscription: WatchlistItem? = null,
)

@Serializable data class Season(val season: Int, val episodes: List<Episode> = emptyList())

@Serializable
data class Episode(
    val season: Int,
    val episode: Int,
    val slug: String,
    val url: String = "",
    @SerialName("release_name") val releaseName: String = "",
    val queued: Boolean = false,
    val downloaded: Boolean = false,
    @SerialName("in_jellyfin") val inJellyfin: Boolean = false,
    val unreleased: Boolean = false,
)

@Serializable
data class AnimeCatalogResponse(
    val results: List<AnimeSummary> = emptyList(),
    val mode: String = "latest",
    val page: Int = 1,
    @SerialName("has_more") val hasMore: Boolean = false,
    val total: Int = 0,
    val disabled: Boolean = false,
    @SerialName("disabled_reason") val disabledReason: String = "",
)

@Serializable
data class AnimeSummary(
    val id: String,
    val title: String,
    @SerialName("media_type") val mediaType: String = "TV",
    val year: String = "",
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("banner_url") val bannerUrl: String = "",
    val description: String = "",
    val genres: List<String> = emptyList(),
    val rating: Double? = null,
    val translations: Map<String, Int> = emptyMap(),
    @SerialName("episode_count") val episodeCount: Int = 0,
)

@Serializable
data class AnimeDetail(
    val id: String,
    val title: String,
    @SerialName("media_type") val mediaType: String = "TV",
    val year: String = "",
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("banner_url") val bannerUrl: String = "",
    val description: String = "",
    val genres: List<String> = emptyList(),
    val rating: Double? = null,
    val translations: Map<String, Int> = emptyMap(),
    val translation: String = "",
    @SerialName("translation_labels") val translationLabels: Map<String, String> = emptyMap(),
    val episodes: List<AnimeEpisode> = emptyList(),
    val page: Int = 1,
    @SerialName("page_count") val pageCount: Int = 1,
    val total: Int = 0,
)

@Serializable data class AnimeEpisode(
    val number: Int,
    val label: String,
    val slug: String,
    val queued: Boolean = false,
    val downloaded: Boolean = false,
)

@Serializable data class QueueResponse(
    val queue: QueueSnapshot = QueueSnapshot(),
    val added: Int = 0,
    val skipped: Int = 0,
    @SerialName("skipped_details") val skippedDetails: Map<String, String> = emptyMap(),
)
@Serializable data class QueueSnapshot(val count: Int = 0, val groups: List<QueueGroup> = emptyList())
@Serializable data class QueueGroup(val name: String, val items: List<QueueItem> = emptyList())
@Serializable data class QueueItem(
    val slug: String,
    val title: String,
    @SerialName("hoster_label") val hosterLabel: String = "",
    val provider: String = "",
    @SerialName("content_language") val contentLanguage: String = "",
    val done: Boolean = false,
)

@Serializable data class QueueSlugsRequest(val slugs: List<String>)
@Serializable data class QueueRemoveRequest(val slug: String)

@Serializable data class WatchlistResponse(val watchlist: List<WatchlistItem> = emptyList())

@Serializable
data class WatchlistItem(
    @SerialName("base_slug") val baseSlug: String,
    val title: String,
    @SerialName("cover_url") val coverUrl: String = "",
    @SerialName("backdrop_url") val backdropUrl: String = "",
    @SerialName("sample_url") val sampleUrl: String = "",
    @SerialName("known_slugs") val knownSlugs: List<String> = emptyList(),
    @SerialName("download_mode") val downloadMode: String = "all",
    @SerialName("download_mode_label") val downloadModeLabel: String = "",
    @SerialName("cleanup_mode") val cleanupMode: String = "keep",
    @SerialName("cleanup_mode_label") val cleanupModeLabel: String = "",
    @SerialName("last_error") val lastError: String = "",
    @SerialName("last_checked") val lastChecked: Double = 0.0,
    @SerialName("tmdb_id") val tmdbId: Int? = null,
    val aliases: List<String> = emptyList(),
    @SerialName("season_episode_counts") val seasonEpisodeCounts: Map<String, Int> = emptyMap(),
    @SerialName("season_counts_checked_at") val seasonCountsCheckedAt: Double = 0.0,
    @SerialName("new_count") val newCount: Int = 0,
    @SerialName("queued_count") val queuedCount: Int = 0,
    @SerialName("failed_count") val failedCount: Int = 0,
    val status: String = "current",
)

@Serializable data class WatchlistAddRequest(
    @SerialName("base_slug") val baseSlug: String,
    val title: String,
    @SerialName("sample_url") val sampleUrl: String,
    @SerialName("known_slugs") val knownSlugs: List<String>,
    @SerialName("download_mode") val downloadMode: String = "all",
    @SerialName("cleanup_mode") val cleanupMode: String? = null,
    @SerialName("tmdb_id") val tmdbId: Int? = null,
    val aliases: List<String>? = null,
    @SerialName("season_episode_counts") val seasonEpisodeCounts: Map<String, Int>? = null,
    @SerialName("season_counts_checked_at") val seasonCountsCheckedAt: Double = 0.0,
)

@Serializable data class WatchlistModeRequest(
    @SerialName("base_slug") val baseSlug: String,
    @SerialName("download_mode") val downloadMode: String,
    @SerialName("cleanup_mode") val cleanupMode: String? = null,
)

@Serializable data class WatchlistRemoveRequest(@SerialName("base_slugs") val baseSlugs: List<String>)
@Serializable data class WatchlistCheckRequest(@SerialName("base_slugs") val baseSlugs: List<String>? = null)
@Serializable data class WatchlistOpenRequest(@SerialName("base_slug") val baseSlug: String)

@Serializable
data class SocketEvent(
    val type: String = "unknown",
    val message: String = "",
    val level: String = "",
    val label: String = "",
    val slug: String = "",
    val msg: String = "",
    val pct: Double? = null,
    val ok: Boolean? = null,
    val active: Int? = null,
    val pending: Int? = null,
    val queue: QueueSnapshot? = null,
    val watchlist: List<WatchlistItem>? = null,
)

@Serializable data class ErrorPayload(
    val detail: String? = null,
    val error: String? = null,
    val code: String? = null,
)
