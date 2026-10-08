/**
 * Type definitions for AiROS Staff
 *
 * Wire contract: FastAPI backend at /api/v1 (tool_21/backend). IDs are
 * `*_uid` strings; the api layer normalizes responses into the display
 * shapes below — screens never read raw backend fields.
 */

export type UserRole =
  | 'super_admin'
  | 'property_manager'
  | 'human_resource'
  | 'department_manager'
  | 'employee';

/** Backend user_to_out shape. */
export interface User {
  uid: string;
  name: string;
  email: string;
  username: string;
  role: UserRole;
  company_uid: string;
  property_uid: string | null;
  employee_uid: string | null;
  zone_uid: string | null;
  phone: string | null;
  job_title: string | null;
  company_name: string | null;
}

export interface Company {
  company_uid: string;
  name: string;
  legal_name: string | null;
  brand_name: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  pin_code: string | null;
  operational_day_start: string;
  created_at: string;
}

/**
 * Employee workplace context — populated ONLY from /auth/me fields plus an
 * optional /zones name lookup. Anything the backend doesn't expose is left
 * out rather than fabricated.
 */
export interface Employee {
  id: string; // employee_uid
  name: string;
  property_uid: string | null;
  zone_uid: string | null;
  zone_name: string | null;
  job_title: string | null;
}

export interface AuthSession {
  access_token: string;
  refresh_token: string;
  user: User;
  company: Company;
}

export interface ApiFieldError {
  field?: string;
  message: string;
  code?: string;
}

export interface ApiError {
  status: number;
  code?: string;
  message: string;
  fieldErrors?: ApiFieldError[];
}

// ---------------------------------------------------------------------------
// Tasks — display model normalized from task_out()
// ---------------------------------------------------------------------------

export type TaskStatus =
  | 'pending'
  | 'assigned'
  | 'in_progress'
  | 'submitted'
  | 'reopened'
  | 'completed'
  | 'cancelled'
  | 'abandoned'
  | 'scheduled'
  | 'overdue';

export type TaskBucket = 'to_do' | 'in_review' | 'done';

export type TaskPriority = 'low' | 'medium' | 'high' | 'critical' | 'urgent';

export interface ChecklistItem {
  id: string;
  label: string;
  required: boolean;
  completed: boolean;
  description?: string | null;
}

export interface VerificationConfig {
  photo_required: boolean;
  min_photos: number;
  max_photos: number;
  checklist_required?: boolean;
  supervisor_approval?: boolean;
}

export interface EvidenceItem {
  id: string;
  url: string;
  uploaded_at?: string | null;
  filename?: string | null;
}

export interface TaskEvent {
  id: string;
  event_type: string;
  timestamp: string;
  notes?: string | null;
  actor_name: string | null;
}

/** One submission attempt (mapped from completion_submissions) — read-only
 *  record of photos already sent for review. */
export interface TaskSubmission {
  attempt: number;
  submitted_at: string | null;
  status: string;
  review_comment: string | null;
  reviewed_by_name: string | null;
  photos: EvidenceItem[];
}

export interface Task {
  id: string; // task_uid
  ticket_number: string | null;
  title: string;
  category: string; // task_type / work_type for display
  location_name: string;
  zone_uid: string | null;
  zone_name: string | null;
  priority: TaskPriority;
  status: TaskStatus;
  /** ISO datetime when known; null for date-only dues. */
  due_at: string | null;
  due_date: string | null;
  due_time: string | null;
  scheduled_for?: string | null;
  expires_at?: string | null;
  instructions: string | null;
  checklist: ChecklistItem[];
  verification_config: VerificationConfig;
  evidence: EvidenceItem[];
  /** Earlier completion attempts — shown read-only when a task is reopened. */
  prior_submissions: TaskSubmission[];
  reopen_reason?: string | null;
  history: TaskEvent[];
  assigned_to_employee_id: string | null;
  assigned_to_name: string | null;
  supervisor_name: string | null;
}

// ---------------------------------------------------------------------------
// Maintenance
// ---------------------------------------------------------------------------

export type MaintenanceCategory =
  | 'Electrical'
  | 'Plumbing'
  | 'Civil'
  | 'Carpentry'
  | 'HVAC'
  | 'Painting'
  | 'Furniture'
  | 'Appliance'
  | 'Internet'
  | 'Water / Drainage'
  | 'Cleaning Equipment'
  | 'Safety'
  | 'Other';

/** Display status — 'open' wire tickets render as 'reported'. */
export type MaintenanceStatus =
  | 'reported'
  | 'assigned'
  | 'in_progress'
  | 'on_hold'
  | 'resolved'
  | 'closed'
  | 'cancelled';

export type MaintenancePriority = 'low' | 'medium' | 'high' | 'critical';

export interface MaintenanceTicket {
  id: string; // ticket_uid — routing key
  ticket_number: string | null; // MT-YYYY-NNNNN display id
  issue: string;
  category: MaintenanceCategory;
  location_name: string;
  zone_uid: string | null;
  zone_name: string | null;
  priority: MaintenancePriority;
  status: MaintenanceStatus;
  description?: string | null;
  /** Issue photos (attachments kind='issue'). */
  photos: string[];
  resolution_photos?: string[];
  /** Resource linkage for workspace matching. */
  room_uid: string | null;
  dorm_uid: string | null;
  bed_uid: string | null;
  washroom_uid: string | null;
  washroom_fixture_uid: string | null;
  assigned_to_employee_id: string | null;
  assigned_to_name: string | null;
  reported_by_name: string | null;
  /** Visible tickets are always mine (assigned or reported) — set by mapper. */
  is_reported_by_me: boolean;
  created_at: string | null;
  resolved_at?: string | null;
  closed_at?: string | null;
  resolution_notes?: string | null;
  history?: {
    status: string;
    timestamp: string;
    actor_name: string | null;
    notes?: string | null;
  }[];
}

// ---------------------------------------------------------------------------
// Zones / workspace
// ---------------------------------------------------------------------------

export type ZoneResourceType = 'room' | 'dorm' | 'bed' | 'washroom' | 'fixture';

/** Mirrors backend visual_state + 'inactive'. */
export type ZoneResourceState =
  | 'available'
  | 'occupied'
  | 'cleaning'
  | 'maintenance'
  | 'inactive';

export interface ZoneResource {
  id: string; // room_uid | dorm_uid | bed_uid | washroom_uid | fixture_uid
  kind: ZoneResourceType;
  type: ZoneResourceType;
  name: string;
  /** null = unknown — unit state is not exposed through this backend. */
  state: ZoneResourceState | null;
  zone_uid: string;
  /** dorm_uid for beds & dorm washrooms; washroom_uid for fixtures. */
  parent_uid: string | null;
  /** Fixtures submit alongside their washroom. */
  washroom_uid?: string;
  path: string[];
  /** uid of an employee-visible active ticket on this resource. */
  active_ticket_id: string | null;
  /** MT-number of that ticket, for display chips. */
  active_ticket_number?: string | null;
  /** Whether the employee may raise a ticket here (coverage). */
  eligible: boolean;
  /** Bed capacity for dorms (from eligible-locations); null when unknown. */
  bed_count?: number | null;
  /** false when sub-resources (e.g. dorm beds) cannot be enumerated. */
  detail_available?: boolean;
}

export interface ZoneSummary {
  id: string; // zone_uid
  name: string;
  type: string | null;
  area_uid: string | null;
  area_name: string | null;
  counts: {
    rooms: number;
    dorms: number;
    beds: number;
    /** null = unknown — washrooms are not listable through this backend. */
    washrooms: number | null;
    other: number;
  };
  /** Active visible maintenance tickets in this zone. */
  open_issues: number;
}

export interface ZoneWorkspace {
  zone: ZoneSummary;
  resources: ZoneResource[];
  active_tickets: {
    id: string;
    ticket_number: string | null;
    resource_id: string;
    issue: string;
    category: MaintenanceCategory;
    status: MaintenanceStatus;
    priority: MaintenancePriority;
  }[];
}

/** Locked target carried from the workspace into the raise-ticket flow. */
export interface MaintenanceTarget {
  kind: ZoneResourceType;
  uid: string;
  washroom_uid?: string; // required when kind === 'fixture'
  zone_id: string;
  name: string;
  path: string[];
}

export interface EligibleLocation {
  id: string; // room_uid | dorm_uid
  kind: 'room' | 'dorm';
  name: string;
  zone_name: string | null;
  /** Dorm bed capacity from eligible-locations; null for rooms/unknown. */
  bed_count?: number | null;
}

// ---------------------------------------------------------------------------
// Attendance — display model (see api/attendance.ts for the wire contract)
// ---------------------------------------------------------------------------

export type WorkdayState = 'not_started' | 'working' | 'on_break' | 'completed';

export type AttendanceDayStatus =
  | 'present'
  | 'week_off'
  | 'leave'
  | 'absent';

export type RequestType = 'leave' | 'week_off';

export type LeaveType =
  | 'casual_leave'
  | 'sick_leave'
  | 'paid_leave'
  | 'unpaid_leave'
  | 'other';

export type RequestStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';

/** One business day of work — start/break/end stamps are ISO datetimes. */
export interface Workday {
  state: WorkdayState;
  /** Business date 'YYYY-MM-DD' (local calendar day). */
  date: string;
  started_at: string | null;
  break_started_at: string | null;
  ended_at: string | null;
}

export interface AttendanceDay {
  date: string; // 'YYYY-MM-DD'
  status: AttendanceDayStatus;
}

/** A date-range leave / week-off request — [from_date..to_date] inclusive. */
export interface DayOffRequest {
  id: string; // request_uid
  from_date: string; // 'YYYY-MM-DD'
  to_date: string; // 'YYYY-MM-DD'
  request_type: RequestType;
  leave_type: LeaveType | null;
  requested_days: number;
  status: RequestStatus;
  reason: string | null;
  created_at: string;
}
