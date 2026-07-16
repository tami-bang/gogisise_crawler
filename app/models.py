"""Crawler-to-backend data contract.

This module is the single source of truth for payloads sent to the NestJS
internal ingestion endpoint. Source API values are normalized in scraper.py;
only normalized values are accepted here.
"""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


KST_OFFSET = timedelta(hours=9)


class ContractModel(BaseModel):
    """Reject undeclared fields so an upstream schema change is visible."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RawRecord(ContractModel):
    """One validated Geumcheon product record sent to the backend."""

    sourceName: Literal["GEUMCHEON"] = "GEUMCHEON"
    collectedAt: datetime
    rawProductName: str = Field(min_length=1, max_length=500)
    species: Literal["BEEF", "PORK"]
    gender: Literal["암소"] | None = None
    storageType: Literal["CHILLED", "FROZEN"]
    category: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    qualityGrade: Literal["1++", "1+", "1", "2", "3", "등외"] | None = None
    yieldGrade: Literal["A", "B"] | None = None
    ageMonths: int | None = Field(default=None, ge=1, le=240)
    pricePerKg: int = Field(gt=0, strict=True)

    @field_validator("collectedAt")
    @classmethod
    def require_kst_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collectedAt must include a timezone offset")
        if value.utcoffset() != KST_OFFSET:
            raise ValueError("collectedAt must use the +09:00 KST offset")
        return value

    @model_validator(mode="after")
    def validate_species_age(self) -> "RawRecord":
        if self.species == "PORK" and self.ageMonths is not None:
            raise ValueError("ageMonths must be null for PORK")
        return self


class BulkPayload(ContractModel):
    """POST /api/v1/internal/market/raw-records request body."""

    records: list[RawRecord] = Field(min_length=1, max_length=100)


class CrawlResult(ContractModel):
    """Observable result of one crawl job."""

    totalFetched: int = Field(default=0, ge=0)
    validRecords: int = Field(default=0, ge=0)
    skippedRecords: int = Field(default=0, ge=0)
    sentToBackend: int = Field(default=0, ge=0)
    backendInserted: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)


class ScrapeOutcome(ContractModel):
    """Internal hand-off from scraper to delivery service."""

    records: list[RawRecord] = Field(default_factory=list)
    result: CrawlResult


class CategoryMap(BaseModel):
    pork: dict = {
        "냉장": {"삼겹": "140101", "목심": "140102", "앞다리": "140103", "뒷다리": "140104", "등심": "140105", "안심": "140106", "갈비": "140107", "등갈비": "140108", "항정": "140109", "등심덧살": "140110", "갈매기": "140111"},
        "냉동": {"냉동삼겹": "140201", "냉동목심": "140202", "냉동뒷다리": "140203", "냉동앞다리": "140204", "냉동등심": "140205", "냉동갈비": "140206", "냉동등갈비": "140207", "냉동항정": "140208", "냉동사태": "140209"}
    }
    hanwoo: dict = {
        "냉장": {"안심": "130101", "등심": "130102", "채끝": "130103", "목심": "130104", "앞다리살": "130105", "부채살": "130106", "우둔": "130107", "홍두깨": "130108", "설도": "130109", "양지": "130110", "차돌박이": "130111", "치마살": "130112", "업진살": "130113", "사태": "130114", "갈비": "130115", "안창살": "130116", "토시살": "130117"},
        "냉동": {"냉동차돌박이": "130201", "냉동우족": "130202", "냉동사골": "130203", "냉동꼬리": "130204", "냉동설깃": "130205", "냉동우둔": "130206", "냉동도가니": "130207", "냉동스지": "130208", "냉동목심": "130209", "냉동갈비": "130210"}
    }
