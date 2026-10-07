import { test } from "node:test";
import assert from "node:assert/strict";
import { createHomeCatalog } from "../../web/js/features/home/catalog.js";
import { createHomeCards } from "../../web/js/features/home/cards.js";

test("anime results with identical IDs retain their provider and open its detail view", () => {
  const mkissa = { id: "bleach", title: "Bleach", provider: "mkissa" };
  const aniworld = { id: "bleach", title: "Bleach", provider: "aniworld" };
  const catalog = createHomeCatalog({
    getAnimeResults: () => [mkissa],
    getSearchResults: () => [{ kind: "anime", item: aniworld }],
  });
  const entries = [catalog.homeAnimeEntry(mkissa), catalog.homeAnimeEntry(aniworld)];
  assert.equal(catalog.uniqueHomeEntries(entries).length, 2);
  assert.equal(catalog.homeEntryKey(entries[0]), "anime:bleach");
  assert.equal(catalog.homeEntryKey(entries[1]), "anime:aniworld:bleach");
  assert.equal(catalog.homeAnimeById("bleach"), mkissa);
  assert.equal(catalog.homeAnimeById("aniworld:bleach"), aniworld);

  const opened = [];
  let rendered;
  const cards = createHomeCards({
    homeAnimeById: catalog.homeAnimeById,
    openAnimeDetail: item => opened.push(["mkissa", item]),
    openAniworldDetail: item => opened.push(["aniworld", item]),
    homeEntryMedia: entry => entry.item,
    getJellyfinStatus: () => "missing",
    homeEntryKey: catalog.homeEntryKey,
    mediaJellyfinStatus: () => "missing",
    renderMediaCard: options => {
      rendered = options;
      return { querySelector: () => null };
    },
    markLanguage() {}, enhanceTaste() {}, enhanceHero() {},
    enhanceDailyTop: card => card,
    openDailyTop: () => false,
  });
  cards.open("anime", "bleach");
  cards.create(entries[1]);
  assert.equal(rendered.key, "aniworld:bleach");
  rendered.onOpen();
  assert.deepEqual(opened, [["mkissa", mkissa], ["aniworld", aniworld]]);
});
