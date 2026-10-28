# Eigene URL für das NAS

Unter **Einstellungen → Externer Zugriff** führt Royal durch die Einrichtung
einer eigenen HTTPS-Adresse. Jeder Betreiber verwendet seine eigene Domain und
sein eigenes Cloudflare-Konto. Es gibt keine zentralen Royal-Subdomains.

## Voraussetzungen und Ablauf

1. NAS-Installation mit bestehendem Docker-Compose-Projekt, eingerichtetem
   Royal-Administratorkonto und eigener Domain mit aktivem DNS bei Cloudflare.
   Bei NAS-Container-Oberflächen ohne Compose muss zuerst ein passendes Projekt
   mit denselben Mounts und Einstellungen erstellt werden. Der Assistent
   übernimmt diese Umstellung nicht automatisch.
2. Eigene Adresse angeben, z. B. `royal.meine-domain.de`. Bei einem abweichenden
   Compose-Dienst dessen Namen in den erweiterten Angaben setzen.
3. Im eigenen Cloudflare-Konto einen remotely managed Tunnel anlegen. Docker
   auswählen, Token kopieren und öffentliche Anwendungsroute einrichten:
   Hostname wie in Royal, Typ HTTP, Service-URL wie im Assistenten. Den Host-Header
   nicht überschreiben. Keine zusätzliche Router-Portfreigabe.
4. Token in Royal einfügen und ZIP herunterladen. Der Token wird nicht gespeichert;
   die ZIP und die darin enthaltene Token-Datei sind vertraulich. In das bestehende
   Compose-Projekt entpacken, Besitzer auf PUID/PGID des Projekts setzen und
   `chmod 600 cloudflare-tunnel.token` ausführen. Die beiliegenden Ignore-Muster
   zur eigenen `.gitignore` hinzufügen. README und angezeigten Startbefehl befolgen.
5. HTTPS-Verbindung in Royal prüfen. Nach Erfolg die eigene Adresse öffnen und
   anmelden. Authenticator unter **Zugang** einrichten; Wiederherstellungscodes
   getrennt sichern. Alte Android/TV-Clients benötigen dafür Code-Eingabe-Unterstützung.

Die Aktivierung bei Cloudflare sowie das Anwenden der Dateien auf dem NAS bleiben
bewusste Schritte des Betreibers. Der Download allein veröffentlicht nichts und
verändert weder DNS noch laufende Container. Vorhandene Tunnel zuerst sichern.
Domainkosten trägt der Betreiber. Bestehende WAN-Portfreigaben entfernen und
IPv6-Firewall prüfen. LAN-Zugriff bleibt verfügbar.

## Technische Grenzen

- Das Overlay ergänzt den vorhandenen Royal-Dienst ausschließlich um explizite
  Host-/Proxy-Umgebungsvariablen. Medienpfade, Images und Portbindungen stammen
  weiter aus der bestehenden Compose-Datei. Keine Docker-Socket-Freigabe.
- Der begrenzte, unprivilegierte cloudflared-Container teilt Royals Netzwerkraum
  und erreicht Royal über Loopback. Nur Loopback ist als Proxy freigegeben;
  direkte LAN-Clients können Cloudflare-IP-Header nicht verwenden. Andere
  Reverse-Proxys müssen getrennt geprüft werden.
- Bei einer späteren Neuerstellung des Royal-Containers auch den Tunnel neu
  erstellen, damit der gemeinsame Netzwerkraum stimmt. Der generierte Befehl
  erstellt beide Dienste neu. Die Token-Datei bleibt für den Betrieb erforderlich.
- Die HTTPS-Prüfung akzeptiert ausschließlich öffentliche DNS-Antworten und
  verbindet sich mit einer geprüften numerischen IP, bei TLS mit dem richtigen
  Domainnamen. Keine Weiterleitungen, Cookies, App-Zugangsdaten oder System-Proxys.
- Eine zufällige kurzlebige Challenge bestätigt die **eigene** Installation;
  das erwartete separate Geheimnis wird nicht an die eingegebene Adresse gesendet.
  Erst danach werden Anmeldepflicht und anonyme API-Abweisung geprüft.
- Genau ein ausstehender Prüfauftrag, auch wenn DNS länger hängt. Wartezeit der
  API höchstens 22 Sekunden, Wiederholungen frühestens nach zehn Sekunden.
  Kein periodischer Scan und kein persistenter Tunnel-Token in Royal.
- Cloudflare Access ist ein separater Zugangsschutz und kann die automatische
  Prüfung blockieren. Dann gibt es keine Erfolgsmeldung. Ein erfolgreicher Test
  bestätigt weder Router-/IPv6-Firewall noch vollständige WebSocket-Funktion
  oder jede Anwendungssicherheits-Eigenschaft.

Rücknahme: Tunnel-Container stoppen und entfernen, öffentliche Route im eigenen
Cloudflare-Konto entfernen, ursprüngliches Compose-Projekt ohne Overlay neu
erstellen. Keine automatische Löschung von Medien oder bestehenden NAS-Dateien.

Offizielle Grundlagen: [Tunnel im Dashboard anlegen](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/),
[Tunnel-Parameter und Token-Datei](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/),
[cloudflared-Version 2026.10.4](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.4).
