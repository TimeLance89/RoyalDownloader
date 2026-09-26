function createInitialState() {
  return {
    tab: "home",
    queue: { count: 0, groups: [], loaded: false },
    download: { active: false, percent: 0, completed: 0, total: 0, failed: 0 },
    queuedSlugs: new Set(),
  };
}
