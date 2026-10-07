"""Structural entities — Area (floor level), Zone, Room, Dorm, Bed, Washroom."""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class Area(Base):
    """A structural level within a property (e.g. Ground Floor, Rooftop)."""

    __tablename__ = "areas"
    __table_args__ = (
        UniqueConstraint("property_id", "name", name="uq_areas_property_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. AREA-001
    level_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    zones: Mapped[list["Zone"]] = relationship(
        back_populates="area", cascade="all, delete-orphan"
    )


class Zone(Base):
    """A functional zone — only 'stay' zones may contain rooms/dorms/beds."""

    __tablename__ = "zones"
    __table_args__ = (
        UniqueConstraint("property_id", "name", name="uq_zones_property_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("areas.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. ZONE-001
    zone_type: Mapped[str] = mapped_column(String(32), nullable=False, default="stay")
    floor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    area: Mapped[Area | None] = relationship(back_populates="zones")
    rooms: Mapped[list["Room"]] = relationship(cascade="all, delete-orphan")
    dorms: Mapped[list["Dorm"]] = relationship(cascade="all, delete-orphan")
    washrooms: Mapped[list["Washroom"]] = relationship(cascade="all, delete-orphan")


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("property_id", "room_number", name="uq_rooms_property_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="CASCADE"), nullable=True, index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("areas.id", ondelete="CASCADE"), nullable=True, index=True
    )
    room_number: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, default="Private Room")
    area_sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # available | occupied | cleaning | maintenance
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    bed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cleaning_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    current_guest: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Dorm(Base):
    __tablename__ = "dorms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="CASCADE"), nullable=True, index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("areas.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dorm_type: Mapped[str] = mapped_column(String(32), nullable=False, default="Mixed Dorm")
    washroom: Mapped[str] = mapped_column(String(32), nullable=False, default="Attached")
    floor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    area_sqft: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Operational status: available | occupied | cleaning | maintenance.
    # Lifecycle enable/disable lives on is_active — NOT this column.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    beds: Mapped[list["Bed"]] = relationship(
        back_populates="dorm", cascade="all, delete-orphan", order_by="Bed.bed_number"
    )
    washrooms: Mapped[list["Washroom"]] = relationship(
        back_populates="dorm", order_by="Washroom.name"
    )


class Washroom(Base):
    """A physical washroom resource.

    dorm_id set → an attached washroom owned by one specific dorm
    (each dorm's configuration is independent). dorm_id NULL → a
    zone-level/common facility shared by the zone.
    """

    __tablename__ = "washrooms"
    __table_args__ = (
        UniqueConstraint("property_id", "name", name="uq_washrooms_property_name"),
        # one attached washroom per dorm (NULLs are distinct →
        # unlimited zone-level facilities allowed)
        UniqueConstraint("dorm_id", name="uq_washrooms_dorm_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zones.id", ondelete="CASCADE"), nullable=True, index=True
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("areas.id", ondelete="CASCADE"), nullable=True, index=True
    )
    dorm_id: Mapped[uuid.UUID | None] = mapped_column(
        # an attached washroom is dorm-owned — it dies with the dorm
        Uuid, ForeignKey("dorms.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    washroom_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # canonical: available | cleaning | maintenance | inactive
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    dorm: Mapped["Dorm | None"] = relationship(back_populates="washrooms")
    fixtures: Mapped[list["WashroomFixture"]] = relationship(
        back_populates="washroom",
        cascade="all, delete-orphan",
        order_by="WashroomFixture.fixture_type, WashroomFixture.fixture_number",
    )


class WashroomFixture(Base):
    """An individual facility object inside a washroom — real row per
    fixture, carrying its own condition status and service timestamps.

    fixture_type is 'shower' | 'stall' | 'urinal' | 'sink' | 'mirror' or a
    free-form custom label ("Hand Dryer"). fixture_number combines with the
    type for display labels like "Stall 02".
    """

    __tablename__ = "washroom_fixtures"
    __table_args__ = (
        UniqueConstraint(
            "washroom_id", "fixture_type", "fixture_number",
            name="uq_washroom_fixtures_type_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    washroom_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("washrooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fixture_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fixture_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # canonical: operational | maintenance | inactive
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="operational")
    last_cleaned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_maintenance_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    washroom: Mapped["Washroom"] = relationship(back_populates="fixtures")


class Bed(Base):
    __tablename__ = "beds"
    __table_args__ = (
        UniqueConstraint("dorm_id", "bed_number", name="uq_beds_dorm_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dorm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dorms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("properties.id", ondelete="CASCADE"), nullable=True, index=True
    )
    bed_number: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "Bed 01"
    # available | occupied | cleaning | maintenance | inactive
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    guest_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    dorm: Mapped[Dorm] = relationship(back_populates="beds")
