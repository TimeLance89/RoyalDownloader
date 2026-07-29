package de.royaldownloader.app.data.remote

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface RoyalApi {
    @GET("api/v1/capabilities") suspend fun capabilitiesV1(): CapabilitiesResponse
    @GET("api/v1/health") suspend fun healthV1(): HealthResponse
    @GET("api/health") suspend fun healthLegacy(): HealthResponse
    @GET("api/v1/auth/status") suspend fun authStatusV1(): AuthStatus
    @GET("api/auth/status") suspend fun authStatusLegacy(): AuthStatus
    @POST("api/v1/auth/login") suspend fun loginV1(@Body body: LoginRequest): Response<MobileLoginResponse>
    @POST("api/auth/login") suspend fun loginLegacy(@Body body: LoginRequest): Response<AuthStatus>
    @POST("api/v1/auth/logout") suspend fun logoutV1(
        @Header("Authorization") authorization: String? = null,
    ): OkResponse
    @POST("api/auth/logout") suspend fun logoutLegacy(
        @Header("Cookie") cookie: String? = null,
    ): OkResponse

    @GET("api/v1/movies") suspend fun moviesV1(
        @Query("mode") mode: String,
        @Query("query") query: String = "",
        @Query("genre") genre: String = "",
        @Query("page") page: Int = 1,
    ): MovieCatalogResponse
    @GET("api/movies") suspend fun moviesLegacy(
        @Query("mode") mode: String,
        @Query("query") query: String = "",
        @Query("genre") genre: String = "",
        @Query("page") page: Int = 1,
    ): MovieCatalogResponse
    @GET("api/v1/movie/{slug}") suspend fun movieV1(@Path("slug") slug: String): MovieDetail
    @GET("api/movie/{slug}") suspend fun movieLegacy(@Path("slug") slug: String): MovieDetail
    @POST("api/v1/tmdb/movies") suspend fun movieMetadataV1(
        @Body body: MovieMetadataRequest,
    ): MovieMetadataResponse
    @POST("api/tmdb/movies") suspend fun movieMetadataLegacy(
        @Body body: MovieMetadataRequest,
    ): MovieMetadataResponse

    @GET("api/v1/series") suspend fun seriesV1(
        @Query("mode") mode: String,
        @Query("query") query: String = "",
        @Query("letter") letter: String = "",
        @Query("page") page: Int = 1,
    ): SeriesCatalogResponse
    @GET("api/series") suspend fun seriesLegacy(
        @Query("mode") mode: String,
        @Query("query") query: String = "",
        @Query("letter") letter: String = "",
        @Query("page") page: Int = 1,
    ): SeriesCatalogResponse
    @POST("api/v1/series/load") suspend fun seriesDetailV1(@Body body: SeriesLoadRequest): SeriesDetail
    @POST("api/series/load") suspend fun seriesDetailLegacy(@Body body: SeriesLoadRequest): SeriesDetail

    @GET("api/v1/anime") suspend fun animeV1(
        @Query("mode") mode: String,
        @Query("query") query: String = "",
        @Query("page") page: Int = 1,
    ): AnimeCatalogResponse
    @GET("api/anime") suspend fun animeLegacy(
        @Query("mode") mode: String,
        @Query("query") query: String = "",
        @Query("page") page: Int = 1,
    ): AnimeCatalogResponse
    @GET("api/v1/anime/{id}") suspend fun animeDetailV1(
        @Path("id") id: String,
        @Query("translation") translation: String = "",
        @Query("episode_page") page: Int = 1,
    ): AnimeDetail
    @GET("api/anime/{id}") suspend fun animeDetailLegacy(
        @Path("id") id: String,
        @Query("translation") translation: String = "",
        @Query("episode_page") page: Int = 1,
    ): AnimeDetail

    @GET("api/v1/queue") suspend fun queueV1(): QueueResponse
    @GET("api/queue") suspend fun queueLegacy(): QueueResponse
    @POST("api/v1/queue/add") suspend fun addQueueV1(@Body body: QueueSlugsRequest): QueueResponse
    @POST("api/queue/add") suspend fun addQueueLegacy(@Body body: QueueSlugsRequest): QueueResponse
    @POST("api/v1/queue/remove") suspend fun removeQueueV1(@Body body: QueueRemoveRequest): QueueResponse
    @POST("api/queue/remove") suspend fun removeQueueLegacy(@Body body: QueueRemoveRequest): QueueResponse
    @POST("api/v1/download/cancel") suspend fun cancelDownloadsV1(): OkResponse
    @POST("api/download/cancel") suspend fun cancelDownloadsLegacy(): OkResponse

    @GET("api/v1/watchlist") suspend fun watchlistV1(): WatchlistResponse
    @GET("api/watchlist") suspend fun watchlistLegacy(): WatchlistResponse
    @POST("api/v1/watchlist/add") suspend fun addWatchlistV1(@Body body: WatchlistAddRequest): WatchlistResponse
    @POST("api/watchlist/add") suspend fun addWatchlistLegacy(@Body body: WatchlistAddRequest): WatchlistResponse
    @POST("api/v1/watchlist/mode") suspend fun watchlistModeV1(@Body body: WatchlistModeRequest): WatchlistResponse
    @POST("api/watchlist/mode") suspend fun watchlistModeLegacy(@Body body: WatchlistModeRequest): WatchlistResponse
    @POST("api/v1/watchlist/remove") suspend fun removeWatchlistV1(@Body body: WatchlistRemoveRequest): WatchlistResponse
    @POST("api/watchlist/remove") suspend fun removeWatchlistLegacy(@Body body: WatchlistRemoveRequest): WatchlistResponse
    @POST("api/v1/watchlist/check") suspend fun checkWatchlistV1(@Body body: WatchlistCheckRequest): WatchlistResponse
    @POST("api/watchlist/check") suspend fun checkWatchlistLegacy(@Body body: WatchlistCheckRequest): WatchlistResponse
    @POST("api/v1/watchlist/open") suspend fun openWatchlistV1(@Body body: WatchlistOpenRequest): SeriesDetail
    @POST("api/watchlist/open") suspend fun openWatchlistLegacy(@Body body: WatchlistOpenRequest): SeriesDetail
}
