let preparePresentation;
try {
  ({ preparePresentation } = await import("./js/composition/index.js"));
} catch (error) {
  document.dispatchEvent(new Event("royal:boot-error"));
  throw error;
}

export const application = preparePresentation();
const { core, profile, settings } = application;

// ── Init ─────────────────────────────────────────────────────────────────
async function initApp() {
  await core.localization.initialize();
  // Blockiert, bis eine gültige Sitzung besteht. Ohne eingerichtetes Konto
  // oder vor der Ersteinrichtung kehrt der Aufruf sofort zurück.
  await profile.auth.requireLogin(); application.initUserProfile(); profile.tasteOnboarding.show();
  // Unabhängig von allen übrigen Startmodulen initialisieren: Ein Fehler in
  // Katalog, Suche oder Einstellungen darf den Kalender nicht blockieren.
  settings.calendar.initialize();
  document.querySelectorAll(".media-modal").forEach((modal) => document.body.appendChild(modal));
  application.mount();
  try {
    await settings.settings.initialize();
    document.dispatchEvent(new Event("royal:settings-ready"));
  } catch (e) {
    console.error("Einstellungen konnten nicht geladen werden:", e);
  }
  const needsSetup = await settings.setup.initialize();
  if (!needsSetup) core.startup.start();
  core.startupCurtain.finish();
}

function start() {
  initApp().catch((error) => {
    document.dispatchEvent(new Event("royal:boot-error"));
    core.startupCurtain.finish();
    console.error("Royal Downloader konnte nicht initialisiert werden:", error);
  });
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
else start();
