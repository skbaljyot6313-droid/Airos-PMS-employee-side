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
  Wallet,
  ChevronRight,
} from 'lucide-react';

export const ProfileScreen: React.FC<{ onOpenSalary?: () => void }> = ({ onOpenSalary }) => {
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
    <div className="flex-1 flex flex-col bg-[#FFFCFA] overflow-y-auto">
      {/* Screen Header */}
      <div className="bg-white border-b border-[#E7E5E4] px-4 pt-3 pb-2.5 sticky top-0 z-20 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
        <h1 className="text-[16px] font-bold tracking-tight text-[#0D1C42] font-['Satoshi']">
          {t('profile.title')}
        </h1>
        <p className="text-xs text-[#667085]">{t('profile.subtitle')}</p>
      </div>

      <div className="p-4 space-y-4 pb-12">
        {/* Profile Identity Card */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm flex flex-col items-center text-center">
          <div className="relative mb-3">
            <div className="w-16 h-16 rounded-full bg-[#0D1C42] text-white flex items-center justify-center font-bold text-lg tracking-wider font-['Satoshi'] shadow-md border-2 border-white ring-2 ring-[#F7E9EE]">
              {getInitials(user?.name)}
            </div>
            <span className="absolute bottom-0 right-0 w-4 h-4 rounded-full bg-[#800020] border-2 border-white" />
          </div>

          <h2 className="text-base font-bold text-[#0D1C42] font-['Satoshi']">
            {user?.name}
          </h2>
          <span className="text-xs font-semibold text-[#667085] mt-0.5">
            @{user?.username}
          </span>

          <div className="flex items-center gap-2 mt-3 flex-wrap justify-center">
            <span className="text-[9px] font-bold uppercase tracking-wider bg-[#F7E9EE] text-[#0D1C42] px-2.5 py-0.5 rounded-full border border-[#EAD3DB]">
              {user?.job_title || t('profile.defaultJobTitle')}
            </span>
            {company?.name && (
              <span className="text-[9px] font-medium bg-[#F6F4F2] text-[#0D1C42] px-2 py-0.5 rounded-full">
                {company.brand_name || company.name}
              </span>
            )}
          </div>
        </div>

        {/* Workplace Assignment (Strictly Read-Only) */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Building2 className="w-4 h-4 text-[#800020]" />
              <h3 className="text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                {t('profile.workplaceAssignment')} ({t('profile.systemLocked')})
              </h3>
            </div>
            <span className="text-[9px] font-bold text-[#98A2B3] uppercase tracking-wider bg-[#FFFCFA] px-1.5 py-0.5 rounded border border-[#E7E5E4]">
              {t('profile.readOnly')}
            </span>
          </div>

          <div className="divide-y divide-[#F6F4F2] text-xs">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#98A2B3]">{t('profile.company')}</span>
              <span className="font-semibold text-[#0D1C42] text-right">
                {company?.brand_name || company?.name || '—'}
              </span>
            </div>

            <div className="py-2 flex items-center justify-between">
              <span className="text-[#98A2B3]">{t('profile.assignedCoverage')}</span>
              <span className="font-semibold text-[#0D1C42] text-right">
                {employee?.zone_name || '—'}
              </span>
            </div>

            <div className="py-2 flex items-center justify-between">
              <span className="text-[#98A2B3]">{t('profile.department')}</span>
              <span className="font-semibold text-[#0D1C42] text-right">
                {employee?.job_title || '—'}
              </span>
            </div>
          </div>
        </div>

        {/* My Shift (Read-Only — schedule set by Property Manager) */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#800020]" />
              <h3 className="text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                {t('profile.myShift')}
              </h3>
            </div>
            {!shiftLoading && !shiftError && (
              <span
                className={`text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${
                  myShift?.status === 'scheduled'
                    ? 'bg-[#F7E9EE] text-[#0D1C42] border-[#EAD3DB]'
                    : 'bg-[#FFFCFA] text-[#98A2B3] border-[#E7E5E4]'
                }`}
              >
                {t(`profile.shiftStatus.${myShift?.status ?? 'not_assigned'}`)}
              </span>
            )}
          </div>

          {shiftLoading ? (
            <div className="space-y-2.5 animate-pulse">
              <div className="h-3.5 rounded bg-[#F6F4F2] w-3/4" />
              <div className="h-3.5 rounded bg-[#F6F4F2] w-1/2" />
              <div className="h-3.5 rounded bg-[#F6F4F2] w-2/3" />
            </div>
          ) : shiftError ? (
            <div className="flex items-center justify-between">
              <span className="text-xs text-[#D64545]">{shiftError}</span>
              <button
                onClick={() => {
                  setShiftLoading(true);
                  void loadShift();
                }}
                className="text-xs font-semibold text-[#800020] hover:underline"
              >
                {t('common.retry')}
              </button>
            </div>
          ) : myShift?.shift ? (
            <div className="divide-y divide-[#F6F4F2] text-xs">
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#98A2B3]">{t('profile.timing')}</span>
                <span className="font-semibold text-[#0D1C42] text-right">
                  {formatShiftTime(myShift.shift.start_time)} –{' '}
                  {formatShiftTime(myShift.shift.end_time)}
                  {myShift.shift.overnight && (
                    <span className="text-[#98A2B3] font-medium"> {t('profile.plusOneDay')}</span>
                  )}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#98A2B3]">{t('profile.workingDays')}</span>
                <span className="font-semibold text-[#0D1C42] text-right">
                  {workingDaysLabel(myShift.shift.working_days)}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#98A2B3]">{t('profile.shift')}</span>
                <span className="font-semibold text-[#0D1C42] text-right">
                  {myShift.shift.shift_name}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#98A2B3]">{t('profile.effective')}</span>
                <span className="font-semibold text-[#0D1C42] text-right">
                  {formatOpDate(myShift.shift.effective_from)}
                  {myShift.shift.effective_until
                    ? ` – ${formatOpDate(myShift.shift.effective_until)}`
                    : t('profile.onwards')}
                </span>
              </div>
              {!myShift.shift.is_working_today && (
                <div className="py-2 flex items-center justify-between">
                  <span className="text-[#98A2B3]">{t('profile.today')}</span>
                  <span className="font-medium text-[#667085] text-right">
                    {t('profile.scheduledDayOff')}
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-[#98A2B3]">
              {t('profile.noShift')}
            </p>
          )}
        </div>

        {/* Salary */}
        {onOpenSalary && (
          <button
            onClick={onOpenSalary}
            className="w-full bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm flex items-center gap-3 text-left active:bg-gray-50"
          >
            <Wallet className="w-4 h-4 text-[#800020]" />
            <span className="flex-1 text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
              {t('nav.salary')}
            </span>
            <ChevronRight className="w-4 h-4 text-[#98A2B3]" />
          </button>
        )}

        {/* Personal Contact Details */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-[#800020]" />
              <h3 className="text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
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
              className="text-xs font-semibold text-[#800020] flex items-center gap-1 hover:underline"
            >
              <Edit3 className="w-3.5 h-3.5" />
              <span>{t('profile.editDetails')}</span>
            </button>
          </div>

          <div className="divide-y divide-[#F6F4F2] text-xs">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#98A2B3]">{t('profile.fullName')}</span>
              <span className="font-medium text-[#0D1C42]">{user?.name}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#98A2B3]">{t('profile.phone')}</span>
              <span className="font-medium text-[#0D1C42]">{user?.phone || '—'}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#98A2B3]">{t('profile.email')}</span>
              <span className="font-medium text-[#0D1C42]">{user?.email || '—'}</span>
            </div>
          </div>
        </div>

        {/* Account Settings — language & accessibility preferences */}
        <AccountSettingsCard />

        {/* Security & System Info */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm space-y-2 text-xs text-[#667085]">
          <div className="flex items-center gap-2 text-[#0D1C42] font-semibold font-['Satoshi']">
            <Shield className="w-4 h-4 text-[#800020]" />
            <span>{t('profile.authScoping')}</span>
          </div>
          <p className="text-[9px] leading-relaxed">
            {t('profile.authScopingDesc')}
          </p>
        </div>

        {/* Sign Out CTA */}
        <div className="pt-2">
          <SecondaryButton
            onClick={() => setShowLogoutConfirm(true)}
            icon={<LogOut className="w-4 h-4 text-[#D64545]" />}
          >
            <span className="text-[#D64545] font-semibold">{t('profile.signOut')}</span>
          </SecondaryButton>
        </div>

        {/* Release-verification marker — harmless build identifier for the
            1.0.2 over-the-air update test. */}
        <p className="text-center text-[9px] text-[#98A2B3] pt-2">
          {t('profile.updateTestMarker')}
        </p>

        {/* Update diagnostics — VITE_UPDATE_DEBUG builds only. */}
        {UPDATE_DEBUG && (
          <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm space-y-2 text-xs">
            <h3 className="text-xs font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
              {t('profile.appInfo')}
            </h3>
            <div className="divide-y divide-[#F6F4F2]">
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Current version</span>
                <span className="font-medium text-[#0D1C42]">{installed?.version ?? '—'}</span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Version code</span>
                <span className="font-medium text-[#0D1C42]">{installed?.versionCode ?? '—'}</span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Latest version</span>
                <span className="font-medium text-[#0D1C42]">
                  {getUpdateState().info?.latest_version ?? '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Latest code</span>
                <span className="font-medium text-[#0D1C42]">
                  {getUpdateState().info?.latest_version_code ?? '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Update plugin</span>
                <span className="font-medium text-[#0D1C42]">
                  {Capacitor.isPluginAvailable('AirosUpdate') ? 'available' : 'NOT AVAILABLE'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Download state</span>
                <span className="font-medium text-[#0D1C42]">{getUpdateFlow().phase}</span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Download progress</span>
                <span className="font-medium text-[#0D1C42]">
                  {getUpdateFlow().progress === null ? '—' : `${getUpdateFlow().progress}%`}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Download error</span>
                <span className="font-medium text-[#0D1C42]">
                  {getUpdateFlow().error ?? '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Pending APK</span>
                <span className="font-medium text-[#0D1C42]">
                  {pending?.exists ? `v${pending.versionCode} (${pending.versionName})` : 'none'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Last check result</span>
                <span className="font-medium text-[#0D1C42]">{getUpdateDiag()}</span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Tracker plugin</span>
                <span className="font-medium text-[#0D1C42]">
                  {Capacitor.isPluginAvailable('AirosLocation') ? 'available' : 'NOT AVAILABLE'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Tracking service</span>
                <span className="font-medium text-[#0D1C42]">
                  {tracker === null ? '—' : tracker.running ? 'running' : 'stopped'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Track session</span>
                <span className="font-medium text-[#0D1C42] truncate max-w-[55%]">
                  {tracker?.sessionId ?? '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Fixes sent / queued</span>
                <span className="font-medium text-[#0D1C42]">
                  {tracker === null ? '—' : `${tracker.sequenceNumber} / ${tracker.queuedCount}`}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Last fix uploaded</span>
                <span className="font-medium text-[#0D1C42]">
                  {tracker?.lastFixAt
                    ? new Date(tracker.lastFixAt).toLocaleTimeString()
                    : '—'}
                </span>
              </div>
              <div className="py-2 flex justify-between">
                <span className="text-[#98A2B3]">Tracker error</span>
                <span className="font-medium text-[#0D1C42]">
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
            <div className="flex items-center justify-between border-b border-[#F6F4F2] pb-3">
              <h3 className="text-base font-bold text-[#0D1C42] font-['Satoshi']">
                {t('profile.editContactTitle')}
              </h3>
              <button
                onClick={() => setIsEditing(false)}
                className="p-1.5 rounded-full text-[#98A2B3] hover:bg-[#F6F4F2]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {editError && (
              <div className="p-3 bg-[#FAEBEB] text-xs text-[#D64545] rounded-xl">
                {editError}
              </div>
            )}

            <form onSubmit={handleSaveProfile} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-[#0D1C42] mb-1 uppercase tracking-wider">
                  {t('profile.fullName')}
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  className="w-full px-3 py-2.5 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-sm text-[#0D1C42] focus:bg-white focus:outline-none focus:border-[#800020]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#0D1C42] mb-1 uppercase tracking-wider">
                  {t('profile.phoneNumber')}
                </label>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-sm text-[#0D1C42] focus:bg-white focus:outline-none focus:border-[#800020]"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[#0D1C42] mb-1 uppercase tracking-wider">
                  {t('profile.emailAddress')}
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-sm text-[#0D1C42] focus:bg-white focus:outline-none focus:border-[#800020]"
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
            <div className="w-12 h-12 rounded-2xl bg-[#FAEBEB] text-[#D64545] flex items-center justify-center mx-auto">
              <LogOut className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-[#0D1C42] font-['Satoshi']">
                {t('profile.signOutTitle')}
              </h3>
              <p className="text-xs text-[#667085] mt-1 leading-relaxed">
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
