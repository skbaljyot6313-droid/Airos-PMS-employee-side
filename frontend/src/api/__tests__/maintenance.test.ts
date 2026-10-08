import { describe, it, expect } from 'vitest';
import {
  mapTicket,
  wireToDisplayStatus,
  MAINTENANCE_TYPE_LABELS,
  maintenanceTypeToWire,
} from '../maintenance';
import { MaintenanceTicketWire } from '../wire';
import { MaintenanceCategory } from '../../types';

const baseWire = (over: Partial<MaintenanceTicketWire> = {}): MaintenanceTicketWire => ({
  ticket_uid: 'mt-1',
  ticket_number: 'MT-2026-00042',
  company_uid: 'co-1',
  property_uid: 'prop-1',
  room_uid: 'room-1',
  room_number: '204',
  dorm_uid: null,
  dorm_name: null,
  bed_uid: null,
  bed_number: null,
  washroom_uid: null,
  washroom_name: null,
  washroom_fixture_uid: null,
  washroom_fixture_label: null,
  location_label: '204',
  reported_by_name: 'Reporter',
  maintenance_type: 'plumbing',
  issue: 'Leaking sink',
  description: 'Drip under cabinet',
  priority: 'high',
  status: 'open',
  assigned_to: 'emp-2',
  assigned_to_name: 'Bob',
  zone_uid: 'zone-1',
  allocation_batch_id: null,
  allocation_status: 'auto_assigned',
  allocation_method: null,
  allocation_reason: null,
  due_date: null,
  resolved_at: null,
  closed_at: null,
  resolution_notes: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  events: [],
  attachments: [],
  ...over,
});

const zones = new Map([['zone-1', 'North Wing']]);

describe('mapTicket', () => {
  it('maps wire open → display reported; other statuses pass through', () => {
    expect(mapTicket(baseWire({ status: 'open' }), zones).status).toBe('reported');
    for (const s of ['assigned', 'in_progress', 'on_hold', 'resolved', 'closed', 'cancelled']) {
      expect(mapTicket(baseWire({ status: s }), zones).status).toBe(s);
    }
    expect(wireToDisplayStatus('open')).toBe('reported');
  });

  it('splits attachments into issue/resolution photos keeping raw urls', () => {
    const att = (uid: string, kind: 'issue' | 'resolution', url: string) => ({
      attachment_uid: uid,
      url,
      file_name: url,
      mime_type: 'image/jpeg',
      size_bytes: 1,
      kind,
      attempt: 1,
      uploaded_by_name: 'A',
      created_at: '2026-01-01T00:00:00Z',
    });
    const t = mapTicket(
      baseWire({ attachments: [att('a1', 'issue', '/uploads/i1.jpg'), att('a2', 'resolution', '/uploads/r1.jpg')] }),
      zones
    );
    expect(t.photos).toEqual(['/uploads/i1.jpg']);
    expect(t.resolution_photos).toEqual(['/uploads/r1.jpg']);
  });

  it('preserves resource uids and maps events to history', () => {
    const t = mapTicket(
      baseWire({
        washroom_uid: 'wc-1',
        washroom_fixture_uid: 'fx-1',
        events: [
          { event_uid: 'ev-1', action: 'created', actor_name: 'A', comment: null, at: '2026-01-01T00:00:00Z' },
          { event_uid: 'ev-2', action: 'assigned', actor_name: 'S', comment: 'to Bob', at: '2026-01-01T01:00:00Z' },
        ],
      }),
      zones
    );
    expect(t.washroom_uid).toBe('wc-1');
    expect(t.washroom_fixture_uid).toBe('fx-1');
    expect(t.history).toHaveLength(2);
    expect(t.history?.[1]).toMatchObject({ status: 'assigned', actor_name: 'S', notes: 'to Bob' });
  });

  it('computes is_reported_by_me from the assignment heuristic', () => {
    expect(mapTicket(baseWire({ assigned_to: 'emp-2' }), zones, 'emp-1').is_reported_by_me).toBe(true);
    expect(mapTicket(baseWire({ assigned_to: 'emp-1' }), zones, 'emp-1').is_reported_by_me).toBe(false);
  });
});

describe('MAINTENANCE_TYPE_LABELS round-trip', () => {
  it('covers all 13 wire values and converts back', () => {
    const expected = [
      'electrical', 'plumbing', 'civil', 'carpentry', 'hvac', 'painting',
      'furniture', 'appliance', 'internet', 'water_drainage',
      'cleaning_equipment', 'safety_security', 'other',
    ];
    expect(Object.keys(MAINTENANCE_TYPE_LABELS).sort()).toEqual(expected.sort());
    for (const wire of expected) {
      const label = MAINTENANCE_TYPE_LABELS[wire];
      expect(label).toBeTruthy();
      expect(maintenanceTypeToWire(label as MaintenanceCategory)).toBe(wire);
    }
  });
});
