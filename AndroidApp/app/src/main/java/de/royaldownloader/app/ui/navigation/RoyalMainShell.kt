package de.royaldownloader.app.ui.navigation

import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.*
import de.royaldownloader.app.data.RoyalRepository
import de.royaldownloader.app.ui.components.*
import de.royaldownloader.app.ui.detail.DetailKind
import de.royaldownloader.app.ui.detail.DetailScreen
import de.royaldownloader.app.ui.detail.DetailViewModel
import de.royaldownloader.app.ui.discover.DiscoverScreen
import de.royaldownloader.app.ui.discover.DiscoverViewModel
import de.royaldownloader.app.ui.home.HomeScreen
import de.royaldownloader.app.ui.home.HomeViewModel
import de.royaldownloader.app.ui.queue.QueueScreen
import de.royaldownloader.app.ui.queue.QueueViewModel
import de.royaldownloader.app.ui.settings.SettingsScreen
import de.royaldownloader.app.ui.settings.SettingsViewModel
import de.royaldownloader.app.ui.simpleViewModelFactory
import de.royaldownloader.app.ui.watchlist.WatchlistScreen
import de.royaldownloader.app.ui.watchlist.WatchlistViewModel

private const val HOME = "home"
private const val DISCOVER = "discover"
private const val QUEUE = "queue"
private const val WATCHLIST = "watchlist"
private const val SETTINGS = "settings"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RoyalMainShell(
    repository: RoyalRepository,
) {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route.orEmpty()
    val rootRoutes = setOf(HOME, DISCOVER, QUEUE, WATCHLIST, SETTINGS)
    val showChrome = currentRoute in rootRoutes
    val queue by repository.queue.collectAsStateWithLifecycle()
    val destinations = listOf(
        RoyalNavigationDestination(HOME, "Home", Icons.Rounded.Home, Icons.Rounded.Home),
        RoyalNavigationDestination(DISCOVER, "Entdecken", Icons.Rounded.Search, Icons.Rounded.TravelExplore),
        RoyalNavigationDestination(QUEUE, "Queue", Icons.Rounded.Download, Icons.Rounded.Downloading, queue.count.takeIf { it > 0 }),
        RoyalNavigationDestination(WATCHLIST, "Abos", Icons.Rounded.BookmarkBorder, Icons.Rounded.Bookmark),
        RoyalNavigationDestination(SETTINGS, "Setup", Icons.Rounded.Settings, Icons.Rounded.Settings),
    )

    Scaffold(
        containerColor = androidx.compose.ui.graphics.Color.Transparent,
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        bottomBar = {
            if (showChrome) {
                RoyalNavigationBar(
                    destinations = destinations,
                    selectedKey = currentRoute,
                    onDestinationSelected = { destination ->
                        navController.navigate(destination.key) {
                            popUpTo(navController.graph.findStartDestination().id) { saveState = true }
                            launchSingleTop = true
                            restoreState = true
                        }
                    },
                    modifier = Modifier.navigationBarsPadding(),
                )
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = HOME,
            modifier = Modifier
                .fillMaxSize()
                .then(if (showChrome) Modifier.statusBarsPadding() else Modifier)
                .padding(if (showChrome) padding else PaddingValues(0.dp)),
        ) {
            composable(HOME) {
                val vm: HomeViewModel = viewModel(factory = simpleViewModelFactory { HomeViewModel(repository) })
                HomeScreen(
                    viewModel = vm,
                    onMovie = { navController.openMovie(it) },
                    onSeries = { base, sample -> navController.openSeries(base, sample) },
                    onAnime = { navController.openAnime(it) },
                    onOpenQueue = { navController.navigate(QUEUE) },
                    onOpenWatchlist = { navController.navigate(WATCHLIST) },
                )
            }
            composable(DISCOVER) {
                val vm: DiscoverViewModel = viewModel(factory = simpleViewModelFactory { DiscoverViewModel(repository) })
                DiscoverScreen(
                    viewModel = vm,
                    onMovie = { navController.openMovie(it) },
                    onSeries = { base, sample -> navController.openSeries(base, sample) },
                    onAnime = { navController.openAnime(it) },
                )
            }
            composable(QUEUE) {
                val vm: QueueViewModel = viewModel(factory = simpleViewModelFactory { QueueViewModel(repository) })
                QueueScreen(vm)
            }
            composable(WATCHLIST) {
                val vm: WatchlistViewModel = viewModel(factory = simpleViewModelFactory { WatchlistViewModel(repository) })
                WatchlistScreen(
                    viewModel = vm,
                    onOpenSeries = { base -> navController.openSubscribedSeries(base) },
                )
            }
            composable(SETTINGS) {
                val vm: SettingsViewModel = viewModel(factory = simpleViewModelFactory { SettingsViewModel(repository) })
                SettingsScreen(vm)
            }
            composable("detail/movie?slug={slug}") { entry ->
                val slug = entry.arguments?.getString("slug").orEmpty()
                val vm: DetailViewModel = viewModel(
                    key = "movie:$slug",
                    factory = simpleViewModelFactory { DetailViewModel(repository, DetailKind.MOVIE, slug) },
                )
                DetailScreen(vm, DetailKind.MOVIE, onBack = navController::popBackStack)
            }
            composable("detail/series?base={base}&sample={sample}&subscription={subscription}") { entry ->
                val base = entry.arguments?.getString("base").orEmpty()
                val sample = entry.arguments?.getString("sample").orEmpty()
                val fromWatchlist = entry.arguments?.getString("subscription").toBoolean()
                val vm: DetailViewModel = viewModel(
                    key = "series:$base:$fromWatchlist",
                    factory = simpleViewModelFactory {
                        DetailViewModel(repository, DetailKind.SERIES, base, sample, fromWatchlist)
                    },
                )
                DetailScreen(vm, DetailKind.SERIES, onBack = navController::popBackStack)
            }
            composable("detail/anime?id={id}") { entry ->
                val id = entry.arguments?.getString("id").orEmpty()
                val vm: DetailViewModel = viewModel(
                    key = "anime:$id",
                    factory = simpleViewModelFactory { DetailViewModel(repository, DetailKind.ANIME, id) },
                )
                DetailScreen(vm, DetailKind.ANIME, onBack = navController::popBackStack)
            }
        }
    }
}

private fun NavHostController.openMovie(slug: String) = navigate("detail/movie?slug=${Uri.encode(slug)}")
private fun NavHostController.openSeries(base: String, sample: String) =
    navigate("detail/series?base=${Uri.encode(base)}&sample=${Uri.encode(sample)}&subscription=false")
private fun NavHostController.openSubscribedSeries(base: String) =
    navigate("detail/series?base=${Uri.encode(base)}&sample=&subscription=true")
private fun NavHostController.openAnime(id: String) = navigate("detail/anime?id=${Uri.encode(id)}")
