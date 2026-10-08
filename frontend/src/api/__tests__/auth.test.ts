import { describe, it, expect } from 'vitest';
import { isEmployeeSession } from '../../context/authGate';
import { AuthResponseWire, MeResponseWire } from '../wire';

const user = (role: string, employee_uid: string | null) => ({
  uid: 'u-1',
  name: 'Alice',
  email: 'a@x.com',
  username: 'alice',
  role,
  company_uid: 'co-1',
  property_uid: 'prop-1',
  employee_uid,
  zone_uid: null,
  phone: null,
  job_title: 'Housekeeper',
  company_name: 'Acme',
});

const company = {
  company_uid: 'co-1',
  name: 'Acme Hotels',
  legal_name: null,
  brand_name: 'Acme',
  email: null,
  phone: null,
  address: null,
  pin_code: null,
  operational_day_start: '06:00',
  created_at: '2026-01-01T00:00:00Z',
};

describe('wire auth shapes', () => {
  it('fixtures satisfy AuthResponseWire / MeResponseWire', () => {
    const login: AuthResponseWire = {
      access_token: 'a',
      refresh_token: 'r',
      token_type: 'bearer',
      user: user('employee', 'emp-1'),
      company,
    };
    const me: MeResponseWire = { user: login.user, company };
    expect(login.user.role).toBe('employee');
    expect(me.user.employee_uid).toBe('emp-1');
  });
});

describe('isEmployeeSession', () => {
  it('accepts role=employee with an employee_uid', () => {
    expect(isEmployeeSession(user('employee', 'emp-1'))).toBe(true);
  });
  it.each([
    user('property_manager', 'emp-1'),
    user('super_admin', null),
    user('employee', null),
    user('employee', ''),
  ])('rejects %#', (u) => {
    expect(isEmployeeSession(u)).toBe(false);
  });
  it('rejects null/undefined', () => {
    expect(isEmployeeSession(null)).toBe(false);
    expect(isEmployeeSession(undefined)).toBe(false);
  });
});
