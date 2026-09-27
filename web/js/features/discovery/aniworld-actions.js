export function createAniworldActions({
  getAniworld,
}) {
  function aniworldBrowse(...args) { return getAniworld().browse(...args); }
  function loadNextAniworldPage(...args) { return getAniworld().next(...args); }
  function openAniworldDetail(...args) { return getAniworld().open(...args); }
  function loadAniworldDetail(...args) { return getAniworld().loadDetail(...args); }
  function renderAniworldResults(...args) { return getAniworld().renderResults(...args); }
  function renderAniworldDetail(...args) { return getAniworld().renderDetail(...args); }
  function renderAniworldEpisodes(...args) { return getAniworld().renderEpisodes(...args); }
  function syncAniworldQueueFlags(...args) { return getAniworld().syncQueue(...args); }
  function markAniworldSlugDownloaded(...args) { return getAniworld().markDownloaded(...args); }
  function aniworldAddSelected(...args) { return getAniworld().addSelected(...args); }
  function aniworldVisibleEpisodes(...args) { return getAniworld().visibleEpisodes(...args); }
  function aniworldSelectableEpisodes(...args) { return getAniworld().selectableEpisodes(...args); }
  function updateAniworldInfiniteState(...args) { return getAniworld().updateInfinite(...args); }
  return { aniworldBrowse, loadNextAniworldPage, openAniworldDetail, loadAniworldDetail, renderAniworldResults, renderAniworldDetail, renderAniworldEpisodes, syncAniworldQueueFlags, markAniworldSlugDownloaded, aniworldAddSelected, aniworldVisibleEpisodes, aniworldSelectableEpisodes, updateAniworldInfiniteState };
}
