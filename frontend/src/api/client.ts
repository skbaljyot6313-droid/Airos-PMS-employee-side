/**
 * Centralized API client — the single boundary for every HTTP request to the
 * FastAPI backend (mounted at /api/v1).
 *
 * - Bearer access token + refresh token (localStorage)
 * - On 401: one refresh attempt (single-flight), one retry, then sign-out
 * - FastAPI error envelope: { detail: string | { message, field? } | [{loc,msg,type}] }
 *
 * Base URL comes from VITE_API_URL (see .env) — e.g.
 *   http://10.0.2.2:8000/api/v1   Android emulator → host loopback
 *   http://localhost:8000/api/v1  browser dev
 * No screen constructs URLs or touches fetch outside this file.
 */

import { ApiError, ApiFieldError } from '../types';
import { perfMarkOnce } from '../utils/perf';

const ACCESS_KEY = 'airos_staff_access_token';
const REFRESH_KEY = 'airos_staff_refresh_token';

/** Dispatched after a successful access-token refresh — the native
 *  location service listens so its upload auth stays fresh. */
export const TOKEN_REFRESHED_EVENT = 'airos_token_refreshed';

export const secureStorage = {
  getToken: (): string | null => {
    try {
      return localStorage.getItem(ACCESS_KEY);
    } catch {
      return null;
    }
  },
  getRefreshToken: (): string | null => {
    try {
      return localStorage.getItem(REFRESH_KEY);
    } catch {
      return null;
    }
  },
  setTokens: (access: string, refresh: string): void => {
    try {
      localStorage.setItem(ACCESS_KEY, access);
      localStorage.setItem(REFRESH_KEY, refresh);
    } catch (e) {
      console.error('Failed to persist session tokens', e);
    }
  },
  setAccessToken: (access: string): void => {
    try {
      localStorage.setItem(ACCESS_KEY, access);
    } catch (e) {
      console.error('Failed to persist access token', e);
    }
  },
  clearTokens: (): void => {
    try {
      localStorage.removeItem(ACCESS_KEY);
      localStorage.removeItem(REFRESH_KEY);
    } catch (e) {
      console.error('Failed to clear session tokens', e);
    }
  },
};

export const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1').replace(/\/+$/, '');

/** Origin without the /api/vN suffix — media paths (/uploads/…) hang off it. */
export const API_ORIGIN = API_BASE.replace(/\/api\/v\d+$/, '');

/** Resolve a media path (/uploads/x.jpg) against the API origin — absolute
 *  storage URLs pass through untouched. */
export const mediaUrl = (p: string): string =>
  /^https?:\/\//i.test(p) ? p : `${API_ORIGIN}${p.startsWith('/') ? p : `/${p}`}`;

/** Raw technical strings that should never reach the UI — thrown by fetch,
 *  the Capacitor bridge, and other non-API paths. */
const TECHNICAL_MESSAGE =
  /failed to fetch|networkerror|network request failed|load failed|the internet connection appears to be offline|err_internet_disconnected|err_connection|abort:?ed|timeout of \d+|econn|socket|dns|ssl|tls|unexpected token|json\.parse|is not valid json|undefined is not|cannot read propert|null is not/i;

/** Narrow an unknown thrown value to a display message. ApiError messages
 *  (client.ts) are already user-friendly and pass through; raw technical
 *  noise from non-API paths (fetch, plugins, JSON) maps to the fallback. */
export const errorMessage = (e: unknown, fallback: string): string => {
  if (
    typeof e === 'object' && e !== null &&
    'message' in e && typeof (e as { message: unknown }).message === 'string'
  ) {
    const msg = (e as { message: string }).message;
    const isApiError = 'status' in e; // apiClient always stamps a status
    if (!isApiError && (TECHNICAL_MESSAGE.test(msg) || !msg.trim())) {
      return fallback;
    }
    return msg;
  }
  return fallback;
};

const FALLBACK_MESSAGES: Record<number, string> = {
  400: 'The request was invalid.',
  401: 'Your session has expired. Please sign in again.',
  403: 'You do not have permission to perform this action.',
  404: 'Not found.',
  409: 'This conflicts with the current state. Refresh and try again.',
  422: 'Please check the submitted values.',
  429: 'Too many requests — please wait a moment and try again.',
  500: 'A server error occurred. Please try again.',
  502: 'The server is unavailable right now. Please try again.',
  503: 'The server is unavailable right now. Please try again.',
};

export const normalizeError = (status: number, body: unknown): ApiError => {
  const detail = (body as { detail?: unknown } | null)?.detail;
  // Backend also emits { error: { code, message } } — some paths (unhandled
  // 500/503) send ONLY that envelope, so it feeds both code and message.
  const errObj = (body as { error?: { code?: string; message?: string } } | null)?.error;
  const errCode = typeof errObj?.code === 'string' ? errObj.code : undefined;

  // FastAPI 422 shape: { detail: [{ loc: [.., 'field'], msg, type }] }
  if (Array.isArray(detail)) {
    const fieldErrors: ApiFieldError[] = detail.map((d) => ({
      field: Array.isArray(d?.loc) ? String(d.loc[d.loc.length - 1]) : undefined,
      message: d?.msg || d?.message || 'Validation error',
      code: d?.type,
    }));
    return {
      status,
      code: errCode,
      message: fieldErrors[0]?.message || 'Validation failed.',
      fieldErrors,
    };
  }

  if (typeof detail === 'string' && detail) return { status, code: errCode, message: detail };
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const d = detail as { message: string; field?: string; code?: string };
    return {
      status,
      code: d.code ?? errCode,
      message: d.message,
      fieldErrors: d.field ? [{ field: d.field, message: d.message }] : [],
    };
  }

  // Error-only envelope: { error: { code, message } } (500/503 paths).
  if (errObj && typeof errObj.message === 'string' && errObj.message) {
    return { status, code: errCode, message: errObj.message };
  }

  return { status, code: errCode, message: FALLBACK_MESSAGES[status] ?? `Request failed (${status}).` };
};

interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  /** false for /auth/login and /auth/refresh themselves. */
  auth?: boolean;
  /** internal — set by the retry pass so we only refresh once per call. */
  _retried?: boolean;
  _busyRetries?: number;
  _netRetries?: number;
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = secureStorage.getRefreshToken();
  if (!refreshToken) return false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: controller.signal,
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { access_token?: string };
    if (!data?.access_token) return false;
    secureStorage.setAccessToken(data.access_token);
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(TOKEN_REFRESHED_EVENT));
    }
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/** Single-flight refresh — concurrent 401s share one refresh request. */
const singleFlightRefresh = (): Promise<boolean> => {
  refreshInFlight ??= refreshAccessToken().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
};

export async function apiClient<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 45000, auth = true, _retried, _busyRetries = 0, _netRetries = 0, ...init } = options;

  const headers = new Headers(init.headers || {});
  if (!headers.has('Content-Type') && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (auth && !headers.has('Authorization')) {
    const token = secureStorage.getToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);
  }

  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const url = `${API_BASE}${cleanEndpoint}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  perfMarkOnce('t4_first_req');
  try {
    const res = await fetch(url, { ...init, headers, signal: controller.signal });
    perfMarkOnce('t5_first_res');

    if (res.status === 401 && auth && !_retried) {
      if (await singleFlightRefresh()) {
        return apiClient<T>(endpoint, { ...options, _retried: true });
      }
      secureStorage.clearTokens();
      window.dispatchEvent(new CustomEvent('airos_unauthorized'));
      throw {
        status: 401,
        code: 'UNAUTHORIZED',
        message: 'Session expired. Please sign in again.',
      } as ApiError;
    }

    if (res.status === 204) return undefined as T;

    const text = await res.text();
    let data: unknown;
    try {
      data = text ? JSON.parse(text) : undefined;
    } catch {
      data = undefined;
    }
    if (!res.ok) {
      const error = normalizeError(res.status, data);
      if (
        res.status === 503 && error.code === 'DATABASE_BUSY' &&
        (init.method ?? 'GET').toUpperCase() === 'GET' &&
        !cleanEndpoint.startsWith('/auth/') && !init.signal?.aborted &&
        _busyRetries < 2
      ) {
        clearTimeout(timer);
        await new Promise((resolve) => setTimeout(resolve, 1000 * 2 ** _busyRetries + Math.random() * 250));
        return apiClient<T>(endpoint, { ...options, _busyRetries: _busyRetries + 1 });
      }
      throw error;
    }
    return data as T;
  } catch (err: unknown) {
    if (typeof err === 'object' && err !== null && 'status' in err) throw err as ApiError;
    if (
      typeof err === 'object' && err !== null &&
      (err as { name?: unknown }).name === 'AbortError'
    ) {
      throw {
        status: 0,
        code: 'TIMEOUT',
        message: 'The request timed out. Check your connection and try again.',
      } as ApiError;
    }
    // fetch() rejections ("Failed to fetch") cover a wide transient range —
    // radio switches, TCP resets, preflight hiccups — not just real offline.
    // Give safe reads one short retry before surfacing an error.
    const method = (init.method ?? 'GET').toUpperCase();
    const isRead = method === 'GET' || method === 'HEAD';
    if (isRead && _netRetries < 1 && !init.signal?.aborted) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      return apiClient<T>(endpoint, { ...options, _netRetries: _netRetries + 1 });
    }
    const offline =
      typeof navigator !== 'undefined' && navigator.onLine === false;
    throw {
      status: 0,
      code: offline ? 'OFFLINE' : 'NETWORK_ERROR',
      message: offline
        ? "You're offline. Reconnect to the internet and we'll retry automatically."
        : 'Unable to connect to the Airco PMS server. Check your connection and try again.',
    } as ApiError;
  } finally {
    clearTimeout(timer);
  }
}
