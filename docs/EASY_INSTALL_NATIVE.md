# Native Easy Install – .NET 10 / WPF

RoyalDownloader Easy Install ist eine **eigenständige Windows-Anwendung in C#/.NET 10**.
Der Installer selbst benötigt kein Python und ist kein Tkinter/PyInstaller-Wrapper.

## Windows-PC

- Die EXE enthält ein offiziell bezogenes, SHA-256-geprüftes uv-Werkzeug und einen
  exakt versionierten Quellstand von RoyalDownloader.
- Für den **RoyalDownloader-Server** erstellt uv eine **private Python-3.12-Laufzeit
  im Royal-Programmordner**. Weder ein bestehendes Python 3.14 noch PATH oder
  die globale Registry werden verändert.
- Programme und Medien erhalten getrennte Zielordner. Vorhandene Programmordner
  werden nicht überschrieben.
- Chrome und FFmpeg müssen nicht pauschal vor der Installation nachinstalliert werden.
  Manche Provider- oder Medienfunktionen können sie später gezielt benötigen.
- Der normale Browserzugang erfolgt lokal über http://127.0.0.1:8765.
- Für den ersten Download des privaten Laufzeitsystems und der Abhängigkeiten
  ist eine Internetverbindung erforderlich.

## NAS

- Die NAS-Installation benötigt auf dem Windows-PC kein Python.
- SSH fragt den öffentlichen Hostschlüssel ab, **bevor** das echte Passwort
  verwendet wird. Der SHA-256-Fingerabdruck muss unabhängig bestätigt werden.
- Auch die SFTP-Übertragung vergleicht exakt den bestätigten SSH-Hostschlüssel.
- Der Installer prüft Docker Compose, die NAS-Architektur (x86_64), vorhandene
  Medienpfade, Schreibrechte, Platz, Port 8765 und Container-Kollisionen.
- Neue Projektdateien werden zuerst in einen zufälligen Staging-Pfad hochgeladen.
  Danach wird das Archiv per SHA-256 verifiziert und die Compose-Konfiguration
  geprüft. Erst dann wird der neue Projektordner veröffentlicht.
- Der Installer verändert **keine** Medien-ACLs, bestehenden Docker-Container
  oder vorhandene RoyalDownloader-Installationen.
- Port 8765 wird im lokalen Netz verfügbar. Eine direkte öffentliche
  Freigabe oder Router-Portweiterleitung wird nicht empfohlen.

## Abnahme und Grenzen

Der Installer ist ein Entwicklungsbuild. Der CI-Selbsttest prüft eingebettete
Pakete, Hashwerte und Basis-Pfadregeln, führt jedoch **keine echte Installation
auf einem PC oder NAS** aus.

Vor einem öffentlichen Release sind ein Windows-Neuinstallationstest, ein
separater NAS-Test mit sicheren Testpfaden, Abbruch-/Fehlerfalltests und eine
Authenticode-Signatur erforderlich. Ein Update vorhandener Installationen wird
bewusst nicht angeboten.

Quellen: installer/native/ – Windows-Build via
.github/workflows/native-installer-windows.yml.

Die alte Datei RoyalDownloader-Setup.pyw ist ein historischer Python-Prototyp
und keine Grundlage der nativen Anwendung.
