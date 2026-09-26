import { sharedPresentation } from "./js/shell/presentation.js";
import { initUserProfile } from "./js/shell/actions/user-profile.js";
import { initSettings } from "./js/shell/actions/settings.js";
import { preparePresentation, mountApplication } from "./js/composition/index.js";

preparePresentation();

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
  mountApplication();
  try {
    await initSettings();
    document.dispatchEvent(new Event("royal:settings-ready"));
  } catch (e) {
    console.error("Einstellungen konnten nicht geladen werden:", e);
  }
  const needsSetup = await sharedPresentation.setup.initialize();
  if (!needsSetup) sharedPresentation.startup.start();
  sharedPresentation.startupCurtain.finish();
}

document.addEventListener("DOMContentLoaded", () => {
  initApp().catch((error) => {
    sharedPresentation.startupCurtain.finish();
    console.error("Royal Downloader konnte nicht initialisiert werden:", error);
  });
});
