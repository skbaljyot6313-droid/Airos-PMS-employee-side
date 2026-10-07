import React from 'react';
import { ZoneResource, ZoneWorkspace } from '../../types';
import { ResourceStateBadge, RESOURCE_TYPE_ICONS } from './UnitTile';
import { Wrench, Ticket, X } from 'lucide-react';

type ActiveTicket = ZoneWorkspace['active_tickets'][number];

interface UnitActionSheetProps {
  resource: ZoneResource;
  activeTicket: ActiveTicket | null;
  onRaise: (resource: ZoneResource) => void;
  onViewTicket: (ticketId: string) => void;
  onClose: () => void;
}

export const UnitActionSheet: React.FC<UnitActionSheetProps> = ({
  resource,
  activeTicket,
  onRaise,
  onViewTicket,
  onClose,
}) => {
  return (
    <div
      className="fixed md:absolute inset-0 z-40 flex items-end justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[420px] bg-white rounded-t-3xl p-5 pb-8"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-10 h-1 bg-[#E4E8E6] rounded-full mx-auto mb-4" />

        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="p-2.5 rounded-xl bg-[#F0F2F1] text-[#667174] flex-shrink-0">
              {RESOURCE_TYPE_ICONS[resource.type]}
            </div>
            <div className="min-w-0">
              <h4 className="text-base font-bold text-[#20292C] font-['Space_Grotesk'] truncate">
                {resource.name}
              </h4>
              <span className="text-[11px] text-[#8D999C] block truncate">
                {resource.path.join(' · ')}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[#8D999C] hover:bg-[#F0F2F1] transition-colors flex-shrink-0"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex items-center gap-2 mb-5">
          <ResourceStateBadge state={resource.state} size="md" />
        </div>

        {activeTicket ? (
          <div className="space-y-3">
            <div className="rounded-xl border border-[#F8C8C6] bg-[#FCEBEA]/50 p-3.5">
              <span className="text-[10px] font-bold text-[#D9534F] uppercase tracking-wider block mb-1">
                Active Maintenance
              </span>
              <span className="font-mono text-xs font-bold text-[#20292C] bg-white px-2 py-0.5 rounded inline-block mb-1">
                {activeTicket.ticket_number || activeTicket.id}
              </span>
              <p className="text-xs text-[#667174] leading-snug">{activeTicket.issue}</p>
            </div>
            <button
              type="button"
              onClick={() => onViewTicket(activeTicket.id)}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-[#20292C] text-white text-sm font-semibold hover:bg-[#11181A] active:scale-[0.99] transition-all"
            >
              <Ticket className="w-4 h-4" />
              View Ticket
            </button>
          </div>
        ) : resource.state === 'maintenance' || resource.state === 'inactive' ? (
          // Flagged but no ticket visible to this employee — someone outside
          // their scope owns it. Raising a duplicate is not offered.
          <div className="rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] p-3.5">
            <p className="text-xs text-[#667174] leading-relaxed">
              {resource.state === 'maintenance'
                ? 'This unit is under maintenance. A ticket is already active against it.'
                : 'This unit is inactive and not currently in service.'}
            </p>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => onRaise(resource)}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-[#33B059] text-white text-sm font-semibold hover:bg-[#278B46] active:scale-[0.99] transition-all shadow-sm"
          >
            <Wrench className="w-4 h-4" />
            Raise Maintenance
          </button>
        )}
      </div>
    </div>
  );
};
