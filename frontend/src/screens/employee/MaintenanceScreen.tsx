import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { ZoneSummary } from '../../types';
import { fetchMaintenanceZonesApi } from '../../api/maintenance';
import { errorMessage } from '../../api/client';
import { ZoneCard } from '../../components/maintenance/ZoneCard';
import { EmptyState, ErrorState, LoadingState } from '../../components/common/FeedbackStates';
import { RefreshCw } from 'lucide-react';

interface MaintenanceScreenProps {
  onSelectZone: (zone: ZoneSummary) => void;
  onMaintenanceCountChange?: (count: number) => void;
}

export const MaintenanceScreen: React.FC<MaintenanceScreenProps> = ({
  onSelectZone,
  onMaintenanceCountChange,
}) => {
  const { user } = useAuth();
  const [zones, setZones] = useState<ZoneSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(
    async (isRefresh = false) => {
      try {
        if (isRefresh) setRefreshing(true);
        else setLoading(true);
        setError(null);

        const data = await fetchMaintenanceZonesApi(user?.employee_uid ?? undefined);
        setZones(data.zones || []);

        const activeAssigned = (data.assigned_to_me || []).filter(
          (t) => t.status !== 'resolved' && t.status !== 'closed' && t.status !== 'cancelled'
        ).length;
        if (onMaintenanceCountChange) {
          onMaintenanceCountChange(activeAssigned);
        }
      } catch (err: unknown) {
        setError(errorMessage(err, 'Unable to load your zones.'));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [onMaintenanceCountChange, user?.employee_uid]
  );

  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <div className="flex-1 flex flex-col bg-[#F7F8F6] overflow-y-auto">
      {/* Sticky Top Header */}
      <div className="bg-white border-b border-[#E4E8E6] px-5 pt-4 pb-3.5 sticky top-0 z-20 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-xs font-semibold text-[#667174] uppercase tracking-wider block">
              Property Maintenance
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-[#20292C] font-['Space_Grotesk']">
              Maintenance
            </h1>
            <p className="text-xs text-[#8D999C] mt-0.5">Select a zone to inspect its units</p>
          </div>

          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="p-2 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-[#20292C] hover:bg-[#EFEFEF] transition-all"
            aria-label="Refresh zones"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-[#33B059]' : 'text-[#667174]'}`} />
          </button>
        </div>
      </div>

      {/* Zone List */}
      <div className="flex-1 p-4">
        {loading ? (
          <LoadingState message="Loading your zones..." />
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadData(false)} />
        ) : zones.length === 0 ? (
          <EmptyState
            type="maintenance"
            title="No zones assigned"
            description="You currently don't have a zone or area assigned. Contact your supervisor if this is unexpected."
            actionLabel="Refresh"
            onAction={() => loadData(true)}
          />
        ) : (
          <div className="space-y-3 pb-8">
            <span className="block text-[10px] font-bold text-[#8D999C] uppercase tracking-wider px-1">
              Your Zones
            </span>
            {zones.map((zone) => (
              <ZoneCard key={zone.id} zone={zone} onClick={() => onSelectZone(zone)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
