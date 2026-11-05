"""Queue semantics must distinguish an AI answer from an unresolved input."""
import pytest

from backend.app.review_queue import classify_review


@pytest.mark.parametrize("entry", [
    {"type": "ai_interpretation", "value": 0, "method": "ai_verified", "state": "known"},
    {"type": "ai_interpretation", "value": [], "method": "ai_verified_after_retry", "state": "known"},
    {"type": "name_mapping", "value": "kind_of", "status": "pending_approval"},
    {"type": "ai_interpretation", "id": "design:D-014/part", "value": None},
    {"type": "correction", "value": "Corrected title"},
])
def test_available_ai_answers_need_oversight(entry):
    assert classify_review(entry)[0] == "human_review"


@pytest.mark.parametrize("entry", [
    {"type": "template", "value": None},
    {"type": "link", "value": []},
    {"type": "weight"},
    {"type": "ai_interpretation", "state": "unknown", "value": None},
    {"type": "ai_interpretation", "state": "options", "options": [3, 6], "method": "ai_verified"},
    {"type": "possible_reading", "selected": None},
    {"type": "name_mapping", "value": None},
    {"type": "ai_interpretation", "id": "design:D-015/part", "input_reason": "Geometry is incomplete"},
])
def test_pipeline_gaps_need_intervention(entry):
    queue, reason = classify_review(entry)
    assert queue == "human_input" and reason


@pytest.mark.parametrize("status", ["accepted", "rejected", "human_confirmed", "human_rejected", "approved", "reviewed"])
def test_recorded_human_decisions_leave_both_open_queues(status):
    assert classify_review({"type": "template", "status": status})[0] == "resolved"
