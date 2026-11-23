"""Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geo: str = Field(min_length=2, max_length=2)
    offer_id: int = Field(gt=0)


class StreamRead(BaseModel):
    id: int
    keitaro_stream_id: int
    kind: str
    offer_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class CampaignRead(BaseModel):
    id: int
    keitaro_id: int
    name: str
    geo: str
    offer_id: int
    created_at: datetime
    streams: list[StreamRead] = []

    model_config = ConfigDict(from_attributes=True)


class OfferAdd(BaseModel):
    offer_id: int = Field(gt=0)
