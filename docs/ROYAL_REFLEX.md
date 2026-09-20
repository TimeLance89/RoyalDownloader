# Royal Reflex

Royal Reflex ist die lokale Entscheidungsengine von Royal Intelligence. Sie bewertet ausschließlich vorhandene Startseiten-Kandidaten und besitzt keinen Zugriff auf Downloads, Queue, Provider, Dateien, Storage oder Automation.

## Architektur

Royal Intelligence liefert einen kompakten Geschmackszustand und maximal 24 Katalog-Kandidaten an Royal Reflex. Das lokale Ollama-Backend beantwortet in **einer** begrenzten Inference pro Kandidatenpool nur Zeilen im Format `key|score|angle|noul`. Royal Reflex validiert jede Zeile strikt und erzeugt daraus die geschlossenen Primitive:

- **Choice**: ausschließlich `taste`, `adjacent` oder `surprise`.
- **Score**: Level 0–4, normalisiert auf 0–100.
- **Noul**: vom Modell begrenzter Wert 0–1 für Empfehlungswert.

Ollama liefert in seiner lokalen API keine verlässlichen Token-Logprobs. Deshalb veröffentlicht Royal Reflex keine erfundenen Wahrscheinlichkeitsverteilungen. `confidence` ist transparent ein Separation-Proxy: `0.5 + 0.5 × |score - 2| / 2`; er beschreibt nicht die tatsächliche Korrektheit.

RoyalDownloader kombiniert Score (80 %) und Noul (20 %), wählt maximal acht gültige Kandidaten und verhindert gleiche Genregruppen. Gründe werden deterministisch aus echten Genreüberschneidungen erzeugt.

## Betrieb

Aktivierung und Laufzeit liegen beim Modul **Royal Intelligence**. Das einzige Backend ist lokales Ollama; Modell, URL und Timeout bleiben frei konfigurierbar. Kleine Modelle um 1.5–2B Parameter sind der vorgesehene Low-Resource-Bereich, größere lokale Modelle können robuster sein. Es gibt keine Cloud-API und keine laufenden API-Kosten.

Der Cache gilt sechs Stunden; Modell, Reflex-Version, Profil und Kandidatenmenge sind Teil des Keys. Bei Timeout, Parsing- oder Backend-Fehler wird nur der Intelligence-Bereich ausgelassen, während die Startseite und alle Core-Funktionen normal laufen.

Eine spätere Benchmark-/Distillation-Erweiterung kann dieselbe `evaluate(state, questions)`-Grenze nutzen. Nutzerdaten werden nicht exportiert oder gesammelt.
