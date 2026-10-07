import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { User, Company, Employee, ApiError } from '../types';
import { secureStorage, errorMessage } from '../api/client';
import { loginApi, getMeApi, logoutApi, updateMeApi } from '../api/auth';
import { getZoneNameMap, invalidateZoneCache } from '../api/directory';
import { isEmployeeSession, EMPLOYEE_GATE_MESSAGE } from './authGate';

interface AuthContextType {
  user: User | null;
  company: Company | null;
  /** Workplace context — populated from /auth/me + zone name lookup. */
  employee: Employee | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  authError: string | null;
  login: (identifier: string, password: string) => Promise<void>;
  logout: () => void;
  updateProfile: (data: { name?: string; phone?: string; email?: string }) => Promise<void>;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [authError, setAuthError] = useState<string | null>(null);

  const logout = useCallback(() => {
    const refresh = secureStorage.getRefreshToken();
    secureStorage.clearTokens();
    invalidateZoneCache();
    setUser(null);
    setCompany(null);
    setEmployee(null);
    setAuthError(null);
    void logoutApi(refresh);
  }, []);

  /** Build the workplace context from /auth/me fields only; the zone name
   *  is patched in asynchronously (best-effort — never throws). */
  const enrichEmployee = useCallback(async (u: User) => {
    if (!u.employee_uid) {
      setEmployee(null);
      return;
    }
    setEmployee({
      id: u.employee_uid,
      name: u.name,
      property_uid: u.property_uid,
      zone_uid: u.zone_uid,
      zone_name: null,
      job_title: u.job_title,
    });
    if (u.zone_uid) {
      try {
        const zoneNames = await getZoneNameMap();
        const name = zoneNames.get(u.zone_uid) ?? null;
        if (name) {
          setEmployee((prev) => (prev && prev.zone_uid === u.zone_uid ? { ...prev, zone_name: name } : prev));
        }
      } catch {
        // zone name is presentation-only — a failure must not kill the session
      }
    }
  }, []);

  const applySession = useCallback(
    async (u: User, c: Company) => {
      if (!isEmployeeSession(u)) {
        throw {
          status: 403,
          code: 'FORBIDDEN',
          message: EMPLOYEE_GATE_MESSAGE,
        } as ApiError;
      }
      setUser(u);
      setCompany(c);
      await enrichEmployee(u);
    },
    [enrichEmployee]
  );

  const refreshSession = useCallback(async () => {
    const access = secureStorage.getToken();
    const refresh = secureStorage.getRefreshToken();
    if (!access && !refresh) {
      setIsLoading(false);
      return;
    }
    try {
      setIsLoading(true);
      const data = await getMeApi();
      await applySession(data.user, data.company);
      setAuthError(null);
    } catch (err: unknown) {
      const status =
        typeof err === 'object' && err !== null ? (err as { status?: number }).status : undefined;
      if (status === 401) {
        secureStorage.clearTokens();
      } else if (status === 403) {
        // Authenticated but not an operations employee — drop the session
        // and surface the gate message on the login screen.
        secureStorage.clearTokens();
        setAuthError(errorMessage(err, EMPLOYEE_GATE_MESSAGE));
      }
      // Network / 5xx: keep tokens so a retry can restore the session.
      console.warn('Session restoration failed:', err);
    } finally {
      setIsLoading(false);
    }
  }, [applySession]);

  useEffect(() => {
    void refreshSession();

    const handleUnauthorized = () => {
      secureStorage.clearTokens();
      setUser(null);
      setCompany(null);
      setEmployee(null);
      setAuthError('Your session has timed out. Please sign in again.');
    };
    window.addEventListener('airos_unauthorized', handleUnauthorized);
    return () => window.removeEventListener('airos_unauthorized', handleUnauthorized);
  }, [refreshSession]);

  const login = async (identifier: string, password: string) => {
    try {
      setIsLoading(true);
      setAuthError(null);
      const data = await loginApi(identifier.trim(), password);
      secureStorage.setTokens(data.access_token, data.refresh_token);
      await applySession(data.user, data.company);
    } catch (err: unknown) {
      const msg = errorMessage(err, 'Unable to sign in. Please verify your credentials.');
      setAuthError(msg);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const updateProfile = async (data: { name?: string; phone?: string; email?: string }) => {
    const u = await updateMeApi(data);
    setUser(u);
    if (u.employee_uid) {
      setEmployee((prev) => (prev ? { ...prev, name: u.name } : prev));
    }
  };

  const clearError = () => setAuthError(null);

  return (
    <AuthContext.Provider
      value={{
        user,
        company,
        employee,
        isAuthenticated: isEmployeeSession(user),
        isLoading,
        authError,
        login,
        logout,
        updateProfile,
        clearError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
