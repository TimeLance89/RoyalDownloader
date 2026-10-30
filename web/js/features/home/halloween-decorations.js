/** Existing licensed PNG artwork, attached only to the edges of existing Home surfaces. */
const placements = [
  { id: "hero-web", host: "#home-hero", asset: "corner-web", kind: "web", edge: "top-left", stage: 1 },
  { id: "hero-bats", host: "#home-hero", asset: "bat-flight", kind: "bats", edge: "top-right", stage: 2 },
  { id: "series-web", host: ".home-rail-series", asset: "corner-web", kind: "web", edge: "rail-left", stage: 2 },
  { id: "hero-pumpkin", host: "#home-hero", asset: "jack-o-lantern", kind: "pumpkin", edge: "hero-right", stage: 3 },
  { id: "gems-bats", host: ".home-rail-gems", asset: "bat-flight", kind: "bats", edge: "rail-right", stage: 3 },
  { id: "hero-web-final", host: "#home-hero", asset: "corner-web", kind: "web", edge: "top-right", stage: 4 },
  { id: "hero-pumpkin-final", host: "#home-hero", asset: "jack-o-lantern", kind: "pumpkin", edge: "hero-pair", stage: 4 },
  { id: "gems-pumpkin", host: ".home-rail-gems", asset: "jack-o-lantern", kind: "pumpkin", edge: "rail-left", stage: 4 },
  { id: "new-web", host: ".home-rail-new", asset: "corner-web", kind: "web", edge: "rail-left", stage: 4 },
];

export function clearHalloweenDecorations(root) {
  root.querySelectorAll(".home-event-decoration").forEach(node => node.remove());
}

export function renderHalloweenDecorations(root, stage) {
  for (const placement of placements) {
    const existing = root.querySelector(`[data-event-decoration="${placement.id}"]`);
    if (placement.stage > stage) { existing?.remove(); continue; }
    if (existing) continue;
    const host = root.querySelector(placement.host);
    if (!host) continue;
    const image = root.ownerDocument.createElement("img");
    image.className = `home-event-decoration event-decor-${placement.kind} event-decor-${placement.edge}`;
    image.dataset.eventDecoration = placement.id;
    image.src = `/assets/events/${placement.asset}.png`;
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    image.draggable = false;
    image.decoding = "async";
    host.append(image);
  }
}
