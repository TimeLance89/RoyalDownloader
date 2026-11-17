# RoyalDownloader Easy Installer

Entrypoint: `../RoyalDownloader-Setup.pyw` → `installer.ui.main()`.

- UI: `ui.py` – a six-step Tkinter wizard with fully offline preview.
- Execution: `core.py` – independent Windows and NAS backends.
- Bundled source: `build_source.py` uses `git archive` at the current commit,
  preserving and hashing the exact shipped revision.
- QA: `../tests/test_easy_installer.py` and the Windows CI `--self-test` smoke.

**A packaged EXE is not checked into Git.** The Windows build generates
`dist/RoyalDownloader-Setup.exe`, uploaded as an Actions artifact.

To view the UI locally without any installation:

```bash
python -m installer.ui --preview
```

The preview always shows a warning and never executes SSH or Docker actions.
