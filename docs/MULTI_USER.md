# Multi-User Core V1

RoyalDownloader verwaltet Haushaltskonten in `users.json`; Passwörter werden ausschließlich als PBKDF2-Hash gespeichert. Eine vorhandene Einzelkonto-Konfiguration wird beim ersten Start als aktiver Administrator migriert. Downloads, Queue, Provider, Storage und Systemintegrationen bleiben gemeinsame Instanzressourcen.

Administratoren können über die geschützten Benutzer-Endpunkte Mitglieder oder weitere Administratoren anlegen. Neue Konten haben keinen Passwort-Hash und stehen auf `setup_required`. Der erste Login setzt mit Benutzername, Passwort und Bestätigung ein eigenes Passwort und erstellt danach eine neue, benutzergebundene Sitzung.

Sitzungen speichern nur einen Token-Hash und den `user_id`. Deaktivierung oder Admin-Reset widerruft alle Sitzungen dieses Benutzers. Der letzte aktive Administrator kann nicht deaktiviert werden. Passwort-Hashes werden niemals über die API ausgegeben.

Die serverseitige `current_user`-Funktion löst die Identität aus der Sitzung auf; künftige Taste-Profile, Watchlists und Empfehlungen können dadurch sauber `user_id`-bezogen werden. Diese V1 migriert keine bestehenden globalen Katalog-, Queue- oder Watchlist-Daten.
