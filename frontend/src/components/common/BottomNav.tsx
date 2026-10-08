import React from 'react';
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
  const tabs = [
    {
      id: 'tasks' as TabType,
      label: 'Tasks',
      icon: ClipboardList,
      badge: tasksCount && tasksCount > 0 ? tasksCount : null,
    },
    {
      id: 'maintenance' as TabType,
      label: 'Maintenance',
      icon: Wrench,
      badge: maintenanceCount && maintenanceCount > 0 ? maintenanceCount : null,
    },
    {
      id: 'attendance' as TabType,
      label: 'Attendance',
      icon: CalendarCheck,
      badge: null,
    },
    {
      id: 'profile' as TabType,
      label: 'Profile',
      icon: User,
      badge: null,
    },
  ];

  return (
    <nav
      aria-label="Bottom Navigation"
      className="bg-white border-t border-[#E4E8E6] px-4 pt-1.5 pb-3 flex items-center justify-around flex-shrink-0 z-30 select-none shadow-[0_-2px_10px_rgba(0,0,0,0.03)]"
    >
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = currentTab === tab.id;

        return (
          <button
            key={tab.id}
            onClick={() => onChangeTab(tab.id)}
            className={`flex-1 flex flex-col items-center justify-center py-1 px-2 rounded-xl transition-all relative min-h-[48px] ${
              isActive
                ? 'text-[#33B059]'
                : 'text-[#8D999C] hover:text-[#667174] active:scale-95'
            }`}
          >
            <div className="relative">
              <Icon
                className={`w-5 h-5 transition-transform ${
                  isActive ? 'stroke-[2.25] scale-105' : 'stroke-[1.75]'
                }`}
              />
              {tab.badge !== null && (
                <span className="absolute -top-1.5 -right-2.5 bg-[#33B059] text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full min-w-[16px] text-center leading-tight shadow-sm">
                  {tab.badge}
                </span>
              )}
            </div>
            <span
              className={`text-[11px] mt-1 font-['Space_Grotesk'] tracking-tight ${
                isActive ? 'font-bold text-[#33B059]' : 'font-medium text-[#667174]'
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
