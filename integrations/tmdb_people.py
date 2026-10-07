"""Person discovery and deduplicated credits, using the existing TMDB transport."""

from copy import deepcopy
import time


def _image(path):
    return f"https://image.tmdb.org/t/p/w500{path}" if path else ""


def _person(row):
    return {
        "id": row["id"], "name": row.get("name", ""),
        "profile_url": _image(row.get("profile_path")),
        "department": row.get("known_for_department", ""),
        "known_for": [item.get("title") or item.get("name", "")
                      for item in row.get("known_for", []) if not item.get("adult")],
    }


class TMDBPeopleMixin:
    def _people_cached(self, key, fetch):
        now = time.monotonic()
        with self._lock:
            cached = self._people_cache.get(key)
            if cached and now - cached[0] < 3600:
                return deepcopy(cached[1])
        value = fetch()
        if value is not None:
            with self._lock:
                if len(self._people_cache) >= 128:
                    self._people_cache.pop(next(iter(self._people_cache)))
                self._people_cache[key] = (now, deepcopy(value))
        return value

    def people(self, query="", page=1):
        query = query.strip()

        def fetch():
            params = {"language": self.language, "page": page, "include_adult": "false"}
            if query:
                params["query"] = query
            payload = self._request("/search/person" if query else "/person/popular", params)
            if payload is None:
                return None
            return {"results": [_person(row) for row in payload.get("results", [])
                                if row.get("id") and not row.get("adult")],
                    "page": page, "total_pages": max(1, min(500, payload.get("total_pages", 1)))}

        return self._people_cached((self.language, query.casefold(), page), fetch)

    def person(self, person_id):
        def fetch():
            row = self._request(f"/person/{person_id}", {
                "language": self.language, "append_to_response": "combined_credits",
            })
            if not row or not row.get("id") or row.get("adult"):
                return None
            credits = row.get("combined_credits")
            if not isinstance(credits, dict):
                return None
            works = {}
            for kind in ("cast", "crew"):
                for credit in credits.get(kind, []):
                    media_type = credit.get("media_type")
                    if media_type not in ("movie", "tv") or not credit.get("id") or credit.get("adult"):
                        continue
                    key = (media_type, credit["id"])
                    date = credit.get("release_date") or credit.get("first_air_date") or ""
                    item = works.setdefault(key, {
                        "tmdb_id": credit["id"], "media_type": media_type,
                        "slug": f"tmdb:{credit['id']}",
                        "title": credit.get("title") or credit.get("name", ""),
                        "original_title": credit.get("original_title") or credit.get("original_name", ""),
                        "year": date[:4], "release_date": date,
                        "cover_url": _image(credit.get("poster_path")),
                        "backdrop_url": _image(credit.get("backdrop_path")),
                        "description": credit.get("overview", ""),
                        "rating": credit.get("vote_average", 0),
                        "vote_count": credit.get("vote_count", 0),
                        "popularity": credit.get("popularity", 0),
                        "roles": [], "characters": [], "departments": [],
                    })
                    role = credit.get("character") if kind == "cast" else credit.get("job")
                    department = "Acting" if kind == "cast" else credit.get("department", "Crew")
                    if role and role not in item["roles"]:
                        item["roles"].append(role)
                    if kind == "cast" and role and role not in item["characters"]:
                        item["characters"].append(role)
                    if department not in item["departments"]:
                        item["departments"].append(department)
            return {**_person(row), "biography": row.get("biography", ""),
                    "birthday": row.get("birthday"), "deathday": row.get("deathday"),
                    "birthplace": row.get("place_of_birth", ""),
                    "also_known_as": row.get("also_known_as", []),
                    "credits": sorted(works.values(), key=lambda item: item["popularity"], reverse=True)}

        return self._people_cached((self.language, "person", person_id), fetch)
