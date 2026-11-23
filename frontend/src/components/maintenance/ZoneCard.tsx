import React from 'react';
import { ZoneSummary } from '../../types';
import { ArrowRight, AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface ZoneCardProps {
  zone: ZoneSummary;
  onClick: () => void;
}

export const ZoneCard: React.FC<ZoneCardProps> = ({ zone, onClick }) => {
  const { t } = useTranslation();
  const stats: { label: string; value: number | string }[] = [
    { label: t('maintenance.rooms'), value: zone.counts.rooms },
    { label: t('maintenance.dorms'), value: zone.counts.dorms },
    { label: t('maintenance.beds'), value: zone.counts.beds },
    { label: t('maintenance.washrooms'), value: zone.counts.washrooms ?? '—' },
    ...(zone.counts.other > 0
      ? [{ label: t('maintenance.otherUnits'), value: zone.counts.other }]
      : []),
  ];

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      className="bg-white rounded-2xl p-4 border border-[#E7E5E4] hover:border-[#D6D3D1] transition-all active:scale-[0.99] cursor-pointer shadow-[0_1px_3px_rgba(0,0,0,0.03)]"
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="min-w-0">
          <h3 className="text-[13px] font-bold text-[#0D1C42] font-['Satoshi'] truncate">
            {zone.name}
          </h3>
          {zone.type && (
            <span className="text-[9px] font-semibold text-[#667085] uppercase tracking-wider">
              {zone.type}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-[#800020] font-semibold text-xs flex-shrink-0">
          <span>{t('maintenance.viewZone')}</span>
          <ArrowRight className="w-4 h-4 stroke-[2.5]" />
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2 py-2.5 border-t border-b border-[#F6F4F2]">
        {stats.slice(0, 4).map((s) => (
          <div key={s.label} className="text-center">
            <span className="block text-base font-bold text-[#0D1C42] font-['Satoshi']">
              {s.value}
            </span>
            <span className="text-[9px] font-medium text-[#98A2B3] uppercase tracking-wide">
              {s.label}
            </span>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between mt-2.5">
        <div className="flex items-center gap-2">
          {stats.length > 4 && (
            <span className="text-[9px] text-[#667085]">
              +{stats[4].value} {t('maintenance.otherUnitsSuffix')}
            </span>
          )}
        </div>
        {zone.open_issues > 0 ? (
          <span className="flex items-center gap-1 text-[9px] font-semibold text-[#C2410C] bg-[#FFF1E8] px-2 py-1 rounded-lg">
            <AlertTriangle className="w-3.5 h-3.5" />
            {t('maintenance.openIssues', { count: zone.open_issues })}
          </span>
        ) : (
          <span className="text-[9px] font-medium text-[#0D1C42] bg-[#F7E9EE] px-2 py-1 rounded-lg">
            {t('maintenance.allClear')}
          </span>
        )}
      </div>
    </div>
  );
};
