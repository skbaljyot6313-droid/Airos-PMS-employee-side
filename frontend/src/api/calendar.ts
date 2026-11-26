/** Work-calendar API — one scoped feed for allocated work + the day's
 * attendance/activity timeline. */

import { apiClient } from './client';
import { mapDayOffRequest, mapWorkday } from './attendance';
import { mapTicket } from './maintenance';
import { mapMaintenanceToTask, mapTask } from './tasks';
import { getZoneNameMap } from './directory';
import { WorkCalendarWire } from './wire';
import { DayOffRequest, Task, Workday } from '../types';

export interface WorkCalendarData {
  days: { date: string; attendance: Workday }[];
  requests: DayOffRequest[];
  tasks: Task[];
}

export async function fetchWorkCalendarApi(
  dateFrom: string,
  dateTo: string
): Promise<WorkCalendarData> {
  const [res, zoneNames] = await Promise.all([
    apiClient<WorkCalendarWire>(
      `/work-calendar?date_from=${dateFrom}&date_to=${dateTo}`,
      { method: 'GET' }
    ),
    getZoneNameMap(),
  ]);

  const maintenance = res.maintenance.map((wire) =>
    mapMaintenanceToTask(mapTicket(wire, zoneNames), zoneNames)
  );
  return {
    days: res.days.map((d) => ({
      date: d.date,
      attendance: mapWorkday(d.attendance),
    })),
    requests: res.requests.map(mapDayOffRequest),
    tasks: [...res.tasks.map((t) => mapTask(t, zoneNames)), ...maintenance],
  };
}
