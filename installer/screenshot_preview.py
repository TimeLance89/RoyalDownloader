"""Capture real Tkinter UI in preview-only mode; never contacts a device."""
from __future__ import annotations

import os
import time
from pathlib import Path
from PIL import ImageGrab
import tkinter as tk
from installer.ui import RoyalSetupApp


def capture(app, output_dir: Path, filename: str, page: int, method: str):
    app.method.set(method)
    if method == "nas":
        app.host_fingerprint = "SHA256:5bTjHYyQFjLNL5kc5hGKUqDl8HEeEopSFsgeHmX48T4 (Beispiel)"
        app.verify_ack.set(True)
    app.page=page
    if page == 3:
        app.preflight_passed=True
        app.preflight_details="VORSCHAU · Voraussetzungen simuliert, keine reale NAS-Verbindung."
    if page == 4:
        app.log_lines=["Demo · Installationspaket geprüft", "Demo · Verbindung gesichert", "Demo · Zielverzeichnisse überprüft", "Demo · Keine Daten übertragen"]
    app.show_page()
    app.root.update()
    time.sleep(0.25)
    app.root.update()
    x=app.root.winfo_rootx();y=app.root.winfo_rooty();w=app.root.winfo_width();h=app.root.winfo_height()
    ImageGrab.grab(bbox=(x,y,x+w,y+h)).save(output_dir/filename)


def main():
    out=Path(os.environ.get("ROYAL_SCREENSHOT_DIR","/mnt/data/RoyalDownloader-EasyInstall-Screenshots"))
    out.mkdir(parents=True,exist_ok=True)
    root=tk.Tk()
    app=RoyalSetupApp(root,preview=True)
    root.update()
    for fn,page,method in [
        ("01-auswahl.png",0,"windows"),
        ("02-windows-voraussetzungen.png",1,"windows"),
        ("03-nas-ssh.png",1,"nas"),
        ("04-nas-speicher.png",2,"nas"),
        ("05-nas-sicherheitspruefung.png",3,"nas"),
        ("06-installation.png",4,"nas"),
        ("07-abschluss.png",5,"nas"),
    ]:
        capture(app,out,fn,page,method)
    root.destroy()
    print("Screenshots in",out)

if __name__ == "__main__":
    main()
