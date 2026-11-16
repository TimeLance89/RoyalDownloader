"""MediaSegments reads through the existing authenticated Jellyfin transport."""

from integrations.jellyfin_saved import jellyfin_id


class JellyfinSegmentsMixin:
    def media_segment_user(self, user_id):
        return self._saved_request("GET", f"/Users/{jellyfin_id(user_id)}")

    def media_segment_video(self, user_id, item_id):
        return self._saved_request("GET", "/Items", params={
            "UserId": jellyfin_id(user_id), "Ids": jellyfin_id(item_id),
            "IncludeItemTypes": "Movie,Episode", "Recursive": "true", "Limit": 1,
            "EnableImages": "false", "EnableUserData": "false",
            "ExcludeLocationTypes": "Virtual,Offline", "IsMissing": "false",
            "IsPlaceHolder": "false",
        })

    def media_segments(self, item_id):
        # The service filters supported segment types after reading the native list.
        # A comma-separated value is not portable for Jellyfin's enum collection.
        return self._saved_request("GET", f"/MediaSegments/{jellyfin_id(item_id)}")
