/**
 * Registration API — public /api/v1/registration endpoints.
 * UNAUTHENTICATED by design: this is the pre-account onboarding flow.
 * Errors arrive as ApiError with `code` (e.g. INVALID_ORGANIZATION_CODE,
 * REGISTRATION_ALREADY_PENDING, EMAIL_ALREADY_EXISTS, USERNAME_TAKEN)
 * and optional `field` for inline form errors.
 */

import { apiClient } from './client';

export interface VerifyCodeResponse {
  valid: boolean;
  organization_name: string | null;
}

export interface RegistrationPayload {
  organization_code: string;
  full_name: string;
  username: string;
  email: string;
  phone?: string;
  date_of_birth?: string; // YYYY-MM-DD
  gender?: string;
  designation: string;
  department?: string;
  employment_type?: string;
  joining_date?: string; // YYYY-MM-DD
  reporting_manager?: string;
  salary?: string;
  salary_frequency?: 'monthly' | 'daily' | 'hourly';
  password: string;
}

export interface RegistrationSubmitResponse {
  request_uid: string;
  status: 'pending';
  organization_name: string;
}

export async function verifyCodeApi(code: string): Promise<VerifyCodeResponse> {
  return apiClient<VerifyCodeResponse>('/registration/verify-code', {
    method: 'POST',
    auth: false,
    body: JSON.stringify({ code }),
  });
}

export async function submitRegistrationApi(
  payload: RegistrationPayload,
): Promise<RegistrationSubmitResponse> {
  return apiClient<RegistrationSubmitResponse>('/registration', {
    method: 'POST',
    auth: false,
    body: JSON.stringify(payload),
  });
}
