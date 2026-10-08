import React from 'react';
import { ZoneResource, ZoneResourceState, ZoneResourceType } from '../../types';
import {
  DoorOpen,
  Hotel,
  BedSingle,
  Droplets,
  Wrench,
  Plus,
  Ticket,
} from 'lucide-react';

export const RESOURCE_STATE_STYLES: Record<
  ZoneResourceState,
  { label: string; dot: string; text: string; bg: string }
> = {
  available: { label: 'Available', dot: 'bg-[#33B059]', text: 'text-[#278B46]', bg: 'bg-[#E8F7ED]' },
  occupied: { label: 'Occupied', dot: 'bg-[#7C5CFF]', text: 'text-[#5B3FD4]', bg: 'bg-[#F1EDFF]' },
  cleaning: { label: 'Cleaning', dot: 'bg-[#C9A227]', text: 'text-[#8A6D1A]', bg: 'bg-[#FBF6E8]' },
  maintenance: { label: 'Maintenance', dot: 'bg-[#D9534F]', text: 'text-[#D9534F]', bg: 'bg-[#FCEBEA]' },
  inactive: { label: 'Inactive', dot: 'bg-[#8D999C]', text: 'text-[#667174]', bg: 'bg-[#F0F2F1]' },
};

export const RESOURCE_TYPE_ICONS: Record<ZoneResourceType, React.ReactNode> = {
  room: <DoorOpen className="w-4 h-4" />,
  dorm: <Hotel className="w-4 h-4" />,
  bed: <BedSingle className="w-4 h-4" />,
  washroom: <Droplets className="w-4 h-4" />,
  fixture: <Wrench className="w-4 h-4" />,
};

const UNAVAILABLE_STYLE = {
  label: 'State unavailable',
  dot: 'bg-[#8D999C]',
  text: 'text-[#667174]',
  bg: 'bg-[#F0F2F1]',
};

export const ResourceStateBadge: React.FC<{ state: ZoneResourceState | null; size?: 'sm' | 'md' }> = ({
  state,
  size = 'sm',
}) => {
  const s = state ? RESOURCE_STATE_STYLES[state] : UNAVAILABLE_STYLE;
  return (
    <span
      className={`inline-flex items-center gap-1 font-semibold rounded-md ${s.bg} ${s.text} ${
        size === 'sm' ? 'text-[10px] px-1.5 py-0.5' : 'text-xs px-2 py-1'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
};

interface UnitTileProps {
  resource: ZoneResource;
  onPress: (resource: ZoneResource) => void;
}

export const UnitTile: React.FC<UnitTileProps> = ({ resource, onPress }) => {
  const hasTicket = !!resource.active_ticket_id;

  return (
    <div
      onClick={() => onPress(resource)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onPress(resource)}
      className={`bg-white rounded-xl p-3 border transition-all active:scale-[0.98] cursor-pointer text-left ${
        hasTicket
          ? 'border-[#F8C8C6] shadow-[0_1px_3px_rgba(217,83,79,0.08)]'
          : 'border-[#E4E8E6] hover:border-[#D2D8D6] shadow-[0_1px_2px_rgba(0,0,0,0.02)]'
      }`}
    >
      <div className="flex items-center justify-between gap-1 mb-1.5">
        <span className="text-[#8D999C]">{RESOURCE_TYPE_ICONS[resource.type]}</span>
        <ResourceStateBadge state={resource.state} />
      </div>
      <span className="block text-[13px] font-semibold text-[#20292C] leading-tight truncate mb-1.5">
        {resource.name}
      </span>
      {hasTicket ? (
        <span className="inline-flex items-center gap-1 text-[10px] font-bold text-[#D9534F] truncate">
          <Ticket className="w-3 h-3 flex-shrink-0" />
          {resource.active_ticket_number || 'Ticket'}
        </span>
      ) : (
        <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-[#33B059]">
          <Plus className="w-3 h-3 stroke-[3]" />
          Maint
        </span>
      )}
    </div>
  );
};
