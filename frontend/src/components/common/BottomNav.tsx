import React from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardList, Wrench, CalendarCheck, User } from 'lucide-react';

export type TabType = 'tasks' | 'maintenance' | 'attendance' | 'profile';

interface BottomNavProps {
  currentTab: TabType;
  onChangeTab: (tab: TabType) => void;
  tasksCount?: number;
  maintenanceCount?: number;
}

export const BottomNav: React.FC<BottomNavProps> = ({
  currentTab,
  onChangeTab,
  tasksCount,
  maintenanceCount,
}) => {
  const { t } = useTranslation();
  const tabs = [
    {
      id: 'tasks' as TabType,
      label: t('nav.tasks'),
      icon: ClipboardList,
      badge: tasksCount && tasksCount > 0 ? tasksCount : null,
    },
    {
      id: 'maintenance' as TabType,
      label: t('nav.maintenance'),
      icon: Wrench,
      badge: maintenanceCount && maintenanceCount > 0 ? maintenanceCount : null,
    },
    {
      id: 'attendance' as TabType,
      label: t('nav.attendance'),
      icon: CalendarCheck,
      badge: null,
    },
    {
      id: 'profile' as TabType,
      label: t('nav.profile'),
      icon: User,
      badge: null,
    },
  ];

  return (
    <nav
      aria-label={t('nav.label')}
      className="bg-surface border-t border-line px-2 pt-1 flex items-center justify-around flex-shrink-0 z-30 select-none pb-[max(0.5rem,env(safe-area-inset-bottom))]"
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = currentTab === tab.id;

        return (
          <button
            key={tab.id}
            onClick={() => onChangeTab(tab.id)}
            aria-current={isActive ? 'page' : undefined}
            className={`flex-1 flex flex-col items-center justify-center pt-1 pb-1.5 px-2 transition-colors relative min-h-[44px] ${
              isActive ? 'text-ink' : 'text-mute hover:text-sub'
            }`}
          >
            {/* Lime marker — signature accent for the active destination */}
            <span
              aria-hidden
              className={`absolute top-0 h-[3px] w-5 rounded-full transition-colors ${
                isActive ? 'bg-lime' : 'bg-transparent'
              }`}
            />
            <div className="relative">
              <Icon
                className={`w-5 h-5 transition-transform ${
                  isActive ? 'stroke-[2.25]' : 'stroke-[1.75]'
                }`}
              />
              {tab.badge !== null && (
                <span className="absolute -top-1 -right-2 bg-acc text-white text-[9px] font-semibold px-1 rounded-full min-w-[14px] text-center leading-[14px]">
                  {tab.badge}
                </span>
              )}
            </div>
            <span
              className={`text-[11px] mt-1 tracking-tight ${
                isActive ? 'font-semibold text-ink' : 'font-medium text-mute'
              }`}
            >
              {tab.label}
            </span>
          </button>
        );
      })}
    </nav>
  );
};
