"""Read series membership back from the database in a form assertions can be written against."""

from src.features.catalog.series import SeriesModel
from src.features.catalog.video import VideoModel


async def stored_series(name: str) -> list[str] | None:
    """
    The series named `name` as stored, read back as its members' video names in order.

    None when no such series exists. An id with no video behind it is shown as the id
    itself, so a dangling reference is visible in the assertion instead of vanishing.
    """
    series = await SeriesModel.find_one({"name": name})
    if series is None:
        return None
    by_id = {
        v.id: v.name
        for v in await VideoModel.find({"_id": {"$in": series.videoIds}}).to_list()
    }
    return [by_id.get(vid, str(vid)) for vid in series.videoIds]


async def series_name_of(video: VideoModel) -> str | None:
    """The name of the series a video's stored seriesId points at, re-read from the database."""
    stored = await VideoModel.get(video.id)
    if stored.seriesId is None:
        return None
    series = await SeriesModel.get(stored.seriesId)
    return series.name if series is not None else str(stored.seriesId)
