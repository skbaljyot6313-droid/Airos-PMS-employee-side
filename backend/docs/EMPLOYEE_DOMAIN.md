# Employee domain

An authenticated `User` with role `employee` links to one `Employee`, one company, one property, and optional zone/area coverage. The user identity is the authorization source; client-supplied tenant IDs are never trusted.

- Task lists and details are restricted to `Task.employee_id == user.employee_id`. Start and submit repeat the assignee check.
- Maintenance lists include tickets assigned to the employee or reported by that user. Creation is limited to rooms/dorms (and related targets) inside zone/area coverage.
- Resource hierarchy is Property → Area → Zone → Room or Dorm → Bed. Washrooms are zone-level or dorm-attached; fixtures have independent state.
- Room/bed occupancy is represented by open `Occupancy` rows. Dorm occupancy is derived from beds. Washrooms have no occupancy axis.
- Task submission records history, a completion attempt, and evidence. Supervisor review remains outside this employee API, but its persistence fields are retained.
- Maintenance resolution records notes/evidence and remains blocking until supervisor closure. `ResourceStateService` remains the sole state authority.
- Employee status/leave/department fields remain on the model and allocation eligibility helper because maintenance auto-allocation depends on them.
