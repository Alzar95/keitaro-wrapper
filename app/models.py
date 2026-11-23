"""SQLAlchemy ORM models."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    keitaro_id: Mapped[int] = mapped_column(unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geo: Mapped[str] = mapped_column(String(2), nullable=False)
    offer_id: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    keitaro_stream_id: Mapped[int] = mapped_column(unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # "google" | "offer"
    offer_id: Mapped[int | None] = mapped_column(nullable=True)  # only for kind="offer"

    campaign: Mapped["Campaign"] = relationship(back_populates="streams")
