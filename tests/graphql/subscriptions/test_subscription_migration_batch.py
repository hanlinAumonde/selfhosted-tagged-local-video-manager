"""The batch progress subscription: a pure observer of the batch's children."""

import pytest

from src.features.migration.migration_batch import BatchSummary
from src.platform.jobs.progress import ProgressFrame
from src.platform.jobs.progress_bus import BatchEvent
from tests.graphql.helpers import MIGRATION_BATCH_PROGRESS, assert_no_errors

pytestmark = pytest.mark.subscription

BATCH_ID = "65f000000000000000000b01"


def _summary(active: int, completed: int) -> BatchSummary:
    return BatchSummary(
        batch_id=BATCH_ID, total=2, active=active, completed=completed, failed=0, cancelled=0
    )


class TestMigrationBatchProgress:
    async def test_relays_the_summary_and_the_child_frames(
        self, subscribe_gql, mock_progress_bus, mock_migration_batch_service,
    ):
        """
        Scenario: the subscription republishes what the bus observes
          Given a progress bus that, for batch "B", yields an opening summary of 2 active
            children, then a PROCESSING frame for "t1" at 50 of 100 bytes, then a COMPLETED
            frame for "t1" with a summary of 1 completed and 1 active
          When migrationBatchProgress is subscribed for "B"
          Then three events are received
          And the first carries the summary and a null task
          And the second carries task "t1" with bytesTransferred "50" and a null summary
          And the third carries task "t1" COMPLETED and the fresh summary
        """
        observed: list[str] = []

        async def observe_batch(batch_id, summarize, is_settled):
            observed.append(batch_id)
            yield BatchEvent(summary=_summary(active=2, completed=0))
            yield BatchEvent(frame=ProgressFrame(task_id="t1", status="PROCESSING", current=50, total=100))
            yield BatchEvent(
                summary=_summary(active=1, completed=1),
                frame=ProgressFrame(task_id="t1", status="COMPLETED", current=100, total=100),
            )

        mock_progress_bus.observe_batch.side_effect = observe_batch

        events = await subscribe_gql(MIGRATION_BATCH_PROGRESS, {"input": {"batchId": BATCH_ID}})

        for event in events:
            assert_no_errors(event)
        payloads = [e.data["migrationBatchProgress"] for e in events]
        assert observed == [BATCH_ID]
        assert len(payloads) == 3
        assert payloads[0]["summary"]["active"] == 2 and payloads[0]["task"] is None
        assert payloads[1]["summary"] is None
        assert (payloads[1]["task"]["taskId"], payloads[1]["task"]["bytesTransferred"]) == ("t1", "50")
        assert payloads[2]["task"]["status"] == "COMPLETED"
        assert (payloads[2]["summary"]["completed"], payloads[2]["summary"]["active"]) == (1, 1)
