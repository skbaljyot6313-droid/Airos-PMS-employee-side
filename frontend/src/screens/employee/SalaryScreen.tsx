import React, { useCallback, useEffect, useState } from 'react';
import { salaryApi, type SalaryOverview, type SalaryPeriodView } from '../../api/salary';
import { API_BASE, secureStorage, errorMessage } from '../../api/client';

const money = (v: string | number) =>
  Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const Row: React.FC<{ label: string; value: string; basis?: string }> = ({ label, value, basis }) => (
  <div className="flex justify-between gap-3 py-1 text-[11px]">
    <span className="text-ink">
      {label}
      {basis ? <span className="block text-[10px] text-mute">{basis}</span> : null}
    </span>
    <span className="font-medium tabular-nums">{money(value)}</span>
  </div>
);

export const SalaryScreen: React.FC = () => {
  const [overview, setOverview] = useState<SalaryOverview | null>(null);
  const [history, setHistory] = useState<SalaryPeriodView[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, h] = await Promise.all([salaryApi.overview(), salaryApi.history()]);
      setOverview(o);
      setHistory(h.items);
      setError(null);
    } catch (err) {
      setError(errorMessage(err, 'Could not load your salary information.'));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const downloadSlip = async (period: string) => {
    try {
      const token = secureStorage.getToken();
      const res = await fetch(salaryApi.slipUrl(period), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      window.open(url, '_blank', 'noopener');
    } catch {
      setError('Could not download the salary slip.');
    }
  };

  const latest = overview?.last_finalized ?? null;

  return (
    <div className="p-4 space-y-5 overflow-y-auto">
      <h1 className="text-[14px] font-semibold text-ink">Salary</h1>
      {error && <p role="alert" className="text-[10px] text-red-700">{error}</p>}

      {overview?.structure && (
        <section className="rounded-xl border border-line p-4">
          <h2 className="text-[10px] font-semibold text-mute uppercase tracking-wide mb-2">Current salary</h2>
          <Row label={overview.structure.calc_method === 'monthly' ? 'Monthly basic' : `Basic (per ${overview.structure.calc_method === 'daily' ? 'day' : 'hour'})`}
               value={overview.structure.basic} />
          <Row label="House rent allowance" value={overview.structure.hra} />
          {overview.structure.allowances.map((a) => (
            <Row key={a.name} label={a.name} value={a.amount} />
          ))}
          <p className="text-[10px] text-mute mt-2">Effective from {overview.structure.effective_from}</p>
        </section>
      )}

      <section className="rounded-xl border border-line p-4">
        <h2 className="text-[10px] font-semibold text-mute uppercase tracking-wide mb-2">Latest finalized pay</h2>
        {latest ? (
          <>
            <p className="text-[10px] text-mute mb-2">
              {latest.period} · {latest.status === 'paid' ? `Paid${latest.paid_at ? ` on ${latest.paid_at.slice(0, 10)}` : ''}${latest.payment_method ? ` via ${latest.payment_method}` : ''}` : 'Approved, payment pending'}
            </p>
            <Row label="Net payable" value={latest.net} />
          </>
        ) : (
          <p className="text-[11px] text-mute">No finalized salary yet. Confirmed figures appear once a period is approved.</p>
        )}
      </section>

      {overview?.draft_estimate && (
        <section className="rounded-xl border border-dashed border-line p-4">
          <h2 className="text-[10px] font-semibold text-mute uppercase tracking-wide mb-2">
            Estimate — {overview.draft_estimate.period}
          </h2>
          <p className="text-[10px] text-mute mb-2">
            Draft calculation, not yet approved. Final salary may change.
          </p>
          <Row label="Estimated gross" value={overview.draft_estimate.gross} />
          <Row label="Estimated deductions" value={overview.draft_estimate.total_deductions} />
          <Row label="Estimated net" value={overview.draft_estimate.net} />
        </section>
      )}

      <section className="rounded-xl border border-line p-4">
        <h2 className="text-[10px] font-semibold text-mute uppercase tracking-wide mb-2">History</h2>
        {history.length === 0 && <p className="text-[11px] text-mute">No finalized periods.</p>}
        <ul className="divide-y divide-line">
          {history.map((p) => (
            <li key={p.period} className="py-2">
              <button className="w-full flex justify-between text-left" onClick={() => setOpen(open === p.period ? null : p.period)}>
                <span className="text-[11px]">{p.period}</span>
                <span className="text-[11px] font-medium tabular-nums">₹ {money(p.net)}</span>
              </button>
              {open === p.period && (
                <div className="mt-2 pl-1">
                  <div className="text-[10px] font-semibold text-mute mt-2">Earnings</div>
                  {p.earnings.map((e) => <Row key={e.code + e.label} label={e.label} value={e.amount} basis={e.basis} />)}
                  <div className="text-[10px] font-semibold text-mute mt-2">Deductions</div>
                  {p.deductions.length === 0 && <p className="text-[10px] text-mute">None</p>}
                  {p.deductions.map((d) => <Row key={d.code + d.label} label={d.label} value={d.amount} basis={d.basis} />)}
                  <Row label="Gross" value={p.gross} />
                  <Row label="Total deductions" value={p.total_deductions} />
                  <div className="text-[10px] font-semibold text-mute mt-2">Attendance</div>
                  <p className="text-[10px]">
                    Present {String(p.metrics.present_days ?? 0)} · Absent {String(p.metrics.absent_days ?? 0)} ·
                    Half days {String(p.metrics.half_days ?? 0)} · Late {String(p.metrics.late_entries ?? 0)} ·
                    Paid leave {String(p.metrics.paid_leave_days ?? 0)} · Unpaid leave {String(p.metrics.unpaid_leave_days ?? 0)}
                  </p>
                  <p className="text-[10px]">
                    Working {String(p.metrics.worked_hours ?? 0)} h · Break {String(p.metrics.break_hours ?? 0)} h ·
                    Overtime {String(p.metrics.overtime_hours ?? 0)} h
                  </p>
                  {(Number(p.metrics.cl_consumed ?? 0) > 0 || Number(p.metrics.lop_group_days ?? 0) > 0) && (
                    <p className="text-[10px]">
                      Half-day conversions: {String(p.metrics.cl_consumed ?? 0)} CL used ·
                      {String(p.metrics.lop_group_days ?? 0)} day(s) LOP
                    </p>
                  )}
                  {p.notes.map((n) => <p key={n} className="text-[10px] text-mute">• {n}</p>)}
                  <button className="mt-3 text-[11px] text-ink underline" onClick={() => downloadSlip(p.period)}>
                    Download salary slip
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>
      <p className="text-[9px] text-mute">Read-only. Contact HR to dispute a figure. API: {API_BASE}</p>
    </div>
  );
};
