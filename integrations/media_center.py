"""Provider selection; legacy Jellyfin-shaped snapshots stay API compatible."""
from urllib.parse import urlsplit

from integrations.jellyfin_client import JellyfinClient


def validate_server_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
    except ValueError:
        valid = False
    if not valid or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Gültige HTTP(S)-Serveradresse ohne Zugangsdaten oder URL-Parameter erforderlich.")
    return value


def media_client(config: dict, timeout: float = 20):
    if config.get("provider") == "plex":
        from integrations.plex_client import PlexClient
        return PlexClient(config.get("url", ""), config.get("api_key", ""), timeout,
                          libraries=config.get("libraries", []), server_id=config.get("server_id", ""))
    return JellyfinClient(config.get("url", ""), config.get("api_key", ""), timeout=timeout)


def profile_identity(user: dict, config: dict) -> tuple[str, str]:
    if config.get("provider") == "plex":
        binding = (user.get("media_profiles") or {}).get("plex", {})
        if binding.get("server_id") != config.get("server_id"):
            return "", ""
        return str(binding.get("user_id") or ""), str(binding.get("user_name") or "")
    return str(user.get("jellyfin_user_id") or ""), str(user.get("jellyfin_user_name") or "")
