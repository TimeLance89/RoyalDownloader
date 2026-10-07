"""Apply guarded home-row additions against the pinned upstream source."""

from pathlib import Path


def patch_watchlist(root):
    directory = root / "app/src/main/java/org/jellyfin/androidtv/ui/home"
    template = Path(__file__).with_name("RoyalWatchlistHomeRow.kt")
    (directory / template.name).write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    path = directory / "HomeRowsFragment.kt"
    text = path.read_text(encoding="utf-8")
    additions = (
        ("\t\t\tregisterListener(notificationsRow::onItemClicked)\n", "\t\t\tregisterListener(notificationsRow::onItemClicked)\n\t\t\tregisterListener { _, item, _, _ -> royalWatchlist.onItemClicked(item) }\n"),
        ("\t// Special rows\n", "\t// Special rows\n\tprivate val royalWatchlist by lazy { RoyalWatchlistHomeRow(this, api, userRepository) }\n"),
        ("\t\t\t\t// Add rows in order\n", "\t\t\t\t// Add rows in order\n\t\t\t\troyalWatchlist.addToRowsAdapter(requireContext(), cardPresenter, adapter as MutableObjectAdapter<Row>)\n"),
        ("\tprivate fun refreshRows(force: Boolean = false, delayed: Boolean = true) {\n", "\tprivate fun refreshRows(force: Boolean = false, delayed: Boolean = true) {\n\t\troyalWatchlist.refresh()\n"),
    )
    for anchor, replacement in additions:
        if text.count(anchor) != 1:
            raise SystemExit(f"HomeRowsFragment watchlist anchor mismatch: {anchor.strip()}")
        text = text.replace(anchor, replacement, 1)
    path.write_text(text, encoding="utf-8")

    # Hide the routing suffix in native playlist cards/details too. The server
    # identity, lookup name and selected item ID remain unchanged.
    display_patches = (
        ("ui/itemhandling/BaseItemDtoBaseRowItem.kt", "\tbaseItem = item,\n",
         "\tbaseItem = org.jellyfin.androidtv.ui.home.RoyalWatchlistPolicy.displayItem(item),\n"),
        ("ui/itemdetail/ItemListFragmentHelper.kt", "\t\tif (isActive) setBaseItem(item)\n",
         "\t\tif (isActive) setBaseItem(org.jellyfin.androidtv.ui.home.RoyalWatchlistPolicy.displayItem(item))\n"),
    )
    for relative, anchor, replacement in display_patches:
        target = root / "app/src/main/java/org/jellyfin/androidtv" / relative
        text = target.read_text(encoding="utf-8")
        if text.count(anchor) != 1:
            raise SystemExit(f"Watchlist display anchor mismatch: {relative}")
        target.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")

    tests = root / "app/src/test/kotlin/ui/home"
    tests.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("RoyalWatchlistPolicyTests.kt")
    (tests / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
