from itertools import combinations
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.modules.notification.events import EVENT_SCHEMAS
from app.modules.notification.worker import drain_outbox
from app.modules.social.feed.schemas import PostUpdateRequest
from tests.vt034.pairwise import CASES, FACTORS


def test_tc01_pairwise_independent_pair_audit():
    # Independent oracle: enumerate factor/value pairs, not generator's pairs().
    levels = list(FACTORS.values())
    for i, j in combinations(range(len(levels)), 2):
        for left in levels[i]:
            for right in levels[j]:
                assert any(row[i] == left and row[j] == right for row in CASES)
    assert len(CASES) < 36


@pytest.mark.parametrize("body", ["", " \n\t", "x" * 10001])
def test_tc02_invalid_body(body):
    with pytest.raises(ValidationError):
        PostUpdateRequest(body=body)


@pytest.mark.parametrize("body", ["x", "đ" * 10000])
def test_tc03_exact_body_boundaries(body):
    assert PostUpdateRequest(body=body).body == body


def test_tc04_update_event_is_consumable():
    assert "SOCIAL_POST_UPDATED" in EVENT_SCHEMAS


@pytest.mark.parametrize("size", [0, -1, 1001, 1000000, 1.5, True])
def test_tc05_invalid_batch_rejected_before_database(size):
    factory = MagicMock(side_effect=AssertionError("must not open database"))
    with pytest.raises(ValueError):
        drain_outbox(session_factory=factory, batch_size=size)
    factory.assert_not_called()


@pytest.mark.parametrize("size", [1, 1000])
def test_tc06_batch_accepts_inclusive_boundary(size):
    factory = MagicMock()
    factory.return_value.__enter__.return_value.scalar.return_value = None
    assert drain_outbox(session_factory=factory, batch_size=size) == 0
    factory.assert_called_once()
