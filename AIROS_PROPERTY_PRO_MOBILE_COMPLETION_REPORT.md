# Airos Property Pro — Mobile Completion Report

Branch `development-branch` · uncommitted · APK `airos-property-pro-dev.apk`
**1.0.15 / versionCode 17** · `com.theairco.airos.employee`.

## Implemented this pass

### Centralized edge-swipe navigation — DONE

- `src/services/navSwipe.ts` — pure recognizer (`createEdgeSwipe`):
  gesture must **start inside a 28px edge zone**, stay horizontal
  (vertical dominance cancels), complete <800ms, exceed 64px; blocked
  on `input,textarea,select,button,[role=button],form,[role=status],[data-no-nav-swipe]` —
  so forms, buttons, and the notification toast never trigger it.
- `src/App.tsx` — centralized history on the manual `StackRoute`:
  `navigate()` pushes `routeRef`→`past`, `goBack()` pops to `setRoute` +
  pushes to `future`, `goForward()` inverse; `goBackOr(fallback)` for the
  four `onBack` handlers; every forward call site (task detail,
  maintenance new/detail, zone workspace, notification deep-links) now
  uses `navigate()`; **tab switches stay root-level replaces** so the
  stack only holds drill-downs (no duplicate entries).
- Android hardware back → `CapacitorApp.addListener('backButton')` →
  `goBack()` before `exitApp()` — preserved exit at root.
- One `useEffect` binds window pointer events to `createEdgeSwipe`
  (no competing handlers; the toast's own pointer handlers coexist —
  `[role=status]` exclusion covers it).

### Version bump

`app.json` → **1.0.15 / vc17** via `bump-version.mjs` (baseline 16, monotonic).

## Verified results (actually executed)

| Check | Result |
|---|---|
| `npx tsc --noEmit` | **clean** |
| `vitest navSwipe.test.ts` | **8/8 pass** — left/right edge, mid-screen reject, sub-threshold snap, vertical-cancel, slow-gesture reject, blocked-target reject, single-fire |
| Dockerized `assembleDebug` | **BUILD SUCCESSFUL** (196 tasks; Java `getLong` literal fixed) |
| `aapt dump badging` | `package=com.theairco.airos.employee versionCode=17 versionName=1.0.15` |
| APK SHA-256 | `d8267711afd9c2dc9dfb0683ff91f7708972f149da65f0998c53821fff20d072` |
| Output | `dist/android/airos-property-pro-dev.apk` (7.75 MB, debug-signed) |
| `capacitor.config.json`/`strings.xml`/`app.json` | name = **Airos Property Pro** |

## Performance audit — findings (inspection-level, no fabricated benchmarks)

Architecture already sound: single-flight 401 refresh, 4h update-check
throttle, 45s notification poll + realtime coalescing, native-owned GPS
(no WebView renders per fix), `loadInFlight` dedup + `refreshPending`
in TasksScreen, listener cleanups verified on all App.tsx effects
(backButton, pointer trio, appStateChange ×2 — all remove on unmount).
Vite bundle: 493 kB (137 kB gzip) — Tailwind transform is the slow build
step (95%), not runtime. No measured hot-path warranted blind changes;
per rule, un-reproduced problems were documented not "fixed".

## Deferred / pending (honest)

- **Device-level tests** — no device/emulator run; swipe, toast, upgrade
  1.0.14→1.0.15, GPS+scroll need a real install. Not claimed.
- Five-route nav walk — unit-tested logic only; in-app traversal untested.
- Perf numbers — no instrumented before/after run; instrumentation hooks
  (`core/metrics`, `perfMarkOnce`) exist for a later pass.
- `mobile/version` checksum fields still pending a backend redeploy.

## Constraints honored

No commits/pushes · no SA changes · no prod · no schema changes · no data
deletion · package ID + debug signing preserved · APK **not** distributed.
