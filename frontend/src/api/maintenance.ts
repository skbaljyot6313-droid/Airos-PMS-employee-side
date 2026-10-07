/**
 * Maintenance API — tickets, coverage-scoped locations, and the zone
 * workspace assembled from /zones + /maintenance/eligible-locations +
 * /maintenance (the only structure data this backend exposes).
 *
 * Backend guarantees relied on here:
 * - GET /maintenance is scoped to tickets assigned to me OR reported by me.
 * - POST /maintenance enforces zone/area coverage server-side (403 outside).
 * - Zone names are unique per property, and /maintenance/eligible-locations
 *   returns zone_name only — matching on name is therefore safe.
 */

import { apiClient } from './client';
import { getZoneNameMap, getZonesCached } from './directory';
import {
  EligibleLocationsWire,
  ListResponseWire,
  MaintenanceTicketWire,
} from './wire';
import {
  MaintenanceTicket,
  MaintenanceCategory,
  MaintenanceStatus,
  EligibleLocation,
  ZoneSummary,
  ZoneWorkspace,
  ZoneResource,
} from '../types';

const titleCase = (s: string): string =>
  s.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());

/** Backend maintenance_type → display category (matches the picklist). */
export const MAINTENANCE_TYPE_LABELS: Record<string, MaintenanceCategory> = {
  electrical: 'Electrical',
  plumbing: 'Plumbing',
  civil: 'Civil',
  carpentry: 'Carpentry',
  hvac: 'HVAC',
  painting: 'Painting',
  furniture: 'Furniture',
  appliance: 'Appliance',
  internet: 'Internet',
  water_drainage: 'Water / Drainage',
  cleaning_equipment: 'Cleaning Equipment',
  safety_security: 'Safety',
  other: 'Other',
};

const TYPE_WIRE: Record<MaintenanceCategory, string> = {
  Electrical: 'electrical',
  Plumbing: 'plumbing',
  Civil: 'civil',
  Carpentry: 'carpentry',
  HVAC: 'hvac',
  Painting: 'painting',
  Furniture: 'furniture',
  Appliance: 'appliance',
  Internet: 'internet',
  'Water / Drainage': 'water_drainage',
  'Cleaning Equipment': 'cleaning_equipment',
  Safety: 'safety_security',
  Other: 'other',
};

/** Display category → backend wire value. */
export const maintenanceTypeToWire = (label: MaintenanceCategory): string =>
  TYPE_WIRE[label] ?? label.toLowerCase();

export const wireToDisplayStatus = (s: string): MaintenanceStatus =>
  s === 'open' ? 'reported' : (s as MaintenanceStatus);

/** Wire statuses that block a resource (raise-ticket is gated on these). */
const ACTIVE_TICKET_STATUSES = new Set(['open', 'assigned', 'in_progress', 'on_hold']);

const isActiveWire = (t: { status: string }) => ACTIVE_TICKET_STATUSES.has(t.status);

/** Synthetic group for eligible locations the backend reports without a zone. */
const UNZONED_ID = '__unzoned__';
const UNZONED_NAME = 'Other covered locations';

// ---------------------------------------------------------------------------
// Ticket mapping
// ---------------------------------------------------------------------------

export const mapTicket = (
  t: MaintenanceTicketWire,
  zoneNames: Map<string, string>,
  myEmployeeUid?: string
): MaintenanceTicket => {
  const attachments = t.attachments ?? [];
  // Raw backend paths — views resolve them via mediaUrl() at render time.
  const issuePhotos = attachments
    .filter((a) => a.kind === 'issue')
    .map((a) => a.url)
    .filter((u): u is string => !!u);
  const resolutionPhotos = attachments
    .filter((a) => a.kind === 'resolution')
    .map((a) => a.url)
    .filter((u): u is string => !!u);

  const assignedUid: string | null = t.assigned_to ?? null;

  return {
    id: t.ticket_uid,
    ticket_number: t.ticket_number ?? null,
    issue: t.issue,
    category:
      MAINTENANCE_TYPE_LABELS[t.maintenance_type] ??
      (titleCase(t.maintenance_type ?? 'other') as MaintenanceCategory),
    location_name:
      (t.room_number ? `Room ${t.room_number}` : null) ??
      t.location_label ??
      t.dorm_name ??
      t.washroom_name ??
      'Property',
    zone_uid: t.zone_uid ?? null,
    zone_name: t.zone_uid ? zoneNames.get(t.zone_uid) ?? null : null,
    priority: t.priority as MaintenanceTicket['priority'],
    status: wireToDisplayStatus(t.status),
    description: t.description ?? null,
    photos: issuePhotos,
    resolution_photos: resolutionPhotos,
    room_uid: t.room_uid ?? null,
    dorm_uid: t.dorm_uid ?? null,
    bed_uid: t.bed_uid ?? null,
    washroom_uid: t.washroom_uid ?? null,
    washroom_fixture_uid: t.washroom_fixture_uid ?? null,
    assigned_to_employee_id: assignedUid,
    assigned_to_name: t.assigned_to_name ?? null,
    reported_by_name: t.reported_by_name ?? null,
    // Server scope: an employee only sees tickets assigned to them or ones
    // they reported — not assigned ⇒ they reported it. The wire does not
    // carry reported_by_uid, so this is the best available heuristic.
    is_reported_by_me: !!myEmployeeUid && assignedUid !== myEmployeeUid,
    created_at: t.created_at ?? null,
    resolved_at: t.resolved_at ?? null,
    closed_at: t.closed_at ?? null,
    resolution_notes: t.resolution_notes ?? null,
    history: (t.events ?? []).map((e) => ({
      status: e.action,
      timestamp: e.at,
      actor_name: e.actor_name,
      notes: e.comment,
    })),
  };
};

// ---------------------------------------------------------------------------
// Ticket endpoints
// ---------------------------------------------------------------------------

export async function fetchMaintenanceApi(myEmployeeUid?: string): Promise<{
  assigned_to_me: MaintenanceTicket[];
  reported_by_me: MaintenanceTicket[];
}> {
  const [res, zoneNames] = await Promise.all([
    apiClient<ListResponseWire<MaintenanceTicketWire>>('/maintenance', { method: 'GET' }),
    getZoneNameMap(),
  ]);
  const tickets = res.items.map((t) => mapTicket(t, zoneNames, myEmployeeUid));
  return {
    assigned_to_me: tickets.filter((t) => !t.is_reported_by_me),
    reported_by_me: tickets.filter((t) => t.is_reported_by_me),
  };
}

export async function getMaintenanceDetailApi(id: string, myEmployeeUid?: string): Promise<MaintenanceTicket> {
  const [t, zoneNames] = await Promise.all([
    apiClient<MaintenanceTicketWire>(`/maintenance/${encodeURIComponent(id)}`, { method: 'GET' }),
    getZoneNameMap(),
  ]);
  return mapTicket(t, zoneNames, myEmployeeUid);
}

export async function createMaintenanceTicketApi(payload: {
  property_uid: string;
  room_uid?: string;
  dorm_uid?: string;
  bed_uid?: string;
  washroom_uid?: string;
  washroom_fixture_uid?: string;
  category: MaintenanceCategory;
  issue: string;
  description?: string;
  priority: string;
  attachment_urls?: string[];
}): Promise<MaintenanceTicket> {
  const { category, ...rest } = payload;
  const t = await apiClient<MaintenanceTicketWire>('/maintenance', {
    method: 'POST',
    body: JSON.stringify({ ...rest, maintenance_type: maintenanceTypeToWire(category) }),
  });
  return mapTicket(t, new Map());
}

export async function startMaintenanceTicketApi(id: string): Promise<MaintenanceTicket> {
  const t = await apiClient<MaintenanceTicketWire>(`/maintenance/${encodeURIComponent(id)}/start`, {
    method: 'POST',
  });
  return mapTicket(t, new Map());
}

export async function resolveMaintenanceTicketApi(
  id: string,
  payload: { resolution_notes: string; photo_urls?: string[] }
): Promise<MaintenanceTicket> {
  const t = await apiClient<MaintenanceTicketWire>(`/maintenance/${encodeURIComponent(id)}/resolve`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return mapTicket(t, new Map());
}

// ---------------------------------------------------------------------------
// Eligible locations (coverage-scoped raise targets)
// ---------------------------------------------------------------------------

const fetchEligibleWire = (): Promise<EligibleLocationsWire> =>
  apiClient<EligibleLocationsWire>('/maintenance/eligible-locations');

export async function fetchEligibleLocationsApi(): Promise<EligibleLocation[]> {
  const res = await fetchEligibleWire();
  const rooms: EligibleLocation[] = (res.rooms ?? []).map((r) => ({
    id: r.room_uid,
    kind: 'room',
    name: `Room ${r.room_number}`,
    zone_name: r.zone_name ?? null,
    bed_count: null,
  }));
  const dorms: EligibleLocation[] = (res.dorms ?? []).map((d) => ({
    id: d.dorm_uid,
    kind: 'dorm',
    name: d.name,
    zone_name: d.zone_name ?? null,
    bed_count: d.bed_count ?? null,
  }));
  return [...rooms, ...dorms];
}

// ---------------------------------------------------------------------------
// Zone workspace — /zones + /maintenance/eligible-locations + /maintenance
// ---------------------------------------------------------------------------

interface ZoneBucket {
  /** ZoneSummary.id — zone_uid or the synthetic '__unzoned__'. */
  id: string;
  name: string;
  type: string | null;
  area_uid: string | null;
  rooms: { uid: string; label: string }[];
  dorms: { uid: string; label: string; bed_count: number | null }[];
  unitUids: Set<string>;
}

const buildZoneBuckets = (
  zones: { zone_uid: string; name: string; zone_type: string | null; area_uid: string | null }[],
  eligible: EligibleLocationsWire
): ZoneBucket[] => {
  const buckets: ZoneBucket[] = [];

  const bucketFor = (zoneName: string | null): ZoneBucket => {
    let b = buckets.find((x) => (zoneName ? x.name === zoneName : x.id === UNZONED_ID));
    if (!b) {
      if (zoneName === null) {
        b = { id: UNZONED_ID, name: UNZONED_NAME, type: null, area_uid: null, rooms: [], dorms: [], unitUids: new Set() };
      } else {
        const z = zones.find((zz) => zz.name === zoneName);
        b = {
          id: z?.zone_uid ?? `zone:${zoneName}`,
          name: zoneName,
          type: z?.zone_type ?? null,
          area_uid: z?.area_uid ?? null,
          rooms: [],
          dorms: [],
          unitUids: new Set(),
        };
      }
      buckets.push(b);
    }
    return b;
  };

  for (const r of eligible.rooms ?? []) {
    const b = bucketFor(r.zone_name ?? null);
    const label = `Room ${r.room_number}`;
    b.rooms.push({ uid: r.room_uid, label });
    b.unitUids.add(r.room_uid);
  }
  for (const d of eligible.dorms ?? []) {
    const b = bucketFor(d.zone_name ?? null);
    b.dorms.push({ uid: d.dorm_uid, label: d.name, bed_count: d.bed_count ?? null });
    b.unitUids.add(d.dorm_uid);
  }
  return buckets;
};

/** Active (blocking) visible tickets whose target belongs to the bucket —
 *  matched by eligible unit uid, or by the ticket's own zone_uid. */
const zoneActiveTickets = (
  tickets: MaintenanceTicket[],
  bucket: ZoneBucket
): MaintenanceTicket[] =>
  tickets.filter((t) => {
    if (!ACTIVE_TICKET_STATUSES.has(t.status === 'reported' ? 'open' : t.status)) return false;
    const targetUid = t.room_uid ?? t.dorm_uid ?? t.bed_uid ?? t.washroom_uid ?? t.washroom_fixture_uid;
    return (targetUid !== null && bucket.unitUids.has(targetUid)) || t.zone_uid === bucket.id;
  });

const ticketTargetUid = (t: MaintenanceTicket): string =>
  t.room_uid ?? t.dorm_uid ?? t.bed_uid ?? t.washroom_uid ?? t.washroom_fixture_uid ?? '';

/**
 * Covered zones = zones containing at least one eligible (coverage-scoped)
 * room or dorm. Beds, washrooms and fixtures are not listable through this
 * backend, so counts other than rooms/dorms/beds report as unknown (null).
 *
 * The single /maintenance fetch doubles as the ticket list — the caller gets
 * the assigned/reported split in the same payload (no second request).
 */
export async function fetchMaintenanceZonesApi(myEmployeeUid?: string): Promise<{
  zones: ZoneSummary[];
  assigned_to_me: MaintenanceTicket[];
  reported_by_me: MaintenanceTicket[];
}> {
  const [zonesItems, eligible, ticketsRes, zoneNames] = await Promise.all([
    getZonesCached(),
    fetchEligibleWire().catch(() => ({ rooms: [], dorms: [] })),
    apiClient<ListResponseWire<MaintenanceTicketWire>>('/maintenance', { method: 'GET' }).catch(
      () => ({ items: [] as MaintenanceTicketWire[], total: 0 })
    ),
    getZoneNameMap(),
  ]);

  const buckets = buildZoneBuckets(zonesItems, eligible);
  const tickets = ticketsRes.items.map((t) => mapTicket(t, zoneNames, myEmployeeUid));

  const zones: ZoneSummary[] = buckets.map((b) => ({
    id: b.id,
    name: b.name,
    type: b.type,
    area_uid: b.area_uid,
    area_name: null,
    counts: {
      rooms: b.rooms.length,
      dorms: b.dorms.length,
      beds: b.dorms.reduce((n, d) => n + (d.bed_count ?? 0), 0),
      washrooms: null, // not exposed by this backend
      other: 0,
    },
    open_issues: zoneActiveTickets(tickets, b).length,
  }));

  return {
    zones,
    assigned_to_me: tickets.filter((t) => !t.is_reported_by_me),
    reported_by_me: tickets.filter((t) => t.is_reported_by_me),
  };
}

export async function fetchZoneWorkspaceApi(zoneId: string, myEmployeeUid?: string): Promise<ZoneWorkspace> {
  const [zonesItems, eligible, ticketsRes, zoneNames] = await Promise.all([
    getZonesCached(),
    fetchEligibleWire(),
    apiClient<ListResponseWire<MaintenanceTicketWire>>('/maintenance', { method: 'GET' }).catch(
      () => ({ items: [] as MaintenanceTicketWire[], total: 0 })
    ),
    getZoneNameMap(),
  ]);

  const buckets = buildZoneBuckets(zonesItems, eligible);
  const bucket = buckets.find((b) => b.id === zoneId);
  const tickets = ticketsRes.items.map((t) => mapTicket(t, zoneNames, myEmployeeUid));
  const active = bucket ? zoneActiveTickets(tickets, bucket) : [];

  const ticketForUnit = (uid: string) =>
    active.find((t) => ticketTargetUid(t) === uid) ?? null;

  const resources: ZoneResource[] = [];
  if (bucket) {
    for (const r of bucket.rooms) {
      const t = ticketForUnit(r.uid);
      resources.push({
        id: r.uid,
        kind: 'room',
        type: 'room',
        name: r.label,
        state: null, // unit state is not exposed through these endpoints
        zone_uid: zoneId,
        parent_uid: null,
        path: [bucket.name, r.label],
        active_ticket_id: t?.id ?? null,
        active_ticket_number: t?.ticket_number ?? null,
        eligible: true,
      });
    }
    for (const d of bucket.dorms) {
      const t = ticketForUnit(d.uid);
      resources.push({
        id: d.uid,
        kind: 'dorm',
        type: 'dorm',
        name: d.label,
        state: null,
        zone_uid: zoneId,
        parent_uid: null,
        path: [bucket.name, d.label],
        active_ticket_id: t?.id ?? null,
        active_ticket_number: t?.ticket_number ?? null,
        eligible: true,
        bed_count: d.bed_count,
        // Beds are not enumerable through this backend — no per-bed drill-in.
        detail_available: false,
      });
    }
  }

  const summary: ZoneSummary = {
    id: zoneId,
    name: bucket?.name ?? 'Zone',
    type: bucket?.type ?? null,
    area_uid: bucket?.area_uid ?? null,
    area_name: null,
    counts: {
      rooms: bucket?.rooms.length ?? 0,
      dorms: bucket?.dorms.length ?? 0,
      beds: bucket?.dorms.reduce((n, d) => n + (d.bed_count ?? 0), 0) ?? 0,
      washrooms: null,
      other: 0,
    },
    open_issues: active.length,
  };

  return {
    zone: summary,
    resources,
    // Include tickets whose target (bed/washroom/fixture) has no tile —
    // the resource_id still carries the uid for display.
    active_tickets: active.map((t) => ({
      id: t.id,
      ticket_number: t.ticket_number,
      resource_id: ticketTargetUid(t),
      issue: t.issue,
      category: t.category,
      status: t.status,
      priority: t.priority,
    })),
  };
}
