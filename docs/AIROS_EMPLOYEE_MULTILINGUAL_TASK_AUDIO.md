# AiROS Employee — Multilingual & Task Audio Implementation

Employee language preferences persisted server-side, full application i18n
(English / Hindi / Marathi), and per-task text-to-speech via the device
TTS engine. All local-development only — no remote infrastructure touched.

## Architecture overview

```
┌─ Backend ─────────────────────────────────────────────┐
│ app/domain/languages.py        single language registry│
│ app/models/employee_preference.py   employee_preferences
│ app/repositories|services|schemas/employee_preference  │
│ app/api/v1/preferences.py      /mobile/employee/prefs │
│ alembic x8b3d6f1a4c7           new table migration    │
└───────────────────────────────────────────────────────┘
┌─ Frontend ────────────────────────────────────────────┐
│ i18n/languages.ts           local registry (mirror)   │
│ i18n/index.ts               i18next init + setUiLanguage
│ i18n/resources/{en,hi,mr}.ts  translation bundles     │
│ i18n/taskText.ts            task text + speech resolver
│ api/preferences.ts          GET/PATCH client          │
│ services/preferencesService.ts  cache + sync + apply  │
│ services/audio/             TTSProvider + AudioService │
│ components/common/SpeakButton, VoiceMissingSheet      │
│ components/profile/AccountSettingsCard                 │
└───────────────────────────────────────────────────────┘
```

## Languages

| Code | UI name | BCP-47 TTS locale |
|------|---------|-------------------|
| `en` | English | `en-IN` |
| `hi` | हिन्दी   | `hi-IN` |
| `mr` | मराठी   | `mr-IN` |

`text_language` drives the UI (i18next). `audio_language` drives TTS.
They are independent — a Hindi UI can read tasks aloud in Marathi.

## API

All under `/api/v1/mobile/employee/preferences`, JWT-authenticated;
employee identity comes from the token, never a request parameter.

- `GET /` → `{ text_language, audio_language, available_languages[] }`
  Missing row → defaults (`en`/`en`) with `available_languages` from the
  registry. Never 404s an existing employee.
- `PATCH /` → partial updates `{ text_language? , audio_language? }`.
  One field can change without touching the other. Unsupported codes →
  422. Returns the updated object.
- `GET /languages` → registry metadata (no auth-dependent data).

## Database

`employee_preferences` (migration `x8b3d6f1a4c7`, parent `w3b7d9f1a4c6`):

- `id` uuid PK · `employee_id` uuid FK→`employees.id` ON DELETE CASCADE,
  UNIQUE + indexed · `text_language`/`audio_language` varchar(8) NOT NULL
  DEFAULT 'en' · tz-aware `created_at`/`updated_at` (server `now()`).

One row per employee. Employees without a row behave as `en`/`en`, so
no backfill is required. Downgrade drops index + table (reversible).

## Frontend i18n

- `i18next` + `react-i18next`; English fallback; missing keys log a
  dev-mode warning instead of rendering `undefined`.
- Resources are typed so `hi`/`mr` must define every `en` key —
  parity is enforced by `tsc` and the `flatten`-parity test.
- `setUiLanguage(code)` swaps the active language in place; no reload,
  route preserved, all mounted components re-render through the hook.
- Translated surfaces: bottom nav, login, connection-error, update
  dialog, status/priority badges, feedback/empty/error states, buttons'
  loading labels, all employee screens (Tasks, TaskDetail, Maintenance
  list/new/detail, ZoneWorkspace, Attendance, Profile + Account
  Settings), notification toast chrome.
- Backend-rendered notification body text remains in its original
  language by design — the payload contract is unchanged.

## Task text resolution (`i18n/taskText.ts`)

`resolveTaskText(task, lang)` / `resolveSpeechText(task, lang)`:

1. Server-provided per-field translations (`title_translations`,
   `description_translations` — additive wire fields; absent today).
2. Structured template by semantic `work_type`/`category` with the
   location interpolated (`TASK_TEMPLATES` — cleaning/maintenance/
   inspection families keyed on the work vocabulary, not the scheduling
   `task_type`).
3. The original English text — never an empty description.

`ticketToSpeakable(ticket)` adapts maintenance tickets to the task
shape (issue→title, description→instructions) — no unsafe casts.

## Audio (services/audio)

- `TTSProvider` — interface over
  `@capacitor-community/text-to-speech@6` (Capacitor-7 compatible; the
  8.x line requires Cap 8 and was rejected). One class covers Android
  native and the plugin's web SpeechSynthesis path.
- `AudioService` — singleton owning playback: serialized generation
  tokens (a stale completion can't clobber newer state), `speakTask`
  stops any current utterance first and the plugin is called with
  `QueueStrategy.Flush`, same-task click toggles off. Stops on route
  change, unmount (`SpeakButton` effect), logout (`reset`), and app
  backgrounding (`Capacitor App 'pause'`).
- Voice availability is cross-checked against
  `getSupportedVoices()` (engine `isLanguageSupported` false-positives
  on some Android engines). Missing voice → `VoiceUnavailableError` →
  `voice_missing` status → `VoiceMissingSheet` with the localized
  explanation, `openInstall()` (Android TTS settings), and a pointer to
  Profile → Account Settings.

## Preference lifecycle

`App.tsx`: after auth resolves → `preferencesService.loadForEmployee`
(applies per-employee localStorage cache instantly, re-syncs with the
server in the background — login never blocks on it). Logout → `clear()`
+ `audioService.reset()`. Account Settings PATCHes through the service;
i18n swaps only after the server confirms.

## Adding a language (e.g. Gujarati)

1. `app/domain/languages.py` + `frontend/src/i18n/languages.ts`:
   `{ code:'gu', name:'Gujarati', native_name:'ગુજરાતી', locale:'gu-IN' }`.
2. `i18n/resources/gu.ts` mirroring `en` — `tsc` fails until every key
   exists.
3. Optionally add `TASK_TEMPLATES['…'].gu` entries for structured task
   speech. No schema, API, or migration changes needed — `varchar(8)`
   and the validators read the registry.

## Local validation status

- `cd backend && python -m pytest` — 384 passed (SQLite in-memory;
  asyncpg stubbed in `tests/conftest.py` because the host App Control
  policy blocks its compiled DLL — tests never open Postgres).
- `cd frontend && npm run lint` (`tsc --noEmit`) — clean.
- `cd frontend && npm run test` (vitest) — 198 passed, incl. i18n key
  parity, task-text fallback, and AudioService lifecycle/overlap/
  missing-voice coverage.
- `cd frontend && npm run build` — production bundle OK.
- Alembic: single head `x8b3d6f1a4c7`; upgrade/downgrade are code-level
  verified — the configured `.env` points at the remote Supabase pooler
  and Docker isn't available here, so `alembic upgrade head` was NOT run.
  Run it against a local database only.

## Running it locally

Two supported paths — both fully local:

- `python main.py --seed` — Docker stack (local postgres + redis +
  migrations + api:8000 + web:3000). The launcher force-overrides any
  remote `DATABASE_URL` to the bundled postgres, and `web` serves the
  `dist/` baked at image build — re-run after frontend changes.
- `python main.py --local --seed --web` — no Docker required: backend on
  local SQLite (`backend/dev.db` via `scripts/dev_local_db.py`), frontend
  via live Vite dev server at :3000. Seed creates the demo tenant plus
  two assigned tasks so the speaker button is immediately visible.

Login: `employee@demo.local` / `Demo!Pass123` → Profile → Account
Settings (Text/Audio language), Tasks → speaker icon per card.

Android emulator: `python main.py --native` (or `--local`) without `--web`
injects `server.url → http://10.0.2.2:<port>` into capacitor.config.json,
so the app loads the live dev server instead of the bundled `dist/`
snapshot. A plain `npx cap sync` install only refreshes bundled assets
after `npm run build`.

## Known limitations

- Device TTS voices (esp. Marathi) must exist on the handset; the
  voice-missing sheet covers the install path. Real-device audio was
  verified by mocked tests only — physical Android validation pending.
- Notification bodies from the backend are shown as sent (English);
  only notification chrome/labels are localized.
- Maintenance detail screen speaks the ticket issue + description;
  zone-workspace unit tiles are resource states, not tasks, so they
  intentionally have no speaker button.
