import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from '../../context/AuthContext';
import { ZoneResource, ZoneWorkspace, ZoneSummary } from '../../types';
import { fetchZoneWorkspaceApi } from '../../api/maintenance';
import { errorMessage } from '../../api/client';
import { ScreenHeader } from '../../components/common/ScreenHeader';
import { UnitTile } from '../../components/maintenance/UnitTile';
import { DormCard } from '../../components/maintenance/DormCard';
import { UnitActionSheet } from '../../components/maintenance/UnitActionSheet';
import { EmptyState, ErrorState, LoadingState } from '../../components/common/FeedbackStates';
import { RefreshCw, AlertTriangle } from 'lucide-react';

interface ZoneWorkspaceScreenProps {
  zoneId: string;
  onBack: () => void;
  onRaiseMaintenance: (resource: ZoneResource) => void;
  onViewTicket: (ticketId: string) => void;
}

// Generic resource section — any resource type can plug in here
const ResourceSection: React.FC<{ title: string; children: React.ReactNode }> = ({
  title,
  children,
}) => (
  <section>
    <h3 className="text-[10px] font-bold text-[#8D999C] uppercase tracking-wider px-1 mb-2">
      {title}
    </h3>
    {children}
  </section>
);

export const ZoneWorkspaceScreen: React.FC<ZoneWorkspaceScreenProps> = ({
  zoneId,
  onBack,
  onRaiseMaintenance,
  onViewTicket,
}) => {
  const { user } = useAuth();
  const [workspace, setWorkspace] = useState<ZoneWorkspace | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedUnit, setSelectedUnit] = useState<ZoneResource | null>(null);

  const loadData = useCallback(
    async (isRefresh = false) => {
      try {
        if (isRefresh) setRefreshing(true);
        else setLoading(true);
        setError(null);
        const data = await fetchZoneWorkspaceApi(zoneId, user?.employee_uid ?? undefined);
        setWorkspace(data);
      } catch (err: unknown) {
        setError(errorMessage(err, "Couldn't load this zone."));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [zoneId, user?.employee_uid]
  );

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Only rooms and dorms are listable through this backend.
  const grouped = useMemo(() => {
    const resources = workspace?.resources || [];
    return {
      rooms: resources.filter((r) => r.type === 'room'),
      dorms: resources.filter((r) => r.type === 'dorm'),
    };
  }, [workspace]);

  const selectedTicket = selectedUnit?.active_ticket_id
    ? workspace?.active_tickets.find((t) => t.id === selectedUnit.active_ticket_id) || null
    : null;

  const zone: ZoneSummary | undefined = workspace?.zone;
  const totalUnits = workspace?.resources.length || 0;

  return (
    <div className="flex-1 flex flex-col bg-[#F7F8F6] overflow-y-auto">
      <ScreenHeader
        title={zone?.name || 'Zone'}
        subtitle={
          zone
            ? `${zone.counts.rooms} Rooms · ${zone.counts.dorms} Dorms · ${zone.counts.beds} Beds`
            : 'Loading zone...'
        }
        onBack={onBack}
        rightElement={
          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="p-2 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-[#20292C] hover:bg-[#EFEFEF] transition-all"
            aria-label="Refresh zone"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-[#33B059]' : 'text-[#667174]'}`} />
          </button>
        }
      />

      <div className="flex-1 p-4 pb-8 space-y-5">
        {loading ? (
          <LoadingState message="Loading zone workspace..." />
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadData(false)} />
        ) : !workspace || totalUnits === 0 ? (
          <EmptyState
            type="maintenance"
            title="No covered units"
            description="No covered units — you don't have rooms or dorms in your coverage for this zone."
            actionLabel="Refresh"
            onAction={() => loadData(true)}
          />
        ) : (
          <>
            {/* Zone meta strip */}
            {zone && zone.open_issues > 0 && (
              <div className="flex items-center gap-2 bg-[#FFF1E8] border border-[#FBDDC7] rounded-xl px-3.5 py-2.5 text-xs font-semibold text-[#C2410C]">
                <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                {zone.open_issues} active maintenance issue{zone.open_issues === 1 ? '' : 's'} in this zone
              </div>
            )}

            {/* Rooms */}
            {grouped.rooms.length > 0 && (
              <ResourceSection title="Rooms">
                <div className="grid grid-cols-2 gap-2">
                  {grouped.rooms.map((room) => (
                    <UnitTile key={room.id} resource={room} onPress={setSelectedUnit} />
                  ))}
                </div>
              </ResourceSection>
            )}

            {/* Dormitories — beds/washrooms are not enumerable via the API */}
            {grouped.dorms.length > 0 && (
              <ResourceSection title="Dormitories">
                <div className="space-y-2.5">
                  {grouped.dorms.map((dorm) => (
                    <DormCard
                      key={dorm.id}
                      dorm={dorm}
                      onUnitPress={setSelectedUnit}
                    />
                  ))}
                </div>
              </ResourceSection>
            )}
          </>
        )}
      </div>

      {/* Unit bottom sheet — raise maintenance or view existing ticket */}
      {selectedUnit && (
        <UnitActionSheet
          resource={selectedUnit}
          activeTicket={selectedTicket || null}
          onRaise={(res) => {
            setSelectedUnit(null);
            onRaiseMaintenance(res);
          }}
          onViewTicket={(id) => {
            setSelectedUnit(null);
            onViewTicket(id);
          }}
          onClose={() => setSelectedUnit(null)}
        />
      )}
    </div>
  );
};
