import re
from dataclasses import dataclass

from beanie import PydanticObjectId
from bson import ObjectId
from bson.errors import InvalidId

from src.features.catalog.series import SeriesModel
from src.features.catalog.video import VideoModel
from src.logger import get_logger

logger = get_logger("series_service")


@dataclass(frozen=True)
class SeriesPlacement:
    """Where one video sits: its series, and its 1-based position in it."""

    video_id: str
    series_name: str
    order: int


@dataclass(frozen=True)
class SeriesChange:
    """
    What a write did. ``changed`` exists because the order no longer lives on the videos:
    a reorder writes no video document, so a caller counting video writes alone would
    report it as a no-op.
    """

    series_id: PydanticObjectId | None
    changed: bool


class SeriesService:
    """
    Owns both halves of series membership — the series' ``videoIds`` and each video's
    ``seriesId`` back-reference — so the two are only ever written together, here.
    """

    async def search_by_prefix(self, keyword: str, limit: int) -> list[str]:
        """
        Return series names containing `keyword` case-insensitively, capped at `limit`.

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
        query: dict = {}
        if keyword:
            query["name"] = {"$regex": re.escape(keyword), "$options": "i"}

        names = sorted(await SeriesModel.get_pymongo_collection().distinct("name", query))
        if not keyword:
            return names[:limit]

        lowered = keyword.lower()
        prefix_matches = [n for n in names if n.lower().startswith(lowered)]
        contains_matches = [n for n in names if not n.lower().startswith(lowered)]
        return (prefix_matches + contains_matches)[:limit]

    async def get_videos_in_series(self, name: str, valid_categories: list[str]) -> list[VideoModel]:
        """
        Return the videos of a series in series order, restricted to `valid_categories`.

        An id the series lists but no video carries any more is skipped rather than failing
        the whole listing.

        :param name: The name of the series to retrieve videos for.
        :type name: str
        :param valid_categories: List of valid categories to filter videos.
        :type valid_categories: list[str]
        :return: List of videos in the specified series.
        :rtype: list[VideoModel]
        """
        if not name or not valid_categories:
            return []
        series = await SeriesModel.find_one({"name": name})
        if series is None:
            return []

        by_id = {
            v.id: v
            for v in await VideoModel.find(
                {"_id": {"$in": series.videoIds}, "category": {"$in": valid_categories}}
            ).to_list()
        }
        return [by_id[vid] for vid in series.videoIds if vid in by_id]

    async def positions_of(self, videos: list[VideoModel]) -> dict[str, SeriesPlacement]:
        """
        Read where each video sits, with one query for the whole list.

        :param videos: The videos to look up.
        :type videos: list[VideoModel]
        :return: A placement per video id; videos in no series are absent.
        :rtype: dict[str, SeriesPlacement]
        """
        series_ids = {v.seriesId for v in videos if v.seriesId is not None}
        if not series_ids:
            return {}

        positions: dict[PydanticObjectId, tuple[str, int]] = {}
        for series in await SeriesModel.find({"_id": {"$in": list(series_ids)}}).to_list():
            for index, vid in enumerate(series.videoIds, start=1):
                positions[vid] = (series.name, index)

        placements = {}
        for video in videos:
            if video.id in positions:
                name, order = positions[video.id]
                placements[str(video.id)] = SeriesPlacement(str(video.id), name, order)
        return placements

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def assign(self, target_series_name: str, ordered_video_ids: list[str]) -> SeriesChange:
        """
        Place a selection into a series, in the requested relative order.

        ``ordered_video_ids`` is a *relative* sequence: the panel that produced it may only
        have seen the selected videos, so it cannot know what else the target holds. The
        slots the selection takes are the ones it already held in the target, plus one
        appended slot per video joining; sorted, they are filled by the requested sequence
        in order. A selection made only of existing members therefore permutes itself and
        leaves the rest of the series untouched, while a newcomer dropped between two
        members lands exactly where it was dropped.

        The target is created if no series has that name yet. Every series the selection
        departs loses those videos, and is deleted if nothing is left in it.

        :param target_series_name: The series the selection is being placed into.
        :type target_series_name: str
        :param ordered_video_ids: The selection, in the requested relative order.
        :type ordered_video_ids: list[str]
        :return: The target's id, and whether anything was written.
        :rtype: SeriesChange
        """
        selected = await self._resolve(ordered_video_ids)
        target = await SeriesModel.find_one({"name": target_series_name})
        if not selected:
            return SeriesChange(target.id if target else None, False)

        members = list(target.videoIds) if target else []
        new_ids = self._place(members, [v.id for v in selected])
        changed = new_ids != members

        if target is None:
            target = SeriesModel(name=target_series_name, videoIds=new_ids)
            await target.insert()
        elif changed:
            await SeriesModel.get_pymongo_collection().update_one(
                {"_id": target.id}, {"$set": {"videoIds": new_ids}}
            )

        joining = [v.id for v in selected if v.seriesId != target.id]
        if joining:
            await self._pull(joining, keep=target.id)
            await VideoModel.get_pymongo_collection().update_many(
                {"_id": {"$in": joining}}, {"$set": {"seriesId": target.id}}
            )
            changed = True

        return SeriesChange(target.id, changed)

    async def clear(self, video_ids: list[str]) -> SeriesChange:
        """
        Take a selection out of whatever series it is in.

        :param video_ids: The videos being cleared.
        :type video_ids: list[str]
        :return: Whether anything was written.
        :rtype: SeriesChange
        """
        selected = await self._resolve(video_ids)
        ids = [v.id for v in selected]
        pulled = await self._pull(ids)

        referencing = [v.id for v in selected if v.seriesId is not None]
        if referencing:
            await VideoModel.get_pymongo_collection().update_many(
                {"_id": {"$in": referencing}}, {"$set": {"seriesId": None}}
            )
        return SeriesChange(None, pulled or bool(referencing))

    async def detach(self, video_ids: list[str]) -> None:
        """
        Drop deleted videos from their series. Their documents are already gone, so only
        the series side is left to settle.

        :param video_ids: The ids of the deleted videos.
        :type video_ids: list[str]
        """
        await self._pull(self._object_ids(video_ids))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _place(members: list[PydanticObjectId], selection: list[PydanticObjectId]) -> list[PydanticObjectId]:
        """The target's new sequence once `selection` is placed into `members`."""
        chosen = set(selection)
        kept = [m for m in members if m not in chosen]
        occupied = [i for i, m in enumerate(members) if m in chosen]
        appended = range(len(members), len(members) + len(selection) - len(occupied))
        slots = sorted([*occupied, *appended])

        # Slots and leftovers partition every position exactly once, so the merged map is
        # dense and its keys in ascending order are the series as it will read.
        taken = set(slots)
        free = [i for i in range(len(slots) + len(kept)) if i not in taken]
        final = dict(zip(slots, selection)) | dict(zip(free, kept))
        return [final[i] for i in sorted(final)]

    @staticmethod
    async def _pull(video_ids: list, keep: PydanticObjectId | None = None) -> bool:
        """
        Remove the ids from every series listing them (other than `keep`), and delete any
        series left empty by it. Returns whether any series listed them.
        """
        if not video_ids:
            return False
        scope: dict = {"videoIds": {"$in": video_ids}}
        if keep is not None:
            scope["_id"] = {"$ne": keep}

        collection = SeriesModel.get_pymongo_collection()
        affected = await collection.distinct("_id", scope)
        if not affected:
            return False
        await collection.update_many(
            {"_id": {"$in": affected}}, {"$pull": {"videoIds": {"$in": video_ids}}}
        )
        await collection.delete_many({"_id": {"$in": affected}, "videoIds": {"$size": 0}})
        return True

    @staticmethod
    def _object_ids(video_ids: list[str]) -> list[ObjectId]:
        object_ids = []
        for vid in video_ids:
            try:
                object_ids.append(ObjectId(vid))
            except (InvalidId, TypeError):
                continue
        return object_ids

    @classmethod
    async def _resolve(cls, video_ids: list[str]) -> list[VideoModel]:
        """The named videos that still exist, in the order they were named, without repeats."""
        by_id = {
            str(v.id): v
            for v in await VideoModel.find(
                {"_id": {"$in": cls._object_ids(video_ids)}}
            ).to_list()
        }
        seen: set[str] = set()
        resolved = []
        for vid in video_ids:
            if vid in by_id and vid not in seen:
                seen.add(vid)
                resolved.append(by_id[vid])
        return resolved
