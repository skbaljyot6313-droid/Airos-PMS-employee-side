import React, { useEffect, useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import {
  startLocationTracking,
  stopLocationTracking,
} from './services/locationTracker';
import { DeviceFrame } from './components/common/DeviceFrame';
import { BottomNav, TabType } from './components/common/BottomNav';
import { LoginScreen } from './screens/auth/LoginScreen';
import { TasksScreen } from './screens/employee/TasksScreen';
import { TaskDetailScreen } from './screens/employee/TaskDetailScreen';
import { MaintenanceScreen } from './screens/employee/MaintenanceScreen';
import { AttendanceScreen } from './screens/employee/AttendanceScreen';
import { ZoneWorkspaceScreen } from './screens/employee/ZoneWorkspaceScreen';
import { MaintenanceNewScreen } from './screens/employee/MaintenanceNewScreen';
import { MaintenanceDetailScreen } from './screens/employee/MaintenanceDetailScreen';
import { ProfileScreen } from './screens/employee/ProfileScreen';
import { LoadingState } from './components/common/FeedbackStates';
import { MaintenanceTarget, ZoneResource, ZoneSummary } from './types';

type StackRoute =
  | { type: 'tabs'; tab: TabType }
  | { type: 'task-detail'; taskId: string }
  | { type: 'zone-workspace'; zoneId: string }
  | { type: 'maintenance-new'; target?: MaintenanceTarget }
  | { type: 'maintenance-detail'; ticketId: string; zoneId?: string };

const AppNavigator: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  const [route, setRoute] = useState<StackRoute>({ type: 'tabs', tab: 'tasks' });
  const [todoCount, setTodoCount] = useState<number>(0);
  const [maintenanceCount, setMaintenanceCount] = useState<number>(0);

  // Foreground-only live location loop — runs while an employee session
  // is authenticated; native-only (web dev skips), never backgrounds.
  useEffect(() => {
    if (!isAuthenticated) return;
    void startLocationTracking();
    return () => stopLocationTracking();
  }, [isAuthenticated]);

  if (isLoading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-white p-6">
        <div className="w-12 h-12 rounded-2xl bg-[#33B059] flex items-center justify-center text-white mb-3 shadow-sm animate-pulse">
          <span className="font-bold text-lg font-['Space_Grotesk']">A</span>
        </div>
        <LoadingState message="Validating employee credentials..." />
      </div>
    );
  }

  // Route Guard: Unauthenticated users are routed to Login
  if (!isAuthenticated) {
    return <LoginScreen />;
  }

  // Employee Application Stack & Tab Routing
  return (
    <div className="flex-1 flex flex-col h-full bg-[#F7F8F6] relative">
      <div className="flex-1 flex flex-col min-h-0 relative">
        {route.type === 'task-detail' ? (
          <TaskDetailScreen
            taskId={route.taskId}
            onBack={() => setRoute({ type: 'tabs', tab: 'tasks' })}
            onTaskUpdated={() => {
              // Task status updated
            }}
          />
        ) : route.type === 'zone-workspace' ? (
          <ZoneWorkspaceScreen
            zoneId={route.zoneId}
            onBack={() => setRoute({ type: 'tabs', tab: 'maintenance' })}
            onRaiseMaintenance={(resource: ZoneResource) =>
              setRoute({
                type: 'maintenance-new',
                target: {
                  kind: resource.kind,
                  uid: resource.id,
                  washroom_uid: resource.washroom_uid,
                  zone_id: resource.zone_uid,
                  name: resource.name,
                  path: resource.path,
                },
              })
            }
            onViewTicket={(ticketId) =>
              setRoute({ type: 'maintenance-detail', ticketId, zoneId: route.zoneId })
            }
          />
        ) : route.type === 'maintenance-new' ? (
          <MaintenanceNewScreen
            onBack={() =>
              setRoute(
                route.target
                  ? { type: 'zone-workspace', zoneId: route.target.zone_id }
                  : { type: 'tabs', tab: 'maintenance' }
              )
            }
            onSuccess={(newTicketId) =>
              setRoute({ type: 'maintenance-detail', ticketId: newTicketId })
            }
            target={route.target}
          />
        ) : route.type === 'maintenance-detail' ? (
          <MaintenanceDetailScreen
            ticketId={route.ticketId}
            onBack={() =>
              setRoute(
                route.zoneId
                  ? { type: 'zone-workspace', zoneId: route.zoneId }
                  : { type: 'tabs', tab: 'maintenance' }
              )
            }
            onTicketUpdated={() => {
              // Ticket updated
            }}
          />
        ) : (
          <>
            {route.tab === 'tasks' && (
              <TasksScreen
                onSelectTask={(taskId) => setRoute({ type: 'task-detail', taskId })}
                onTasksCountChange={setTodoCount}
              />
            )}
            {route.tab === 'maintenance' && (
              <MaintenanceScreen
                onSelectZone={(zone: ZoneSummary) =>
                  setRoute({ type: 'zone-workspace', zoneId: zone.id })
                }
                onMaintenanceCountChange={setMaintenanceCount}
              />
            )}
            {route.tab === 'attendance' && <AttendanceScreen />}
            {route.tab === 'profile' && <ProfileScreen />}
          </>
        )}
      </div>

      {/* Show Bottom Tabs only when on root tabs */}
      {route.type === 'tabs' && (
        <BottomNav
          currentTab={route.tab}
          onChangeTab={(tab) => setRoute({ type: 'tabs', tab })}
          tasksCount={todoCount}
          maintenanceCount={maintenanceCount}
        />
      )}
    </div>
  );
};

export default function App() {
  return (
    <AuthProvider>
      <DeviceFrame>
        <AppNavigator />
      </DeviceFrame>
    </AuthProvider>
  );
}
