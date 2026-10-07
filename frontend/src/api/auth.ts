/**
 * Authentication API — /api/v1/auth endpoints.
 * Login returns access + refresh tokens with the user/company payload;
 * /auth/me restores the session after app restart.
 */

import { apiClient } from './client';
import { AuthSession, User, Company } from '../types';

export async function loginApi(identifier: string, password: string): Promise<AuthSession> {
  return apiClient<AuthSession>('/auth/login', {
    method: 'POST',
    auth: false,
    body: JSON.stringify({ identifier, password }),
  });
}

export async function getMeApi(): Promise<{ user: User; company: Company }> {
  return apiClient<{ user: User; company: Company }>('/auth/me', { method: 'GET' });
}

export async function logoutApi(refreshToken: string | null): Promise<void> {
  if (!refreshToken) return;
  try {
    await apiClient('/auth/logout', {
      method: 'POST',
      auth: false,
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  } catch {
    /* revocation is best-effort — local tokens are cleared regardless */
  }
}

export async function updateMeApi(payload: {
  name?: string;
  phone?: string;
  email?: string;
}): Promise<User> {
  return apiClient<User>('/auth/me', { method: 'PATCH', body: JSON.stringify(payload) });
}
