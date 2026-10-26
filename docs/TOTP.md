# Zwei-Faktor-Anmeldung mit Authenticator

RD unterstützt TOTP gemäß RFC 6238: sechs Ziffern, 30 Sekunden und HMAC-SHA1.
Die Einrichtung funktioniert beispielsweise mit Google Authenticator aus dem
Play Store. Eine Anmeldung bei Google ist für dessen Offline-Codes nicht nötig.
Andere Apps mit Unterstützung für `otpauth://totp` sind ebenfalls kompatibel.

## Einrichten

1. RD über die HTTPS-Adresse öffnen und anmelden.
2. **Einstellungen → Zugang → Konto & Sicherheit → Zwei-Faktor-Anmeldung** öffnen.
3. Das aktuelle RD-Passwort eingeben und **Authenticator einrichten** wählen.
4. In Google Authenticator einen Code hinzufügen und den QR-Code scannen.
   Alternativ den angezeigten Einrichtungsschlüssel manuell eingeben.
5. Den aktuellen sechsstelligen Code in RD eingeben und die Aktivierung bestätigen.
6. Die zehn einmaligen Wiederherstellungscodes getrennt vom Telefon sichern.
   RD zeigt sie nur bei ihrer Erstellung an. Danach **Codes gesichert** wählen.

Erst die erfolgreiche Bestätigung aktiviert 2FA für dieses Konto. Die Einrichtung
verfällt nach zehn Minuten. Die Aktivierung meldet andere Sitzungen des Kontos
ab; die aktuelle Sitzung wird durch eine mit 2FA bestätigte Sitzung ersetzt.

Danach benötigt jede neue Anmeldung zusätzlich zum Passwort einen aktuellen
Authenticator-Code oder einen unbenutzten Wiederherstellungscode. Das gilt auch
im LAN. Es gibt keine anhand von IP-Adressen gesteuerte Ausnahme. Konten ohne
aktiviertes 2FA behalten ihren bisherigen Anmeldeablauf. Die Funktion aktiviert
sich beim Update nicht selbst und verpflichtet andere Konten nicht automatisch.

Ein akzeptierter Code kann nicht erneut verwendet werden, auch nicht direkt nach
der Einrichtung. Für die nächste Aktion den nächsten Code abwarten. Telefon und
NAS sollten ihre Uhr automatisch synchronisieren; RD toleriert einen benachbarten
Zeitschritt. Nach fünf falschen Codes greift eine kontoweite zeitweilige Sperre.

## Wiederherstellung und Wechsel des Telefons

- Ein Wiederherstellungscode ersetzt bei der Anmeldung den Authenticator-Code.
  Er wird erst nach korrektem Passwort und dauerhaft gespeicherter Prüfung verbraucht.
- Neue Wiederherstellungscodes erfordern das Passwort und einen gültigen Faktor.
  Sie ersetzen alle bisherigen Codes.
- Zum Wechsel des Authenticator-Schlüssels zuerst mit Passwort und gültigem
  Faktor deaktivieren und anschließend erneut einrichten.
- Ein administrativer Passwort-Reset entfernt 2FA nicht. Auch bei der ersten
  Anmeldung nach dem Reset bleibt der bestehende zweite Faktor erforderlich.
- Fehlen Telefon und sämtliche Wiederherstellungscodes, existiert keine
  öffentliche Passwort-only-Resetfunktion für 2FA. Dann ist lokale administrative
  Wiederherstellung aus einer vertrauenswürdigen NAS-Sicherung erforderlich.

## Speicherung und Betrieb

Die Kontodatei `users.json` enthält nur verschlüsselte TOTP-Schlüssel und Hashes
der zufälligen Wiederherstellungscodes. Der Verschlüsselungsschlüssel `mfa.key`
liegt daneben im persistenten Konfigurationsverzeichnis. Beide Dateien werden
mit Dateirechten 0600 angelegt. **Beide zusammen sichern** und den Zugriff auf
die Sicherung beschränken. Die Verschlüsselung schützt keine vollständige
NAS-Übernahme, bei der ein Angreifer auch die Schlüsseldatei lesen kann.

Bei fehlendem oder beschädigtem Schlüssel scheitert TOTP geschlossen. Ein noch
gültiger Wiederherstellungscode kann weiterhin zur Wiederherstellung verwendet
werden. RD ersetzt einen fehlenden Schlüssel bei vorhandenen aktiven 2FA-Konten
nicht automatisch. Speicherfehler erzeugen keine erfolgreiche Anmeldung.

Sitzungen enthalten die bestätigte 2FA-Generation. Eine Aktivierung oder erneute
Einrichtung macht ältere und kontolose Altsitzungen ungültig, selbst wenn deren
Widerruf nicht gespeichert werden kann. Basic-Auth wird für Konten mit aktivem
2FA abgewiesen. Profilwechsel umgehen die Code-Prüfung ebenfalls nicht.

QR-Codes werden lokal erzeugt. Einrichtungsschlüssel und Wiederherstellungscodes
gehen an keinen externen QR-Dienst und werden im Browser nicht dauerhaft
gespeichert. Beim Verlassen der Kontoeinstellungen werden sie aus der Oberfläche
entfernt. Bestehender CSRF-, Cookie-, Host- und Profilbesitzschutz gilt weiterhin.

Wie die vorhandenen Konto-/Sitzungsdateien ist diese Implementierung für einen
RD-Backendprozess vorgesehen. Mehrere unabhängige Backendprozesse dürfen diese
Dateien nicht gleichzeitig als gemeinsame Authentifizierungsdatenbank verwenden.
Ein Downgrade auf eine Version ohne TOTP-Unterstützung kann 2FA nicht durchsetzen;
solche Versionen dürfen mit diesen Kontodaten nicht öffentlich betrieben werden.

## Android-/TV-Clients

Die nativen Clientquellen liegen nicht in diesem Repository. Die API unterstützt
2FA; ältere Clients ohne Code-Eingabefeld können sich bei aktivierten Konten nicht
neu anmelden. Sie erhalten eine strukturierte `mfa_required`-Antwort und keinen
Bearer. Vor Aktivierung auf einem gemeinsam verwendeten Konto den eingesetzten
Client auf Code-Eingabe prüfen. Es gibt keinen Passwort-only-Fallback für alte Apps.

Details für Cliententwickler stehen in [ANDROID_API.md](ANDROID_API.md).

## Referenzen

- [RFC 6238](https://www.rfc-editor.org/rfc/rfc6238)
- [Google Authenticator installieren und verwenden](https://support.google.com/accounts/answer/1066447?hl=de)
