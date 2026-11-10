"""Guided RoyalDownloader installer GUI. Runs offline until the user opts in.

The build produces a standalone .exe on Windows. No hidden SSH verification,
container changes or implicit software installation happens while browsing the wizard.
"""
from __future__ import annotations

import argparse
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

from .core import (
    InstallError, NasConfig, NasSession, WindowsConfig, find_python_312,
    install_nas, install_windows, install_prerequisites_via_winget,
    packaged_source, preflight_nas, preflight_windows,
    validate_nas, validate_windows,
)

COL = {
    "navy": "#0b1326", "navy2": "#15233b", "navy3": "#233755",
    "white": "#ffffff", "paper": "#f7f9fc", "line": "#e5eaf2", "ink": "#152238",
    "sub": "#65758c", "blue": "#2272ef", "blue2": "#eaf2ff", "teal": "#10b5a2",
    "green": "#157c58", "greenbg": "#e3f5ed", "amber": "#a86113", "amberbg": "#fff4dc",
    "red": "#bd3445", "redbg": "#fff1f3",
}
F = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
TOTAL = 6
STEPS = ["Installationsart", "Verbindung", "Speicher & Pfade", "Sicherheitsprüfung", "Installation", "Abschluss"]


def _tt(name: str, size: int, weight: str = "normal") -> tuple:
    return (F, size, weight)


class RoyalSetupApp:
    def __init__(self, root: tk.Tk, preview: bool = False):
        self.root = root
        self.preview = preview
        self.root.title("RoyalDownloader · Easy Install")
        self.root.geometry("1080x734")
        self.root.minsize(970, 695)
        self.root.configure(background=COL["paper"])
        self.page = 0
        self.method = tk.StringVar(value="windows")
        self.host = tk.StringVar(value="nas.mein-zuhause.de" if preview else "")
        self.port = tk.StringVar(value="22")
        self.user = tk.StringVar(value="meinbenutzer" if preview else "")
        self.secret = tk.StringVar(value="")
        self.keyfile = tk.StringVar(value="")
        self.ssh_auth = tk.StringVar(value="password")
        self.verify_ack = tk.BooleanVar(value=False)
        self.host_fingerprint = ""
        self.connection = None
        self.install_base = tk.StringVar(value=str(Path.home() / "AppData/Local/RoyalDownloader") if os.name == "nt" else "C:\\Users\\Alex\\AppData\\Local\\RoyalDownloader")
        self.movies = tk.StringVar(value="C:\\Users\\Alex\\Videos\\Royal\\Filme")
        self.series = tk.StringVar(value="C:\\Users\\Alex\\Videos\\Royal\\Serien")
        self.nas_base = tk.StringVar(value="/volume1/docker/RoyalDownloader-Easy")
        self.nas_movies = tk.StringVar(value="/volume1/Filme")
        self.nas_series = tk.StringVar(value="/volume1/Serien")
        self.python_path = tk.StringVar(value="")
        self.preflight_passed = False
        self.preflight_details = ""
        self.installed = None
        self.log_lines: list[str] = []
        self.task_active = False
        self.events: queue.Queue = queue.Queue()
        self._start_layout()
        self.show_page()
        self.root.after(80, self._pump_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _start_layout(self):
        self.shell = tk.Frame(self.root, bg=COL["paper"])
        self.shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(self.shell, bg=COL["navy"], width=273)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.brand = tk.Frame(self.sidebar, bg=COL["navy"])
        self.brand.pack(anchor="w", fill="x", padx=29, pady=(31, 25))
        mark = tk.Label(self.brand, text="R", font=_tt("x", 22, "bold"), bg=COL["blue"], fg="white", width=2, height=1)
        mark.pack(side="left")
        b = tk.Frame(self.brand, bg=COL["navy"])
        b.pack(side="left", padx=(11, 0))
        tk.Label(b, text="ROYAL", bg=COL["navy"], fg="white", font=_tt("x", 16, "bold")).pack(anchor="w")
        tk.Label(b, text="DOWNLOADER  ·  SETUP", bg=COL["navy"], fg="#8da3c6", font=_tt("x", 8, "bold")).pack(anchor="w")
        tk.Label(self.sidebar, text="EINRICHTUNG", bg=COL["navy"], fg="#798faf", font=_tt("x", 9, "bold")).pack(anchor="w", padx=31, pady=(7, 12))
        self.step_rows = []
        for index, text in enumerate(STEPS):
            outer = tk.Frame(self.sidebar, bg=COL["navy"], height=53)
            outer.pack(fill="x", padx=13)
            outer.pack_propagate(False)
            inner = tk.Frame(outer, bg=COL["navy"])
            inner.pack(fill="both", expand=True, padx=7, pady=4)
            number = tk.Label(inner, text=f"{index + 1:02d}", width=3, font=_tt("x", 10, "bold"),
                              bg=COL["navy2"], fg="#8196b7")
            number.pack(side="left", padx=(11, 10), pady=5)
            label = tk.Label(inner, text=text, font=_tt("x", 10), bg=COL["navy"], fg="#a1b3cb", anchor="w")
            label.pack(side="left", expand=True, fill="x")
            self.step_rows.append((outer, inner, number, label))
        bottom = tk.Frame(self.sidebar, bg=COL["navy"])
        bottom.pack(side="bottom", fill="x", padx=27, pady=32)
        tk.Label(bottom, text="SCHUTZ IST STANDARD", font=_tt("x", 8, "bold"), fg="#7ce1d6", bg=COL["navy"]).pack(anchor="w")
        tk.Label(bottom, text="SSH-Hostschlüssel · geprüfte Archive\nKeine Änderung an bestehenden Daten", font=_tt("x", 9),
                 fg="#9aacc6", bg=COL["navy"], justify="left", wraplength=220).pack(anchor="w", pady=(7, 0))

        self.content = tk.Frame(self.shell, bg=COL["paper"])
        self.content.pack(side="left", fill="both", expand=True)
        top = tk.Frame(self.content, bg=COL["paper"])
        top.pack(fill="x", padx=42, pady=(29, 16))
        self.tag = tk.Label(top, text="ROYAL EASY INSTALL  /  01", bg=COL["blue2"], fg=COL["blue"],
                            font=_tt("x", 9, "bold"), padx=11, pady=7)
        self.tag.pack(side="left")
        if self.preview:
            tk.Label(top, text="VORSCHAU – KEINE INSTALLATION", fg=COL["amber"], bg=COL["amberbg"],
                     font=_tt("x", 8, "bold"), padx=11, pady=8).pack(side="right")
        self.head = tk.Frame(self.content, bg=COL["paper"])
        self.head.pack(fill="x", padx=43, pady=(4, 20))
        self.heading = tk.Label(self.head, bg=COL["paper"], fg=COL["ink"], font=_tt("x", 24, "bold"), anchor="w")
        self.heading.pack(fill="x")
        self.subtitle = tk.Label(self.head, bg=COL["paper"], fg=COL["sub"], font=_tt("x", 10),
                                 justify="left", anchor="w", wraplength=700)
        self.subtitle.pack(fill="x", pady=(8, 0))
        # Pack footer before the scrolling viewport so navigation is NEVER pushed
        # offscreen when NAS pages grow taller than a laptop's available height.
        self.footer = tk.Frame(self.content, bg=COL["paper"])
        self.footer.pack(side="bottom", fill="x", padx=43, pady=(12, 25))
        self.body_view = tk.Frame(self.content, bg=COL["paper"])
        self.body_view.pack(side="top", fill="both", expand=True, padx=43)
        self.body_canvas = tk.Canvas(self.body_view, bg=COL["paper"], bd=0,
                                     relief="flat", highlightthickness=0, takefocus=0)
        self.body_canvas.pack(side="left", fill="both", expand=True)
        self.body_scrollbar = tk.Scrollbar(self.body_view, orient="vertical", command=self.body_canvas.yview)
        self.body_scrollbar.pack(side="right", fill="y")
        self.body_canvas.configure(yscrollcommand=self.body_scrollbar.set)
        self.body = tk.Frame(self.body_canvas, bg=COL["paper"])
        self.body_window = self.body_canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _event: self.body_canvas.configure(scrollregion=self.body_canvas.bbox("all")))
        self.body_canvas.bind("<Configure>", lambda event: self.body_canvas.itemconfigure(self.body_window, width=event.width))
        self.root.bind_all("<MouseWheel>", lambda event: self.body_canvas.yview_scroll(-int(event.delta / 120), "units"))
        self.root.bind_all("<Button-4>", lambda _event: self.body_canvas.yview_scroll(-1, "units"))
        self.root.bind_all("<Button-5>", lambda _event: self.body_canvas.yview_scroll(1, "units"))
        tk.Frame(self.footer, bg=COL["line"], height=1).pack(fill="x", pady=(0, 19))
        actions = tk.Frame(self.footer, bg=COL["paper"])
        actions.pack(fill="x")
        self.back = self._button(actions, "←  Zurück", self.previous, secondary=True)
        self.back.pack(side="left")
        self.footnote = tk.Label(actions, text="", bg=COL["paper"], fg=COL["sub"], font=_tt("x", 9))
        self.footnote.pack(side="left", padx=15)
        self.next = self._button(actions, "Weiter  →", self.advance)
        self.next.pack(side="right")

    def _button(self, parent, text, command, secondary=False, disabled=False):
        return tk.Button(parent, text=text, command=command,
                         font=_tt("x", 10, "bold"), cursor="hand2", bd=0,
                         bg="white" if secondary else COL["blue"],
                         fg=COL["ink"] if secondary else "white", activebackground=COL["blue2"] if secondary else "#145eda",
                         activeforeground=COL["ink"] if secondary else "white",
                         relief="flat", padx=19, pady=11, state="disabled" if disabled else "normal")

    def _card(self, parent=None, bg=None, pady=18, padx=21):
        outer = tk.Frame(parent or self.body, bg=bg or COL["white"], highlightbackground=COL["line"], highlightthickness=1)
        inner = tk.Frame(outer, bg=bg or COL["white"])
        inner.pack(fill="both", expand=True, padx=padx, pady=pady)
        return outer, inner

    def _section(self, parent, title, hint=""):
        tk.Label(parent, text=title, bg=parent["bg"], fg=COL["ink"], font=_tt("x", 12, "bold"), anchor="w").pack(fill="x")
        if hint:
            tk.Label(parent, text=hint, bg=parent["bg"], fg=COL["sub"], font=_tt("x", 9),
                     anchor="w", justify="left", wraplength=655).pack(fill="x", pady=(4, 12))

    def _field(self, parent, label: str, var: tk.StringVar, masked=False, width=None):
        row = tk.Frame(parent, bg=parent["bg"])
        row.pack(fill="x", pady=(7, 5))
        tk.Label(row, text=label, bg=parent["bg"], fg=COL["ink"], font=_tt("x", 9, "bold")).pack(anchor="w", pady=(0, 5))
        entry = tk.Entry(row, textvariable=var, show="●" if masked else "", font=_tt("x", 10),
                         bg="#fbfcff", fg=COL["ink"], relief="solid", bd=1, highlightthickness=0,
                         insertbackground=COL["ink"])
        entry.pack(fill="x", ipady=8, ipadx=8)
        return entry

    def _info(self, parent, title, msg, tone="blue"):
        bg = {"blue": COL["blue2"], "green": COL["greenbg"], "amber": COL["amberbg"], "red": COL["redbg"]}[tone]
        fg = {"blue": COL["blue"], "green": COL["green"], "amber": COL["amber"], "red": COL["red"]}[tone]
        box = tk.Frame(parent, bg=bg)
        box.pack(fill="x", pady=(12, 3))
        tk.Label(box, text=title, font=_tt("x", 10, "bold"), bg=bg, fg=fg, anchor="w").pack(fill="x", padx=15, pady=(12, 3))
        tk.Label(box, text=msg, font=_tt("x", 9), bg=bg, fg=COL["ink"], justify="left",
                 anchor="w", wraplength=615).pack(fill="x", padx=15, pady=(0, 13))
        return box

    def _switch_target(self, value):
        if self.method.get() != value:
            self.method.set(value)
            self.preflight_passed = False
            self.host_fingerprint = ""
            self.verify_ack.set(False)
            if self.connection:
                self.connection.close(); self.connection = None
            self.show_page()

    def show_page(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.body_canvas.yview_moveto(0)
        for index, (outer, inner, number, label) in enumerate(self.step_rows):
            active = index == self.page
            outer.configure(bg=COL["navy"])
            inner.configure(bg=COL["navy3"] if active else COL["navy"])
            number.configure(bg=COL["blue"] if active else COL["navy2"], fg="white" if active else "#90a5c2",
                             text="✓" if index < self.page else f"{index+1:02d}")
            label.configure(bg=COL["navy3"] if active else COL["navy"], fg="white" if active else "#a1b3cb",
                            font=_tt("x", 10, "bold" if active else "normal"))
        self.tag.configure(text=f"ROYAL EASY INSTALL  /  {self.page + 1:02d}")
        sections = [
            ("Willkommen bei Royal.", "Installiere RoyalDownloader auf diesem PC oder richte ihn direkt auf deinem NAS ein – ohne Handarbeit in Docker."),
            ("Verbindung herstellen", "Wir prüfen zuerst die Voraussetzungen. Bei einem NAS verifizieren wir den SSH-Hostschlüssel, bevor Zugangsdaten verwendet werden."),
            ("Ein Zuhause für deine Medien", "Wähle klare, getrennte Orte für die Anwendung sowie Filme und Serien. Bestehende Mediendateien bleiben unangetastet."),
            ("Alles bereit für den Start?", "Royal prüft Schreibrechte, verfügbare Ressourcen und mögliche Konflikte, bevor eine einzige Datei verändert wird."),
            ("Royal wird eingerichtet", "Du siehst genau, welche Arbeit gerade ausgeführt wird. Passwörter und Sicherheitscodes erscheinen nicht im Protokoll."),
            ("Bereit für deinen ersten Start.", "Der Installer hat seine Arbeit abgeschlossen. Ab jetzt führt dich der RoyalDownloader-Assistent durch deine persönlichen Einstellungen."),
        ]
        self.heading.configure(text=sections[self.page][0])
        self.subtitle.configure(text=sections[self.page][1])
        self.back.configure(state="normal" if self.page > 0 and not self.task_active and self.page < 5 else "disabled")
        self.next.configure(text=["Weiter  →", "Weiter  →", "Weiter  →", "Voraussetzungen prüfen", "Jetzt installieren", "Fertig"][self.page],
                            state="normal" if not self.task_active else "disabled")
        self.footnote.configure(text="SCHRITT %d VON %d" % (self.page+1,TOTAL))
        getattr(self, f"_page{self.page}")()

    def _page0(self):
        outer, inner = self._card()
        outer.pack(fill="x", pady=(4, 14))
        self._section(inner, "Wo möchtest du RoyalDownloader verwenden?", "Beide Wege führen anschließend in denselben persönlichen Einrichtungsassistenten.")
        for value, symbol, title, summary, badge in (
            ("windows", "▣", "Auf diesem Windows-PC", "Eine lokale Anwendung mit eigenem Startmenü und isolierter Python-Umgebung.", "Einfach"),
            ("nas", "▥", "Auf meinem NAS / Heimserver", "Verschlüsselt über SSH verbinden, Docker prüfen und Royal selbstständig einrichten.", "24 / 7"),
        ):
            selected = self.method.get() == value
            c = tk.Frame(inner, bg=COL["blue2"] if selected else COL["paper"],
                         highlightbackground=COL["blue"] if selected else COL["line"], highlightthickness=2 if selected else 1,
                         cursor="hand2")
            c.pack(fill="x", pady=(4, 9), ipady=8)
            icon = tk.Label(c, text=symbol, font=_tt("x", 23), bg=c["bg"], fg=COL["blue"])
            icon.pack(side="left", padx=(18, 17))
            tag = tk.Label(c, text="✓ GEWÄHLT" if selected else badge, fg=COL["blue"], bg=c["bg"], font=_tt("x", 8, "bold"), width=11)
            tag.pack(side="right", padx=(4, 10))
            ct = tk.Frame(c, bg=c["bg"]);ct.pack(side="left", fill="both", expand=True)
            t = tk.Label(ct, text=title, font=_tt("x", 12, "bold"), fg=COL["ink"], bg=c["bg"], anchor="w")
            t.pack(fill="x", pady=(5, 2))
            d = tk.Label(ct, text=summary, font=_tt("x", 9), fg=COL["sub"], bg=c["bg"], anchor="w", wraplength=460, justify="left")
            d.pack(fill="x", pady=(0, 5))
            for el in (c, icon, ct, t, d, tag):
                el.bind("<Button-1>", lambda _ev, v=value: self._switch_target(v))
        self._info(self.body, "Deine Installation bleibt unter deiner Kontrolle", "Keine Cloud-Pflicht, keine ungefragten Portfreigaben, keine Änderung bestehender Docker-Container. Für das NAS benötigst du SSH und einen Benutzer mit Docker-Berechtigung.")

    def _page1(self):
        outer, inner = self._card()
        outer.pack(fill="x")
        if self.method.get() == "windows":
            self._section(inner, "Windows-Voraussetzungen", "Für die Anwendung wird Python 3.12 in einer eigenen Umgebung verwendet. Es wird nichts global über pip installiert.")
            detected = find_python_312() if os.name == "nt" else None
            tk.Label(inner, text=f"Python 3.12: {'gefunden ('+detected+')' if detected else 'nicht gefunden / Vorschau unter Linux'}",
                     bg=inner["bg"], fg=COL["green"] if detected else COL["amber"], font=_tt("x", 10)).pack(anchor="w", pady=(6, 10))
            self._field(inner, "Python 3.12 – eigener Interpreter (optional)", self.python_path)
            tk.Label(inner, text="Wenn Python fehlt, installiere es zunächst von python.org mit dem Windows-Launcher.\nChrome/Chromium und FFmpeg werden vor dem Start geprüft.",
                     bg=inner["bg"], fg=COL["sub"], font=_tt("x", 9), justify="left").pack(anchor="w", pady=(12, 4))
            self._button(inner, "Fehlende Komponenten automatisch installieren", self.setup_windows_dependencies).pack(anchor="w", pady=(10, 5))
            self._button(inner, "Offizielle Python-Seite öffnen", lambda: __import__("webbrowser").open("https://www.python.org/downloads/windows/"), secondary=True).pack(anchor="w", pady=(4, 0))
            self._info(inner,"Du entscheidest","Der automatische Weg verwendet WinGet für Python 3.12, Chrome und FFmpeg. Er verändert keine Programme ohne deine ausdrückliche Zustimmung.","blue")
        else:
            self._section(inner, "Sichere SSH-Verbindung zum NAS", "SSH muss auf deinem NAS aktiviert sein. Die Verbindung wird mit einer überprüften Host-Identität geschützt.")
            top = tk.Frame(inner, bg=inner["bg"]); top.pack(fill="x")
            left = tk.Frame(top, bg=inner["bg"]);left.pack(side="left", fill="both", expand=True, padx=(0, 11))
            right = tk.Frame(top, bg=inner["bg"], width=90);right.pack(side="left", fill="y");right.pack_propagate(False)
            self._field(left, "NAS-IP oder Hostname", self.host)
            self._field(right, "SSH-Port", self.port)
            self._field(inner, "SSH-Benutzer (kein root)", self.user)
            self._button(inner,"1 · SSH-Hostschlüssel abrufen",self.probe_fingerprint,secondary=True).pack(anchor="w",pady=(11,6))
            if self.host_fingerprint:
                self._info(inner,"Hostschlüssel-Fingerabdruck",self.host_fingerprint,"green" if self.verify_ack.get() else "amber")
                tk.Checkbutton(inner,text="Ich habe den Fingerabdruck unabhängig am NAS geprüft.", variable=self.verify_ack,
                               font=_tt("x",9),bg=inner["bg"],fg=COL["ink"],activebackground=inner["bg"]).pack(anchor="w",pady=(7,2))
            auth = tk.Frame(inner, bg=inner["bg"]);auth.pack(fill="x", pady=(13, 0))
            tk.Label(auth,text="2 · Danach Anmeldung wählen",font=_tt("x",9,"bold"),bg=inner["bg"],fg=COL["ink"]).pack(anchor="w",pady=(0,7))
            for option,text in (("password","Passwort"),("key","Privater SSH-Schlüssel")):
                tk.Radiobutton(auth, text=text, variable=self.ssh_auth, value=option, bg=inner["bg"], fg=COL["ink"],
                               activebackground=inner["bg"], font=_tt("x",9), command=self.show_page).pack(side="left", padx=(0, 23))
            if self.ssh_auth.get()=="password":
                self._field(inner,"SSH-Passwort (wird nicht gespeichert)",self.secret,masked=True)
            else:
                self._field(inner,"Pfad zur SSH-Schlüsseldatei",self.keyfile)
                self._button(inner,"Datei auswählen",lambda: self.keyfile.set(filedialog.askopenfilename()),secondary=True).pack(anchor="w",pady=(4,0))
        if self.method.get()=="nas":
            self._info(self.body,"So findest du den Fingerabdruck", "Vergleiche den angezeigten SHA256-Wert mit dem SSH-Hostschlüssel deines NAS, z. B. über dessen lokale Verwaltung bzw. `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Bei Abweichungen abbrechen.","amber")

    def _page2(self):
        outer, inner = self._card()
        outer.pack(fill="x")
        if self.method.get()=="windows":
            self._section(inner,"Lokale Ordner auswählen","Royal speichert seine Anwendung unabhängig von deinen Filmen und Serien. Neue Datenordner können angelegt werden.")
            self._field(inner,"Programmordner",self.install_base)
            self._button(inner,"Ordner wählen",lambda:self.install_base.set(filedialog.askdirectory() or self.install_base.get()),secondary=True).pack(anchor="w",pady=(0,4))
            self._field(inner,"Zielordner für Filme",self.movies)
            self._field(inner,"Zielordner für Serien",self.series)
            self._info(inner,"Wichtig","Ein bereits belegter Programmordner wird nie überschrieben. Eigene Medienordner werden getrennt gespeichert.")
        else:
            self._section(inner,"NAS-Speicherpfade","Die folgenden Pfade sind auf dem NAS, nicht auf deinem Windows-PC. Die Medienordner müssen bereits vorhanden und beschreibbar sein.")
            self._field(inner,"Neuer Projektordner (muss noch frei sein)",self.nas_base)
            self._field(inner,"Bestehender Filmordner auf dem NAS",self.nas_movies)
            self._field(inner,"Bestehender Serienordner auf dem NAS",self.nas_series)
            self._info(inner,"Docker übernimmt die Zuordnung", "Royal nutzt innerhalb des Containers /movies und /serien. Der Installer verbindet diese automatisch mit den oben angegebenen NAS-Ordnern. Kein rekursives chmod/chown.")
        self._info(self.body,"Keine unangekündigten Eingriffe","Royal löscht keine Medien, ersetzt keine vorhandene Installation und verändert keine bestehenden Container. Bei Konflikten stoppt die Einrichtung.")

    def _page3(self):
        outer, inner = self._card()
        outer.pack(fill="x")
        self._section(inner,"Technische Prüfung vor der Installation","Erst prüfen, dann installieren. Dieser Schritt führt keine Docker-Starts, Dateiübertragungen oder Paketinstallationen aus.")
        checks = [
            ("01", "Quelle & Integrität", "Gebündelte Overnight-Version und SHA-256 werden kontrolliert."),
            ("02", "System & Speicher", "Benötigte Laufzeit, freie Kapazität und Pfade werden geprüft."),
            ("03", "Bestehende Installationen", "Royal verweigert das Überschreiben vorhandener Projekte."),
            ("04", "Netzwerk & Sicherheit", "SSH-Fingerprint bzw. lokaler Netzwerkzugriff werden kontrolliert."),
        ]
        for n,title,note in checks:
            row=tk.Frame(inner,bg=inner["bg"]);row.pack(fill="x",pady=9)
            tk.Label(row,text=n,font=_tt("x",10,"bold"),fg=COL["blue"],bg=inner["bg"],width=4).pack(side="left")
            texts=tk.Frame(row,bg=inner["bg"]);texts.pack(side="left",fill="x",expand=True)
            tk.Label(texts,text=title,font=_tt("x",10,"bold"),bg=inner["bg"],fg=COL["ink"],anchor="w").pack(fill="x")
            tk.Label(texts,text=note,font=_tt("x",9),bg=inner["bg"],fg=COL["sub"],anchor="w").pack(fill="x",pady=(2,0))
        if self.preflight_passed:
            self._info(inner,"Prüfung bestanden",self.preflight_details or "Alle notwendigen Voraussetzungen erfüllt.","green")
        elif self.preflight_details:
            self._info(inner,"Prüfung noch nicht erfolgreich",self.preflight_details,"amber")
        else:
            self._info(inner,"Noch nicht geprüft","Klicke unten auf „Voraussetzungen prüfen“. Erst nach erfolgreicher Prüfung ist eine Installation möglich.","amber")

    def _page4(self):
        outer, inner = self._card();outer.pack(fill="both",expand=True)
        self._section(inner,"Installationsprotokoll","Nur der freigegebene neue Programmordner wird angelegt. Secrets werden nicht in den Meldungen ausgegeben.")
        status=tk.Frame(inner,bg=COL["blue2"]);status.pack(fill="x",pady=(0,13))
        self.progress_label=tk.Label(status,text="BEREIT · Die Installation startet erst nach Bestätigung.",
                                     bg=COL["blue2"],fg=COL["blue"],font=_tt("x",9,"bold"),anchor="w")
        self.progress_label.pack(fill="x",padx=13,pady=12)
        view_frame=tk.Frame(inner,bg="#121e30")
        view_frame.pack(fill="both",expand=True)
        self.log_view=tk.Text(view_frame,font=("Consolas" if os.name=="nt" else "DejaVu Sans Mono",9),
                              bg="#121e30",fg="#d1e2ef",wrap="word",bd=0, padx=13,pady=13,
                              height=11,state="normal")
        self.log_view.pack(fill="both",expand=True)
        for line in self.log_lines:
            self.log_view.insert("end", "›  " + line + "\n\n")
        self.log_view.configure(state="disabled")
        self._info(inner,"Nicht unterbrechen","Während der Installation bitte das Fenster geöffnet lassen. Ein fehlgeschlagener frischer NAS-Start bleibt als Diagnoseprojekt erhalten.","amber")

    def _page5(self):
        outer, inner = self._card()
        outer.pack(fill="x",pady=(0,13))
        success=bool(self.installed)
        tk.Label(inner,text="✓" if success else "◎",font=_tt("x",29,"bold"),fg=COL["teal"] if success else COL["blue"],
                 bg=inner["bg"]).pack(anchor="w")
        self._section(inner,"RoyalDownloader ist vorbereitet" if success else "Vorschau: so sieht der Abschluss aus",
                      "Ab jetzt folgt die persönliche Ersteinrichtung im Webbrowser.")
        url=self.installed.get("url") if self.installed else ("http://192.168.178.47:8765" if self.method.get()=="nas" else "http://127.0.0.1:8765")
        tk.Label(inner,text=url,fg=COL["blue"],bg=inner["bg"],font=_tt("x",14,"bold"),anchor="w").pack(fill="x",pady=(7,9))
        tk.Label(inner,text="1. Royal im Browser aufrufen    2. Sicherheitscode eingeben    3. Benutzerkonto erstellen\n4. Inhalte & Speicher bestätigen    5. Optional Jellyfin verbinden",
                 fg=COL["sub"],bg=inner["bg"],font=_tt("x",9),anchor="w",justify="left").pack(fill="x",pady=(4,14))
        if self.installed:
            missing=self.installed.get("missing_optional","")
            if missing:
                self._info(inner,"Noch nicht vollständig startbereit",f"Fehlende Komponenten: {missing}. Installiere sie über den Windows-Voraussetzungsschritt oder WinGet, damit alle Downloadfunktionen arbeiten.","amber")
            self._info(inner,"Dein einmaliger Einrichtungscode",self.installed.get("token",""),"green")
            self._button(inner,"Code in die Zwischenablage kopieren",self.copy_token).pack(anchor="w",pady=(10,4))
            if self.method.get()=="windows":
                self._button(inner,"RoyalDownloader starten",self.start_local,secondary=True).pack(anchor="w",pady=(6,4))
            else:
                self._info(inner,"LAN-Adresse","Öffne die Adresse von einem Gerät in deinem Heimnetz. Keine öffentliche Portfreigabe vornehmen.")
        else:
            self._info(inner,"Nur Demo", "Es wurden keine Dateien auf einem PC oder NAS installiert. Der spätere persönliche Sicherheitscode wird hier angezeigt.","amber")

    def _windows_cfg(self):
        return WindowsConfig(Path(self.install_base.get()).expanduser(),Path(self.movies.get()).expanduser(),
                             Path(self.series.get()).expanduser(),self.python_path.get().strip())

    def _nas_cfg(self):
        try: port=int(self.port.get())
        except ValueError: raise InstallError("Bitte einen numerischen SSH-Port eingeben.")
        return NasConfig(self.host.get().strip(),port,self.user.get().strip(),self.nas_base.get().strip(),
                         self.nas_movies.get().strip(),self.nas_series.get().strip(),
                         password=self.secret.get() if self.ssh_auth.get()=="password" else "",
                         private_key_path=self.keyfile.get().strip() if self.ssh_auth.get()=="key" else "")

    def setup_windows_dependencies(self):
        if self.preview:
            messagebox.showinfo("Vorschaumodus", "Hier werden keine Pakete installiert.", parent=self.root)
            return
        if self.task_active:
            return
        if not messagebox.askyesno("Windows-Voraussetzungen installieren",
                                   "Über den offiziellen Windows Package Manager werden fehlende Komponenten geprüft und bei Bedarf Python 3.12, Google Chrome und FFmpeg installiert. Fortfahren?",
                                   parent=self.root):
            return
        def job():
            installed = install_prerequisites_via_winget(lambda msg: self.events.put(("prereq",msg,None)))
            self.events.put(("prereq_complete", ", ".join(installed) if installed else "Alles war bereits installiert", None))
        self._background(job)

    def probe_fingerprint(self):
        if self.preview:
            self.host_fingerprint="SHA256:VORSCHAU-KEIN-ECHTER-SSH-SCHLUESSEL"
            self.show_page();return
        if self.task_active:return
        def job():
            session=NasSession(self._nas_cfg())
            kind,fingerprint=session.probe_key()
            self.events.put(("fingerprint",f"{kind} · {fingerprint}",fingerprint))
        self._background(job)

    def _background(self,job:Callable):
        self.task_active=True;self.back.configure(state="disabled");self.next.configure(state="disabled")
        def worker():
            try:job()
            except Exception as exc:self.events.put(("error",str(exc),None))
            finally:self.events.put(("done",None,None))
        threading.Thread(target=worker,daemon=True).start()

    def _pump_events(self):
        try:
            while True:
                typ,value,extra=self.events.get_nowait()
                if typ=="fingerprint":
                    self.host_fingerprint=extra;self.verify_ack.set(False);self.show_page()
                elif typ=="prereq":
                    self.subtitle.configure(text=value)
                elif typ=="prereq_complete":
                    messagebox.showinfo("Voraussetzungen", value, parent=self.root)
                    self.show_page()
                elif typ=="log":
                    self.log_lines.append(value)
                    if self.page==4 and hasattr(self,"log_view"):
                        self.log_view.configure(state="normal")
                        self.log_view.insert("end","›  "+value+"\n\n")
                        self.log_view.see("end");self.log_view.configure(state="disabled")
                        self.progress_label.configure(text="IN ARBEIT · "+value[:80])
                elif typ=="ready":
                    self.preflight_passed=True;self.preflight_details=value
                    if self.page==3:self.show_page()
                elif typ=="installed":
                    self.installed=value;self.page=5;self.show_page()
                elif typ=="error":
                    if self.page==3:
                        self.preflight_passed=False;self.preflight_details=value;self.show_page()
                    else:
                        self.log_lines.append("FEHLER: "+value)
                        if self.page==4:self.show_page()
                        messagebox.showerror("RoyalDownloader · Abbruch",value,parent=self.root)
                elif typ=="done":
                    self.task_active=False
                    self.back.configure(state="normal" if self.page in (1,2,3,4) else "disabled")
                    self.next.configure(state="normal")
        except queue.Empty:pass
        self.root.after(80,self._pump_events)

    def advance(self):
        if self.task_active:return
        if self.page==0:
            self.page=1
        elif self.page==1:
            if self.method.get()=="nas":
                try:validate_nas(self._nas_cfg())
                except InstallError as exc:messagebox.showerror("SSH-Verbindung",str(exc),parent=self.root);return
                if not self.host_fingerprint or not self.verify_ack.get():
                    messagebox.showwarning("Hostschlüssel bestätigen","Bitte SSH-Hostschlüssel abrufen und unabhängig vergleichen.",parent=self.root);return
            self.page=2
        elif self.page==2:
            try:
                if self.method.get()=="nas":validate_nas(self._nas_cfg())
                elif not self.preview:validate_windows(self._windows_cfg())
            except InstallError as exc:messagebox.showerror("Ordner prüfen",str(exc),parent=self.root);return
            self.preflight_passed=False;self.preflight_details=""
            self.page=3
        elif self.page==3:
            if self.preflight_passed:self.page=4
            else:self.run_preflight();return
        elif self.page==4:
            if self.installed:
                self.page=5
            else:
                self.run_install();return
        else:
            self._close();return
        self.show_page()

    def previous(self):
        if self.page>0 and not self.task_active:
            self.page-=1;self.show_page()

    def run_preflight(self):
        if self.preview:
            self.preflight_passed=True
            self.preflight_details="VORSCHAU · Beispielprüfung erfolgreich – kein echtes Gerät kontaktiert."
            self.show_page();return
        def job():
            if self.method.get()=="windows":
                package=packaged_source("zip")
                info=preflight_windows(self._windows_cfg())
                self.events.put(("ready",f"Quelle {package.commit[:12]} · Python 3.12 · {info['free_gib']} GiB frei",None))
            else:
                if not self.verify_ack.get() or not self.host_fingerprint:
                    raise InstallError("Fingerabdruck muss zuerst bestätigt werden.")
                package=packaged_source("tar")
                sess=NasSession(self._nas_cfg())
                try:
                    sess.trust_and_connect(self.host_fingerprint)
                    data=preflight_nas(self._nas_cfg(),sess)
                    self.events.put(("ready",f"Quelle {package.commit[:12]} · NAS {data['architecture']} · {data['free_gib']} GiB frei · keine Konflikte",None))
                finally:sess.close()
        self._background(job)

    def run_install(self):
        if self.preview:
            self.log_lines=["Vorschau: SSH-Hostschlüssel geprüft", "Vorschau: Quellarchiv verifiziert", "Vorschau: Docker-Konfiguration geprüft", "Vorschau: Keine Installation ausgeführt"]
            self.page=5;self.show_page();return
        if not self.preflight_passed:
            messagebox.showwarning("Prüfung fehlt","Bitte zuerst alle Voraussetzungen prüfen.",parent=self.root);return
        if not messagebox.askyesno("Installation starten", "Der Installer legt jetzt einen NEUEN Programmordner an und installiert RoyalDownloader. Bestehende Medien und Container werden nicht verändert. Fortfahren?",parent=self.root):return
        self.log_lines=[];self.show_page()
        def progress(msg):self.events.put(("log",msg,None))
        def job():
            if self.method.get()=="windows":
                info=install_windows(self._windows_cfg(),packaged_source("zip"),progress)
            else:
                sess=NasSession(self._nas_cfg())
                try:
                    sess.trust_and_connect(self.host_fingerprint)
                    info=install_nas(self._nas_cfg(),sess,packaged_source("tar"),progress)
                finally:sess.close()
            self.events.put(("installed",info,None))
        self._background(job)

    def copy_token(self):
        if not self.installed:return
        self.root.clipboard_clear();self.root.clipboard_append(self.installed["token"])
        messagebox.showinfo("Kopiert","Der Sicherheitscode wurde in die Zwischenablage kopiert.",parent=self.root)

    def start_local(self):
        if not self.installed:return
        path=self.installed.get("launcher","")
        if os.name=="nt" and Path(path).exists():
            subprocess.Popen(["cmd","/c","start","",path],creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:messagebox.showinfo("Starten","Starte die Datei „RoyalDownloader starten.cmd“ in deinem Installationsordner.",parent=self.root)

    def _close(self):
        if self.task_active:
            messagebox.showwarning("Installation läuft","Bitte den laufenden Schritt abschließen lassen. Das Fenster bleibt geöffnet.",parent=self.root)
            return
        if self.connection:self.connection.close()
        self.secret.set("");self.root.destroy()


def main():
    parser=argparse.ArgumentParser(description="RoyalDownloader Easy Install")
    parser.add_argument("--preview",action="store_true",help="Offline preview without any target changes")
    parser.add_argument("--self-test",action="store_true",help="Offline packaged self-check; no GUI")
    args=parser.parse_args()
    if args.self_test:
        packaged_source("zip");packaged_source("tar")
        from .core import verify_source_tar
        verify_source_tar(packaged_source("tar").archive)
        print("RoyalDownloader Easy Installer: package integrity OK")
        return
    root=tk.Tk()
    RoyalSetupApp(root,preview=args.preview)
    root.mainloop()


if __name__=="__main__":
    main()
