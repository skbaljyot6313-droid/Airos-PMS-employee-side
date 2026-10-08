import React, { useState } from 'react';
import { ZoneResource } from '../../types';
import { RESOURCE_TYPE_ICONS } from './UnitTile';
import { ChevronDown, BedSingle, Droplets } from 'lucide-react';

interface DormCardProps {
  dorm: ZoneResource;
  onUnitPress: (resource: ZoneResource) => void;
}

export const DormCard: React.FC<DormCardProps> = ({ dorm, onUnitPress }) => {
  const [expanded, setExpanded] = useState<boolean>(false);
  const openIssues = dorm.active_ticket_id ? 1 : 0;
  const bedsLabel =
    dorm.bed_count != null ? `${dorm.bed_count} Bed${dorm.bed_count === 1 ? '' : 's'}` : 'Dorm';

  return (
    <div className="bg-white rounded-2xl border border-[#E4E8E6] shadow-[0_1px_3px_rgba(0,0,0,0.03)] overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full p-4 flex items-center justify-between gap-3 text-left hover:bg-[#FBFBFA] transition-colors"
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 rounded-xl bg-[#F0F2F1] text-[#667174] flex-shrink-0">
            {RESOURCE_TYPE_ICONS.dorm}
          </div>
          <div className="min-w-0">
            <span className="block text-sm font-bold text-[#20292C] font-['Space_Grotesk'] truncate">
              {dorm.name}
            </span>
            <span className="text-[11px] text-[#667174]">
              {bedsLabel}
              {openIssues > 0 && (
                <span className="text-[#C2410C] font-semibold">
                  {' '}· {openIssues} open issue{openIssues === 1 ? '' : 's'}
                </span>
              )}
            </span>
          </div>
        </div>
        <ChevronDown
          className={`w-4 h-4 text-[#8D999C] transition-transform flex-shrink-0 ${expanded ? 'rotate-180' : ''}`}
        />
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 space-y-4 border-t border-[#F0F2F1]">
          {/* Dorm-level actions */}
          <button
            type="button"
            onClick={() => onUnitPress(dorm)}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg border border-dashed border-[#D2D8D6] text-[11px] font-semibold text-[#20292C] hover:bg-[#F7F8F6] transition-colors"
          >
            <Droplets className="w-3.5 h-3.5 text-[#8D999C]" />
            Dorm-level issue
          </button>

          <div>
            <div className="flex items-center gap-1.5 text-[10px] font-bold text-[#8D999C] uppercase tracking-wider mb-2 mt-2">
              <BedSingle className="w-3.5 h-3.5" />
              <span>Beds</span>
            </div>
            {dorm.detail_available === false ? (
              <p className="text-xs text-[#8D999C]">
                {dorm.bed_count ?? 0} beds · Bed-level detail is not available in this app
              </p>
            ) : (
              <p className="text-xs text-[#8D999C]">No beds assigned to this dorm.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
