import React from 'react';
import { MaintenanceTicket } from '../../types';
import { StatusBadge } from '../common/StatusBadge';
import { PriorityBadge } from '../common/PriorityBadge';
import { MapPin, User, Calendar, Image as ImageIcon } from 'lucide-react';

interface MaintenanceCardProps {
  ticket: MaintenanceTicket;
  currentEmployeeId: string;
  onClick: () => void;
}

export const MaintenanceCard: React.FC<MaintenanceCardProps> = ({
  ticket,
  currentEmployeeId,
  onClick,
}) => {
  const isAssignedToMe = ticket.assigned_to_employee_id === currentEmployeeId;
  const isReportedByMe = ticket.is_reported_by_me;

  const dateObj = ticket.created_at ? new Date(ticket.created_at) : null;
  const dateFormatted = dateObj
    ? `${dateObj.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${dateObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : '—';

  return (
    <div
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      className="bg-white rounded-2xl p-4 border border-[#E4E8E6] hover:border-[#D2D8D6] transition-all active:scale-[0.99] cursor-pointer shadow-[0_1px_3px_rgba(0,0,0,0.03)]"
    >
      {/* Top Header: ID & Badges */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold text-[#667174] bg-[#F0F2F1] px-2 py-0.5 rounded-md">
            {ticket.ticket_number || ticket.id}
          </span>
          <span className="text-[11px] font-semibold text-[#8D999C] uppercase tracking-wide">
            {ticket.category}
          </span>
        </div>
        <PriorityBadge priority={ticket.priority} />
      </div>

      {/* Issue title */}
      <h3 className="text-[15px] font-semibold text-[#20292C] leading-snug mb-1.5 font-['Space_Grotesk']">
        {ticket.issue}
      </h3>

      {/* Location */}
      <div className="flex items-center gap-1.5 text-xs text-[#667174] mb-3">
        <MapPin className="w-3.5 h-3.5 text-[#8D999C] flex-shrink-0" />
        <span className="font-medium text-[#20292C]">{ticket.location_name}</span>
        <span className="text-[#8D999C]">·</span>
        <span>{ticket.zone_name}</span>
      </div>

      {/* Assignment pill & photos */}
      <div className="flex items-center justify-between text-xs py-2 border-t border-[#F0F2F1] mb-2.5">
        <div className="flex items-center gap-1.5">
          <User className="w-3.5 h-3.5 text-[#8D999C]" />
          <span className="text-[#667174]">
            {isAssignedToMe
              ? 'Assigned to you'
              : ticket.assigned_to_name
              ? `Tech: ${ticket.assigned_to_name}`
              : 'Unassigned'}
          </span>
          {isReportedByMe && (
            <span className="ml-1 text-[10px] font-medium bg-[#E8F7ED] text-[#278B46] px-1.5 py-0.5 rounded">
              Reported by you
            </span>
          )}
        </div>

        {ticket.photos.length > 0 && (
          <div className="flex items-center gap-1 text-[11px] text-[#667174]">
            <ImageIcon className="w-3 h-3 text-[#8D999C]" />
            <span>{ticket.photos.length}</span>
          </div>
        )}
      </div>

      {/* Bottom: Date & Status */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[11px] text-[#8D999C]">
          <Calendar className="w-3.5 h-3.5" />
          <span>{dateFormatted}</span>
        </div>
        <StatusBadge status={ticket.status} size="sm" />
      </div>
    </div>
  );
};
