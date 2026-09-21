"""
Behaviour of the generic progress frame the task template emits.

The frame is what a running task reports and what every observer receives, so it has to
describe progress without assuming the work is a byte transfer.
"""

import dataclasses

import pytest

from src.platform.jobs.progress import ProgressFrame

pytestmark = pytest.mark.unit


def test_frame_reports_progress_in_a_declared_unit():
    """A byte copy, a transcode and a scan all report through the same shape."""
    frame = ProgressFrame(
        task_id="tid", status="PROCESSING", current=30, total=120, unit="frames"
    )

    assert frame.current == 30
    assert frame.total == 120
    assert frame.unit == "frames"


def test_unit_defaults_to_bytes():
    """Byte transfer is the common case, so callers need not spell it out."""
    frame = ProgressFrame(task_id="tid", status="PROCESSING", current=1, total=2)

    assert frame.unit == "bytes"


def test_percentage_is_derived_from_current_and_total():
    frame = ProgressFrame(task_id="tid", status="PROCESSING", current=50, total=200)

    assert frame.percentage == 25.0


def test_percentage_is_rounded_to_one_decimal():
    frame = ProgressFrame(task_id="tid", status="PROCESSING", current=1, total=3)

    assert frame.percentage == 33.3


def test_percentage_is_zero_when_total_is_not_measurable():
    """A task with no measurable total reports 0% rather than dividing by zero."""
    frame = ProgressFrame(task_id="tid", status="UPDATING_DB", current=0, total=0)

    assert frame.percentage == 0.0


def test_frame_is_immutable():
    """One frame is broadcast to every observer of a task; no observer may mutate it."""
    frame = ProgressFrame(task_id="tid", status="PROCESSING", current=1, total=2)

    with pytest.raises(dataclasses.FrozenInstanceError):
        frame.current = 99


def test_message_is_optional():
    frame = ProgressFrame(task_id="tid", status="PROCESSING", current=1, total=2)

    assert frame.message is None
