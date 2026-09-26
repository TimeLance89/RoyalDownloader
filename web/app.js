import { prepareLegacyPresentation, mountLegacyApplication } from "./js/legacy-adapter.js";

prepareLegacyPresentation();

// ── Init ─────────────────────────────────────────────────────────────────
async function initApp() {
  await sharedPresentation.localization.initialize();
  // Blockiert, bis eine gültige Sitzung besteht. Ohne eingerichtetes Konto
  // oder vor der Ersteinrichtung kehrt der Aufruf sofort zurück.
  await sharedPresentation.auth.requireLogin(); initUserProfile(); sharedPresentation.tasteOnboarding.show();
  // Unabhängig von allen übrigen Startmodulen initialisieren: Ein Fehler in
  // Katalog, Suche oder Einstellungen darf den Kalender nicht blockieren.
  sharedPresentation.calendar.initialize();
  document.querySelectorAll(".media-modal").forEach((modal) => document.body.appendChild(modal));
  mountLegacyApplication();
  try {
    await initSettings();
    document.dispatchEvent(new Event("royal:settings-ready"));
  } catch (e) {
    console.error("Einstellungen konnten nicht geladen werden:", e);
  }
  const needsSetup = await sharedPresentation.setup.initialize();
  if (!needsSetup) sharedPresentation.startup.start();
  window.royalLoader?.finish();
}

document.addEventListener("DOMContentLoaded", () => {
  initApp().catch((error) => {
    window.royalLoader?.finish();
    console.error("Royal Downloader konnte nicht initialisiert werden:", error);
  });
});
