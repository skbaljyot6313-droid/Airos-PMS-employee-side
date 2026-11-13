import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useTranslation } from 'react-i18next';
import { AccountSettingsCard } from '../../components/profile/AccountSettingsCard';
import { PrimaryButton, SecondaryButton, DangerButton } from '../../components/common/Buttons';
import { errorMessage } from '../../api/client';
import {
  checkForUpdates,
  getUpdateDiag,
  getUpdateFlow,
  getUpdateState,
  installedInfo,
  InstalledInfo,
} from '../../services/updateService';
import { NativeUpdate, PendingApk } from '../../services/updateInstaller';
import {
  NativeLocation,
  NativeTrackerState,
} from '../../services/nativeLocation';
import { Capacitor } from '@capacitor/core';
import {
  getMyShiftApi,
  formatShiftTime,
  formatOpDate,
  workingDaysLabel,
} from '../../api/shift';
import { MyShift } from '../../types';
import {
  User,
  Phone,
  Mail,
  Building2,
  MapPin,
  Briefcase,
  LogOut,
  Edit3,
  Check,
  X,
  Shield,
  Clock,
  Sparkles,
} from 'lucide-react';

export const ProfileScreen: React.FC = () => {
  const { user, company, employee, logout, updateProfile } = useAuth();
  const { t } = useTranslation();

  // Edit personal info modal state
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [name, setName] = useState<string>(user?.name || '');
  const [phone, setPhone] = useState<string>(user?.phone || '');
  const [email, setEmail] = useState<string>(user?.email || '');
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [editSuccess, setEditSuccess] = useState<boolean>(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Sign out confirmation dialog
  const [showLogoutConfirm, setShowLogoutConfirm] = useState<boolean>(false);

  // My Shift — refetched on every mount (the screen remounts when the
  // employee returns to this tab, so admin changes appear without an
  // app reinstall). Read-only: scheduling is an admin operation.
  const [myShift, setMyShift] = useState<MyShift | null>(null);
  const [shiftLoading, setShiftLoading] = useState<boolean>(true);
  const [shiftError, setShiftError] = useState<string | null>(null);
  const loadShift = useCallback(async () => {
    setShiftError(null);
    try {
      setMyShift(await getMyShiftApi());
    } catch (err: unknown) {
      setMyShift(null);
      setShiftError(errorMessage(err, t('profile.shiftLoadError')));
    } finally {
      setShiftLoading(false);
    }
  }, []);
  useEffect(() => {
    void loadShift();
  }, [loadShift]);

  // Diagnostics — only compiled in when built with VITE_UPDATE_DEBUG=true.
  const UPDATE_DEBUG = import.meta.env.VITE_UPDATE_DEBUG === 'true';
  const [installed, setInstalled] = useState<InstalledInfo | null>(null);
  const [pending, setPending] = useState<PendingApk | null>(null);
  const [tracker, setTracker] = useState<NativeTrackerState | null>(null);
  const [diagTick, setDiagTick] = useState(0);
  useEffect(() => {
    if (!UPDATE_DEBUG) return;
    void installedInfo().then(setInstalled);
    void NativeUpdate.getPendingApk().then(setPending).catch(() => setPending(null));
    void NativeLocation.getState().then(setTracker).catch(() => setTracker(null));
  }, [UPDATE_DEBUG, diagTick]);

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    try {
      setIsSaving(true);
      setEditError(null);
      await updateProfile({
        name: name.trim(),
        phone: phone.trim(),
        email: email.trim(),
      });
      setEditSuccess(true);
      setTimeout(() => {
        setEditSuccess(false);
        setIsEditing(false);
      }, 1000);
    } catch (err: unknown) {
      setEditError(errorMessage(err, t('profile.updateContactError')));
    } finally {
      setIsSaving(false);
    }
  };

  const getInitials = (n?: string) => {
    if (!n) return 'EM';
    const parts = n.split(' ');
    if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    return parts[0].slice(0, 2).toUpperCase();
  };

  return (
    <div className="flex-1 flex flex-col bg-[#F7F8F6] overflow-y-auto">
      {/* Screen Header */}
      <div className="bg-white border-b border-[#E4E8E6] px-4 pt-3 pb-2.5 sticky top-0 z-20 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
        <h1 className="text-[21px] font-bold tracking-tight text-[#20292C] font-['Space_Grotesk']">
          {t('profile.title')}
        </h1>
        <p className="text-xs text-[#667174]">{t('profile.subtitle')}</p>
      </div>

      <div className="p-4 space-y-4 pb-12">
        {/* Profile Identity Card */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm flex flex-col items-center text-center">
          <div className="relative mb-3">
            <div className="w-16 h-16 rounded-full bg-[#20292C] text-white flex items-center justify-center font-bold text-lg tracking-wider font-['Space_Grotesk'] shadow-md border-2 border-white ring-2 ring-[#E8F7ED]">
              {getInitials(user?.name)}
            </div>
            <span className="absolute bottom-0 right-0 w-4 h-4 rounded-full bg-[#33B059] border-2 border-white" />
          </div>

          <h2 className="text-base font-bold text-[#20292C] font-['Space_Grotesk']">
            {user?.name}
          </h2>
          <span className="text-xs font-semibold text-[#667174] mt-0.5">
            @{user?.username}
          </span>

          <div className="flex items-center gap-2 mt-3 flex-wrap justify-center">
            <span className="text-[11px] font-bold uppercase tracking-wider bg-[#E8F7ED] text-[#278B46] px-2.5 py-0.5 rounded-full border border-[#BBECCC]">
              {user?.job_title || t('profile.defaultJobTitle')}
            </span>
            {company?.name && (
              <span className="text-[11px] font-medium bg-[#F0F2F1] text-[#20292C] px-2 py-0.5 rounded-full">
                {company.brand_name || company.name}
              </span>
            )}
          </div>
        </div>

        {/* Workplace Assignment (Strictly Read-Only) */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-[#33B059]" />
              <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                {t('profile.workplaceAssignment')} ({t('profile.systemLocked')})
              </h3>
            </div>
            <span className="text-[10px] font-bold text-[#8D999C] uppercase tracking-wider bg-[#F7F8F6] px-1.5 py-0.5 rounded border border-[#E4E8E6]">
              {t('profile.readOnly')}
            </span>
          </div>

          <div className="divide-y divide-[#F0F2F1] text-xs">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">{t('profile.company')}</span>
              <span className="font-semibold text-[#20292C] text-right">
                {company?.brand_name || company?.name || '—'}
              </span>
            </div>

            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">{t('profile.assignedCoverage')}</span>
              <span className="font-semibold text-[#20292C] text-right">
                {employee?.zone_name || '—'}
              </span>
            </div>

            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">{t('profile.department')}</span>
              <span className="font-semibold text-[#20292C] text-right">
                {employee?.job_title || '—'}
              </span>
            </div>
          </div>
        </div>

        {/* My Shift (Read-Only — schedule set by Property Manager) */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#33B059]" />
              <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                {t('profile.myShift')}
              </h3>
            </div>
            {!shiftLoading && !shiftError && (
              <span
                className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${
                  myShift?.status === 'scheduled'
                    ? 'bg-[#E8F7ED] text-[#278B46] border-[#BBECCC]'
                    : 'bg-[#F7F8F6] text-[#8D999C] border-[#E4E8E6]'
                }`}
              >
                {t(`profile.shiftStatus.${myShift?.status ?? 'not_assigned'}`)}
              </span>
            )}
          </div>

          {shiftLoading ? (
            <div className="space-y-2.5 animate-pulse">
              <div className="h-3.5 rounded bg-[#F0F2F1] w-3/4" />
              <div className="h-3.5 rounded bg-[#F0F2F1] w-1/2" />
              <div className="h-3.5 rounded bg-[#F0F2F1] w-2/3" />
            </div>
          ) : shiftError ? (
            <div className="flex items-center justify-between">
              <span className="text-xs text-[#D9534F]">{shiftError}</span>
              <button
                onClick={() => {
                  setShiftLoading(true);
                  void loadShift();
                }}
                className="text-xs font-semibold text-[#33B059] hover:underline"
              >
                {t('common.retry')}
              </button>
            </div>
          ) : myShift?.shift ? (
            <div className="divide-y divide-[#F0F2F1] text-xs">
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#8D999C]">{t('profile.timing')}</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {formatShiftTime(myShift.shift.start_time)} –{' '}
                  {formatShiftTime(myShift.shift.end_time)}
                  {myShift.shift.overnight && (
                    <span className="text-[#8D999C] font-medium"> {t('profile.plusOneDay')}</span>
                  )}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#8D999C]">{t('profile.workingDays')}</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {workingDaysLabel(myShift.shift.working_days)}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#8D999C]">{t('profile.shift')}</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {myShift.shift.shift_name}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#8D999C]">{t('profile.effective')}</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {formatOpDate(myShift.shift.effective_from)}
                  {myShift.shift.effective_until
                    ? ` – ${formatOpDate(myShift.shift.effective_until)}`
                    : t('profile.onwards')}
                </span>
              </div>
              {!myShift.shift.is_working_today && (
                <div className="py-2 flex items-center justify-between">
                  <span className="text-[#8D999C]">{t('profile.today')}</span>
                  <span className="font-medium text-[#667174] text-right">
                    {t('profile.scheduledDayOff')}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-[#8D999C]">
              {t('profile.noShift')}
            </p>
          )}
        </div>

        {/* Personal Contact Details */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-[#33B059]" />
              <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                {t('profile.personalContact')}
              </h3>
            </div>
            <button
              onClick={() => {
                setName(user?.name || '');
                setPhone(user?.phone || '');
                setEmail(user?.email || '');
                setIsEditing(true);
              }}
              className="text-xs font-semibold text-[#33B059] flex items-center gap-1 hover:underline"
            >
              <Edit3 className="w-3.5 h-3.5" />
              <span>{t('profile.editDetails')}</span>
            </button>
          </div>

          <div className="divide-y divide-[#F0F2F1] text-xs">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">{t('profile.fullName')}</span>
              <span className="font-medium text-[#20292C]">{user?.name}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">{t('profile.phone')}</span>
              <span className="font-medium text-[#20292C]">{user?.phone || '—'}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">{t('profile.email')}</span>
              <span className="font-medium text-[#20292C]">{user?.email || '—'}</span>
            </div>
          </div>
        </div>

        {/* Account Settings — language & accessibility preferences */}
        <AccountSettingsCard />

        {/* Security & System Info */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-2 text-xs text-[#667174]">
          <div className="flex items-center gap-2 text-[#20292C] font-semibold font-['Space_Grotesk']">
            <Shield className="w-4 h-4 text-[#33B059]" />
            <span>{t('profile.authScoping')}</span>
          </div>
          <p className="text-[11px] leading-relaxed">
            {t('profile.authScopingDesc')}
          </p>
        </div>

        {/* Sign Out CTA */}
        <div className="pt-2">
          <SecondaryButton
            onClick={() => setShowLogoutConfirm(true)}
            icon={<LogOut className="w-4 h-4 text-[#D9534F]" />}
          >
            <span className="text-[#D9534F] font-semibold">{t('profile.signOut')}</span>
          </SecondaryButton>
        </div>

        {/* Release-verification marker — harmless build identifier for the
            1.0.2 over-the-air update test. */}
        <p className="text-center text-[11px] text-[#8D999C] pt-2">
          {t('profile.updateTestMarker')}
        </p>

        {/* Update diagnostics — VITE_UPDATE_DEBUG builds only. */}
        {UPDATE_DEBUG && (
          <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-2 text-xs">
            <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
              {t('profile.appInfo')}
            </h3>
            <div className="divide-y divide-[#F0F2F1]">
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Current version</span>
                <span className="font-medium text-[#20292C]">{installed?.version ?? '—'}</span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Version code</span>
                <span className="font-medium text-[#20292C]">{installed?.versionCode ?? '—'}</span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Latest version</span>
                <span className="font-medium text-[#20292C]">
                  {getUpdateState().info?.latest_version ?? '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Latest code</span>
                <span className="font-medium text-[#20292C]">
                  {getUpdateState().info?.latest_version_code ?? '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Update plugin</span>
                <span className="font-medium text-[#20292C]">
                  {Capacitor.isPluginAvailable('AirosUpdate') ? 'available' : 'NOT AVAILABLE'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Download state</span>
                <span className="font-medium text-[#20292C]">{getUpdateFlow().phase}</span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Download progress</span>
                <span className="font-medium text-[#20292C]">
                  {getUpdateFlow().progress === null ? '—' : `${getUpdateFlow().progress}%`}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Download error</span>
                <span className="font-medium text-[#20292C]">
                  {getUpdateFlow().error ?? '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Pending APK</span>
                <span className="font-medium text-[#20292C]">
                  {pending?.exists ? `v${pending.versionCode} (${pending.versionName})` : 'none'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Last check result</span>
                <span className="font-medium text-[#20292C]">{getUpdateDiag()}</span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Tracker plugin</span>
                <span className="font-medium text-[#20292C]">
                  {Capacitor.isPluginAvailable('AirosLocation') ? 'available' : 'NOT AVAILABLE'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Tracking service</span>
                <span className="font-medium text-[#20292C]">
                  {tracker === null ? '—' : tracker.running ? 'running' : 'stopped'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Track session</span>
                <span className="font-medium text-[#20292C] truncate max-w-[55%]">
                  {tracker?.sessionId ?? '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Fixes sent / queued</span>
                <span className="font-medium text-[#20292C]">
                  {tracker === null ? '—' : `${tracker.sequenceNumber} / ${tracker.queuedCount}`}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Last fix uploaded</span>
                <span className="font-medium text-[#20292C]">
                  {tracker?.lastFixAt
                    ? new Date(tracker.lastFixAt).toLocaleTimeString()
                    : '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#8D999C]">Tracker error</span>
                <span className="font-medium text-[#20292C]">
                  {tracker?.lastError ?? '—'}
                </span>
              </div>
            </div>
            <SecondaryButton
              size="sm"
              onClick={async () => {
                await checkForUpdates(true);
                setDiagTick((t) => t + 1);
              }}
            >
              {t('profile.checkForUpdates')}
            </SecondaryButton>
          </div>
        )}
      </div>

      {/* Edit Profile Modal */}
      {isEditing && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-end md:items-center justify-center p-0 md:p-4">
          <div className="bg-white w-full max-w-md rounded-t-3xl md:rounded-3xl p-5 space-y-4 animate-in slide-in-from-bottom duration-200">
            <div className="flex items-center justify-between border-b border-[#F0F2F1] pb-3">
              <h3 className="text-base font-bold text-[#20292C] font-['Space_Grotesk']">
                {t('profile.editContactTitle')}
              </h3>
              <button
                onClick={() => setIsEditing(false)}
                className="p-1.5 rounded-full text-[#8D999C] hover:bg-[#F0F2F1]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {editError && (
              <div className="p-3 bg-[#FCEBEA] text-xs text-[#D9534F] rounded-xl">
                {editError}
              </div>
            )}

            <form onSubmit={handleSaveProfile} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-[#20292C] mb-1 uppercase tracking-wider">
                  {t('profile.fullName')}
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  className="w-full px-3 py-2.5 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-sm text-[#20292C] focus:bg-white focus:outline-none focus:border-[#33B059]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#20292C] mb-1 uppercase tracking-wider">
                  {t('profile.phoneNumber')}
                </label>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-sm text-[#20292C] focus:bg-white focus:outline-none focus:border-[#33B059]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#20292C] mb-1 uppercase tracking-wider">
                  {t('profile.emailAddress')}
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-sm text-[#20292C] focus:bg-white focus:outline-none focus:border-[#33B059]"
                />
              </div>

              <div className="pt-2 flex gap-3">
                <SecondaryButton type="button" onClick={() => setIsEditing(false)}>
                  {t('common.cancel')}
                </SecondaryButton>
                <PrimaryButton
                  type="submit"
                  loading={isSaving}
                  icon={editSuccess ? <Check className="w-4 h-4 stroke-[3]" /> : undefined}
                >
                  {editSuccess ? t('common.saved') : t('profile.saveChanges')}
                </PrimaryButton>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Logout Confirmation Dialog */}
      {showLogoutConfirm && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-white w-full max-w-sm rounded-2xl p-5 text-center space-y-3 animate-in zoom-in-95 duration-150 shadow-xl">
            <div className="w-12 h-12 rounded-2xl bg-[#FCEBEA] text-[#D9534F] flex items-center justify-center mx-auto">
              <LogOut className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-[#20292C] font-['Space_Grotesk']">
                {t('profile.signOutTitle')}
              </h3>
              <p className="text-xs text-[#667174] mt-1 leading-relaxed">
                {t('profile.signOutDesc')}
              </p>
            </div>
            <div className="flex gap-2.5 pt-2">
              <SecondaryButton onClick={() => setShowLogoutConfirm(false)}>
                Cancel
              </SecondaryButton>
              <DangerButton
                onClick={() => {
                  setShowLogoutConfirm(false);
                  logout();
                }}
              >
                {t('profile.signOut')}
              </DangerButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
