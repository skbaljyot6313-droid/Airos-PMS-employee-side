import React, { useState } from 'react';
import { ZoneResource } from '../../types';
import { UnitTile, RESOURCE_TYPE_ICONS } from './UnitTile';
import { ResourceStateBadge } from './UnitTile';
import { ChevronDown, Wrench } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface WashroomCardProps {
  washroom: ZoneResource;
  fixtures: ZoneResource[];
  onUnitPress: (resource: ZoneResource) => void;
}

/**
 * Washroom tile — expands to show its real fixture rows (toilets, sinks,
 * showers) so per-fixture tickets can be raised.
 */
export const WashroomCard: React.FC<WashroomCardProps> = ({ washroom, fixtures, onUnitPress }) => {
  const [expanded, setExpanded] = useState<boolean>(false);
  const { t } = useTranslation();

  return (
    <div className="bg-white rounded-xl border border-[#E7E5E4] shadow-[0_1px_2px_rgba(0,0,0,0.02)] overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full p-3 flex items-center justify-between gap-2 text-left hover:bg-[#FBFBFA] transition-colors"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-2 rounded-lg bg-[#F6F4F2] text-[#667085] flex-shrink-0">
            {RESOURCE_TYPE_ICONS.washroom}
          </div>
          <div className="min-w-0">
            <span className="block text-[10px] font-semibold text-[#0D1C42] leading-tight truncate">
              {washroom.name}
            </span>
            <span className="text-[9px] text-[#98A2B3]">
              {fixtures.length > 0
                ? `${fixtures.length} ${t('maintenance.fixtures')}`
                : t('maintenance.noFixtures')}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <ResourceStateBadge state={washroom.state} />
          <ChevronDown
            className={`w-3.5 h-3.5 text-[#98A2B3] transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 space-y-2 border-t border-[#F6F4F2]">
          {/* Washroom-level actions */}
          <button
            type="button"
            onClick={() => onUnitPress(washroom)}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-dashed border-[#D6D3D1] text-[9px] font-semibold text-[#0D1C42] hover:bg-[#FFFCFA] transition-colors"
          >
            <Wrench className="w-3.5 h-3.5 text-[#98A2B3]" />
            {t('maintenance.washroomLevelIssue')}
          </button>

          {fixtures.length > 0 && (
            <div className="grid grid-cols-2 gap-2">
              {fixtures.map((f) => (
                <UnitTile key={f.id} resource={f} onPress={onUnitPress} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
