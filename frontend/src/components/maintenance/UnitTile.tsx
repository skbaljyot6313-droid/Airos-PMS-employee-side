import React from 'react';
import { useTranslation } from 'react-i18next';
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
  { dot: string; text: string; bg: string }
> = {
  available: { dot: 'bg-[#16865B]', text: 'text-[#0E6B47]', bg: 'bg-[#E3F3EC]' },
  occupied: { dot: 'bg-[#7C5CFF]', text: 'text-[#5B3FD4]', bg: 'bg-[#F1EDFF]' },
  cleaning: { dot: 'bg-[#C9A227]', text: 'text-[#8A6D1A]', bg: 'bg-[#FBF6E8]' },
  maintenance: { dot: 'bg-[#D64545]', text: 'text-[#D64545]', bg: 'bg-[#FAEBEB]' },
  inactive: { dot: 'bg-[#98A2B3]', text: 'text-[#667085]', bg: 'bg-[#F6F4F2]' },
};

export const RESOURCE_TYPE_ICONS: Record<ZoneResourceType, React.ReactNode> = {
  room: <DoorOpen className="w-4 h-4" />,
  dorm: <Hotel className="w-4 h-4" />,
  bed: <BedSingle className="w-4 h-4" />,
  washroom: <Droplets className="w-4 h-4" />,
  fixture: <Wrench className="w-4 h-4" />,
};

const UNAVAILABLE_STYLE = {
  dot: 'bg-[#98A2B3]',
  text: 'text-[#667085]',
  bg: 'bg-[#F6F4F2]',
};

export const ResourceStateBadge: React.FC<{ state: ZoneResourceState | null; size?: 'sm' | 'md' }> = ({
  state,
  size = 'sm',
}) => {
  const { t } = useTranslation();
  const s = state ? RESOURCE_STATE_STYLES[state] : UNAVAILABLE_STYLE;
  const label = state ? t(`resourceState.${state}`) : t('resourceState.unavailable');
  return (
    <span
      className={`inline-flex items-center gap-1 font-semibold rounded-md ${s.bg} ${s.text} ${
        size === 'sm' ? 'text-[9px] px-1.5 py-0.5' : 'text-xs px-2 py-1'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {label}
    </span>
  );
};

interface UnitTileProps {
  resource: ZoneResource;
  onPress: (resource: ZoneResource) => void;
}

export const UnitTile: React.FC<UnitTileProps> = ({ resource, onPress }) => {
  const { t } = useTranslation();
  const hasTicket = !!resource.active_ticket_id;

  return (
    <div
      onClick={() => onPress(resource)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onPress(resource)}
      className={`bg-white rounded-xl p-3 border transition-all active:scale-[0.98] cursor-pointer text-left ${
        hasTicket
          ? 'border-[#F0C8C8] shadow-[0_1px_3px_rgba(217,83,79,0.08)]'
          : 'border-[#E7E5E4] hover:border-[#D6D3D1] shadow-[0_1px_2px_rgba(0,0,0,0.02)]'
      }`}
    >
      <div className="flex items-center justify-between gap-1 mb-1.5">
        <span className="text-[#98A2B3]">{RESOURCE_TYPE_ICONS[resource.type]}</span>
        <ResourceStateBadge state={resource.state} />
      </div>
      <span className="block text-[10px] font-semibold text-[#0D1C42] leading-tight truncate mb-1.5">
        {resource.name}
      </span>
      {hasTicket ? (
        <span className="inline-flex items-center gap-1 text-[9px] font-bold text-[#D64545] truncate">
          <Ticket className="w-3 h-3 flex-shrink-0" />
          {resource.active_ticket_number || t('common.viewTicket')}
        </span>
      ) : (
        <span className="inline-flex items-center gap-0.5 text-[9px] font-semibold text-[#800020]">
          <Plus className="w-3 h-3 stroke-[3]" />
          {t('maintenance.maint')}
        </span>
      )}
    </div>
  );
};
