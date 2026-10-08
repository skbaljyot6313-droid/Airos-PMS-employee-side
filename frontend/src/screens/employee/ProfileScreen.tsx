import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { PrimaryButton, SecondaryButton, DangerButton } from '../../components/common/Buttons';
import { errorMessage } from '../../api/client';
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
