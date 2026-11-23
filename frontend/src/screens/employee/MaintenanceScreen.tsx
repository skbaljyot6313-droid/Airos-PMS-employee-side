import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { ZoneSummary } from '../../types';
import { fetchMaintenanceZonesApi } from '../../api/maintenance';
import { errorMessage } from '../../api/client';
import { subscribeRealtimeEvents } from '../../services/realtime';
import { ZoneCard } from '../../components/maintenance/ZoneCard';
import { EmptyState, ErrorState, LoadingState } from '../../components/common/FeedbackStates';
import { RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface MaintenanceScreenProps {
  onSelectZone: (zone: ZoneSummary) => void;
  onMaintenanceCountChange?: (count: number) => void;
}

export const MaintenanceScreen: React.FC<MaintenanceScreenProps> = ({
  onSelectZone,
  onMaintenanceCountChange,
}) => {
  const { user } = useAuth();
  const { t } = useTranslation();
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
        setError(errorMessage(err, t('maintenance.loadError')));
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

  // Realtime invalidation — maintenance events refresh zones/counts.
  useEffect(
    () =>
      subscribeRealtimeEvents(['maintenance.', 'ticket.'], () =>
        loadData(true),
      ),
    [loadData],
  );

  return (
    <div className="flex-1 flex flex-col bg-[#FFFCFA] overflow-y-auto">
      {/* Sticky Top Header */}
      <div className="bg-white border-b border-[#E7E5E4] px-4 pt-3 pb-2.5 sticky top-0 z-20 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <span className="text-[9px] font-semibold text-[#667085] uppercase tracking-wider block">
              {t('maintenance.eyebrow')}
            </span>
            <h1 className="text-[16px] font-bold tracking-tight text-[#0D1C42] font-['Satoshi']">
              {t('maintenance.title')}
            </h1>
            <p className="text-xs text-[#98A2B3] mt-0.5">{t('maintenance.selectZoneHint')}</p>
          </div>

          <button
            onClick={() => loadData(true)}
            disabled={refreshing}
            className="p-2 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-[#0D1C42] hover:bg-[#F6F4F2] transition-all"
            aria-label={t('maintenance.refresh')}
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-[#800020]' : 'text-[#667085]'}`} />
          </button>
        </div>
      </div>

      {/* Zone List */}
      <div className="flex-1 p-4">
        {loading ? (
          <LoadingState message={t('maintenance.loading')} />
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadData(false)} />
        ) : zones.length === 0 ? (
          <EmptyState
            type="maintenance"
            title={t('maintenance.noZones')}
            description={t('maintenance.noZonesDesc')}
            actionLabel={t('common.refresh')}
            onAction={() => loadData(true)}
          />
        ) : (
          <div className="space-y-3 pb-8">
            <span className="block text-[9px] font-bold text-[#98A2B3] uppercase tracking-wider px-1">
              {t('maintenance.yourZones')}
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
