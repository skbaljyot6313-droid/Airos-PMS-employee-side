import React from 'react';
import { ZoneSummary } from '../../types';
import { ArrowRight, AlertTriangle } from 'lucide-react';

interface ZoneCardProps {
  zone: ZoneSummary;
  onClick: () => void;
}

export const ZoneCard: React.FC<ZoneCardProps> = ({ zone, onClick }) => {
  const stats: { label: string; value: number | string }[] = [
    { label: 'Rooms', value: zone.counts.rooms },
    { label: 'Dorms', value: zone.counts.dorms },
    { label: 'Beds', value: zone.counts.beds },
    { label: 'Washrooms', value: zone.counts.washrooms ?? '—' },
    ...(zone.counts.other > 0 ? [{ label: 'Other Units', value: zone.counts.other }] : []),
  ];

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      className="bg-white rounded-2xl p-4 border border-[#E4E8E6] hover:border-[#D2D8D6] transition-all active:scale-[0.99] cursor-pointer shadow-[0_1px_3px_rgba(0,0,0,0.03)]"
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="min-w-0">
          <h3 className="text-[16px] font-bold text-[#20292C] font-['Space_Grotesk'] truncate">
            {zone.name}
          </h3>
          {zone.type && (
            <span className="text-[11px] font-semibold text-[#667174] uppercase tracking-wider">
              {zone.type}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-[#33B059] font-semibold text-xs flex-shrink-0">
          <span>View Zone</span>
          <ArrowRight className="w-4 h-4 stroke-[2.5]" />
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2 py-2.5 border-t border-b border-[#F0F2F1]">
        {stats.slice(0, 4).map((s) => (
          <div key={s.label} className="text-center">
            <span className="block text-base font-bold text-[#20292C] font-['Space_Grotesk']">
              {s.value}
            </span>
            <span className="text-[10px] font-medium text-[#8D999C] uppercase tracking-wide">
              {s.label}
            </span>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between mt-2.5">
        <div className="flex items-center gap-2">
          {stats.length > 4 && (
            <span className="text-[11px] text-[#667174]">
              +{stats[4].value} other units
            </span>
          )}
        </div>
        {zone.open_issues > 0 ? (
          <span className="flex items-center gap-1 text-[11px] font-semibold text-[#C2410C] bg-[#FFF1E8] px-2 py-1 rounded-lg">
            <AlertTriangle className="w-3.5 h-3.5" />
            {zone.open_issues} Open Issue{zone.open_issues === 1 ? '' : 's'}
          </span>
        ) : (
          <span className="text-[11px] font-medium text-[#278B46] bg-[#E8F7ED] px-2 py-1 rounded-lg">
            All clear
          </span>
        )}
      </div>
    </div>
  );
};
