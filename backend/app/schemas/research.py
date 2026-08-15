"""Validation models for persisted Agent-run feedback."""

from typing import Literal

from pydantic import BaseModel


NegativeFeedbackReason = Literal[
    "incorrect",
    "missing_evidence",
    "too_slow",
    "over_complicated",
]


class RunFeedbackUpdate(BaseModel):
    rating: Literal["positive", "negative"]
    reason: NegativeFeedbackReason | None = None
