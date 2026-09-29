import re
from dataclasses import dataclass

import pymongo
from bson import ObjectId
from bson.errors import InvalidId

from src.features.catalog.video import VideoModel
from src.logger import get_logger

logger = get_logger("series_service")


@dataclass(frozen=True)
class SeriesPlacement:
    """Where one video ends up: its series, and its position in it."""

    video_id: str
    series_name: str | None
    order: int | None


class SeriesService:

    async def search_by_prefix(self, keyword: str, limit: int) -> list[str]:
        """
        Return series names (derived from VideoModel.seriesName) containing `keyword`
        case-insensitively, capped at `limit`. No dictionary collection is used; this
        reads `distinct` directly off the videos collection.

        Names starting with the keyword are ranked ahead of names merely containing it,
        mirroring the prefix-then-contains ordering of `getSuggestions`. Both groups are
        sorted alphabetically, so a shrinking `limit` only ever trims the weaker matches.

        :param keyword: The substring to search for; empty means "no filter".
        :type keyword: str
        :param limit: The maximum number of series names to return.
        :type limit: int
        :return: List of series names matching the keyword.
        :rtype: list[str]
        """
        query: dict = {"seriesName": {"$ne": None}}
        if keyword:
            escaped = re.escape(keyword)
            query["seriesName"] = {"$ne": None, "$regex": escaped, "$options": "i"}

        names = await VideoModel.get_pymongo_collection().distinct("seriesName", query)
        names = sorted(n for n in names if n)
        if not keyword:
            return names[:limit]

        lowered = keyword.lower()
        prefix_matches = [n for n in names if n.lower().startswith(lowered)]
        contains_matches = [n for n in names if not n.lower().startswith(lowered)]
        return (prefix_matches + contains_matches)[:limit]

    async def get_videos_in_series(self, name: str, valid_categories: list[str]) -> list[VideoModel]:
        """
        Return videos belonging to a series, sorted by seriesOrder ascending (nulls last).

        :param name: The name of the series to retrieve videos for.
        :type name: str
        :param valid_categories: List of valid categories to filter videos.
        :type valid_categories: list[str]
        :return: List of videos in the specified series.
        :rtype: list[VideoModel]
        """
        if not name or not valid_categories:
            return []
        return (
            await VideoModel.find(
                {"seriesName": name, "category": {"$in": valid_categories}}
            )
            .sort([("seriesOrder", pymongo.ASCENDING), ("name", pymongo.ASCENDING)])
            .to_list()
        )

    # ------------------------------------------------------------------
    # Planning a re-ordering
    # ------------------------------------------------------------------

    async def plan_assignment(
        self, target_series_name: str, ordered_video_ids: list[str]
    ) -> list[SeriesPlacement]:
        """
        Work out where every affected video ends up when a selection is placed into a series.

        ``ordered_video_ids`` is a *relative* sequence, not a set of final numbers: the
        panel that produced it only ever saw the selected videos, so it cannot know what
        else the target series holds. The slots the selection takes are the ones it already
        held in the target, plus one appended slot per video joining; sorted, they are
        filled by the requested sequence in order. A selection made only of existing
        members therefore permutes itself and leaves the rest of the series untouched,
        while a newcomer dropped between two members lands exactly where it was dropped.

        The plan covers videos the caller never named — the target's other members, and
        whatever is left in the series the selection departed — because both of those
        groups carry numbers that have to stay consistent with the new arrangement. It
        states the intended end state for each, including the ones that are already there;
        deciding which are worth writing is the caller's job.

        :param target_series_name: The series the selection is being placed into.
        :type target_series_name: str
        :param ordered_video_ids: The selection, in the requested relative order.
        :type ordered_video_ids: list[str]
        :return: The intended end state of every affected video.
        :rtype: list[SeriesPlacement]
        """
        selected = await self._resolve(ordered_video_ids)
        selected_ids = {str(v.id) for v in selected}

        members = await self._sorted_members(target_series_name)
        kept = [m for m in members if str(m.id) not in selected_ids]
        occupied = [i for i, m in enumerate(members) if str(m.id) in selected_ids]
        appended = range(len(members), len(members) + len(selected) - len(occupied))
        slots = sorted([*occupied, *appended])

        # Slots and leftovers partition every position exactly once, so the merged map is
        # dense and its keys in ascending order are the series as it will read.
        free = [i for i in range(len(slots) + len(kept)) if i not in set(slots)]
        final = dict(zip(slots, selected)) | dict(zip(free, kept))

        placements = [
            SeriesPlacement(
                video_id=str(final[slot].id),
                series_name=target_series_name,
                order=order,
            )
            for order, slot in enumerate(sorted(final), start=1)
        ]
        placements.extend(await self._compact_donors(selected, exclude=target_series_name))
        return placements

    async def plan_clear(self, video_ids: list[str]) -> list[SeriesPlacement]:
        """
        Work out the end state when a selection is taken out of whatever series it is in.

        Same reason as ``plan_assignment`` for reaching beyond the selection: pulling three
        videos out of the middle of a series leaves the members behind them carrying the
        numbers they had, so what remains is compacted.

        :param video_ids: The videos being cleared.
        :type video_ids: list[str]
        :return: The intended end state of every affected video.
        :rtype: list[SeriesPlacement]
        """
        selected = await self._resolve(video_ids)
        placements = [
            SeriesPlacement(video_id=str(v.id), series_name=None, order=None)
            for v in selected
        ]
        placements.extend(await self._compact_donors(selected, exclude=None))
        return placements

    async def _compact_donors(
        self, leaving: list[VideoModel], exclude: str | None
    ) -> list[SeriesPlacement]:
        """Renumber what is left of every series the selection is walking out of."""
        donors = {
            v.seriesName for v in leaving
            if v.seriesName is not None and v.seriesName != exclude
        }
        leaving_ids = {str(v.id) for v in leaving}

        placements: list[SeriesPlacement] = []
        for donor in donors:
            remaining = [
                m for m in await self._sorted_members(donor)
                if str(m.id) not in leaving_ids
            ]
            placements.extend(
                SeriesPlacement(video_id=str(m.id), series_name=donor, order=order)
                for order, m in enumerate(remaining, start=1)
            )
        return placements

    @staticmethod
    async def _resolve(video_ids: list[str]) -> list[VideoModel]:
        """The named videos that still exist, in the order they were named, without repeats."""
        object_ids = []
        for vid in video_ids:
            try:
                object_ids.append(ObjectId(vid))
            except (InvalidId, TypeError):
                continue

        by_id = {
            str(v.id): v
            for v in await VideoModel.find({"_id": {"$in": object_ids}}).to_list()
        }
        seen: set[str] = set()
        resolved = []
        for vid in video_ids:
            if vid in by_id and vid not in seen:
                seen.add(vid)
                resolved.append(by_id[vid])
        return resolved

    @staticmethod
    async def _sorted_members(series_name: str) -> list[VideoModel]:
        """
        Every video in a series, in the order it currently reads.

        Sorted in Python rather than by the database because a member with no order at all
        has to sort after the numbered ones, and `None` sorts first in MongoDB.
        """
        members = await VideoModel.find({"seriesName": series_name}).to_list()
        return sorted(
            members,
            key=lambda m: (
                m.seriesOrder is None,
                m.seriesOrder if m.seriesOrder is not None else 0,
                m.name,
            ),
        )
