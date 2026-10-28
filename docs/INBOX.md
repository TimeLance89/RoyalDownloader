# Abo-Inbox

- **Entfernen** entfernt eine Meldung aus der eigenen Inbox. **Alle entfernen**
  entfernt die Meldungen des gewählten Filters, einschließlich der zusammengefassten
  Quellenhinweise. Das ist auch für normale Mitglieder verfügbar.
- Abonnements, Dateien, geplante Downloads und automatische Prüfungen bleiben
  bestehen. Abos werden weiterhin unter **Abos verwalten** bearbeitet.
- Entfernungen werden pro Benutzer auf dem NAS gespeichert, gelten auch auf
  anderen Browsern nach Aktualisierung und bleiben nach einem Neustart erhalten.
  Fehlgeschlagenes Speichern blendet die betroffenen Meldungen nicht aus.
- Entfernt wird der angezeigte Meldungsstand. Neue Folgen, Downloadbelege, neue
  Quellenstörungen und neue Revisionen offizieller Mitteilungen können wieder
  erscheinen. Poll-Zeitpunkt und Prüffortschritt erzeugen keine neue Meldung.
- Technische Quellenhinweise stehen als ein eingeklappter Abschnitt hinter der
  Abo-Aktivität. Der Abschnitt zählt als ein Inbox-Eintrag; seine Überschrift
  nennt die Zahl der enthaltenen Hinweise. Der Filter **Offen** enthält diese
  technischen Quellenhinweise nicht.
- Eine unvollständige oder nur eingeschränkt mögliche Hosterprüfung zählt nicht
  allein wegen einer älteren Diagnose als bestätigter Fehler. Überwachung und
  Reparaturversuche laufen unabhängig von entfernten Inbox-Meldungen weiter.

Technisch liegen nur undurchsichtige Meldungskennungen in `inbox.sqlite3` neben
der Benutzerdatei. Alle Zugriffe binden die Anmeldung und optional den erwarteten
Profil-Header. Bei Kontolöschung werden dessen Kennungen entfernt. Die Datei ist
unter POSIX nur für den ausführenden Benutzer lesbar. Maximal 10.000 Kennungen pro
Benutzer; die Grenze führt zu einer sichtbaren Fehlermeldung, nicht zur stillen
Wiederherstellung alter Meldungen. Es werden keine Abos oder Downloadzustände in
dieser Datei verändert.
