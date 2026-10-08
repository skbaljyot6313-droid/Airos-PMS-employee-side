"""ResourceStateService — the ONLY service permitted to commit operational
resource-state transitions (spec §4).

    transition() — explicit state change: lock → validate → authorize →
                   write → immutable audit event.
    derive()     — recompute a resource's status from its active work
                   (absorbs the old OpsStatusService blocker logic). Only
                   "cleaning"/"maintenance" resources are ever released or
                   re-flagged — "occupied"/"available"/"inactive" are never
                   overridden by work derivation.
    explain()    — read-only answer to "why is this resource in this state?"

Nothing else may execute `resource.status = ...` as a business operation.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.resource_events import (
    SRC_ADMIN_OVERRIDE,
    SRC_DERIVE,
    SRC_RECONCILIATION,
)
from app.domain.resource_states import (
    BLOCKING_MAINTENANCE,
    BLOCKING_TASK,
    RELEASE_ELIGIBLE,
    STATUS_SETS,
)
from app.domain.transitions import is_legal
from app.models.maintenance import MaintenanceTicket
from app.models.occupancy import Occupancy
from app.models.resource_state_event import ResourceStateEvent
from app.models.structure import (
    Bed,
    Dorm,
    Room,
    Washroom,
    WashroomFixture,
)
from app.models.property import Property
from app.models.task import Task
from app.models.user import User, UserRole
from app.dependencies.auth import Forbidden
from app.services.structure import (
    ConflictErr,
    NotFoundErr,
    ValidationErr,
)

_MODELS = {
    "room": Room,
    "dorm": Dorm,
    "bed": Bed,
    "washroom": Washroom,
    "fixture": WashroomFixture,
}

_LABEL_ATTR = {
    "room": "room_number",
    "dorm": "name",
    "bed": "bed_number",
    "washroom": "name",
}


class ResourceStateService:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------------
    # Load + lock
    # ------------------------------------------------------------------

    async def _lock(
        self, resource_type: str, resource_id: uuid.UUID
    ):
        model = _MODELS.get(resource_type)
        if model is None:
            raise ValidationErr(
                f"Unknown resource type '{resource_type}'.",
                field="resource_type",
            )
        await self.session.flush()  # pending writes visible to the read
        res = await self.session.execute(
            select(model).where(model.id == resource_id).with_for_update()
        )
        row = res.scalar_one_or_none()
        if row is None:
            raise NotFoundErr(
                f"{resource_type.title()} not found."
            )
        return row

    async def _check_scope(self, user: User | None, row) -> None:
        """Tenant scoping for direct resource access — a resource id is
        only reachable if it belongs to the caller's company (SA) or
        property (everyone else). Mirrors StructureService._property_for_write
        — IDOR-safe: out-of-scope ids are 'not found', never 'exists'."""
        if user is None:
            return
        property_id = getattr(row, "property_id", None)
        if property_id is None and isinstance(row, Bed):
            dorm = await self.session.get(Dorm, row.dorm_id)
            property_id = dorm.property_id if dorm else None
        prop = (
            await self.session.get(Property, property_id)
            if property_id else None
        )
        if prop is None:
            raise NotFoundErr("Resource not found.")
        if user.role == UserRole.SUPER_ADMIN:
            if prop.company_id != user.company_id:
                raise NotFoundErr("Resource not found.")
        elif user.property_id != prop.id:
            raise NotFoundErr("Resource not found.")

    # ------------------------------------------------------------------
    # Explicit transition — lock, validate, authorize, write, audit
    # ------------------------------------------------------------------

    async def transition(
        self,
        resource_type: str,
        resource_id: uuid.UUID,
        to: str,
        *,
        user: User | None,
        source: str,
        reason: str | None = None,
        task_id: uuid.UUID | None = None,
        ticket_id: uuid.UUID | None = None,
        occupancy_id: uuid.UUID | None = None,
    ):
        """Commit one operational transition. Returns (row, prev, new).

        - canonical `to` enforced per resource type
        - legal transition table + source gates enforced
        - admin_override requires a staff role (super_admin /
          property_manager, scoped to their own property) + mandatory reason
        - →occupied requires an open occupancy record (invariant)
        """
        to = (to or "").strip().lower()
        allowed = STATUS_SETS.get(resource_type)
        if allowed is None:
            raise ValidationErr(
                f"Unknown resource type '{resource_type}'.",
                field="resource_type",
            )
        if to not in allowed:
            raise ValidationErr(
                f"'{to}' is not a valid {resource_type} status "
                f"({', '.join(sorted(allowed))}).",
                field="to",
            )
        row = await self._lock(resource_type, resource_id)
        prev = row.status

        await self._check_scope(user, row)

        if source == SRC_ADMIN_OVERRIDE:
            if user is None or user.role not in (
                UserRole.SUPER_ADMIN, UserRole.PROPERTY_MANAGER
            ):
                raise Forbidden(
                    "Direct resource transitions require a staff role "
                    "(Super Admin or Property Manager)."
                )
            if not (reason or "").strip():
                raise ValidationErr(
                    "An administrative transition requires a reason.",
                    field="reason",
                )
        actor_name = user.name if user else "System"

        if prev == to:
            return row, prev, to

        # Escape hatch: a legacy/dirty current state is outside the graph —
        # allow moving OUT of it (records the correction) rather than
        # trapping the resource forever.
        if prev in allowed and not is_legal(resource_type, prev, to, source):
            raise ConflictErr(
                f"Illegal {resource_type} transition: {prev} → {to} "
                f"via '{source}'."
            )

        if to == "occupied":
            # OCCUPIED is illegal without an open occupancy record.
            occ = await self._open_occupancy(row)
            if occupancy_id is None or occ is None or occ.id != occupancy_id:
                raise ConflictErr(
                    "Cannot mark occupied without an open occupancy record."
                )

        if to in ("available", "inactive") and isinstance(row, (Room, Bed)):
            # Invariant: `available`/`inactive` can never coexist with an
            # open occupancy row. An explicit transition into either state
            # performs checkout semantics — the occupancy is closed and the
            # guest mirror cleared inside the same transaction, so the
            # projection can never silently diverge from the record.
            occ = await self._open_occupancy(row, lock=True)
            if occ is not None:
                occ.checked_out_at = datetime.now(timezone.utc)
                occ.checked_out_by = user.id if user else None
                if isinstance(row, Room):
                    row.current_guest = None
                else:
                    row.guest_name = None
                occupancy_id = occupancy_id or occ.id
        elif to in ("available", "inactive") and isinstance(row, Dorm):
            # A dorm's occupancy lives on its beds — forcing the aggregate
            # out of occupied would orphan bed projections. The caller must
            # check out the beds first; the dorm then derives itself.
            occ = await self._open_occupancy(row)
            if occ is not None:
                raise ConflictErr(
                    "Dorm still has active occupancies — check out the "
                    "occupied beds first."
                )

        row.status = to
        self.session.add(ResourceStateEvent(
            resource_type=resource_type,
            resource_id=row.id,
            property_id=row.property_id,
            previous_state=prev,
            new_state=to,
            source=source,
            reason=(reason or "").strip() or None,
            actor_user_id=user.id if user else None,
            actor_name=actor_name,
            task_id=task_id,
            ticket_id=ticket_id,
            occupancy_id=occupancy_id,
        ))
        await self.session.flush()
        return row, prev, to

    async def _open_occupancy(
        self, row, *, lock: bool = False
    ) -> Occupancy | None:
        if isinstance(row, Room):
            cond = Occupancy.room_id == row.id
        elif isinstance(row, Bed):
            cond = Occupancy.bed_id == row.id
        elif isinstance(row, Dorm):
            # a dorm is occupied via its beds — any open bed occupancy counts
            cond = Occupancy.bed_id.in_(
                select(Bed.id).where(Bed.dorm_id == row.id).scalar_subquery()
            )
        else:
            return None
        q = select(Occupancy).where(
            cond, Occupancy.checked_out_at.is_(None)
        ).limit(1)
        if lock:
            # serialize against a concurrent checkout on the same occupancy
            q = q.with_for_update()
        res = await self.session.execute(q)
        return res.scalar_one_or_none()

    async def _release_axis(
        self, row, resource_type: str, release_to: str
    ) -> str:
        """Resolve the "nothing blocks this resource" state — the single
        place where occupancy is folded back into the projection.

        Rooms/beds have an independent occupancy axis: an open occupancy
        record means the resource is logically OCCUPIED even though no
        work blocks it. `release_to` (normally 'available') only applies
        to genuinely unoccupied units — approving a cleaning task on an
        occupied unit must land back on `occupied`, never `available`.
        Dorms aggregate occupancy in `_derive_dorm` instead."""
        if release_to != "available" or resource_type not in ("room", "bed"):
            return release_to
        occupancy = await self._open_occupancy(row, lock=True)
        return "occupied" if occupancy is not None else release_to

    # ------------------------------------------------------------------
    # Blocking queries
    # ------------------------------------------------------------------

    async def _room_blockers(self, room_id: uuid.UUID) -> dict:
        maint = (await self.session.execute(
            select(MaintenanceTicket.id, MaintenanceTicket.ticket_number)
            .where(
                MaintenanceTicket.room_id == room_id,
                MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE),
            )
        )).all()
        tasks = (await self.session.execute(
            select(Task.id, Task.ticket_number)
            .where(
                Task.room_id == room_id,
                Task.status.in_(BLOCKING_TASK),
            ).execution_options(populate_existing=True)
        )).all()
        return {"maintenance": maint, "tasks": tasks}

    async def _bed_blockers(self, bed_id: uuid.UUID, dorm_id: uuid.UUID) -> dict:
        res = await self.session.execute(
            select(MaintenanceTicket.id).where(
                MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE),
                (MaintenanceTicket.bed_id == bed_id)
                | (
                    (MaintenanceTicket.dorm_id == dorm_id)
                    & MaintenanceTicket.bed_id.is_(None)
                ),
            ).limit(1)
        )
        maint = res.scalar_one_or_none() is not None
        res = await self.session.execute(
            select(Task.bed_ids).where(
                Task.dorm_id == dorm_id,
                Task.status.in_(BLOCKING_TASK),
            )
        )
        task = any(not ids or str(bed_id) in ids for ids in res.scalars())
        return {"maintenance": maint, "task": task}

    async def _dorm_blocked(self, dorm_id: uuid.UUID) -> bool:
        res = await self.session.execute(
            select(MaintenanceTicket.id).where(
                MaintenanceTicket.dorm_id == dorm_id,
                MaintenanceTicket.bed_id.is_(None),
                MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE),
            ).limit(1)
        )
        return res.scalar_one_or_none() is not None

    async def _dorm_task_blocked(self, dorm_id: uuid.UUID) -> bool:
        res = await self.session.execute(
            select(Task.id).where(
                Task.dorm_id == dorm_id,
                Task.status.in_(BLOCKING_TASK),
            ).limit(1)
        )
        return res.scalar_one_or_none() is not None

    async def _washroom_blockers(self, washroom_id: uuid.UUID) -> dict:
        maint = (await self.session.execute(
            select(MaintenanceTicket.id, MaintenanceTicket.ticket_number)
            .where(
                MaintenanceTicket.washroom_id == washroom_id,
                MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE),
            )
        )).all()
        tasks = (await self.session.execute(
            select(Task.id, Task.ticket_number)
            .where(
                Task.washroom_id == washroom_id,
                Task.status.in_(BLOCKING_TASK),
            ).execution_options(populate_existing=True)
        )).all()
        return {"maintenance": maint, "tasks": tasks}

    # ------------------------------------------------------------------
    # Resolver — the ONE place that decides a resource's canonical state
    # ------------------------------------------------------------------
    #
    # Step order (all resource types):
    #   1. occupancy truth   — open occupancies row (rooms/beds; dorm = beds)
    #   2. work blockers     — canonical BLOCKING_MAINTENANCE/BLOCKING_TASK
    #   3. operational state — maintenance > cleaning > (occupied|available)
    #   4. materialize       — status = f(occupancy, operational)
    #
    # Callers express INTENT (task approved, ticket closed, checkout,
    # admin action); this resolver decides the resulting state. No caller
    # may pre-compute a target status itself.

    async def _resolve_leaf_target(
        self, row, resource_type: str, release_to: str
    ) -> str:
        """Canonical target for a non-aggregate resource (room / bed /
        washroom / fixture)."""
        if resource_type == "room":
            blockers = await self._room_blockers(row.id)
            if blockers["maintenance"]:
                return "maintenance"
            if blockers["tasks"]:
                return "cleaning"
            return await self._release_axis(row, "room", release_to)
        if resource_type == "bed":
            blockers = await self._bed_blockers(row.id, row.dorm_id)
            if blockers["maintenance"]:
                return "maintenance"
            if blockers["task"]:
                return "cleaning"
            return await self._release_axis(row, "bed", release_to)
        if resource_type == "washroom":
            blockers = await self._washroom_blockers(row.id)
            if blockers["maintenance"]:
                return "maintenance"
            if blockers["tasks"]:
                return "cleaning"
            return release_to
        if resource_type == "fixture":
            # fixtures have no "cleaning" state — any open work holds them
            # at maintenance; clear work releases to `release_to`
            maint = (await self.session.execute(
                select(MaintenanceTicket.id).where(
                    MaintenanceTicket.washroom_fixture_id == row.id,
                    MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE),
                ).limit(1)
            )).scalar_one_or_none()
            tasks = (await self.session.execute(
                select(Task.id).where(
                    Task.washroom_fixture_id == row.id,
                    Task.status.in_(BLOCKING_TASK),
                ).limit(1)
            )).scalar_one_or_none()
            return "maintenance" if (maint or tasks) else release_to
        return release_to

    # ------------------------------------------------------------------
    # Derive — recompute status from active work (release-or-hold only)
    # ------------------------------------------------------------------

    async def _derive_write(
        self, row, resource_type: str, target: str, *,
        user: User | None, source: str, reason: str | None,
        task_id=None, ticket_id=None, occupancy_id=None,
    ) -> str | None:
        """Write a derived transition — bypasses source gates (the blocker
        queries ARE the authority) but still records the audit event."""
        prev = row.status
        if prev == target:
            return None
        row.status = target
        # flush immediately — callers and later aggregate reads must see the
        # committed projection, not a pending in-memory write
        await self.session.flush()
        self.session.add(ResourceStateEvent(
            resource_type=resource_type,
            resource_id=row.id,
            property_id=row.property_id,
            previous_state=prev,
            new_state=target,
            source=source or SRC_DERIVE,
            reason=reason,
            actor_user_id=user.id if user else None,
            actor_name=user.name if user else "System",
            task_id=task_id,
            ticket_id=ticket_id,
            occupancy_id=occupancy_id,
        ))
        return target

    async def derive(
        self,
        resource_type: str,
        resource_id: uuid.UUID | None,
        *,
        release_to: str = "available",
        user: User | None = None,
        actor_name: str | None = None,
        source: str = SRC_DERIVE,
        reason: str | None = None,
        task_id: uuid.UUID | None = None,
        ticket_id: uuid.UUID | None = None,
        audit=None,
    ) -> str | None:
        """Re-derive a resource's status from its active work.

        maintenance blockers → "maintenance" · blocking tasks → "cleaning" ·
        nothing → release_to. Only RELEASE_ELIGIBLE states are touched —
        occupied/available/inactive resources are never overridden. Returns
        the new status when it changed, else None. `audit` is an optional
        callback receiving a human-readable note for the caller's own
        event stream (task history / ticket events).
        """
        if resource_id is None:
            return None
        if resource_type == "dorm":
            return await self._derive_dorm(
                resource_id, release_to=release_to, user=user,
                actor_name=actor_name, source=source, reason=reason,
                task_id=task_id, ticket_id=ticket_id, audit=audit,
            )

        row = await self._lock(resource_type, resource_id)
        await self._check_scope(user, row)
        if row.status not in RELEASE_ELIGIBLE:
            return None
        if resource_type not in ("room", "bed", "washroom", "fixture"):
            return None

        target = await self._resolve_leaf_target(row, resource_type, release_to)

        new = await self._derive_write(
            row, resource_type, target, user=user, source=source,
            reason=reason or f"recompute on {source}",
            task_id=task_id, ticket_id=ticket_id,
        )
        if new is not None and audit is not None:
            audit(_derive_note(resource_type, row, new, source))
        return new

    async def _dorm_has_open_occupancy(self, dorm_id: uuid.UUID) -> bool:
        """Dorm occupancy is the presence of an open occupancy row on ANY
        of its beds — not the beds' materialized status (a bed under
        maintenance can still hold a guest)."""
        res = await self.session.execute(
            select(Occupancy.id).where(
                Occupancy.bed_id.in_(
                    select(Bed.id).where(Bed.dorm_id == dorm_id)
                    .scalar_subquery()
                ),
                Occupancy.checked_out_at.is_(None),
            ).limit(1)
        )
        return res.scalar_one_or_none() is not None

    async def _dorm_bed_facts(
        self, dorm_id: uuid.UUID, *, lock_occupancy: bool = False
    ) -> dict:
        """One batched read of everything the dorm + its beds derive from.

        Each bed's blockers/occupancy used to be queried individually
        (~3 remote round-trips per bed); this gathers them in 3 grouped
        queries instead — remote RTT dominates, so batching is the win.
        Locking is preserved: open occupancy rows are taken FOR UPDATE
        exactly as `_open_occupancy(lock=True)` did per bed.
        """
        res = await self.session.execute(
            select(Bed.id).where(Bed.dorm_id == dorm_id)
        )
        bed_ids = list(res.scalars())

        open_occ_beds: set[uuid.UUID] = set()
        if bed_ids:
            q = select(Occupancy.bed_id).where(
                Occupancy.bed_id.in_(bed_ids),
                Occupancy.checked_out_at.is_(None),
            )
            if lock_occupancy:
                q = q.with_for_update()
            res = await self.session.execute(q)
            open_occ_beds = set(res.scalars())

        # Blocking maintenance — bed-level rows AND the dorm-wide row
        # (bed_id IS NULL), which counts as blocking every bed exactly as
        # `_bed_blockers` defines it. The bed_id IN (...) arm also catches
        # any ticket row that references a bed without dorm_id populated.
        res = await self.session.execute(
            select(MaintenanceTicket.bed_id).where(
                MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE),
                (MaintenanceTicket.dorm_id == dorm_id)
                | MaintenanceTicket.bed_id.in_(bed_ids or [uuid.UUID(int=0)]),
            )
        )
        maint_bed_ids: set[uuid.UUID] = set()
        dorm_maintenance = False
        for bid in res.scalars():
            if bid is None:
                dorm_maintenance = True
            else:
                maint_bed_ids.add(bid)

        # Blocking dorm tasks — bed coverage lives in the bed_ids JSON,
        # matched in memory with the same rule as `_bed_blockers`.
        res = await self.session.execute(
            select(Task.bed_ids).where(
                Task.dorm_id == dorm_id,
                Task.status.in_(BLOCKING_TASK),
            )
        )
        task_bed_id_lists = list(res.scalars())

        return {
            "bed_ids": bed_ids,
            "open_occ_beds": open_occ_beds,
            "maint_bed_ids": maint_bed_ids,
            "dorm_maintenance": dorm_maintenance,
            "task_bed_id_lists": task_bed_id_lists,
            "any_open_occupancy": bool(open_occ_beds),
        }

    @staticmethod
    def _bed_target_from_facts(bed, *, release_to: str, facts: dict) -> str:
        """In-memory equivalent of `_bed_blockers` + `_release_axis`:
        maintenance > cleaning task > occupancy-aware release."""
        if facts["dorm_maintenance"] or bed.id in facts["maint_bed_ids"]:
            return "maintenance"
        if any(
            not ids or str(bed.id) in ids
            for ids in facts["task_bed_id_lists"]
        ):
            return "cleaning"
        if release_to == "available" and bed.id in facts["open_occ_beds"]:
            return "occupied"
        return release_to

    async def _dorm_target(
        self, dorm: Dorm, bed_statuses: list[str], release_to: str,
        *, facts: dict | None = None,
    ) -> str:
        """Canonical aggregate — the single place that computes dorm state:
        dorm-wide maintenance blocker > any cleaning work > any open bed
        occupancy > release_to. `is_active` lifecycle is untouched."""
        maintenance_blocked = facts["dorm_maintenance"] if facts \
            else await self._dorm_blocked(dorm.id)
        if maintenance_blocked:
            return "maintenance"
        if "cleaning" in bed_statuses:
            return "cleaning"
        task_blocked = bool(facts["task_bed_id_lists"]) if facts \
            else await self._dorm_task_blocked(dorm.id)
        if task_blocked:
            return "cleaning"
        any_occupied = facts["any_open_occupancy"] if facts \
            else await self._dorm_has_open_occupancy(dorm.id)
        if any_occupied:
            return "occupied"
        return release_to

    async def _derive_dorm(
        self, dorm_id: uuid.UUID, *, release_to: str,
        user: User | None, actor_name: str | None,
        source: str, reason: str | None = None,
        task_id=None, ticket_id=None, audit=None,
    ) -> str | None:
        """Dorm + every release-eligible bed derive from remaining
        blockers and open occupancy records — occupied beds and retired
        bunks are never touched. The dorm row is an aggregate: dorm-wide
        maintenance > cleaning work > open bed occupancy > released."""
        dorm = await self._lock("dorm", dorm_id)
        await self._check_scope(user, dorm)
        changed: list[str] = []

        # Beds first — their corrected projections feed the aggregate.
        # (Deriving the dorm from stale bed statuses would write a
        # second-order-lag result.)
        res = await self.session.execute(
            select(Bed).where(Bed.dorm_id == dorm.id)
        )
        beds = list(res.scalars())
        facts = await self._dorm_bed_facts(dorm.id, lock_occupancy=True)
        for b in beds:
            if b.status not in RELEASE_ELIGIBLE:
                continue
            bed_target = self._bed_target_from_facts(
                b, release_to=release_to, facts=facts,
            )
            if bed_target == "maintenance":
                continue  # a bed-level ticket still blocks this bed
            if b.status == bed_target:
                continue
            new = await self._derive_write(
                b, "bed", bed_target, user=user, source=source,
                reason=reason or f"recompute on {source} (dorm {dorm.name})",
                task_id=task_id, ticket_id=ticket_id,
            )
            if new:
                changed.append(f"bed {b.bed_number}")

        target = await self._dorm_target(
            dorm, [b.status for b in beds], release_to, facts=facts,
        )
        any_occupied = facts["any_open_occupancy"]
        if dorm.status != target:
            # occupied exits only via its bed-level occupancy lifecycle —
            # an exit is legal when no bed occupancy remains open
            exits_occupied = dorm.status == "occupied" and not any_occupied
            if dorm.status in RELEASE_ELIGIBLE or exits_occupied \
                    or target == "occupied":
                try:
                    await self._derive_write(
                        dorm, "dorm", target, user=user, source=source,
                        reason=reason or f"recompute on {source}",
                        task_id=task_id, ticket_id=ticket_id,
                    )
                    changed.append(f"dorm:{dorm.status}->{target}")
                except (ConflictErr, ValidationErr):
                    pass  # illegal edge under this source — leave for reconcile
        if changed and audit is not None:
            audit(f"Dorm {dorm.name}: → {target} ({source}); "
                  f"{', '.join(changed)}")
        return target if changed else None

    # ------------------------------------------------------------------
    # Repair — canonical projection rewrite (reconciliation backstop)
    # ------------------------------------------------------------------

    async def repair(
        self,
        resource_type: str,
        resource_id: uuid.UUID,
        *,
        user: User | None = None,
        reason: str | None = None,
    ) -> dict:
        """Force a full canonical recompute of the materialized status.

        Unlike derive() this also corrects projection drift on
        NON-release-eligible states: `occupied` without an open occupancy
        collapses to the operational target, `available`/`cleaning`/
        `maintenance` with an open occupancy re-projects `occupied` when
        no work blocks it, and `maintenance`/`cleaning` blockers re-flag
        resources whose projection drifted.

        It NEVER deletes occupancy rows, tasks or tickets — it only writes
        the canonical projection + a `state_reconciliation` audit event.
        `inactive` is a lifecycle state, not work-derived — left alone.
        """
        if resource_type == "dorm":
            return await self._repair_dorm(
                resource_id, user=user, reason=reason
            )
        row = await self._lock(resource_type, resource_id)
        await self._check_scope(user, row)
        prev = row.status
        if prev == "inactive":
            return {
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                "previous_state": prev, "status": prev, "changed": False,
            }
        target = await self._resolve_leaf_target(row, resource_type,
                                                 release_to="available")
        new = await self._derive_write(
            row, resource_type, target, user=user,
            source=SRC_RECONCILIATION,
            reason=reason or "state reconciliation repair",
        )
        return {
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "previous_state": prev, "status": row.status,
            "changed": new is not None,
        }

    async def _repair_dorm(
        self, dorm_id: uuid.UUID, *, user: User | None, reason: str | None
    ) -> dict:
        """Repair each bed's projection first (occupancy + blockers), then
        the dorm's aggregate reads the corrected beds."""
        dorm = await self._lock("dorm", dorm_id)
        await self._check_scope(user, dorm)
        res = await self.session.execute(
            select(Bed).where(Bed.dorm_id == dorm.id).with_for_update()
        )
        beds = list(res.scalars())
        facts = await self._dorm_bed_facts(dorm.id, lock_occupancy=True)
        changed: list[str] = []
        for b in beds:
            if b.status == "inactive":
                continue
            target = self._bed_target_from_facts(
                b, release_to="available", facts=facts,
            )
            new = await self._derive_write(
                b, "bed", target, user=user, source=SRC_RECONCILIATION,
                reason=reason or "state reconciliation repair",
            )
            if new:
                changed.append(f"bed {b.bed_number}")
        prev = dorm.status
        target = await self._dorm_target(
            dorm, [b.status for b in beds], release_to="available",
            facts=facts,
        )
        new = await self._derive_write(
            dorm, "dorm", target, user=user, source=SRC_RECONCILIATION,
            reason=reason or "state reconciliation repair",
        )
        if new:
            changed.append(f"dorm:{prev}->{new}")
        return {
            "resource_type": "dorm",
            "resource_id": str(dorm_id),
            "previous_state": prev, "status": dorm.status,
            "changed": bool(changed),
        }

    # ------------------------------------------------------------------
    # Explain — "why is this resource in this state?"
    # ------------------------------------------------------------------

    async def explain(self, resource_type: str, resource_id: uuid.UUID) -> dict:
        """Read-only blocker/occupancy report for one resource."""
        model = _MODELS.get(resource_type)
        if model is None:
            raise ValidationErr(
                f"Unknown resource type '{resource_type}'.",
                field="resource_type",
            )
        row = await self.session.get(model, resource_id)
        if row is None:
            raise NotFoundErr(f"{resource_type.title()} not found.")

        occupancy = await self._open_occupancy(row)
        result: dict = {
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "status": row.status,
            "open_occupancy": (
                {"id": str(occupancy.id), "guest_name": occupancy.guest_name}
                if occupancy else None
            ),
            "blocking_tickets": [],
            "blocking_tasks": [],
        }
        ticket_q = select(
            MaintenanceTicket.id, MaintenanceTicket.ticket_number,
            MaintenanceTicket.status,
        ).where(MaintenanceTicket.status.in_(BLOCKING_MAINTENANCE))
        task_q = select(
            Task.id, Task.ticket_number, Task.status, Task.title,
        ).where(Task.status.in_(BLOCKING_TASK))
        if resource_type == "room":
            ticket_q = ticket_q.where(MaintenanceTicket.room_id == row.id)
            task_q = task_q.where(Task.room_id == row.id)
        elif resource_type == "bed":
            ticket_q = ticket_q.where(
                (MaintenanceTicket.bed_id == row.id)
                | (
                    (MaintenanceTicket.dorm_id == row.dorm_id)
                    & MaintenanceTicket.bed_id.is_(None)
                )
            )
            task_q = task_q.where(Task.dorm_id == row.dorm_id)
        elif resource_type == "dorm":
            ticket_q = ticket_q.where(
                MaintenanceTicket.dorm_id == row.id,
                MaintenanceTicket.bed_id.is_(None),
            )
            task_q = task_q.where(Task.dorm_id == row.id)
        elif resource_type == "washroom":
            ticket_q = ticket_q.where(MaintenanceTicket.washroom_id == row.id)
            task_q = task_q.where(Task.washroom_id == row.id)
        elif resource_type == "fixture":
            ticket_q = ticket_q.where(
                MaintenanceTicket.washroom_fixture_id == row.id
            )
            task_q = task_q.where(Task.washroom_fixture_id == row.id)
        for tid, num, st in (await self.session.execute(ticket_q)).all():
            result["blocking_tickets"].append(
                {"id": str(tid), "ticket_number": num, "status": st}
            )
        for tid, num, st, title in (await self.session.execute(task_q)).all():
            result["blocking_tasks"].append(
                {"id": str(tid), "ticket_number": num,
                 "status": st, "title": title}
            )
        return result


def _derive_note(resource_type: str, row, new: str, source: str) -> str:
    label = getattr(row, _LABEL_ATTR.get(resource_type, "id"), row.id)
    return (
        f"{resource_type.title()} {label} → {new} ({source})"
    )
