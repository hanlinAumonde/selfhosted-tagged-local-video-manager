#: Formats browsers play natively, so they are streamed as stored instead of transcoded.
BROWSER_MIME_TYPES = {"mp4": "video/mp4", "webm": "video/webm"}

#: What every other format is transcoded to before it is streamed.
TRANSCODED_MIME_TYPE = "video/mp4"

#: Where in a video the thumbnail is taken: past most intros and black opening frames.
THUMBNAIL_SEEK_SECONDS = 10
