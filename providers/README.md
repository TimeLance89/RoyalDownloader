# Provider adapters

Each catalog provider has one isolated module in this directory. Shared search,
movie, series, episode, and hoster models live in `models.py`.

## Catalog

| Module | Provider | Language | Media |
|---|---|---:|---|
| `filmfrei24.py` | FilmFrei24 | German | Movies |
| `filmpalast.py` | Filmpalast | German | Movies, series |
| `megakino.py` | MegaKino | German | Movies, series |
| `moflix.py` | Moflix | German | Movies, series |
| `einschalten.py` | Einschalten | German | Movies |
| `kinox.py` | Kinox | German | Movies |
| `kinoger.py` | KinoGer | German | Movies, series |
| `xcine.py` | XCine | German | Movies, series |
| `serienstream.py` | SerienStream | German | Series |
| `sflix.py` | SFlix | English | Movies, series |
| `ridomovies.py` | Ridomovies | English | Movies, series |
| `mkissa.py` | MKissa | English | Anime |

Register new adapters in `providers/catalog.py` and the relevant server adapter
tables. The central catalog defines media types, default content language,
source recognition, and default priority. Providers must use the shared types
from `providers.models` instead of introducing incompatible result objects.

`content_language` uses a short BCP-47 language code such as `de` or `en`. It
describes the provider's expected content language. A concrete language
reported by the selected hoster takes precedence for the download job.
