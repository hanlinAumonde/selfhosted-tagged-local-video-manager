"""Tests for ``batchUpdateSubscription`` and ``batchDeleteSubscription``."""

from unittest.mock import MagicMock

import pytest

from src.features.migration.migration_task import TaskStatus

from src.features.browsing.batch_operation_service import (
    BatchProgress,
    BatchResultType,
    DirectoryDeletionStrategy,
)
from tests.graphql.helpers import (
    BATCH_DELETE_SUBSCRIPTION,
    BATCH_UPDATE_SUBSCRIPTION,
    make_batch_input,
    make_relative_path_input,
    make_tags_operation,
)


pytestmark = pytest.mark.subscription


def _success_status(message: str) -> BatchProgress:
    return BatchProgress(result_type=BatchResultType.Success, message=message)


def _progress(status: str) -> BatchProgress:
    return BatchProgress(status=status)


def _async_iter_factory(events: list):
    """Build an async-generator factory that yields the supplied events."""
    async def _gen(*_args, **_kwargs):
        for ev in events:
            yield ev
    return _gen


# ----------------------- batch_update by video IDs --------------------------

async def test_batch_update_by_video_ids_streams_progress(
    subscribe_gql, mock_batch_operation_service, video_factory
):
    a = await video_factory(name="a")
    b = await video_factory(name="b")

    mock_batch_operation_service.batch_update.side_effect = _async_iter_factory(
        [_progress("scanning"), _success_status("2 videos updated")]
    )

    payload = make_batch_input(
        video_ids=[str(a.id), str(b.id)],
        relative_path="Test-category/Test-resource",
        tags_operation=make_tags_operation(add=["new"]),
    )
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    assert len(events) == 2
    assert all(ev.errors is None for ev in events)
    assert events[0].data["batchUpdateSubscription"]["status"] == "scanning"
    assert (
        events[1].data["batchUpdateSubscription"]["result"]["resultType"]
        == "Success"
    )
    mock_batch_operation_service.batch_update.assert_called_once()
    mock_batch_operation_service.batch_delete.assert_not_called()


# ----------------------- batch_delete by video IDs --------------------------

async def test_batch_delete_by_video_ids_invokes_delete(
    subscribe_gql, mock_batch_operation_service, video_factory
):
    a = await video_factory(name="a")

    mock_batch_operation_service.batch_delete.side_effect = _async_iter_factory(
        [_progress("removing"), _success_status("done")]
    )

    payload = make_batch_input(
        video_ids=[str(a.id)],
        relative_path="Test-category/Test-resource",
    )
    events = await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": payload})

    assert len(events) == 2
    assert events[0].data["batchDeleteSubscription"]["status"] == "removing"
    mock_batch_operation_service.batch_delete.assert_called_once()
    mock_batch_operation_service.batch_update.assert_not_called()


# ----------------------- Series operation validation -----------------------

async def test_batch_update_series_clear_requires_video_ids(
    subscribe_gql, mock_batch_operation_service, init_db
):
    payload = make_batch_input(
        video_ids=[],
        relative_path="Test-category/Test-resource",
        series_operation={"name": None, "clear": True, "orders": []},
    )
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    assert events
    assert events[0].errors
    mock_batch_operation_service.batch_update.assert_not_called()


async def test_batch_delete_with_series_operation_rejected(
    subscribe_gql, mock_batch_operation_service, video_factory
):
    a = await video_factory(name="a")

    payload = make_batch_input(
        video_ids=[str(a.id)],
        relative_path="Test-category/Test-resource",
        series_operation={"name": None, "clear": True, "orders": []},
    )
    events = await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": payload})

    assert events
    assert events[0].errors
    mock_batch_operation_service.batch_delete.assert_not_called()


async def test_batch_update_series_assign_orders_must_match_ids(
    subscribe_gql, mock_batch_operation_service, video_factory
):
    a = await video_factory(name="a")
    b = await video_factory(name="b")

    # videoIds = {a, b} but orders only mentions a → mismatch.
    payload = make_batch_input(
        video_ids=[str(a.id), str(b.id)],
        relative_path="Test-category/Test-resource",
        series_operation={
            "name": "S",
            "clear": False,
            "orders": [{"videoId": str(a.id), "order": 1}],
        },
    )
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    assert events
    assert events[0].errors
    mock_batch_operation_service.batch_update.assert_not_called()


async def test_batch_update_series_assign_requires_name(
    subscribe_gql, mock_batch_operation_service, video_factory
):
    a = await video_factory(name="a")

    payload = make_batch_input(
        video_ids=[str(a.id)],
        relative_path="Test-category/Test-resource",
        series_operation={
            "name": None,
            "clear": False,
            "orders": [{"videoId": str(a.id), "order": 1}],
        },
    )
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    assert events
    assert events[0].errors


# --------------------------- Invalid input ---------------------------------

async def test_batch_update_invalid_relative_path(
    subscribe_gql, mock_batch_operation_service, init_db
):
    payload = {
        "videoIds": [],
        "relativePath": make_relative_path_input("not-a-category"),
        "tagsOperation": None,
        "seriesOperation": None,
        "author": None,
        "directoryDeletion": None,
    }
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    assert events and events[0].errors
    mock_batch_operation_service.batch_update.assert_not_called()


async def test_batch_update_missing_input(subscribe_gql, init_db):
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {})
    assert events and events[0].errors


# ---------------------- Directory expansion path --------------------------

async def test_batch_update_by_directory_expands_and_calls_browse(
    subscribe_gql,
    mock_batch_operation_service,
    mock_browse_file_service,
    init_db,
):
    fake_entry = MagicMock(name="fake-entry")
    mock_browse_file_service.get_all_video_entries_in_directory.return_value = [
        fake_entry
    ]
    mock_batch_operation_service.batch_update.side_effect = _async_iter_factory(
        [_success_status("ok")]
    )

    payload = make_batch_input(
        video_ids=[],
        relative_path="Test-category/Test-resource",
        tags_operation=make_tags_operation(add=["x"]),
    )
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    # Resolver yields:
    #   1. one progress event per scanned directory (with entries),
    #   2. a "Found N video entries" event,
    #   3. + whatever batch_update yields (here: 1 success event).
    assert len(events) >= 2
    assert all(ev.errors is None for ev in events)
    mock_browse_file_service.get_all_video_entries_in_directory.assert_called()
    mock_batch_operation_service.batch_update.assert_called_once()


# ------------------- batch_delete by directory path ---------------------------

async def test_batch_delete_by_directory_expands_and_calls_browse(
    subscribe_gql,
    mock_batch_operation_service,
    mock_browse_file_service,
    init_db,
):
    fake_entry = MagicMock(name="fake-entry")
    mock_browse_file_service.get_all_video_entries_in_directory.return_value = [
        fake_entry
    ]
    mock_batch_operation_service.batch_delete.side_effect = _async_iter_factory(
        [_success_status("deleted")]
    )

    payload = make_batch_input(
        video_ids=[],
        relative_path="Test-category/Test-resource",
    )
    events = await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": payload})

    assert len(events) >= 2
    assert all(ev.errors is None for ev in events)
    mock_browse_file_service.get_all_video_entries_in_directory.assert_called()
    mock_batch_operation_service.batch_delete.assert_called_once()


# --------------------- Tags operation, both directions -----------------------

async def test_batch_update_passes_both_tag_lists_through_to_the_service(
    subscribe_gql, mock_batch_operation_service, video_factory
):
    a = await video_factory(name="a")
    b = await video_factory(name="b")

    mock_batch_operation_service.batch_update.side_effect = _async_iter_factory(
        [_success_status("ok")]
    )

    payload = make_batch_input(
        video_ids=[str(a.id), str(b.id)],
        relative_path="Test-category/Test-resource",
        tags_operation=make_tags_operation(add=["4k"], remove=["todo"]),
    )
    await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    tags_operation = mock_batch_operation_service.batch_update.call_args.kwargs[
        "tagsOperation"
    ]
    assert tags_operation.addTags == ["4k"]
    assert tags_operation.removeTags == ["todo"]


async def test_batch_update_rejects_a_tag_named_in_both_lists(
    subscribe_gql, mock_batch_operation_service, video_factory
):
    a = await video_factory(name="a")
    b = await video_factory(name="b")

    payload = make_batch_input(
        video_ids=[str(a.id), str(b.id)],
        relative_path="Test-category/Test-resource",
        tags_operation=make_tags_operation(add=["raw"], remove=["raw"]),
    )
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    assert events and events[0].errors
    mock_batch_operation_service.batch_update.assert_not_called()


# ------------------- Deleting a directory, folder and all --------------------

async def test_batch_delete_by_directory_defaults_to_keeping_the_folder(
    subscribe_gql, mock_batch_operation_service, mock_browse_file_service, init_db
):
    mock_browse_file_service.get_all_video_entries_in_directory.return_value = [
        MagicMock(name="fake-entry")
    ]
    mock_batch_operation_service.batch_delete.side_effect = _async_iter_factory(
        [_success_status("deleted")]
    )

    payload = make_batch_input(
        video_ids=[],
        relative_path="Test-category/Test-resource/subdir",
    )
    await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": payload})

    strategy = mock_batch_operation_service.batch_delete.call_args.kwargs[
        "directoryDeletion"
    ]
    assert strategy == DirectoryDeletionStrategy.KeepFolder


async def test_batch_delete_by_directory_can_ask_for_the_folder_to_go_too(
    subscribe_gql, mock_batch_operation_service, mock_browse_file_service, init_db
):
    mock_browse_file_service.get_all_video_entries_in_directory.return_value = [
        MagicMock(name="fake-entry")
    ]
    mock_batch_operation_service.batch_delete.side_effect = _async_iter_factory(
        [_success_status("deleted")]
    )

    payload = make_batch_input(
        video_ids=[],
        relative_path="Test-category/Test-resource/subdir",
        directory_deletion="DeleteFolder",
    )
    await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": payload})

    strategy = mock_batch_operation_service.batch_delete.call_args.kwargs[
        "directoryDeletion"
    ]
    assert strategy == DirectoryDeletionStrategy.DeleteFolder


async def test_a_deletion_strategy_is_rejected_on_a_batch_update(
    subscribe_gql, mock_batch_operation_service, init_db
):
    payload = make_batch_input(
        video_ids=[],
        relative_path="Test-category/Test-resource/subdir",
        directory_deletion="DeleteFolder",
    )
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    assert events and events[0].errors
    mock_batch_operation_service.batch_update.assert_not_called()


async def test_a_deletion_strategy_is_rejected_when_deleting_by_video_ids(
    subscribe_gql, mock_batch_operation_service, video_factory
):
    a = await video_factory(name="a")

    payload = make_batch_input(
        video_ids=[str(a.id)],
        relative_path="Test-category/Test-resource/subdir",
        directory_deletion="DeleteFolder",
    )
    events = await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": payload})

    assert events and events[0].errors
    mock_batch_operation_service.batch_delete.assert_not_called()


async def test_a_deletion_strategy_is_rejected_at_the_category_level(
    subscribe_gql, mock_batch_operation_service, init_db
):
    """The category level lists configured mount points, not places on the storage."""
    payload = make_batch_input(
        video_ids=[],
        relative_path="Test-category",
        directory_deletion="DeleteFolder",
    )
    events = await subscribe_gql(BATCH_DELETE_SUBSCRIPTION, {"input": payload})

    assert events and events[0].errors
    mock_batch_operation_service.batch_delete.assert_not_called()


# ----------------------- Migration lock in batch ops -------------------------

async def test_batch_update_migration_locked_video(
    subscribe_gql, mock_batch_operation_service, video_factory, task_factory
):
    a = await video_factory(name="locked-video")
    await task_factory(source_path=a.path, status=TaskStatus.PROCESSING)

    payload = make_batch_input(
        video_ids=[str(a.id)],
        relative_path="Test-category/Test-resource",
        tags_operation=make_tags_operation(add=["new"]),
    )
    events = await subscribe_gql(BATCH_UPDATE_SUBSCRIPTION, {"input": payload})

    assert events
    assert events[0].errors
    mock_batch_operation_service.batch_update.assert_not_called()
