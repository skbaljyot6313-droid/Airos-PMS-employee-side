# Airos Property Pro — Mobile UX Overhaul (partial execution report)

Branch `development-branch` · APK `1.0.14 (16)` · all work uncommitted.

## Implemented + verified (typecheck clean)

### 1. Overdue work removed from employee views — DONE

`TasksScreen.tsx`: new `visibleTasks = tasks.filter(t => t.status !== 'overdue')`
feeds `filteredTasks` + `todoCount`. The `overdue` literal is the **backend's
authoritative status** (wire type, not a client date-computation), so valid
current allocations, in-review items and completed history are unaffected;
overdue rows remain in PostgreSQL + SA views (presentation-only filter).

### 2. Notification swipe-to-dismiss — DONE

`NotificationToast.tsx`: pointer-drag handler — horizontal swipe **either
direction** past 60px dismisses immediately; shorter drags snap back with a
150ms ease-out + fade. `touch-pan-y` preserves vertical scrolling; taps still
open the deep-link (swipe suppresses the click via a flag); the ✕ button stays
as the accessible alternative; auto-dismiss (6s) unchanged. Per-toast state →
independent dismissal; queue collapse is the existing React list unmount.
Dismissal is persistent-by-design: popup IDs go through the seen-ledger
diff poll, so a dismissed banner never re-toasts, while the notification
row survives in the feed/history.

## Deferred — documented for the next iteration

| Item | Why deferred | Exact path |
|---|---|---|
| Edge-swipe back/forward | Router is the manual `StackRoute` in `App.tsx` — needs a centralized gesture hook on the frame div tracking a forward-stack (pop on right-edge drag, re-push on left-edge drag) | add `useEdgeSwipe` in `App.tsx` keyed off `StackRoute` push/pop |
| Perf audit numbers | No device instrumentation budget this pass | reuse `core/metrics` + `?perf` headers + vitest timing |
| Native-shade sync | OS notifications are `LocationTrackingService`-owned — already respects Android dismissal via the shared seen-ledger | n/a — already correct |
| Rebuild + device tests | Gradle build + device install pending | `.\scripts\build-android-docker.ps1` |

## Verified vs unverified

- `npx tsc --noEmit` — **clean** after all edits.
- Backend pytest — not re-run (no backend change in this task).
- Device-level swipe/overdue tests — **pending APK rebuild + install**;
  do not treat as verified.
- Earlier session results stand: CORS fix live (`airos-eb-api-dev-00002-jxg`),
  `/mobile/version` checksum fields implemented backend-side.

## Files changed

`frontend/src/screens/employee/TasksScreen.tsx` ·
`frontend/src/components/common/NotificationToast.tsx`
(prior session changes also in tree: backend `storage.py`/`mobile.py`/
`schemas/mobile.py`, `AppUpdatePlugin.java`, `updateInstaller.ts`,
`updateService.ts`, `api/mobile.ts`, `capacitor.config.json` name,
`strings.xml`/`app.json` display name).
