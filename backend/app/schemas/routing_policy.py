"""Validation models for versioned complexity routing policy updates."""

from pydantic import BaseModel, Field, model_validator


class RoutingPolicyCreate(BaseModel):
    standard_min_score: int = Field(ge=1, le=9)
    expert_min_score: int = Field(ge=2, le=10)
    expected_active_version: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_threshold_order(self):
        if self.standard_min_score >= self.expert_min_score:
            raise ValueError("standard_min_score must be lower than expert_min_score")
        return self


class RoutingPolicyRollback(BaseModel):
    expected_active_version: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=512)
