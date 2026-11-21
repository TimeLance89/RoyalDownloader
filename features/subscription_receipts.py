"""Keep unread download receipts consistent with a verified library snapshot."""
from providers.models import parse_episode_slug

AUDIO_STATES = {"confirmed", "unclear", "unavailable"}


def record_download_receipt(entry, slug, downloaded_at, audio_check_status=""):
    parsed = parse_episode_slug(slug)
    if not parsed or parsed[1] <= 0:
        return False
    receipts = [item for item in entry.get("downloaded_episode_notifications") or []
                if isinstance(item, dict) and not (
                    (other := parse_episode_slug(item.get("slug", ""))) and other[1:] == parsed[1:])]
    receipt = {"slug": slug, "season": parsed[1], "episode": parsed[2],
               "downloaded_at": downloaded_at, "read": False}
    if audio_check_status in AUDIO_STATES:
        receipt["audio_check_status"] = audio_check_status
    entry["downloaded_episode_notifications"] = [receipt, *receipts][:20]
    return True


def reconcile_download_receipts(entry, present, evaluated, checked_at, history=()):
    completed = {}
    for job in history:
        if job.get("status") != "completed":
            continue
        slug = job.get("slug")
        if float(job.get("completed_at") or 0) > float((completed.get(slug) or {}).get("completed_at") or 0):
            completed[slug] = job
    receipts = []
    for original in entry.get("downloaded_episode_notifications") or []:
        if not isinstance(original, dict):
            continue
        receipt = dict(original)
        parsed = parse_episode_slug(receipt.get("slug", ""))
        # A download finishing during the check was absent from its snapshot.
        # Preserve it until the next check instead of losing the new notice.
        if float(receipt.get("downloaded_at") or 0) > checked_at:
            receipts.append(receipt)
            continue
        if parsed and parsed[1:] in evaluated and parsed[1:] not in present:
            continue
        job = completed.get(receipt.get("slug")) or {}
        if job.get("audio_check_status") in AUDIO_STATES:
            receipt["audio_check_status"] = job["audio_check_status"]
        receipts.append(receipt)
    entry["downloaded_episode_notifications"] = receipts
