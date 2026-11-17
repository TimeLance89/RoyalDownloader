"""Provider-independent, paginated studio and franchise discovery."""

from copy import deepcopy
import json
from pathlib import Path
import re

from core.runtime_cache import BoundedTTLCache

# One curated manifest is shared by the API and the frontend.
MOVIE_WORLD_CATALOG = json.loads(
    Path(__file__).with_name("movie_world_catalog.json").read_text(encoding="utf-8")
)
MOVIE_WORLDS = {
    item["id"]: dict(item["filters"])
    for item in MOVIE_WORLD_CATALOG["worlds"] if item["type"] == "discover"
}
# Keep the established Skywalker collection on its verified TMDB ID.
MOVIE_WORLDS["star-wars"] = {"collection": "10"}
FRANCHISE_COLLECTIONS = {
    item["id"]: tuple(item["collections"])
    for item in MOVIE_WORLD_CATALOG["worlds"] if item["type"] == "collections"
}


def public_movie_world_catalog():
    """Expose labels/groups, never an unvalidated client-supplied TMDB query."""
    return {
        "groups": MOVIE_WORLD_CATALOG["groups"],
        "worlds": [
            {key: item[key] for key in ("id", "group", "type", "de", "en")}
            for item in MOVIE_WORLD_CATALOG["worlds"]
        ],
    }


def _collection_identity(value):
    value = re.sub(r"[^\w]+", " ", str(value or "").casefold()).strip()
    value = re.sub(r"^the\s+", "", value)
    return re.sub(r"\s+collection$", "", value).strip()


GENRE_IDS = {
    "action": "28", "abenteuer": "12", "adventure": "12", "animation": "16",
    "komödie": "35", "comedy": "35", "krimi": "80", "crime": "80",
    "dokumentation": "99", "documentary": "99", "drama": "18",
    "familie": "10751", "family": "10751", "fantasy": "14", "historie": "36",
    "history": "36", "geschichte": "36", "horror": "27", "musik": "10402", "music": "10402",
    "mystery": "9648", "romantik": "10749", "romance": "10749",
    "science fiction": "878", "science-fiction": "878", "sci-fi": "878",
    "thriller": "53", "krieg": "10752", "war": "10752", "western": "37",
}
PERIODS = {
    "2020s": ("2020-01-01", None), "2010s": ("2010-01-01", "2019-12-31"),
    "2000s": ("2000-01-01", "2009-12-31"), "1990s": ("1990-01-01", "1999-12-31"),
    "1980s": ("1980-01-01", "1989-12-31"), "classic": (None, "1999-12-31"),
}
SORTS = {"default": "popularity.desc", "newest": "primary_release_date.desc",
         "oldest": "primary_release_date.asc", "rating": "vote_average.desc",
         "title": "title.asc"}


class TMDBMovieWorldsMixin:
    def movie_world(self, world, page=1, *, language="de", period="all", rating="all",
                    sort="default", genre=""):
        if world not in MOVIE_WORLDS and world not in FRANCHISE_COLLECTIONS:
            raise ValueError("Unknown movie world")
        if not 1 <= page <= 500 or language not in {"de", "en"}:
            raise ValueError("Invalid page or language")
        if period not in {"all", *PERIODS} or rating not in {"all", "6", "7", "8"} or sort not in SORTS:
            raise ValueError("Invalid movie filters")
        genre_id = GENRE_IDS.get(str(genre).strip().casefold())
        if genre and genre != "Alle Genres" and not genre_id:
            raise ValueError("Unsupported movie world genre")
        params = {"with_runtime.gte": "40", **MOVIE_WORLDS.get(world, {}), "page": str(page),
                  "language": "en-US" if language == "en" else "de-DE",
                  "include_adult": "false", "include_video": "false", "sort_by": SORTS[sort]}
        if genre_id:
            existing = params.get("with_genres")
            params["with_genres"] = f"{existing},{genre_id}" if existing else genre_id
        lower, upper = PERIODS.get(period, (None, None))
        if lower:
            params["primary_release_date.gte"] = lower
        if upper:
            params["primary_release_date.lte"] = upper
        if rating != "all":
            params["vote_average.gte"] = rating
        if rating != "all" or sort == "rating":
            params["vote_count.gte"] = "50"
        key = (world, tuple(sorted(params.items())))
        cached = self._movie_world_cache.get(key)
        if cached is not None:
            return deepcopy(cached)
        if world == "star-wars":
            collection = self._request("/collection/10", {"language": params["language"]})
            response = None
            if collection is not None:
                parts = [item for item in collection.get("parts", [])
                         if (not lower or (item.get("release_date") or "") >= lower)
                         and (not upper or "0" < (item.get("release_date") or "") <= upper)
                         and (rating == "all" or (float(item.get("vote_average") or 0) >= float(rating)
                                                  and int(item.get("vote_count") or 0) >= 50))
                         and (not genre_id or int(genre_id) in (item.get("genre_ids") or []))]
                if sort == "title":
                    parts.sort(key=lambda item: (item.get("title") or item.get("original_title") or "").casefold())
                else:
                    field = "vote_average" if sort == "rating" else "release_date"
                    parts.sort(key=lambda item: item.get(field) or (0 if field == "vote_average" else ""),
                               reverse=sort in {"newest", "rating"})
                response = {"results": parts[(page - 1) * 20:page * 20],
                            "total_results": len(parts), "total_pages": (len(parts) + 19) // 20}
        elif world in FRANCHISE_COLLECTIONS:
            result = self._franchise_world(world, page, language, genre_id,
                                           lower, upper, rating, sort)
            self._movie_world_cache[key] = deepcopy(result)
            return result
        else:
            response = self._request("/discover/movie", params)
        if response is None:
            raise RuntimeError("TMDB movie world unavailable")
        results, seen = [], set()
        for item in response.get("results") or []:
            movie_id = item.get("id")
            if not isinstance(movie_id, int) or movie_id <= 0 or movie_id in seen:
                continue
            seen.add(movie_id)
            results.append({
                "slug": f"tmdb:{movie_id}", "tmdb_id": movie_id,
                "url": f"https://www.themoviedb.org/movie/{movie_id}",
                "title": item.get("title") or item.get("original_title") or "",
                "original_title": item.get("original_title") or "",
                "year": (item.get("release_date") or "")[:4],
                "release_date": item.get("release_date") or "",
                "description": item.get("overview") or "",
                "cover_url": self._poster_url(item.get("poster_path") or ""),
                "backdrop_url": self._backdrop_url(item.get("backdrop_path") or ""),
                "rating": round(float(item.get("vote_average") or 0), 1),
                "vote_count": int(item.get("vote_count") or 0),
                "is_movie": True, "provider": "", "content_language": "",
                "metadata_source": "TMDB", "details_loaded": False,
            })
        result = {"results": results, "category": "world", "page": page,
                  "has_more": page < min(int(response.get("total_pages") or 0), 500),
                  "total_results": int(response.get("total_results") or 0), "sources": []}
        if world == "star-wars":
            result["collections"] = [{"collection_id": 10, "title": "Star Wars"}]
        self._movie_world_cache[key] = deepcopy(result)
        return result

    def _lookup_franchise_collection(self, spec, language):
        """Fetch a real TMDB collection, rejecting ambiguous title search matches."""
        cache_key = (spec.get("id"), spec.get("query"), language)
        cached = self._movie_world_collection_cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)
        collection_id = spec.get("id")
        if collection_id is None:
            query = spec.get("query") or ""
            search = self._request("/search/collection", {
                "query": query, "language": "en-US", "page": "1",
            })
            if search is None:
                raise RuntimeError("TMDB collection search unavailable")
            expected = _collection_identity(query)
            candidates = [item for item in search.get("results") or []
                          if _collection_identity(item.get("original_name") or item.get("name")) == expected]
            if not candidates:
                return None
            collection_id = candidates[0].get("id")
        if not isinstance(collection_id, int) or collection_id <= 0:
            return None
        collection = self._request(f"/collection/{collection_id}", {
            "language": "en-US" if language == "en" else "de-DE",
        })
        if collection is None:
            raise RuntimeError("TMDB franchise unavailable")
        value = {"collection_id": collection_id,
                 "title": collection.get("name") or spec.get("query") or "",
                 "parts": collection.get("parts") or []}
        self._movie_world_collection_cache[cache_key] = deepcopy(value)
        return value

    def _franchise_world(self, world, page, language, genre_id, lower, upper, rating, sort):
        collections, all_parts, seen = [], [], set()
        for spec in FRANCHISE_COLLECTIONS[world]:
            collection = self._lookup_franchise_collection(spec, language)
            if collection is None:
                continue
            collections.append({key: collection[key] for key in ("collection_id", "title")})
            for item in collection["parts"]:
                movie_id = item.get("id")
                if not isinstance(movie_id, int) or movie_id <= 0 or movie_id in seen:
                    continue
                seen.add(movie_id)
                release = item.get("release_date") or ""
                if lower and (not release or release < lower):
                    continue
                if upper and (not release or release > upper):
                    continue
                if genre_id and int(genre_id) not in (item.get("genre_ids") or []):
                    continue
                if rating != "all" and (float(item.get("vote_average") or 0) < float(rating)
                                        or int(item.get("vote_count") or 0) < 50):
                    continue
                all_parts.append(item)
        if sort == "title":
            all_parts.sort(key=lambda item: (item.get("title") or item.get("original_title") or "").casefold())
        elif sort == "rating":
            all_parts.sort(key=lambda item: (float(item.get("vote_average") or 0),
                                             int(item.get("vote_count") or 0)), reverse=True)
        else:
            all_parts.sort(key=lambda item: item.get("release_date") or "9999-99-99",
                           reverse=sort == "newest")
        total = len(all_parts)
        results = []
        for item in all_parts[(page - 1) * 20:page * 20]:
            movie_id = item["id"]
            results.append({
                "slug": f"tmdb:{movie_id}", "tmdb_id": movie_id,
                "url": f"https://www.themoviedb.org/movie/{movie_id}",
                "title": item.get("title") or item.get("original_title") or "",
                "original_title": item.get("original_title") or "",
                "year": (item.get("release_date") or "")[:4],
                "release_date": item.get("release_date") or "",
                "description": item.get("overview") or "",
                "cover_url": self._poster_url(item.get("poster_path") or ""),
                "backdrop_url": self._backdrop_url(item.get("backdrop_path") or ""),
                "rating": round(float(item.get("vote_average") or 0), 1),
                "vote_count": int(item.get("vote_count") or 0),
                "is_movie": True, "provider": "", "content_language": "",
                "metadata_source": "TMDB", "details_loaded": False,
            })
        return {"results": results, "category": "world", "page": page,
                "has_more": page * 20 < total, "total_results": total,
                "collections": collections, "sources": []}

    def _init_movie_world_cache(self):
        self._movie_world_cache = BoundedTTLCache("tmdb_movie_worlds", max_entries=128, ttl_seconds=900)
        self._movie_world_collection_cache = BoundedTTLCache("tmdb_franchise_collections", max_entries=128, ttl_seconds=900)
