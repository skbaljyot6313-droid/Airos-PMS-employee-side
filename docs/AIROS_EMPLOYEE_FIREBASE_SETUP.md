# AiROS Employee — Firebase Setup (development)

Firebase project: **`final-airos-os`** (project number `94363806721`,
region `asia-south1`). One project only — no second Firebase project was
or should be created.

## Android app registration

| Field | Value |
|---|---|
| Package name | `com.theairco.airos.employee` |
| Display name | AiROS Employee |
| **Firebase App ID** | `1:94363806721:android:a2c92d7ac6a4c2ea066400` |
| State | ACTIVE |

Registered via the Firebase Management API under the project owner's
gcloud credentials — no console-only steps were required. The matching
`google-services.json` was fetched from the app's config endpoint and
placed at `frontend/android/app/google-services.json` (the Gradle
`google-services` plugin activates automatically — see the conditional
apply in `app/build.gradle`).

> **Replaced config:** the previously committed `google-services.json`
> pointed at the old Firebase project `airos-530a5` (number 732720607924).
> FCM tokens are now issued under `final-airos-os`. **Backend dependency:**
> the Employee API's `FCM_SERVICE_ACCOUNT_JSON` must also be a
> `final-airos-os` service account or server pushes will fail with
> sender-id mismatch — this is a backend env change outside this repo's
> scope; report it to whoever owns the API deployment.

## App Distribution

- API `firebaseappdistribution.googleapis.com`: **enabled** on the project.
- Tester group: **`airos-employee-dev-testers`** — display name
  "AiROS Employee Dev Testers" (created empty).
- Distribution path: Firebase App Distribution REST API
  (`releases:upload` → `:updateReleaseNotes` → `:distribute`), or the
  Firebase CLI equivalent (`firebase appdistribution:distribute`).

### Manual steps required (cannot be automated)

1. **Add testers.** The group exists but is empty — no emails were
   invented. Add real tester emails via:
   - Firebase Console → App Distribution → Testers & Groups →
     `airos-employee-dev-testers` → Add testers, **or**
   - `POST /v1/projects/94363806721/testers:batchAdd` with the emails.
   Testers must accept the emailed invitation and install the
   Firebase App Distribution tester app (or the in-app-update flow).
2. **Accept the invitation on the test device** and sign in with the
   invited Google account.
3. **(Optional, CI) Create a service account** with the
   *Firebase App Distribution Admin* role on `final-airos-os` and store
   its JSON in the GitHub secret `FIREBASE_SERVICE_ACCOUNT_EMPLOYEE_DEV`
   for `dev-distribution.yml`. Workload Identity Federation is the
   preferred alternative — configure it per Google's docs if available.

## What is intentionally NOT used

- **Firebase Authentication** — auth stays the existing JWT + refresh
  flow against the Employee API.
- **Firebase Hosting / Remote Config** — not part of this deployment.
- **Firestore/Storage** — the app has its own backend + S3-compatible
  object storage; no competing storage was created.

## Credentials hygiene

- `google-services.json` contains a client API key that is public by
  design (it ships inside every APK); it is committed intentionally, as
  before.
- No service-account JSON, Firebase tokens, or CI tokens are in the repo.
- Local distribution uses the developer's own `gcloud` credentials.
