import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
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
  MY_SHIFT_STATUS_LABELS,
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
      setShiftError(errorMessage(err, 'Could not load your shift.'));
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
      setEditError(errorMessage(err, 'Failed to update contact information.'));
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
      <div className="bg-white border-b border-[#E4E8E6] px-5 pt-4 pb-3 sticky top-0 z-20 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
        <h1 className="text-2xl font-bold tracking-tight text-[#20292C] font-['Space_Grotesk']">
          Profile
        </h1>
        <p className="text-xs text-[#667174]">Employee Identity & Workplace Assignment</p>
      </div>

      <div className="p-4 space-y-4 pb-12">
        {/* Profile Identity Card */}
        <div className="bg-white rounded-3xl p-6 border border-[#E4E8E6] shadow-sm flex flex-col items-center text-center">
          <div className="relative mb-3">
            <div className="w-20 h-20 rounded-full bg-[#20292C] text-white flex items-center justify-center font-bold text-2xl tracking-wider font-['Space_Grotesk'] shadow-md border-2 border-white ring-4 ring-[#E8F7ED]">
              {getInitials(user?.name)}
            </div>
            <span className="absolute bottom-0 right-0 w-5 h-5 rounded-full bg-[#33B059] border-2 border-white" />
          </div>

          <h2 className="text-xl font-bold text-[#20292C] font-['Space_Grotesk']">
            {user?.name}
          </h2>
          <span className="text-xs font-semibold text-[#667174] mt-0.5">
            @{user?.username}
          </span>

          <div className="flex items-center gap-2 mt-3 flex-wrap justify-center">
            <span className="text-[11px] font-bold uppercase tracking-wider bg-[#E8F7ED] text-[#278B46] px-2.5 py-0.5 rounded-full border border-[#BBECCC]">
              {user?.job_title || 'Operations Employee'}
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
                Workplace Assignment (System Locked)
              </h3>
            </div>
            <span className="text-[10px] font-bold text-[#8D999C] uppercase tracking-wider bg-[#F7F8F6] px-1.5 py-0.5 rounded border border-[#E4E8E6]">
              Read-Only
            </span>
          </div>

          <div className="divide-y divide-[#F0F2F1] text-xs">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">Company</span>
              <span className="font-semibold text-[#20292C] text-right">
                {company?.brand_name || company?.name || '—'}
              </span>
            </div>

            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">Assigned Coverage</span>
              <span className="font-semibold text-[#20292C] text-right">
                {employee?.zone_name || '—'}
              </span>
            </div>

            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">Department</span>
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
                My Shift
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
                {MY_SHIFT_STATUS_LABELS[myShift?.status ?? 'not_assigned']}
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
                Retry
              </button>
            </div>
          ) : myShift?.shift ? (
            <div className="divide-y divide-[#F0F2F1] text-xs">
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#8D999C]">Timing</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {formatShiftTime(myShift.shift.start_time)} –{' '}
                  {formatShiftTime(myShift.shift.end_time)}
                  {myShift.shift.overnight && (
                    <span className="text-[#8D999C] font-medium"> (+1 day)</span>
                  )}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#8D999C]">Working days</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {workingDaysLabel(myShift.shift.working_days)}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#8D999C]">Shift</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {myShift.shift.shift_name}
                </span>
              </div>
              <div className="py-2 flex items-center justify-between">
                <span className="text-[#8D999C]">Effective</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {formatOpDate(myShift.shift.effective_from)}
                  {myShift.shift.effective_until
                    ? ` – ${formatOpDate(myShift.shift.effective_until)}`
                    : ' onwards'}
                </span>
              </div>
              {!myShift.shift.is_working_today && (
                <div className="py-2 flex items-center justify-between">
                  <span className="text-[#8D999C]">Today</span>
                  <span className="font-medium text-[#667174] text-right">
                    Scheduled day off
                  </span>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-[#8D999C]">
              No shift assigned — your manager hasn't scheduled you yet.
            </p>
          )}
        </div>

        {/* Personal Contact Details */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-[#33B059]" />
              <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                Personal Contact
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
              <span>Edit Details</span>
            </button>
          </div>

          <div className="divide-y divide-[#F0F2F1] text-xs">
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">Full Name</span>
              <span className="font-medium text-[#20292C]">{user?.name}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">Phone</span>
              <span className="font-medium text-[#20292C]">{user?.phone || '—'}</span>
            </div>
            <div className="py-2 flex items-center justify-between">
              <span className="text-[#8D999C]">Email</span>
              <span className="font-medium text-[#20292C]">{user?.email || '—'}</span>
            </div>
          </div>
        </div>

        {/* Security & System Info */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-2 text-xs text-[#667174]">
          <div className="flex items-center gap-2 text-[#20292C] font-semibold font-['Space_Grotesk']">
            <Shield className="w-4 h-4 text-[#33B059]" />
            <span>Authorization Scoping</span>
          </div>
          <p className="text-[11px] leading-relaxed">
            Your permissions are enforced server-side according to your property and zone allocation. Task submissions require supervisor verification before completion.
          </p>
        </div>

        {/* Sign Out CTA */}
        <div className="pt-2">
          <SecondaryButton
            onClick={() => setShowLogoutConfirm(true)}
            icon={<LogOut className="w-4 h-4 text-[#D9534F]" />}
          >
            <span className="text-[#D9534F] font-semibold">Sign Out</span>
          </SecondaryButton>
        </div>

        {/* Release-verification marker — harmless build identifier for the
            1.0.2 over-the-air update test. */}
        <p className="text-center text-[11px] text-[#8D999C] pt-2">
          Update Test 1.0.2
        </p>

        {/* Update diagnostics — VITE_UPDATE_DEBUG builds only. */}
        {UPDATE_DEBUG && (
          <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-2 text-xs">
            <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
              App Information (Debug)
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
              Check for updates
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
                Edit Contact Details
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
                  Full Name
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
                  Phone Number
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
                  Email Address
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
                  Cancel
                </SecondaryButton>
                <PrimaryButton
                  type="submit"
                  loading={isSaving}
                  icon={editSuccess ? <Check className="w-4 h-4 stroke-[3]" /> : undefined}
                >
                  {editSuccess ? 'Saved' : 'Save Changes'}
                </PrimaryButton>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Logout Confirmation Dialog */}
      {showLogoutConfirm && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-white w-full max-w-sm rounded-3xl p-6 text-center space-y-4 animate-in zoom-in-95 duration-150 shadow-xl">
            <div className="w-12 h-12 rounded-2xl bg-[#FCEBEA] text-[#D9534F] flex items-center justify-center mx-auto">
              <LogOut className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-[#20292C] font-['Space_Grotesk']">
                Sign Out of AiROS Staff?
              </h3>
              <p className="text-xs text-[#667174] mt-1 leading-relaxed">
                You will need your staff credentials to sign back in and access active operational shifts.
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
                Sign Out
              </DangerButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
