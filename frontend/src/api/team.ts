/**
 * Department-manager team APIs — GET /team scope overview, GET/POST
 * /team/work (list + multi-employee allocation), PATCH cancel/reassign.
 * Server enforces the department scope; the client only sends filters.
 */

import { apiClient } from './client';
import { TaskWire } from './wire';

export interface TeamDepartment {
  department_uid: string;
  name: string;
  code: string | null;
  is_head: boolean;
  counts: Record<string, number>;
  overdue: number;
  employees: {
    employee_uid: string;
    name: string;
    job_title: string | null;
    is_head: boolean;
    open_tasks: number;
  }[];
}

export interface TeamWorkFilters {
  status?: string;
  employee_id?: string;
  date_from?: string;
  date_to?: string;
  priority?: string;
  zone_uid?: string;
}

export interface TeamWorkPayload {
  title: string;
  description?: string | null;
  notes?: string | null;
  work_type?: string | null;
  priority?: string;
  zone_uid?: string | null;
  due_date?: string | null;
  due_time?: string | null;
  scheduled_for?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  break_start_time?: string | null;
  break_end_time?: string | null;
  estimated_minutes?: number | null;
  checklist?: { text: string; completed?: boolean }[] | null;
  employee_uids: string[];
  allow_conflicts?: boolean;
}

export interface ScheduleConflict {
  kind: 'overlap' | 'duplicate';
  task_uid: string;
  title: string;
  employee_uid: string | null;
  employee_name: string | null;
  day: string | null;
  start_time: string | null;
  end_time: string | null;
}

/** Error thrown for HTTP 409 scheduling conflicts — carries the server's
 * conflict list so the UI can render and offer an explicit override. */
export class ConflictError extends Error {
  conflicts: ScheduleConflict[];
  constructor(conflicts: ScheduleConflict[], message?: string) {
    super(message ?? 'Schedule conflict');
    this.conflicts = conflicts;
  }
}

const withConflicts = async <T>(call: Promise<T>): Promise<T> => {
  try {
    return await call;
  } catch (e) {
    const err = e as { status?: number; details?: { conflicts?: ScheduleConflict[] }; message?: string };
    if (err.status === 409 && err.details?.conflicts?.length) {
      throw new ConflictError(err.details.conflicts, err.message);
    }
    throw e;
  }
};

export const teamApi = {
  overview: (): Promise<{ items: TeamDepartment[] }> =>
    apiClient<{ items: TeamDepartment[] }>('/team'),

  work: (departmentUid: string, filters: TeamWorkFilters = {}):
    Promise<{ items: TaskWire[]; total: number }> => {
    const params = new URLSearchParams({ department_id: departmentUid });
    Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    return apiClient(`/team/work?${params}`);
  },

  allocate: (departmentUid: string, payload: TeamWorkPayload):
    Promise<{ items: TaskWire[] }> =>
    withConflicts(apiClient(`/team/work?department_id=${departmentUid}`, {
      method: 'POST', body: JSON.stringify(payload),
    })),

  update: (taskUid: string, patch: Partial<TeamWorkPayload>):
    Promise<TaskWire> =>
    withConflicts(apiClient(`/team/work/${taskUid}`, {
      method: 'PATCH', body: JSON.stringify(patch),
    })),

  cancel: (taskUid: string): Promise<TaskWire> =>
    apiClient(`/team/work/${taskUid}/cancel`, { method: 'POST' }),

  reassign: (taskUid: string, employeeUid: string): Promise<TaskWire> =>
    apiClient(`/team/work/${taskUid}/reassign`, {
      method: 'POST', body: JSON.stringify({ employee_uid: employeeUid }),
    }),
};
