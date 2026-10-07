"""OccupancyService — authoritative check-in / check-out.

`occupied` is a business state backed by an occupancies row, not a UI flag:

    check-in:  resource=available → occupancy row → transition →occupied
    check-out: open occupancy closed → cleaning task generated →
               transition →cleaning  (spec §3 — NO available gap)

Both run inside the caller's transaction; the resource row is locked
SELECT FOR UPDATE so two check-ins can't race the same unit.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.resource_events import (
    SRC_OCCUPANCY_CHECKIN,
    SRC_OCCUPANCY_CHECKOUT,
)
from app.models.occupancy import Occupancy
from app.models.property import Property
from app.models.structure import Bed, Dorm, Room
from app.models.user import User
from app.services.resource_state import ResourceStateService
from app.services.structure import (
    ConflictErr,
    NotFoundErr,
    StructureService,
    ValidationErr,
)


class OccupancyService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.structure = StructureService(session)
        self.state = ResourceStateService(session)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _lock_room(self, user: User, room_id: uuid.UUID) -> Room:
        await self.session.flush()
        res = await self.session.execute(
            select(Room).where(Room.id == room_id).with_for_update()
        )
        room = res.scalar_one_or_none()
        if room is None:
            raise NotFoundErr("Room not found.")
        await self.structure._property_for_write(user, room.property_id)
        return room

    async def _lock_bed(
        self, user: User, bed_id: uuid.UUID
    ) -> tuple[Bed, Dorm]:
        await self.session.flush()
        res = await self.session.execute(
            select(Bed).where(Bed.id == bed_id).with_for_update()
        )
        bed = res.scalar_one_or_none()
        if bed is None:
            raise NotFoundErr("Bed not found.")
        dorm = await self.session.get(Dorm, bed.dorm_id)
        if dorm is None:
            raise NotFoundErr("Dorm not found.")
        await self.structure._property_for_write(user, dorm.property_id)
        return bed, dorm

    async def open_occupancy(
        self, *, room_id=None, bed_id=None
    ) -> Occupancy | None:
        cond = (
            Occupancy.room_id == room_id if room_id
            else Occupancy.bed_id == bed_id
        )
        res = await self.session.execute(
            select(Occupancy).where(cond, Occupancy.checked_out_at.is_(None))
        )
        return res.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Check-in
    # ------------------------------------------------------------------

    async def check_in_room(
        self, user: User, room_id: uuid.UUID, guest_name: str | None
    ) -> Room:
        name = (guest_name or "").strip() or None
        room = await self._lock_room(user, room_id)
        if room.status == "occupied" or await self.open_occupancy(
            room_id=room.id
        ):
            raise ConflictErr("Room already has an active occupant.")
        if room.status != "available":
            raise ConflictErr(
                f"Room {room.room_number} is {room.status} — only an "
                "available room can be checked in."
            )
        occ = Occupancy(
            property_id=room.property_id, room_id=room.id,
            guest_name=name, checked_in_by=user.id,
            checked_in_at=datetime.now(timezone.utc),
        )
        self.session.add(occ)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            raise ConflictErr("Room already has an active occupant.")
        await self.state.transition(
            "room", room.id, "occupied", user=user,
            source=SRC_OCCUPANCY_CHECKIN, occupancy_id=occ.id,
        )
        room.current_guest = occ.guest_name  # display mirror — not authoritative
        await self.session.commit()
        return room

    async def check_in_bed(
        self, user: User, bed_id: uuid.UUID, guest_name: str | None
    ) -> Dorm:
        name = (guest_name or "").strip() or None
        bed, dorm = await self._lock_bed(user, bed_id)
        if dorm is not None and not dorm.is_active:
            raise ConflictErr(
                f"Dorm {dorm.name} is deactivated — its beds cannot be "
                "checked into."
            )
        if bed.status == "occupied" or await self.open_occupancy(bed_id=bed.id):
            raise ConflictErr("Bed already has an active occupant.")
        if bed.status != "available":
            raise ConflictErr(
                f"Bed {bed.bed_number} is {bed.status} — only an "
                "available bed can be checked in."
            )
        occ = Occupancy(
            property_id=dorm.property_id, bed_id=bed.id,
            guest_name=name, checked_in_by=user.id,
            checked_in_at=datetime.now(timezone.utc),
        )
        self.session.add(occ)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            raise ConflictErr("Bed already has an active occupant.")
        await self.state.transition(
            "bed", bed.id, "occupied", user=user,
            source=SRC_OCCUPANCY_CHECKIN, occupancy_id=occ.id,
        )
        bed.guest_name = occ.guest_name
        # dorm aggregates its beds — first guest flips it to occupied
        if dorm.status == "available":
            try:
                await self.state.transition(
                    "dorm", dorm.id, "occupied", user=user,
                    source=SRC_OCCUPANCY_CHECKIN, occupancy_id=occ.id,
                )
            except (ConflictErr, ValidationErr):
                pass
        await self.session.commit()
        return await self.structure._reload_dorm(bed.dorm_id)

    # ------------------------------------------------------------------
    # Check-out — occupied → cleaning atomically (spec §3/§9)
    #
    # ONE checkout pipeline for every entry point (single room, single bed,
    # whole dorm, bulk action):
    #   1. lock resources + open occupancies (FOR UPDATE — serializes
    #      against maintenance close / admin release races)
    #   2. close occupancy rows
    #   3. create the checkout-cleaning task BEFORE the state flip — a
    #      cleaning resource always has an identifiable operational reason
    #   4. commit OCCUPIED → CLEANING via the state engine
    #   5. clear the guest mirror
    #   6. re-derive affected dorm aggregates
    #
    # The resource never passes through "available" — a checked-out dirty
    # unit cannot be reoccupied. No commit here; the caller owns the txn.
    # ------------------------------------------------------------------

    async def _open_occupancy_map(
        self, *, rooms: list[Room], beds: list[Bed]
    ) -> dict[str, dict[uuid.UUID, Occupancy]]:
        """Batch-load (and lock) the open occupancy rows for a set of
        rooms/beds — one query instead of one per unit."""
        room_ids = [r.id for r in rooms]
        bed_ids = [b.id for b in beds]
        out: dict[str, dict[uuid.UUID, Occupancy]] = {"room": {}, "bed": {}}
        if not room_ids and not bed_ids:
            return out
        conds = []
        if room_ids:
            conds.append(Occupancy.room_id.in_(room_ids))
        if bed_ids:
            conds.append(Occupancy.bed_id.in_(bed_ids))
        res = await self.session.execute(
            select(Occupancy).where(
                or_(*conds), Occupancy.checked_out_at.is_(None)
            ).with_for_update()
        )
        for occ in res.scalars():
            if occ.room_id:
                out["room"][occ.room_id] = occ
            if occ.bed_id:
                out["bed"][occ.bed_id] = occ
        return out

    async def checkout_units(
        self,
        user: User,
        prop: Property,
        *,
        rooms: list[Room] | None = None,
        beds: list[Bed] | None = None,
        create_cleaning_task: bool = True,
        reason: str = "Checkout — cleaning required",
    ) -> dict:
        """The unified checkout pipeline. Every checkout entry point
        (room endpoint, bed endpoint, dorm endpoint, bulk action) funnels
        here so occupancy-close → task-spawn → transition can never
        diverge. Caller owns the commit.

        A unit is checked out when it has an OPEN OCCUPANCY or still
        projects `occupied` — the record is the truth, the projection is
        repaired along the way.
        """
        rooms = list(rooms or [])
        beds = list(beds or [])
        occs = await self._open_occupancy_map(rooms=rooms, beds=beds)
        now = datetime.now(timezone.utc)

        out_rooms = [
            r for r in rooms
            if occs["room"].get(r.id) is not None or r.status == "occupied"
        ]
        out_beds = [
            b for b in beds
            if occs["bed"].get(b.id) is not None or b.status == "occupied"
        ]
        generated = []
        dorm_ids: set[uuid.UUID] = set()
        if not out_rooms and not out_beds:
            return {
                "rooms": [], "beds": [], "generated": [],
                "dorm_ids": dorm_ids,
            }

        # 1-2. close every open occupancy on the checked-out units
        for r in out_rooms:
            occ = occs["room"].get(r.id)
            if occ is not None:
                occ.checked_out_at = now
                occ.checked_out_by = user.id
        for b in out_beds:
            occ = occs["bed"].get(b.id)
            if occ is not None:
                occ.checked_out_at = now
                occ.checked_out_by = user.id

        # 3. checkout-cleaning work exists BEFORE the state flips
        if create_cleaning_task:
            generated = await self.structure._generate_cleaning_tasks(
                user, prop, "checkout", out_rooms, out_beds
            )

        # 4-5. commit the transitions — audited occupancy_checkout events
        for r in out_rooms:
            occ = occs["room"].get(r.id)
            if r.status == "occupied":
                await self.state.transition(
                    "room", r.id, "cleaning", user=user,
                    source=SRC_OCCUPANCY_CHECKOUT,
                    occupancy_id=occ.id if occ else None,
                    reason=reason,
                )
            else:
                # drifted projection (e.g. 'available' with an open
                # occupancy) — re-resolve canonically after the close
                await self.state.derive(
                    "room", r.id, release_to="available", user=user,
                    source=SRC_OCCUPANCY_CHECKOUT, reason=reason,
                )
            r.current_guest = None
        for b in out_beds:
            occ = occs["bed"].get(b.id)
            if b.status == "occupied":
                await self.state.transition(
                    "bed", b.id, "cleaning", user=user,
                    source=SRC_OCCUPANCY_CHECKOUT,
                    occupancy_id=occ.id if occ else None,
                    reason=reason,
                )
            else:
                await self.state.derive(
                    "bed", b.id, release_to="available", user=user,
                    source=SRC_OCCUPANCY_CHECKOUT, reason=reason,
                )
            b.guest_name = None
            dorm_ids.add(b.dorm_id)

        # 6. dorms aggregate their beds — recompute each affected dorm;
        # last checkout releases it to cleaning, remaining occupied beds
        # keep it occupied
        for dorm_id in dorm_ids:
            await self.state.derive(
                "dorm", dorm_id, release_to="cleaning", user=user,
                source=SRC_OCCUPANCY_CHECKOUT,
                reason="Checkout — aggregate recompute",
            )
        return {
            "rooms": out_rooms, "beds": out_beds,
            "generated": generated, "dorm_ids": dorm_ids,
        }

    async def check_out_room(self, user: User, room_id: uuid.UUID) -> dict:
        room = await self._lock_room(user, room_id)
        occ = await self.open_occupancy(room_id=room.id)
        if occ is None and room.status != "occupied":
            raise ConflictErr("Room has no active occupant to check out.")
        prop = await self.session.get(Property, room.property_id)
        res = {"rooms": [], "beds": [], "generated": [], "dorm_ids": set()}
        if prop:
            res = await self.checkout_units(user, prop, rooms=[room])
            await self.structure._fire_automation(
                user, room.property_id, "room_checked_out", room.zone_id
            )
        await self.session.commit()
        return {"room": room, "generated": res["generated"]}

    async def check_out_bed(self, user: User, bed_id: uuid.UUID) -> dict:
        bed, dorm = await self._lock_bed(user, bed_id)
        occ = await self.open_occupancy(bed_id=bed.id)
        if occ is None and bed.status != "occupied":
            raise ConflictErr("Bed has no active occupant to check out.")
        prop = await self.session.get(Property, dorm.property_id)
        res = {"generated": []}
        if prop:
            res = await self.checkout_units(user, prop, beds=[bed])
            await self.structure._fire_automation(
                user, prop.id, "bed_available_after_checkout", dorm.zone_id
            )
        await self.session.commit()
        dorm = await self.structure._reload_dorm(bed.dorm_id)
        return {"dorm": dorm, "generated": res["generated"]}
