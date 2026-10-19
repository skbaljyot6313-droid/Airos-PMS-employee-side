/**
 * AiROS Employee API — STAGING load test (k6).
 *
 * Covers the three hot paths the perf overhaul targets:
 *   1. cold start   — login → /auth/me → /bootstrap → /tasks
 *   2. notification burst — /notifications + /unread-count
 *   3. location ingest    — POST /location/current (tracking session)
 *
 * HARD GUARD: refuses to run unless STAGING=1 is set explicitly — this
 * script must NEVER be pointed at production.
 *
 * Usage:
 *   k6 run -e STAGING=1 \
 *          -e BASE_URL=https://<staging-host>/api/v1 \
 *          -e EMAIL=<staging-user> -e PASSWORD=<staging-password> \
 *          scripts/loadtest/staging.js
 *
 * Metrics emitted: http_req_duration, plus per-path checks. Compare the
 * X-DB-* response headers between runs (server log / response headers).
 */
import http from 'k6/http';
import { check, fail, sleep } from 'k6';
import { Trend } from 'k6/metrics';

if (__ENV.STAGING !== '1') {
  fail('Refusing to run: set -e STAGING=1 (this script is staging-only).');
}
const BASE = __ENV.BASE_URL;
if (!BASE) fail('Set -e BASE_URL=https://<staging>/api/v1');
if (!__ENV.EMAIL || !__ENV.PASSWORD) {
  fail('Set -e EMAIL and -e PASSWORD for the staging tenant.');
}

export const options = {
  scenarios: {
    cold_start: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      exec: 'coldStart',
      startTime: '0s',
    },
    notif_burst: {
      executor: 'constant-vus',
      vus: 10,
      duration: '30s',
      exec: 'notifBurst',
      startTime: '35s',
    },
    location_ingest: {
      executor: 'constant-vus',
      vus: 10,
      duration: '30s',
      exec: 'locationIngest',
      startTime: '70s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
  },
};

const tMe = new Trend('me_ms');
const tBootstrap = new Trend('bootstrap_ms');
const tTasks = new Trend('tasks_ms');
const tNotif = new Trend('notif_ms');
const tLoc = new Trend('location_ms');

let token = null;

function login() {
  if (token) return token;
  const res = http.post(`${BASE}/auth/login`, JSON.stringify({
    identifier: __ENV.EMAIL, password: __ENV.PASSWORD,
  }), { headers: { 'Content-Type': 'application/json' } });
  check(res, { 'login 200': (r) => r.status === 200 });
  token = res.json().access_token;
  return token;
}

const auth = () => ({
  headers: { Authorization: `Bearer ${login()}`, 'Content-Type': 'application/json' },
});

export function coldStart() {
  const h = auth();
  const me = http.get(`${BASE}/auth/me`, h);
  tMe.add(me.timings.duration);
  const boot = http.get(`${BASE}/bootstrap`, h);
  tBootstrap.add(boot.timings.duration);
  const tasks = http.get(`${BASE}/tasks`, h);
  tTasks.add(tasks.timings.duration);
  check(boot, {
    'bootstrap 200/404': (r) => r.status === 200 || r.status === 404,
  });
  sleep(1);
}

export function notifBurst() {
  const h = auth();
  const res = http.get(`${BASE}/notifications?limit=50`, h);
  tNotif.add(res.timings.duration);
  const unread = http.get(`${BASE}/notifications/unread-count`, h);
  check(res, { 'notif 200': (r) => r.status === 200 });
  check(unread, { 'unread 200': (r) => r.status === 200 });
  sleep(0.5);
}

export function locationIngest() {
  const h = auth();
  const res = http.post(`${BASE}/location/current`, JSON.stringify({
    latitude: 1.3521, longitude: 103.8198,
    accuracy: 10.0, timestamp: Date.now() / 1000,
  }), h);
  tLoc.add(res.timings.duration);
  // 200 | 404 (tracking not started) | 503 (redis off) — all valid shapes
  check(res, {
    'ingest responded': (r) => [200, 404, 503].includes(r.status),
  });
  sleep(0.3);
}
