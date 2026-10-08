import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import { MaintenanceTicket } from '../../types';
import {
  getMaintenanceDetailApi,
  startMaintenanceTicketApi,
  resolveMaintenanceTicketApi,
} from '../../api/maintenance';
import { uploadMediaApi } from '../../api/media';
import { mediaUrl, errorMessage } from '../../api/client';
import { ScreenHeader } from '../../components/common/ScreenHeader';
import { StatusBadge } from '../../components/common/StatusBadge';
import { PriorityBadge } from '../../components/common/PriorityBadge';
import { PrimaryButton, SecondaryButton } from '../../components/common/Buttons';
import { LoadingState, ErrorState } from '../../components/common/FeedbackStates';
import {
  MapPin,
  Calendar,
  User,
  Wrench,
  Camera,
  Upload,
  X,
  CheckCircle2,
  AlertTriangle,
  Play,
  FileCheck,
  History,
} from 'lucide-react';

interface MaintenanceDetailScreenProps {
  ticketId: string;
  onBack: () => void;
  onTicketUpdated?: () => void;
}

export const MaintenanceDetailScreen: React.FC<MaintenanceDetailScreenProps> = ({
  ticketId,
  onBack,
  onTicketUpdated,
}) => {
  const { user } = useAuth();
  const [ticket, setTicket] = useState<MaintenanceTicket | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Resolve sheet modal state
  const [isResolving, setIsResolving] = useState<boolean>(false);
  const [resolutionNotes, setResolutionNotes] = useState<string>('');
  const [resolutionPhotos, setResolutionPhotos] = useState<string[]>([]);
  const [uploadingPhoto, setUploadingPhoto] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadTicket = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getMaintenanceDetailApi(ticketId, user?.employee_uid ?? undefined);
      setTicket(data);
    } catch (err: unknown) {
      setError(errorMessage(err, 'Unable to retrieve maintenance ticket.'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTicket();
  }, [ticketId]);

  const isAssignedToMe = !!user?.employee_uid && ticket?.assigned_to_employee_id === user.employee_uid;
  const isReportedByMe = !!ticket?.is_reported_by_me;

  const handleStart = async () => {
    if (!ticket) return;
    try {
      setActionLoading(true);
      setActionError(null);
      const updated = await startMaintenanceTicketApi(ticket.id);
      setTicket(updated);
      if (onTicketUpdated) onTicketUpdated();
    } catch (err: unknown) {
      setActionError(errorMessage(err, 'Failed to start maintenance ticket.'));
    } finally {
      setActionLoading(false);
    }
  };

  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setUploadingPhoto(true);
      const reader = new FileReader();
      reader.onload = async (event) => {
        try {
          const dataUrl = event.target?.result as string;
          const uploaded = await uploadMediaApi(dataUrl, file.name);
          setResolutionPhotos((prev) => [...prev, uploaded.path]);
        } catch {
          setActionError('Failed to upload photo.');
        } finally {
          setUploadingPhoto(false);
          if (fileInputRef.current) fileInputRef.current.value = '';
        }
      };
      reader.readAsDataURL(file);
    } catch {
      setUploadingPhoto(false);
    }
  };

  const handleResolve = async () => {
    if (!ticket) return;
    if (resolutionNotes.trim().length < 3) {
      setActionError('Resolution notes must be at least 3 characters.');
      return;
    }

    try {
      setActionLoading(true);
      setActionError(null);
      const updated = await resolveMaintenanceTicketApi(ticket.id, {
        resolution_notes: resolutionNotes.trim(),
        photo_urls: resolutionPhotos,
      });

      setTicket(updated);
      setIsResolving(false);
      if (onTicketUpdated) onTicketUpdated();
    } catch (err: unknown) {
      setActionError(errorMessage(err, 'Unable to submit resolution.'));
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex flex-col bg-[#F7F8F6]">
        <ScreenHeader title="Maintenance Ticket" onBack={onBack} />
        <LoadingState message="Loading ticket details..." />
      </div>
    );
  }

  if (error || !ticket) {
    return (
      <div className="flex-1 flex flex-col bg-[#F7F8F6]">
        <ScreenHeader title="Maintenance Ticket" onBack={onBack} />
        <ErrorState message={error || 'Ticket not found'} onRetry={loadTicket} />
      </div>
    );
  }

  const createdDate = ticket.created_at ? new Date(ticket.created_at) : null;
  const createdFormatted = createdDate
    ? `${createdDate.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${createdDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : '—';

  return (
    <div className="flex-1 flex flex-col bg-[#F7F8F6] overflow-y-auto">
      <ScreenHeader
        title={ticket.ticket_number || ticket.id}
        subtitle={`${ticket.category} · ${ticket.location_name}`}
        onBack={onBack}
        rightElement={<StatusBadge status={ticket.status} size="sm" />}
      />

      <div className="p-4 space-y-4 pb-28">
        {/* Reported by you banner when assigned to another tech */}
        {isReportedByMe && !isAssignedToMe && (
          <div className="bg-[#EEF3FF] border border-[#C2D4FF] p-3.5 rounded-2xl flex items-center gap-2.5 text-xs text-[#2B5DD8]">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            <div>
              <span className="font-bold block font-['Space_Grotesk']">Reported by you</span>
              <span>
                Assigned to {ticket.assigned_to_name || 'an operations specialist'}. You can track status updates here.
              </span>
            </div>
          </div>
        )}

        {actionError && (
          <div className="bg-[#FCEBEA] border border-[#F8C8C6] p-3 rounded-xl text-xs text-[#D9534F] flex items-center justify-between">
            <span>{actionError}</span>
            <button onClick={() => setActionError(null)}><X className="w-4 h-4" /></button>
          </div>
        )}

        {/* Ticket Header Card */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[#667174]">
              {ticket.category}
            </span>
            <PriorityBadge priority={ticket.priority} />
          </div>

          <h2 className="text-xl font-bold text-[#20292C] font-['Space_Grotesk'] leading-tight">
            {ticket.issue}
          </h2>

          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-[#F0F2F1] text-xs">
            <div>
              <span className="text-[11px] text-[#8D999C] uppercase tracking-wider block mb-0.5">Location</span>
              <div className="flex items-center gap-1 text-[#20292C] font-medium">
                <MapPin className="w-3.5 h-3.5 text-[#8D999C]" />
                <span className="truncate">{ticket.location_name}</span>
              </div>
              <span className="text-[11px] text-[#667174] pl-4">{ticket.zone_name}</span>
            </div>

            <div>
              <span className="text-[11px] text-[#8D999C] uppercase tracking-wider block mb-0.5">Reported</span>
              <div className="flex items-center gap-1 font-medium text-[#20292C]">
                <Calendar className="w-3.5 h-3.5 text-[#8D999C]" />
                <span>{createdFormatted}</span>
              </div>
              <span className="text-[11px] text-[#667174] pl-4">by {ticket.reported_by_name}</span>
            </div>
          </div>

          <div className="pt-2 border-t border-[#F0F2F1] text-xs text-[#667174] flex items-center gap-1.5">
            <User className="w-3.5 h-3.5 text-[#8D999C]" />
            <span>
              Assigned technician:{' '}
              <strong className="text-[#20292C]">
                {ticket.assigned_to_name ? (isAssignedToMe ? 'You (Assigned)' : ticket.assigned_to_name) : 'Unassigned'}
              </strong>
            </span>
          </div>
        </div>

        {/* Issue Description */}
        {ticket.description && (
          <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
            <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider mb-2 font-['Space_Grotesk']">
              Issue Description
            </h3>
            <p className="text-xs text-[#20292C] leading-relaxed bg-[#F7F8F6] p-3 rounded-xl border border-[#E4E8E6]">
              {ticket.description}
            </p>
          </div>
        )}

        {/* Initial Issue Photos */}
        {ticket.photos.length > 0 && (
          <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
            <h3 className="text-xs font-bold text-[#20292C] uppercase tracking-wider mb-2 font-['Space_Grotesk']">
              Reported Photos ({ticket.photos.length})
            </h3>
            <div className="grid grid-cols-2 gap-3">
              {ticket.photos.map((url, i) => (
                <div key={i} className="aspect-video rounded-xl overflow-hidden border border-[#E4E8E6]">
                  <img src={mediaUrl(url)} alt="Reported problem" className="w-full h-full object-cover" />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Resolution Details if Resolved */}
        {ticket.status === 'resolved' && (
          <div className="bg-[#E8F7ED] border border-[#BBECCC] rounded-2xl p-4 shadow-sm space-y-2">
            <div className="flex items-center gap-2 text-[#278B46]">
              <FileCheck className="w-5 h-5" />
              <h3 className="text-sm font-bold font-['Space_Grotesk']">
                Resolved by Technician
              </h3>
            </div>
            <p className="text-xs text-[#20292C] font-medium leading-relaxed bg-white p-3 rounded-xl border border-[#BBECCC]">
              {ticket.resolution_notes}
            </p>
            {ticket.resolution_photos && ticket.resolution_photos.length > 0 && (
              <div className="grid grid-cols-2 gap-2 pt-2">
                {ticket.resolution_photos.map((url, i) => (
                  <div key={i} className="aspect-video rounded-xl overflow-hidden border border-[#BBECCC]">
                    <img src={mediaUrl(url)} alt="Resolution" className="w-full h-full object-cover" />
                  </div>
                ))}
              </div>
            )}
            <p className="text-[11px] text-[#667174] pt-1">
              Ticket has been submitted for property manager final audit and closure.
            </p>
          </div>
        )}

        {/* Activity Timeline */}
        {ticket.history && ticket.history.length > 0 && (
          <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
            <div className="flex items-center gap-2 mb-3">
              <History className="w-4 h-4 text-[#33B059]" />
              <h3 className="text-sm font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                Activity
              </h3>
            </div>
            <div className="space-y-3 relative pl-4 before:content-[''] before:absolute before:top-2 before:bottom-2 before:left-1.5 before:w-0.5 before:bg-[#E4E8E6]">
              {ticket.history.map((h, i) => (
                <div key={i} className="relative">
                  <span className="absolute -left-[19px] top-1 w-2.5 h-2.5 rounded-full bg-[#33B059] ring-4 ring-white" />
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-[#20292C] capitalize">
                      {h.status.replace('_', ' ')}
                    </span>
                    <span className="text-[11px] text-[#8D999C]">
                      {new Date(h.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <span className="text-[11px] text-[#667174]">by {h.actor_name}</span>
                  {h.notes && (
                    <p className="text-[11px] text-[#20292C] mt-1 bg-[#F7F8F6] p-2 rounded-lg border border-[#E4E8E6]">
                      {h.notes}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Action Footer for Assigned Employee */}
      {isAssignedToMe && (
        <div className="fixed md:absolute bottom-0 inset-x-0 p-4 bg-white/95 backdrop-blur border-t border-[#E4E8E6] shadow-lg z-20">
          {ticket.status === 'assigned' && (
            <PrimaryButton
              size="lg"
              loading={actionLoading}
              onClick={handleStart}
              icon={<Play className="w-5 h-5 fill-current" />}
            >
              Start Work
            </PrimaryButton>
          )}

          {ticket.status === 'in_progress' && (
            <PrimaryButton
              size="lg"
              onClick={() => setIsResolving(true)}
              icon={<FileCheck className="w-5 h-5" />}
            >
              Resolve Ticket
            </PrimaryButton>
          )}

          {ticket.status === 'resolved' && (
            <div className="text-center py-1">
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#278B46] bg-[#E8F7ED] px-4 py-2 rounded-full border border-[#BBECCC]">
                <CheckCircle2 className="w-4 h-4" />
                Work Resolved · Under Manager Review
              </span>
            </div>
          )}
        </div>
      )}

      {/* Resolution Sheet / Modal */}
      {isResolving && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-end md:items-center justify-center p-0 md:p-4">
          <div className="bg-white w-full max-w-md rounded-t-3xl md:rounded-3xl p-5 space-y-4 animate-in slide-in-from-bottom duration-200">
            <div className="flex items-center justify-between border-b border-[#F0F2F1] pb-3">
              <div>
                <h3 className="text-base font-bold text-[#20292C] font-['Space_Grotesk']">
                  Resolve Maintenance Ticket
                </h3>
                <p className="text-xs text-[#667174]">
                  Describe the corrective action taken to fix the issue.
                </p>
              </div>
              <button
                onClick={() => setIsResolving(false)}
                className="p-1.5 rounded-full text-[#8D999C] hover:bg-[#F0F2F1]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div>
              <label className="block text-xs font-bold text-[#20292C] uppercase tracking-wider mb-1 font-['Space_Grotesk']">
                Resolution Notes (Required, min 3 chars)
              </label>
              <textarea
                value={resolutionNotes}
                onChange={(e) => setResolutionNotes(e.target.value)}
                placeholder="e.g. Replaced leaking seal gasket, adjusted pressure valve, and verified dry operation for 10 minutes."
                rows={3}
                className="w-full p-3 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-xs text-[#20292C] focus:bg-white focus:outline-none focus:border-[#33B059]"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-[#20292C] uppercase tracking-wider mb-2 font-['Space_Grotesk']">
                Resolution Photo Proof (Optional)
              </label>
              <div className="grid grid-cols-2 gap-2 mb-2">
                {resolutionPhotos.map((url, i) => (
                  <div key={i} className="aspect-video rounded-xl overflow-hidden border border-[#E4E8E6] relative">
                    <img src={mediaUrl(url)} alt="Proof" className="w-full h-full object-cover" />
                    <button
                      onClick={() => setResolutionPhotos((p) => p.filter((_, idx) => idx !== i))}
                      className="absolute top-1 right-1 p-1 bg-black/60 rounded-full text-white"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                <label className="aspect-video rounded-xl border-2 border-dashed border-[#D2D8D6] bg-[#F7F8F6] flex flex-col items-center justify-center cursor-pointer p-2 text-center">
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={handlePhotoUpload}
                    className="hidden"
                  />
                  {uploadingPhoto ? (
                    <Upload className="w-4 h-4 text-[#33B059] animate-bounce" />
                  ) : (
                    <>
                      <Camera className="w-4 h-4 text-[#667174] mb-1" />
                      <span className="text-[11px] font-semibold text-[#20292C]">+ Add Photo</span>
                    </>
                  )}
                </label>
              </div>
            </div>

            <div className="pt-2 flex gap-3">
              <SecondaryButton onClick={() => setIsResolving(false)}>
                Cancel
              </SecondaryButton>
              <PrimaryButton
                loading={actionLoading}
                disabled={resolutionNotes.trim().length < 3}
                onClick={handleResolve}
                icon={<CheckCircle2 className="w-4 h-4" />}
              >
                Confirm Resolution
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
