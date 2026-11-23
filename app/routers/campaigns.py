"""Campaigns API router."""

import logging
import re
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.keitaro import KeitaroAPIError, KeitaroClient, KeitaroSettings, get_keitaro_client
from app.models import Campaign, Stream
from app.schemas import CampaignCreate, CampaignRead, OfferAdd

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _build_alias(name: str) -> str:
    """Build a unique campaign alias: lowercase, spaces -> '-', keep [a-z0-9-], max 50 chars, random suffix."""
    alias = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    alias = alias[:50].rstrip("-")
    return f"{alias}-{secrets.token_hex(3)}"


async def _get_campaign_or_404(db: AsyncSession, campaign_id: int) -> Campaign:
    result = await db.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(selectinload(Campaign.streams))
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


async def _rollback_keitaro_campaign(keitaro: KeitaroClient, campaign_id: int | None) -> None:
    """Best-effort cleanup of a created Keitaro campaign on failure."""
    if campaign_id is None:
        return
    if KeitaroSettings().use_keitaro_mock:
        print(f"[MOCK] rollback campaign {campaign_id} (no-op)")
        return
    try:
        # KeitaroClient has no delete_campaign method, so we go through the raw client.
        response = await keitaro._client.delete(f"/campaigns/{campaign_id}")
        response.raise_for_status()
    except Exception:
        logger.warning("Best-effort rollback failed to delete Keitaro campaign %s", campaign_id, exc_info=True)


@router.post("", status_code=201)
async def create_campaign(
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    keitaro: KeitaroClient = Depends(get_keitaro_client),
) -> CampaignRead:
    alias = _build_alias(payload.name)

    campaign_id: int | None = None
    try:
        campaign_response = await keitaro.create_campaign(
            {
                "alias": alias,
                "name": payload.name,
                "domain_id": 1,
                "group_id": "1",
                "traffic_source_id": 1,
            }
        )
        campaign_id = int(campaign_response["id"])

        google_response = await keitaro.create_stream(
            {
                "campaign_id": campaign_id,
                "type": "forced",
                "name": "Geo Redirect to Google",
                "action_type": "redirect",
                "schema": "redirect",
                "action_options": {"url": "https://www.google.com"},
                # payload is an array even if geo has a single value
                "filters": [{"name": "geo", "mode": "accept", "payload": [payload.geo]}],
            }
        )
        google_stream_id = int(google_response["id"])

        offer_response = await keitaro.create_stream(
            {
                "campaign_id": campaign_id,
                "type": "regular",
                "name": "Offer Stream",
                "action_type": "offers",
                "schema": "offers",
                "weight": 100,
                "filters": [],
                "offers": [{"offer_id": payload.offer_id, "share": 100, "state": "active"}],
            }
        )
        offer_stream_id = int(offer_response["id"])

        campaign = Campaign(
            keitaro_id=campaign_id,
            name=payload.name,
            geo=payload.geo,
            offer_id=payload.offer_id,
        )
        campaign.created_at = datetime.now(timezone.utc)
        db.add(campaign)
        await db.flush()

        db.add(
            Stream(
                campaign_id=campaign.id,
                keitaro_stream_id=google_stream_id,
                kind="google",
                offer_id=None,
            )
        )
        db.add(
            Stream(
                campaign_id=campaign.id,
                keitaro_stream_id=offer_stream_id,
                kind="offer",
                offer_id=payload.offer_id,
            )
        )
        await db.flush()

        result = await db.execute(
            select(Campaign)
            .where(Campaign.id == campaign.id)
            .options(selectinload(Campaign.streams))
        )
        saved = result.scalar_one_or_none()
    except KeitaroAPIError as e:
        await _rollback_keitaro_campaign(keitaro, campaign_id)
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Keitaro error: {e.status_code} {e.response_body}") from e
    except Exception:
        await _rollback_keitaro_campaign(keitaro, campaign_id)
        await db.rollback()
        raise

    return CampaignRead.model_validate(saved, from_attributes=True)


@router.get("", response_model=list[CampaignRead])
async def list_campaigns(db: AsyncSession = Depends(get_db)) -> list[CampaignRead]:
    result = await db.execute(
        select(Campaign)
        .options(selectinload(Campaign.streams))
        .order_by(Campaign.created_at.desc())
    )
    campaigns = result.scalars().all()
    return [CampaignRead.model_validate(c, from_attributes=True) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignRead)
async def get_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)) -> CampaignRead:
    campaign = await _get_campaign_or_404(db, campaign_id)
    return CampaignRead.model_validate(campaign, from_attributes=True)


@router.post("/{campaign_id}/offers", status_code=201)
async def add_offer(
    campaign_id: int,
    payload: OfferAdd,
    db: AsyncSession = Depends(get_db),
    keitaro: KeitaroClient = Depends(get_keitaro_client),
) -> CampaignRead:
    campaign = await _get_campaign_or_404(db, campaign_id)

    try:
        stream_response = await keitaro.create_stream(
            {
                "campaign_id": campaign.keitaro_id,
                "type": "regular",
                "name": f"Offer Stream {payload.offer_id}",
                "action_type": "offers",
                "schema": "offers",
                "weight": 100,
                "filters": [],
                "offers": [{"offer_id": payload.offer_id, "share": 100, "state": "active"}],
            }
        )
    except KeitaroAPIError as e:
        raise HTTPException(status_code=502, detail=f"Keitaro error: {e.status_code} {e.response_body}") from e

    stream_id = int(stream_response["id"])
    db.add(
        Stream(
            campaign_id=campaign.id,
            keitaro_stream_id=stream_id,
            kind="offer",
            offer_id=payload.offer_id,
        )
    )
    await db.flush()

    result = await db.execute(
        select(Campaign)
        .where(Campaign.id == campaign.id)
        .options(selectinload(Campaign.streams))
    )
    return CampaignRead.model_validate(result.scalar_one_or_none(), from_attributes=True)


@router.delete("/{campaign_id}/offers/{stream_id}", response_model=CampaignRead)
async def delete_offer(
    campaign_id: int,
    stream_id: int,
    db: AsyncSession = Depends(get_db),
    keitaro: KeitaroClient = Depends(get_keitaro_client),
) -> CampaignRead:
    campaign = await _get_campaign_or_404(db, campaign_id)

    stream = (
        await db.execute(
            select(Stream).where(Stream.id == stream_id, Stream.campaign_id == campaign.id)
        )
    ).scalar_one_or_none()
    if stream is None:
        raise HTTPException(status_code=404, detail="Stream not found")
    if stream.kind != "offer":
        raise HTTPException(status_code=400, detail="Cannot delete google stream via this endpoint")

    try:
        await keitaro.delete_stream(stream.keitaro_stream_id)
    except KeitaroAPIError as e:
        raise HTTPException(status_code=502, detail=f"Keitaro error: {e.status_code} {e.response_body}") from e

    await db.delete(stream)
    await db.flush()

    result = await db.execute(
        select(Campaign)
        .where(Campaign.id == campaign.id)
        .options(selectinload(Campaign.streams))
    )
    return CampaignRead.model_validate(result.scalar_one_or_none(), from_attributes=True)
