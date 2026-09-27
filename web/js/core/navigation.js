/** View lifetime is independent of CSS classes and MutationObserver callbacks. */
export function createNavigation() {
  const features = new Map();
  let current = null;
  return {
    register(name, feature, root) {
      if (features.has(name)) throw new Error(`Feature bereits registriert: ${name}`);
      features.set(name, { feature, root });
      return () => {
        if (current === name) { feature.unmount(); current = null; }
        features.delete(name);
      };
    },
    activate(name, options) {
      if (current === name) return;
      if (current) features.get(current)?.feature.unmount();
      current = name;
      const next = features.get(name);
      if (next) next.feature.mount(next.root, options);
    },
    refresh() { return features.get(current)?.feature.refresh(); },
    dispose() {
      if (current) features.get(current)?.feature.unmount();
      current = null;
    },
  };
}
