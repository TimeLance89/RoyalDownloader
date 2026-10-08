"""Dedicated RD destination using upstream TV input and navigation controls."""
from pathlib import Path


def replace_once(path, anchor, replacement):
    text = path.read_text(encoding="utf-8")
    if text.count(anchor) != 1:
        raise SystemExit(f"RD search anchor mismatch: {path.name}: {anchor.strip()}")
    path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")


def patch_search(root):
    directory = root / "app/src/main/java/org/jellyfin/androidtv"
    search = directory / "ui/search"
    template = Path(__file__).with_name("RoyalSearchViewModel.kt")
    (search / template.name).write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    tests = root / "app/src/test/kotlin/ui/search"
    tests.mkdir(parents=True, exist_ok=True)
    test_source = Path(__file__).with_name("RoyalSearchViewModelTests.kt")
    (tests / test_source.name).write_text(test_source.read_text(encoding="utf-8"), encoding="utf-8")
    replace_once(root / "app/build.gradle.kts",
                 "\ttestImplementation(libs.kotest.runner.junit5)\n",
                 "\ttestImplementation(libs.kotest.runner.junit5)\n\ttestImplementation(\"org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2\")\n")

    # Keep keyboard, voice input and Amazon's fullscreen-keyboard focus fix.
    fragment = (search / "SearchFragment.kt").read_text(encoding="utf-8")
    fragment = fragment.replace("class SearchFragment :", "class RoyalSearchFragment :")
    fragment = fragment.replace("import org.koin.androidx.compose.koinViewModel", "import androidx.lifecycle.ViewModelProvider\nimport org.jellyfin.androidtv.ui.base.Text\nimport org.jellyfin.androidtv.ui.base.button.Button")
    fragment = fragment.replace("val viewModel = koinViewModel<SearchViewModel>()", "val viewModel = ViewModelProvider(this@RoyalSearchFragment)[RoyalSearchViewModel::class.java]")
    fragment = fragment.replace("MainToolbar(MainToolbarActiveButton.Search)", "MainToolbar(MainToolbarActiveButton.RoyalSearch)")
    fragment = fragment.replace("\t\t\tLaunchedEffect(Unit) {\n", "\t\t\tLaunchedEffect(Unit) {\n\t\t\t\tviewModel.refresh()\n", 1)
    fragment = fragment.replace("\t\t\t\t\tSearchTextInput(\n", "\t\t\t\t\tButton(onClick = { RoyalDownloaderBridge.showConfigurationDialog(requireContext()) { viewModel.refresh() } }) { Text(\"RD verbinden\") }\n\n\t\t\t\t\tSearchTextInput(\n", 1)
    (search / "RoyalSearchFragment.kt").write_text(fragment, encoding="utf-8")

    replace_once(directory / "ui/navigation/Destinations.kt",
                 "\tval home = fragmentDestination<HomeFragment>()\n",
                 "\tval home = fragmentDestination<HomeFragment>()\n\tfun royalSearch() = fragmentDestination<org.jellyfin.androidtv.ui.search.RoyalSearchFragment>()\n")
    toolbar = directory / "ui/shared/toolbar/MainToolbar.kt"
    replace_once(toolbar, "\tSearch,\n", "\tSearch,\n\tRoyalSearch,\n")
    replace_once(toolbar,
                 "\t\t\t\t\t\tcontent = { Text(stringResource(R.string.lbl_search)) }\n\t\t\t\t\t)\n",
                 "\t\t\t\t\t\tcontent = { Text(stringResource(R.string.lbl_search)) }\n\t\t\t\t\t)\n\t\t\t\t\tButton(\n\t\t\t\t\t\tonClick = { if (activeButton != MainToolbarActiveButton.RoyalSearch) navigationRepository.navigate(Destinations.royalSearch()) },\n\t\t\t\t\t\tcolors = if (activeButton == MainToolbarActiveButton.RoyalSearch) activeButtonColors else ButtonDefaults.colors(),\n\t\t\t\t\t\tcontent = { Text(\"RD durchsuchen\") },\n\t\t\t\t\t)\n")
