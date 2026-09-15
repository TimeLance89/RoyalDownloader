"""Central update-channel names and their GitHub branch mapping."""

from types import MappingProxyType


UPDATE_CHANNEL_STABLE = "stable"
UPDATE_CHANNEL_OVERNIGHT = "overnight"
DEFAULT_UPDATE_CHANNEL = UPDATE_CHANNEL_STABLE
UPDATE_CHANNEL_BRANCHES = MappingProxyType({
    UPDATE_CHANNEL_STABLE: "main",
    UPDATE_CHANNEL_OVERNIGHT: "overnight",
})
UPDATE_CHANNELS = frozenset(UPDATE_CHANNEL_BRANCHES)
DEFAULT_UPDATE_BRANCH = UPDATE_CHANNEL_BRANCHES[DEFAULT_UPDATE_CHANNEL]


def normalize_update_channel(value: object) -> str:
    channel = str(value or "").strip().casefold()
    return channel if channel in UPDATE_CHANNELS else DEFAULT_UPDATE_CHANNEL


def update_branch_for_channel(channel: object) -> str:
    return UPDATE_CHANNEL_BRANCHES[normalize_update_channel(channel)]


def update_channel_for_branch(branch: object) -> str:
    normalized = str(branch or "").strip().casefold()
    return next(
        (
            channel
            for channel, mapped_branch in UPDATE_CHANNEL_BRANCHES.items()
            if mapped_branch == normalized
        ),
        DEFAULT_UPDATE_CHANNEL,
    )
