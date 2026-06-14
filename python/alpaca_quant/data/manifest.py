"""Validated data quality declarations for research datasets."""

from datetime import date
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator


class DataDeclaration(BaseModel):
    """Data quality metadata required for every research dataset."""

    model_config = ConfigDict(extra="forbid")

    data_declaration_id: str
    tier: Literal[0, 1, 2]
    universe_source: str
    universe_id: str
    survivorship_bias_status: Literal["unknown", "partial", "controlled"]
    corporate_actions_status: Literal["none", "partial", "clean"]
    pit_status: Literal["none", "best_effort", "guaranteed"]
    data_feed: Literal["iex", "sip-historical", "sip-realtime"]
    date_range: tuple[date, date]
    known_gaps: list[str]

    @model_validator(mode="after")
    def validate_quality_gates(self) -> "DataDeclaration":
        start_date, end_date = self.date_range
        if end_date < start_date:
            raise ValueError("date_range end date must be on or after start date")

        if self.tier == 2:
            if self.survivorship_bias_status != "controlled":
                raise ValueError("Tier 2 requires controlled survivorship bias")
            if self.pit_status != "guaranteed":
                raise ValueError("Tier 2 requires guaranteed point-in-time data")

        return self

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible manifest mapping."""
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        """Serialize the declaration as a YAML manifest."""
        return yaml.safe_dump(
            {"data_declaration": self.to_dict()},
            sort_keys=False,
            allow_unicode=True,
        )
