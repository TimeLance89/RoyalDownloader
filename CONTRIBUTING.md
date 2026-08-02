# Contributing to Royal Downloader

Contributions should make long-running self-hosted installations more reliable,
observable, or easier to operate.

## Before making a change

- Use the **Bug report** issue form for reproducible defects.
- Describe larger features in a feature request before implementing them.
- Never publish credentials, API keys, cookies, private media paths, or complete
  configuration files.
- Changes to download, update, persistence, and de-duplication logic must fail
  safely. An uncertain state must never start a duplicate or incorrect download.

## Local setup

```bash
git clone https://github.com/TimeLance89/RoyalDownloader.git
cd RoyalDownloader
python -m venv .venv
```

Linux and macOS:

```bash
source .venv/bin/activate
pip install -r requirements.lock
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
```

Docker Compose is recommended for the complete runtime stack:

```bash
cp .env.example .env
docker compose up -d --build
```

## Required checks

Run at least the following before opening a pull request:

```bash
python -m py_compile *.py
python -m compileall -q providers application_services tests
find web -type f -name '*.js' -print0 | xargs -0 -n1 node --check
node --test tests/frontend_smoke.test.mjs
ruff check --select E9,F63,F7,F82 .
bandit -q -ll -r application_services api_*.py app_state.py auth.py media_paths.py network_guard.py runtime_cache.py self_updater.py websocket_manager.py ytdlp_updater.py
pip-audit -r requirements.lock
docker compose config --quiet
coverage run --source=application_services,app_state,auth,network_guard,runtime_cache,self_updater,websocket_manager,ytdlp_updater -m pytest -q
coverage report --skip-covered
```

## Pull requests

- Keep each pull request focused on one topic.
- Write a short imperative title.
- Explain the problem, the implementation, and the user-visible impact.
- Include desktop and mobile screenshots for UI changes.
- Document new configuration values in `.env.example` and `docs/DOCKER.md`.
- Preserve persistent data formats and existing `settings.ini` files.
- Call out changes to provider behavior, fallback order, or content languages.

## Code style

- **Python:** preserve existing types, locks, cancellation, and error paths.
- **Providers:** use shared models from `providers.models`; register new adapters
  through `providers/catalog.py` and the server integration points.
- **JavaScript:** avoid framework dependencies unless discussed first.
- **UI:** preserve the Obsidian-and-gold visual system, accessibility, and
  responsive behavior.
- **Documentation:** use English, short sections, and executable examples.
