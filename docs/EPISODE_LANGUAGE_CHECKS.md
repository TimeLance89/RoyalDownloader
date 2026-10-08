# Reihenfolge der Episoden-Sprachprüfung

Die Reihenfolge der Quellenprüfung richtet sich nach dem bestätigten Bestand.
Sie erteilt selbst keine Sprachfreigabe und startet keine Downloads.

- Eine direkte Folgen- oder Staffelauswahl erhält Vorrang vor wartenden
  automatischen Prüfungen. Bereits laufende Anfragen werden geteilt.
- Bei bestätigtem leerem Bestand beginnt die automatische Prüfung mit der
  ersten Staffel und arbeitet Folgen und Staffeln aufsteigend ab.
- Bei vorhandenem Bestand beginnt sie mit fehlenden Folgen der letzten
  vorhandenen Staffel und setzt danach mit den folgenden Staffeln fort.
  Beispiel: Staffeln 1–12 vollständig, S13E01–06 vorhanden → S13E07 zuerst.
- Nach jeweils zwei Anschluss-Paketen folgt ein Paket mit älteren Lücken.
  Gibt es keinen neueren Anschluss mehr, werden die älteren Lücken abgearbeitet.
- Ein Paket enthält höchstens vier Folgen. Es laufen weiterhin höchstens
  zwei Anfragen gleichzeitig; eine langsame Anfrage blockiert die andere nicht.

Bestand bedeutet bestätigte Downloads oder vorhandene Jellyfin-Folgen.
Anbieterauflistungen und Warteschlangeneinträge zählen nicht dazu.
Vorhandene, unveröffentlichte und für die aktuelle Sprachwahl bereits geprüfte
Folgen werden übersprungen. Wartende Pakete berücksichtigen neu eingetroffene
Bestandsdaten vor ihrem tatsächlichen Start.

Ein leichtgewichtiger Detailabruf ohne Bestandsdaten wartet für automatische
Prüfungen auf das Enrichment. Eine ausdrückliche Auswahl kann währenddessen
bereits geprüft werden. Ist Jellyfin danach nicht erreichbar oder liegt nur
ein alter Stand vor, gilt der Bestand als unbekannt. Bestätigte vorhandene
Folgen bleiben erhalten; ohne positive Bestandsdaten bleibt vorläufig die
neueste Staffel priorisiert. Sobald neue Bestandsdaten eintreffen, werden
wartende automatische Pakete neu geordnet. Laufende und ausgewählte Prüfungen
behalten ihren Platz.

Regressionen: `tests/frontend/series-selection.test.mjs`,
`tests/movie_catalog_refresh.test.mjs` und
`tests/frontend/series-selection-browser.cjs` (Desktop und Mobilgerät).
