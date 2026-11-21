/**
 * Salary — employee read-only view of their own finalized payroll.
 * Endpoints: GET /salary/me, /salary/me/history, /salary/me/periods/{period},
 * /salary/me/periods/{period}/slip.pdf. Nothing here can write payroll data.
 */

import { apiClient, API_BASE } from './client';

export interface SalaryComponent {
  code: string;
  label: string;
  amount: string;
  basis?: string;
}

export interface SalaryPeriodView {
  period: string;
  status: 'open' | 'submitted' | 'approved' | 'paid';
  is_estimate: boolean;
  gross: string;
  total_deductions: string;
  net: string;
  earnings: SalaryComponent[];
  deductions: SalaryComponent[];
  metrics: Record<string, string | number>;
  notes: string[];
  payment_method: string | null;
  paid_at: string | null;
  approved_at: string | null;
}

export interface SalaryOverview {
  structure: null | {
    calc_method: 'monthly' | 'daily' | 'hourly';
    effective_from: string;
    basic: string;
    hra: string;
    allowances: { name: string; amount: string }[];
    incentive: string;
    overtime_rate: string;
  };
  last_paid: SalaryPeriodView | null;
  last_finalized: SalaryPeriodView | null;
  draft_estimate: SalaryPeriodView | null;
}

export const salaryApi = {
  overview: () => apiClient<SalaryOverview>('/salary/me'),
  history: () => apiClient<{ items: SalaryPeriodView[] }>('/salary/me/history'),
  period: (period: string) => apiClient<SalaryPeriodView>(`/salary/me/periods/${period}`),
  slipUrl: (period: string) => `${API_BASE}/salary/me/periods/${period}/slip.pdf`,
};
