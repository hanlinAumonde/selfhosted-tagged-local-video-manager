"""Tests for migration progress and retry subscriptions.

The subscriptions are observers over the progress the worker publishes: progress must
be read from the bus, and opening one must never kick off execution itself.
"""

import pytest

from src.platform.jobs.progress import ProgressFrame
from src.schema.types.migration_type import MigrationProgressStatus
from tests.graphql.helpers import (
    MIGRATION_PROGRESS_SUBSCRIPTION,
    MIGRATION_RETRY_SUBSCRIPTION,
    assert_no_errors,
)

pytestmark = pytest.mark.subscription

TASK_ID = "507f1f77bcf86cd799439011"


async def _mock_progress_gen(*events):
    for e in events:
        yield e


def _events():
    return [
        ProgressFrame(
            task_id="tid", status="PROCESSING",
            current=50, total=100, message="Copying",
        ),
        ProgressFrame(
            task_id="tid", status="COMPLETED",
            current=100, total=100, message="Done",
        ),
    ]


class TestMigrationProgressSubscription:
    async def test_migration_progress_streams_events(
        self, subscribe_gql, mock_progress_bus,
    ):
        mock_progress_bus.observe.side_effect = (
            lambda *a, **kw: _mock_progress_gen(*_events())
        )

        results = await subscribe_gql(MIGRATION_PROGRESS_SUBSCRIPTION, {
            "input": {"taskId": TASK_ID}
        })
        assert len(results) == 2
        assert_no_errors(results[0])
        assert_no_errors(results[1])

        first = results[0].data["migrationProgressSubscription"]
        assert first["bytesTransferred"] == "50"
        assert first["progressPercentage"] == 50.0

        last = results[1].data["migrationProgressSubscription"]
        assert last["status"] == "COMPLETED"
        assert last["progressPercentage"] == 100.0

    async def test_progress_observes_and_never_submits(
        self, subscribe_gql, mock_progress_bus, mock_migration_dispatcher,
    ):
        """Regression: a page refresh must not spawn a second copy of the same task."""
        mock_progress_bus.observe.side_effect = (
            lambda *a, **kw: _mock_progress_gen(*_events())
        )

        await subscribe_gql(MIGRATION_PROGRESS_SUBSCRIPTION, {"input": {"taskId": TASK_ID}})

        mock_progress_bus.observe.assert_called_once()
        assert mock_progress_bus.observe.call_args.args[0] == TASK_ID
        mock_migration_dispatcher.submit.assert_not_awaited()

    async def test_progress_on_settled_task_yields_nothing(
        self, subscribe_gql, mock_migration_dispatcher,
    ):
        """An already-finished task simply ends the stream instead of erroring."""
        results = await subscribe_gql(MIGRATION_PROGRESS_SUBSCRIPTION, {
            "input": {"taskId": TASK_ID}
        })
        assert results == []
        mock_migration_dispatcher.submit.assert_not_awaited()


class TestProgressFrameMapping:
    """The GraphQL layer keeps the byte-named fields the frontend already queries, even
    though the task template reports progress in generic units."""

    def test_generic_frame_maps_onto_the_published_byte_fields(self):
        frame = ProgressFrame(
            task_id="tid", status="PROCESSING", current=50, total=100, message="Copying",
        )

        published = MigrationProgressStatus.from_service(frame)

        assert published.bytes_transferred == 50
        assert published.total_bytes == 100
        assert published.progress_percentage == 50.0
        assert published.message == "Copying"

    def test_mapping_uses_the_frames_derived_percentage(self):
        """Percentage is computed once, on the frame, not recomputed per transport."""
        frame = ProgressFrame(task_id="tid", status="PROCESSING", current=1, total=3)

        assert MigrationProgressStatus.from_service(frame).progress_percentage == 33.3


class TestMigrationRetrySubscription:
    async def test_migration_retry_streams_events(
        self, subscribe_gql, mock_progress_bus,
    ):
        mock_progress_bus.observe.side_effect = (
            lambda *a, **kw: _mock_progress_gen(*_events())
        )

        results = await subscribe_gql(MIGRATION_RETRY_SUBSCRIPTION, {
            "input": {"taskId": TASK_ID}
        })
        assert len(results) == 2
        assert_no_errors(results[0])

        last = results[1].data["migrationRetrySubscription"]
        assert last["status"] == "COMPLETED"

    async def test_retry_resets_the_task_before_handing_it_to_the_worker_queue(
        self, subscribe_gql, mock_migration_service, mock_migration_dispatcher,
        mock_progress_bus,
    ):
        calls: list[str] = []
        mock_migration_service.prepare_retry.side_effect = (
            lambda task_id: calls.append("prepare_retry")
        )
        mock_migration_dispatcher.submit.side_effect = lambda task_id: calls.append("submit")
        mock_progress_bus.observe.side_effect = (
            lambda *a, **kw: _mock_progress_gen(*_events())
        )

        await subscribe_gql(MIGRATION_RETRY_SUBSCRIPTION, {"input": {"taskId": TASK_ID}})

        mock_migration_service.prepare_retry.assert_awaited_once_with(TASK_ID)
        mock_migration_dispatcher.submit.assert_awaited_once_with(TASK_ID)
        # The worker reads the resume point off the document, so it must be stored first.
        assert calls == ["prepare_retry", "submit"]
