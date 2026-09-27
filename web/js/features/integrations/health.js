const labels = Object.freeze({
  healthy: "Erreichbar", degraded: "Eingeschränkt", offline: "Nicht erreichbar",
  auth_failed: "Anmeldung fehlgeschlagen", disabled: "Deaktiviert", unknown: "Unbekannt",
});

/** Only the server may classify integration health; media ownership is unrelated. */
export function integrationHealth(record) {
  const health = record?.integration_health;
  const state = Object.hasOwn(labels, health?.state) ? health.state : "unknown";
  return Object.freeze({ state, label: labels[state], detail: String(health?.detail || "") });
}
