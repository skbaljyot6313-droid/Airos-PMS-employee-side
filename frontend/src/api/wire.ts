/**
 * Wire DTOs — explicit shapes of FastAPI payloads at /api/v1.
 * These mirror the backend serializers (see docs/backend_API.md §5–6);
 * the api layer maps them into the display types in src/types.
 */

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface AuthUserWire {
  uid: string;
  name: string;
  email: string;
  username: string;
  role: string;
  company_uid: string;
  property_uid: string | null;
  employee_uid: string | null;
  zone_uid: string | null;
  phone: string | null;
  job_title: string | null;
  company_name: string | null;
}

export interface CompanyWire {
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

export interface AuthResponseWire {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: AuthUserWire;
  company: CompanyWire;
}

export interface MeResponseWire {
  user: AuthUserWire;
  company: CompanyWire;
}

export interface TokenRefreshWire {
  access_token: string;
  token_type: string;
}

export interface MediaUploadWire {
  url: string;
  key: string;
}

// ---------------------------------------------------------------------------
// Lists & zones
// ---------------------------------------------------------------------------

export interface ListResponseWire<T> {
  items: T[];
  total: number;
  page?: number;
  limit?: number;
}

export interface ZoneWire {
  zone_uid: string;
  property_uid: string;
  area_uid: string | null;
  name: string;
  code: string | null;
  zone_type: string | null;
  floor: string | null;
  description: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Tasks — task_out
// ---------------------------------------------------------------------------

export interface TaskHistoryEventWire {
  event_uid: string;
  type: string;
  at: string;
  actor_name: string | null;
  note: string | null;
  photos: string[];
}

export interface TaskCompletionImageWire {
  image_uid: string;
  task_uid: string;
  event_uid: string | null;
  submission_uid: string | null;
  url: string;
  file_name: string | null;
  created_by_name: string | null;
  created_at: string;
}

export interface TaskCompletionSubmissionWire {
  submission_uid: string;
  task_uid: string;
  event_uid: string | null;
  attempt_number: number;
  employee_uid: string | null;
  employee_name: string | null;
  submitted_at: string;
  status: string;
  reviewed_at: string | null;
  reviewer_uid: string | null;
  reviewed_by_name: string | null;
  review_comment: string | null;
  images: TaskCompletionImageWire[];
}

export interface TaskChecklistItemWire {
  title: string;
  required?: boolean;
  description?: string | null;
}

export interface TaskVerificationWire {
  photo_required?: boolean;
  min_photos?: number;
  max_photos?: number;
  checklist_required?: boolean;
  supervisor_approval?: boolean;
}

export interface TaskWire {
  task_uid: string;
  ticket_number: string | null;
  property_uid: string;
  zone_uid: string | null;
  area_uid: string | null;
  room_uid: string | null;
  room_number: string | null;
  dorm_uid: string | null;
  dorm_name: string | null;
  bed_uids: string[] | null;
  washroom_uid: string | null;
  washroom_name: string | null;
  washroom_fixture_uid: string | null;
  washroom_fixture_label: string | null;
  supervisor_uid: string | null;
  supervisor_name: string | null;
  employee_uid: string | null;
  assigned_to_name: string | null;
  allocation_batch_id: string | null;
  allocation_status: string | null;
  allocation_method: string | null;
  allocation_reason: string | null;
  title: string;
  description: string | null;
  task_type: string;
  work_type: string | null;
  origin: string | null;
  status: string;
  priority: string;
  due_date: string | null;
  due_time: string | null;
  start_time: string | null;
  recurrence_start_date: string | null;
  recurrence_end_date: string | null;
  recurrence_window_end: string | null;
  created_by_name: string | null;
  recurrence: string | null;
  recurrence_interval_days: number | null;
  series_id: string | null;
  scheduled_for: string | null;
  expires_at: string | null;
  template_id: string | null;
  abandoned_at: string | null;
  abandoned_reason: string | null;
  abandoned_from_status: string | null;
  automation_rule: Record<string, unknown> | null;
  history: TaskHistoryEventWire[];
  completion_images: TaskCompletionImageWire[];
  completion_submissions: TaskCompletionSubmissionWire[];
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string;
  checklist: TaskChecklistItemWire[] | null;
  verification: TaskVerificationWire | null;
}

// ---------------------------------------------------------------------------
// Maintenance — ticket_out
// ---------------------------------------------------------------------------

export interface TicketEventWire {
  event_uid: string;
  action: string;
  actor_name: string | null;
  comment: string | null;
  at: string;
}

export interface TicketAttachmentWire {
  attachment_uid: string;
  url: string;
  file_name: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  kind: 'issue' | 'resolution';
  attempt: number;
  uploaded_by_name: string | null;
  created_at: string;
}

export interface MaintenanceTicketWire {
  ticket_uid: string;
  ticket_number: string | null;
  company_uid: string;
  property_uid: string;
  room_uid: string | null;
  room_number: string | null;
  dorm_uid: string | null;
  dorm_name: string | null;
  bed_uid: string | null;
  bed_number: string | null;
  washroom_uid: string | null;
  washroom_name: string | null;
  washroom_fixture_uid: string | null;
  washroom_fixture_label: string | null;
  location_label: string | null;
  reported_by_name: string | null;
  maintenance_type: string;
  issue: string;
  description: string | null;
  priority: string;
  status: string;
  assigned_to: string | null;
  assigned_to_name: string | null;
  zone_uid: string | null;
  allocation_batch_id: string | null;
  allocation_status: string | null;
  allocation_method: string | null;
  allocation_reason: string | null;
  due_date: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  resolution_notes: string | null;
  created_at: string;
  updated_at: string;
  events: TicketEventWire[];
  attachments: TicketAttachmentWire[];
}

// ---------------------------------------------------------------------------
// Eligible locations — GET /maintenance/eligible-locations
// ---------------------------------------------------------------------------

export interface EligibleRoomWire {
  room_uid: string;
  room_number: string;
  type: string | null;
  zone_name: string | null;
}

export interface EligibleDormWire {
  dorm_uid: string;
  name: string;
  dorm_type: string | null;
  zone_name: string | null;
  bed_count: number;
}

export interface EligibleLocationsWire {
  rooms: EligibleRoomWire[];
  dorms: EligibleDormWire[];
}

// ---------------------------------------------------------------------------
// Attendance — see src/api/attendance.ts for the endpoint map.
// ---------------------------------------------------------------------------

/** GET /attendance/today + POST transition responses. */
export interface WorkdayWire {
  state: 'not_started' | 'working' | 'on_break' | 'completed';
  /** Business date 'YYYY-MM-DD' (backend IST wall-clock convention). */
  date: string;
  started_at: string | null;
  break_started_at: string | null;
  ended_at: string | null;
}

/** Per-calendar-day record inside GET /attendance/calendar — real
 *  attendance_days statuses only; requests never paint day markers. */
export interface AttendanceDayWire {
  date: string; // 'YYYY-MM-DD'
  status: 'present' | 'week_off' | 'leave' | 'absent';
}

export type RequestTypeWire = 'leave' | 'week_off';

export type LeaveTypeWire =
  | 'casual_leave'
  | 'sick_leave'
  | 'paid_leave'
  | 'unpaid_leave'
  | 'other';

/** Date-range leave/week-off request record (POST /attendance/requests,
 *  embedded in the calendar envelope; GET /attendance/requests items). */
export interface AttendanceRequestWire {
  request_uid: string;
  from_date: string; // 'YYYY-MM-DD' — inclusive
  to_date: string; // 'YYYY-MM-DD' — inclusive
  request_type: RequestTypeWire;
  leave_type: LeaveTypeWire | null;
  requested_days: number;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  reason: string | null;
  review_comment: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  employee_uid: string | null;
  employee_name: string;
  created_at: string;
}

/** GET /attendance/calendar?month=YYYY-MM response envelope. */
export interface AttendanceMonthWire {
  days: AttendanceDayWire[];
  requests: AttendanceRequestWire[];
}

// ---------------------------------------------------------------------------
// Live location — current-position-only (Redis latest, 60 s TTL server-side)
// ---------------------------------------------------------------------------

/** POST /location/current body — `timestamp` is the device clock in epoch
 *  seconds; the server stamps its own server_timestamp for ordering. */
export interface LocationUpdateWire {
  latitude: number;
  longitude: number;
  accuracy: number;
  speed?: number;
  heading?: number;
  timestamp: number; // device epoch seconds
}

/** POST /location/current response — small ack, no echoed coordinates. */
export interface LocationAckWire {
  recorded: boolean;
  server_timestamp: number;
  expires_in: number;
}

/** GET /location/current — the caller's OWN latest fix only.
 *  is_live=false means no fix is held (never posted or TTL-expired);
 *  coordinate fields are then null. */
export interface LiveLocationWire {
  is_live: boolean;
  employee_uid: string;
  latitude: number | null;
  longitude: number | null;
  accuracy: number | null;
  speed: number | null;
  heading: number | null;
  device_timestamp: number | null;
  server_timestamp: number | null;
  age_seconds: number | null;
}
