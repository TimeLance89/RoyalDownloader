# Frontend Performance – Messprotokoll

Ausgangspunkt und Messgrenzen: [Baseline](FRONTEND_PERFORMANCE_BASELINE.md).
Die Arbeit ist noch nicht abgeschlossen; folgende Abschnitte dokumentieren geprüfte Zwischenschritte.

## Phase B – native Touch-Steuerung

- Geschlossener mobiler Menü-Scrim respektiert `hidden`. Die bisher versehentlich
  sichtbare Abdunklung und Eingabesperre entfallen. Offenes Menü unverändert.
- Touch/Pen normalisieren erst nach `scrollend` bzw. 180 ms Ruhe, niemals während
  des Fingerkontakts. `pointercancel` beim Beginn nativen Scrollens beendet keine Geste.
- Swipe-Erkennung unterdrückt versehentliche Card-Klicks, ohne native Bewegung zu verhindern.
- Ein echter Cover-Tap deckte zusätzlich eine verschattete `coverUrl`-Funktion auf;
  die lokale Poster-Variable ist jetzt eindeutig benannt.
- 390×844, 430×932 und 768×1024: beide Swipe-Richtungen, schnelle Swipes, Settle,
  vertikales Seiten-Panning, Detail-Tap und Orientation-Wechsel erfolgreich.
  Keine JS-Schreibzugriffe auf `scrollLeft` während Fingerkontakt.
- Tab-Position und Loop-Seam werden in Phase C zusätzlich anhand logischer Anker geprüft.

Rohmessungen: [Phase B](performance/phase-b.json), [Touch](performance/mobile-phase-b.json).
Unverändert 97 logische Einträge, 257 vollständige Cards, 6320 DOM-Elemente.
Noch keine Performanceverbesserung durch DOM-Reduktion beansprucht.

### Bewusste CSS-Ausnahme

Der eingefrorene Vor-Refactor-Stand bleibt unverändert. Im CSS-Vergleich erhält
nur dessen **geschlossener** Menü-Scrim dieselbe `hidden`-Korrektur. Damit wird
die beabsichtigte Oberfläche verglichen; die fehlerhafte Abdunklung ist ausdrücklich
kein zu erhaltendes Designmerkmal. Alle übrigen 2398 Elementvergleiche bleiben strikt.
