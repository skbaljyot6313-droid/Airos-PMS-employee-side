import React, { useState } from 'react';
import { ZoneResource } from '../../types';
import { UnitTile, RESOURCE_TYPE_ICONS } from './UnitTile';
import { ResourceStateBadge } from './UnitTile';
import { ChevronDown, Wrench } from 'lucide-react';

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

  return (
    <div className="bg-white rounded-xl border border-[#E4E8E6] shadow-[0_1px_2px_rgba(0,0,0,0.02)] overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full p-3 flex items-center justify-between gap-2 text-left hover:bg-[#FBFBFA] transition-colors"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-2 rounded-lg bg-[#F0F2F1] text-[#667174] flex-shrink-0">
            {RESOURCE_TYPE_ICONS.washroom}
          </div>
          <div className="min-w-0">
            <span className="block text-[13px] font-semibold text-[#20292C] leading-tight truncate">
              {washroom.name}
            </span>
            <span className="text-[10px] text-[#8D999C]">
              {fixtures.length > 0
                ? `${fixtures.length} fixture${fixtures.length === 1 ? '' : 's'}`
                : 'No fixtures'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <ResourceStateBadge state={washroom.state} />
          <ChevronDown
            className={`w-3.5 h-3.5 text-[#8D999C] transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 space-y-2 border-t border-[#F0F2F1]">
          {/* Washroom-level actions */}
          <button
            type="button"
            onClick={() => onUnitPress(washroom)}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-dashed border-[#D2D8D6] text-[11px] font-semibold text-[#20292C] hover:bg-[#F7F8F6] transition-colors"
          >
            <Wrench className="w-3.5 h-3.5 text-[#8D999C]" />
            Washroom-level issue
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
