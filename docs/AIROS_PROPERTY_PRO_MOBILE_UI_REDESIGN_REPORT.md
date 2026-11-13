# Airos Property Pro — Mobile UI Redesign Report

Branch `development-branch` · uncommitted · target APK 1.0.16 / vc18.

## Design tokens retuned (`src/index.css`)

| Token | Was | Now |
|---|---|---|
| `--color-app` (canvas) | `#FFFFFF` | `#F4F5F3` — grey canvas behind cards |
| `--color-ink` | `#171918` | `#202522` |
| `--color-sub` | `#666D68` | `#858B88` |
| `--color-line` | `#E8EBE7` | `#E7EAE7` |
| `--color-lime` | `#C8F169` | `#B8E957` (spec accent) |
| `--color-dng` | `#D9363E` | `#D94B55` |
| `--color-ok` | `#278447` | `#32865B` |

These tokens drive every screen (`bg-app`, `text-ink`, `text-mute`,
`border-line` utilities) — so Maintenance/Attendance/Profile and detail
screens inherit the palette automatically; no per-screen overrides needed.

## Tasks screen (`TasksScreen.tsx` + `TaskCard.tsx`)

- **Cards replace flat rows**: the `divide-y` list became
  `px-4 pt-4 pb-8 space-y-3` on the grey canvas; `TaskCard` is now a white
  card — `bg-surface border-line rounded-[14px] p-4`, subtle press scale,
  no shadow (keeps it minimal).
- **Hierarchy**: category 11px semibold uppercase → priority mark →
  **title 17px semibold Space Grotesk** (strongest element) →
  location·zone 13px → due clock row 13px. Red reserved for the Overdue
  label only.
- **Header**: greeting 11px → heading bumped to **28px bold** "Your tasks";
  context row (brand icon + zone) unchanged; compact refresh button kept.
- **Tabs**: equal-width segmented tabs retained — dark semibold active,
  muted inactive, lime 3px rounded indicator, hairline divider.
- **Long titles**: `line-clamp-2` on the card (no clipping/overlap);
  location/bed detail stays in the metadata line, not the title.

## Bottom navigation (`BottomNav.tsx`)

Icon 18→**22px**, label 10→**12px** (medium), label spacing → mt-1.5,
existing 3px lime active marker + top border + safe-area padding kept;
48px+ touch targets already satisfied.

## Verified

- `npx tsc --noEmit` — **clean** (after all edits).
- APK build + aapt validation — see build output below.

## Pending verification

- Visual device pass (compact phone, safe area, scroll overlap).
- Screenshots — no device emulator frames available in this pass.
- Other screens rely on inherited tokens; any screen still using raw
  white canvas can adopt `bg-surface` cards in a follow-up pass.

## Preserved

Toast swipe-to-dismiss, edge-swipe navigation, overdue filtering,
auth/attendance/GPS/maintenance flows — untouched.
