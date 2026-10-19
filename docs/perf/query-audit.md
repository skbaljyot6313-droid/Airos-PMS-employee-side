# Phase 2 — Query Audit

Baseline for the query-reduction work. Counts are **code-traced sequential
round trips** (one RTT ≈ 300–700 ms on the production Singapore→Mumbai
path); `+1` auth lookup applies to every authenticated route via
`get_current_user`. Verify each against `X-DB-Count` on staging before
optimizing further.

Legend: queries run sequentially (S) or parallelizable (P); `sel` =
selectinload secondary query.

## Hot-path endpoints

| Endpoint | Auth q | Business queries | Sequential RTTs | Parallelizable? | Phase-2 action |
|---|---|---|---|---|---|
| `POST /auth/login` | — | user-by-identifier(1) + touch_last_login(1) + refresh insert(1) | 3 | partially (touch+insert → 1 txn, already one commit) | argon2 done; leave as-is |
| `POST /auth/refresh` | — | refresh_token(1) + user(1) | 2 | yes → 1 batch | candidate for `asyncio.gather` (independent lookups) |
| `GET /auth/me` | 1 users+company join | — | 1 | — | folds into `/bootstrap` |
| `GET /tasks` | 1 | list_tasks(1) — eager loads deliberately skipped | 1 | — | fine; add ETag |
| `GET /maintenance` | 1 | tickets(1) + events sel(1) + attachments sel(1) | 3 | sel pairs can't gather on one session | consider lazy detail-load: list omits events/attachments → 1 |
| `GET /maintenance/eligible-locations` | 1 | emp(1) + zones-in-area(1) + rooms(1) + dorms(1) + beds sel(1) + zones-map(1) + washrooms(1) + fixtures sel(1) | **≤8** | rooms/dorms/washrooms/zone-map after coverage → gather ≤3 | top candidate: coverage then `gather` 3 read batches |
| `GET /zones` | 1 | zones(1) | 1 | — | add ETag (stable reference data) |
| `GET /notifications` | 1 | unread? + ledger-tasks(1) + ledger-tickets(1) + dedupe EXISTS(≤n) + list(1) | 3+n | ledger reads independent → gather 2 | gather ledger pair; cap dedupe EXISTS; move unread-count off read |
| `POST /devices/register` | 1 | lookup(1) + upsert(1) | 2 | — | leave |
| `GET /attendance/today` | 1 | day(1) + breaks sel + shift-ish | ~3 | — | audit live via X-DB-Count first |
| `GET /attendance/calendar` | 1 | days(1) + requests(1) | ~2–3 | yes → gather | candidate |
| `GET /attendance/shift` | 1 | assignment(1) | 1 | — | folds into `/bootstrap` |
| `POST /location/start` | 1 | insert(1) | 1 | — | leave |
| `POST /location/current` | **0** (authctx hit) | — | **0** | — | done in Phase 1 |
| `GET /location/current` | **0** | — | **0** | — | done in Phase 1 |
| `GET /realtime/token` | 1 | — (JWT mint) | 0 | — | leave |
| `GET /mobile/version` | — | active release(1) | 1 | — | leave |

## Structural findings

1. **Every authenticated request pays +1 users-row lookup**
   (`get_current_user` → `UserRepository.get_by_id`). With ~280 calls/30min
   per active user this is the largest aggregate query source. Phase-1
   solved it for `/location/*`; generalize the same `mt:authctx` cache
   (60s TTL) to `get_current_user` — invalidation on `PATCH /auth/me`,
   logout, deactivation.

2. **`GET /maintenance/eligible-locations` is the worst single handler** —
   ≤8 sequential RTTs. Post-coverage reads are independent; `asyncio.gather`
   (bounded ≤3) cuts ~5 RTTs. Alternatively one UNION query — keep gather
   first (smaller diff).

3. **`GET /notifications` does write-work on read** — ledger sync +
   `EXISTS` dedupe per event inside the request. Keep sync-on-read (it's
   the SA-integration backstop) but gather the two ledger scans.

4. **Sequential awaits inside one session can't be trivially gathered** —
   SQLAlchemy forbids concurrent operations on one `AsyncSession`
   (`MissingGreenlet`/state corruption). Options ranked:
   a. Split into parallel SQL via `session.connection()` streams? — no,
      same limitation.
   b. Gather multiple **independent** awaits is unsafe on shared session →
      use `session.bind.connect()` raw coroutines only for pure SELECTs,
      or accept serial calls and instead reduce count (joins/UNION).
   c. Cheapest real win: replace N round trips with ONE SQL statement
      (joins, UNION ALL, or `selectinload`) where shapes allow.

5. **Startup fan-out** (client): `/auth/me` → `/zones` → `/tasks` +
   `/maintenance` + `/notifications` + `/realtime/token` +
   `/location/start` + `/devices/register` + `/mobile/version`. A
   `/bootstrap` endpoint collapsing me+zones+shift+unread_count into one
   call removes 3 calls and ~3 serial dependencies.

## Phase 2 work items (ordered)

| Item | Scope | RTT saving | Risk |
|---|---|---|---|
| 2.1 `GET /bootstrap` | `{user,company,zones,shift,unread_count}` in ≤3 queries | −3 startup RTTs | low — additive endpoint |
| 2.2 authctx for `get_current_user` | Redis 60s user-row cache, invalidation on patch/logout/deactivate | −1 RTT × ~all calls | medium — cache invalidation rules |
| 2.3 eligible-locations gather | coverage → 3 parallel read batches (rooms+dorms / zones-map / washrooms+fixtures) | ~5 RTTs | low — same session via gather-safe helper or split sessions |
| 2.4 notifications ledger gather | task-events ∥ ticket-events scans | ~1 RTT + dedupe cap | low |
| 2.5 ETag on `/tasks`,`/maintenance`,`/zones` | `If-None-Match` → 304 | avoids full payload RTT on unchanged | low — additive header |
| 2.6 `/maintenance` list lazy detail | list omits events/attachments (detail endpoint already returns them) | −2 sel RTTs | medium — check all consumers of list payload first |

## Deferred to Phase 5+

- Worker/pool sizing, arq worker, region placement — gated on
  `X-PoolWait-ms`/`X-DB-*` staging data.
- Durable offline mutation queue — business decision pending.

## Measurement contract

Every changed handler MUST log `X-DB-Count` before/after on staging.
Target per audit goals: `/auth/me`+`/bootstrap` cold-start total ≤6 DB
queries across all startup calls; eligible-locations ≤3 sequential RTTs;
`/notifications` ≤5 sequential RTTs.
