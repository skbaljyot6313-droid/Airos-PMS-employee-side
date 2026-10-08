import React, { useState, useEffect, useRef } from 'react';
import { Capacitor } from '@capacitor/core';
import { Camera as CapCamera, CameraResultType, CameraSource } from '@capacitor/camera';
import { Task, EvidenceItem } from '../../types';
import { getTaskDetailApi, submitTaskApi, startTaskApi } from '../../api/tasks';
import { uploadMediaApi } from '../../api/media';
import { mediaUrl, errorMessage } from '../../api/client';
import { ScreenHeader } from '../../components/common/ScreenHeader';
import { StatusBadge } from '../../components/common/StatusBadge';
import { PriorityBadge } from '../../components/common/PriorityBadge';
import { PrimaryButton, SecondaryButton } from '../../components/common/Buttons';
import { LoadingState, ErrorState } from '../../components/common/FeedbackStates';
import {
  MapPin,
  Clock,
  User,
  CheckSquare,
  Square,
  Camera,
  Upload,
  X,
  AlertTriangle,
  Calendar,
  CheckCircle2,
  FileText,
  History,
  Image as ImageIcon,
  Send,
  RotateCcw,
} from 'lucide-react';

interface TaskDetailScreenProps {
  taskId: string;
  onBack: () => void;
  onTaskUpdated?: () => void;
}

export const TaskDetailScreen: React.FC<TaskDetailScreenProps> = ({
  taskId,
  onBack,
  onTaskUpdated,
}) => {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<boolean>(false);
  const [notes, setNotes] = useState<string>('');

  // Local checklist state for interactive checking
  const [checklist, setChecklist] = useState<{ id: string; label: string; required: boolean; completed: boolean }[]>([]);
  // Local evidence photos
  const [evidenceList, setEvidenceList] = useState<EvidenceItem[]>([]);
  const [uploadingPhoto, setUploadingPhoto] = useState<boolean>(false);
  const [showPhotoOptions, setShowPhotoOptions] = useState<boolean>(false);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);

  const loadTask = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getTaskDetailApi(taskId);
      setTask(data);
      setChecklist(data.checklist);
      // Reopened tasks start with an empty editable list — earlier photos
      // stay visible read-only under "Previously Submitted" instead.
      setEvidenceList(data.status === 'reopened' ? [] : data.evidence);
    } catch (err: unknown) {
      setError(errorMessage(err, 'Unable to load task details.'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTask();
  }, [taskId]);

  const handleToggleChecklist = (itemId: string) => {
    if (!task || !canWork) return;
    setChecklist((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, completed: !item.completed } : item))
    );
  };

  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const inputEl = e.target;
    const file = inputEl.files?.[0];
    if (!file) return;

    try {
      setUploadingPhoto(true);
      setActionError(null);

      // Convert file to data URI
      const reader = new FileReader();
      reader.onload = async (event) => {
        try {
          const dataUrl = event.target?.result as string;
          const uploaded = await uploadMediaApi(dataUrl, file.name);
          setEvidenceList((prev) => [
            ...prev,
            { id: uploaded.key, url: uploaded.path, filename: file.name, uploaded_at: null },
          ]);
        } catch (uploadErr: unknown) {
          setActionError(errorMessage(uploadErr, 'Failed to upload photo evidence.'));
        } finally {
          setUploadingPhoto(false);
          inputEl.value = '';
        }
      };
      reader.readAsDataURL(file);
    } catch (err: unknown) {
      setActionError(errorMessage(err, 'Unable to process image file.'));
      setUploadingPhoto(false);
    }
  };

  const handleNativePhoto = async (source: 'camera' | 'gallery') => {
    setShowPhotoOptions(false);
    try {
      setUploadingPhoto(true);
      setActionError(null);
      const photo = await CapCamera.getPhoto({
        resultType: CameraResultType.DataUrl,
        source: source === 'camera' ? CameraSource.Camera : CameraSource.Photos,
        quality: 85,
      });
      if (photo.dataUrl) {
        const fileName = `evidence_${Date.now()}.${photo.format || 'jpeg'}`;
        const uploaded = await uploadMediaApi(photo.dataUrl, fileName);
        setEvidenceList((prev) => [
          ...prev,
          { id: uploaded.key, url: uploaded.path, filename: fileName, uploaded_at: null },
        ]);
      }
    } catch (err: unknown) {
      if (!/cancel/i.test(errorMessage(err, ''))) {
        setActionError(errorMessage(err, 'Failed to capture photo.'));
      }
    } finally {
      setUploadingPhoto(false);
    }
  };

  const handleRemovePhoto = (photoId: string) => {
    if (!task || !canWork) return;
    setEvidenceList((prev) => prev.filter((p) => p.id !== photoId));
  };

  const handleSubmitForReview = async () => {
    if (!task) return;
    setActionError(null);

    // 1. Validate required checklist items
    const requiredIncomplete = checklist.some((item) => item.required && !item.completed);
    if (requiredIncomplete) {
      setActionError('All required checklist items must be checked before submitting.');
      return;
    }

    // 2. Validate photos
    const minPhotos = task.verification_config.min_photos;
    if (task.verification_config.photo_required && evidenceList.length < minPhotos) {
      setActionError(
        `At least ${minPhotos} photo evidence item${minPhotos > 1 ? 's are' : ' is'} required before submission.`
      );
      return;
    }

    try {
      setActionLoading(true);
      // The backend lifecycle is start → submit: starting marks the task
      // in_progress and flags the resource for cleaning. Startable tasks
      // are auto-started in the same action so no Start button is needed.
      if (['pending', 'assigned', 'reopened'].includes(task.status)) {
        await startTaskApi(task.id);
      }
      const updated = await submitTaskApi(task.id, {
        note: notes.trim() || undefined,
        photo_urls: evidenceList.map((p) => p.url),
      });

      setTask(updated);
      setSubmitSuccess(true);
      if (onTaskUpdated) onTaskUpdated();
    } catch (err: unknown) {
      setActionError(errorMessage(err, 'Submission failed. Please check connection and try again.'));
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex flex-col bg-[#F7F8F6]">
        <ScreenHeader title="Task Details" onBack={onBack} />
        <LoadingState message="Retrieving task operational specifications..." />
      </div>
    );
  }

  if (error || !task) {
    return (
      <div className="flex-1 flex flex-col bg-[#F7F8F6]">
        <ScreenHeader title="Task Details" onBack={onBack} />
        <ErrorState message={error || 'Task not found'} onRetry={loadTask} />
      </div>
    );
  }

  const isExpired = task.expires_at && new Date(task.expires_at).getTime() < Date.now();
  const dueTime = task.due_at ? new Date(task.due_at).getTime() : null;
  const isOverdue =
    task.status === 'overdue' ||
    (!!dueTime && dueTime < Date.now() && !['completed', 'cancelled', 'submitted'].includes(task.status));

  const canWork = ['assigned', 'pending', 'in_progress', 'reopened'].includes(task.status) && !isExpired;
  const isSubmitted = task.status === 'submitted';
  const isCompleted = task.status === 'completed';
  const isReopened = task.status === 'reopened';

  // Submission statuses come from the review workflow (pending/approved/disapproved).
  const submissionStatusChip = (status: string): string => {
    if (status === 'approved') return 'bg-[#E8F7ED] text-[#278B46] border-[#BBECCC]';
    if (status === 'disapproved' || status === 'rejected')
      return 'bg-[#FCEBEA] text-[#D9534F] border-[#F8C8C6]';
    return 'bg-[#EEF3FF] text-[#2B5DD8] border-[#C2D4FF]';
  };

  const dueDate = task.due_at ? new Date(task.due_at) : null;
  const dueFormatted = dueDate
    ? `${dueDate.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${dueDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : task.due_date
    ? new Date(task.due_date + 'T00:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' })
    : '—';

  return (
    <div className="flex-1 flex flex-col bg-[#F7F8F6] overflow-y-auto">
      <ScreenHeader
        title={task.ticket_number || task.title}
        subtitle={`${task.category} · ${task.location_name}`}
        onBack={onBack}
        rightElement={<StatusBadge status={isOverdue ? 'overdue' : task.status} size="sm" />}
      />

      <div className="p-4 space-y-4 pb-28">
        {/* Reopened / Rework Banner */}
        {task.status === 'reopened' && task.reopen_reason && (
          <div className="bg-[#FDF6E8] border border-[#F5DEAB] rounded-2xl p-4 shadow-sm">
            <div className="flex items-start gap-2.5">
              <div className="p-2 bg-[#F5DEAB]/50 rounded-xl text-[#B87C10]">
                <RotateCcw className="w-5 h-5 stroke-[2.25]" />
              </div>
              <div className="flex-1">
                <h4 className="text-sm font-bold text-[#B87C10] font-['Space_Grotesk']">
                  Returned for Correction
                </h4>
                <p className="text-xs text-[#20292C] font-medium mt-1 leading-relaxed">
                  {task.reopen_reason}
                </p>
                <p className="text-[11px] text-[#667174] mt-2 font-medium">
                  Please review the supervisor feedback, make the required changes, and submit the task again.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Expired Banner */}
        {isExpired && (
          <div className="bg-[#FCEBEA] border border-[#F8C8C6] rounded-2xl p-4 text-xs text-[#D9534F] flex items-center gap-2.5">
            <AlertTriangle className="w-5 h-5 flex-shrink-0" />
            <div>
              <span className="font-bold block">Task Execution Window Expired</span>
              <span>This task has surpassed its valid operational window and can no longer be worked on.</span>
            </div>
          </div>
        )}

        {/* Success Confirmation Banner */}
        {submitSuccess && (
          <div className="bg-[#E8F7ED] border border-[#BBECCC] rounded-2xl p-4 text-xs text-[#278B46] flex items-start gap-3 shadow-sm">
            <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <span className="font-bold text-sm block font-['Space_Grotesk'] mb-0.5">
                Submitted for Review
              </span>
              <span>
                Your completed work and photographic evidence have been sent to the Property Manager for verification.
              </span>
            </div>
          </div>
        )}

        {/* Action Error Banner */}
        {actionError && (
          <div className="bg-[#FCEBEA] border border-[#F8C8C6] rounded-2xl p-3.5 text-xs text-[#D9534F] flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div className="flex-1">{actionError}</div>
            <button onClick={() => setActionError(null)} className="text-[#D9534F]">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Task Title & Meta Card */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-[#667174]">
              {task.category}
            </span>
            <PriorityBadge priority={task.priority} />
          </div>

          <h2 className="text-xl font-bold text-[#20292C] font-['Space_Grotesk'] leading-tight">
            {task.title}
          </h2>

          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-[#F0F2F1] text-xs">
            <div>
              <span className="text-[11px] text-[#8D999C] uppercase tracking-wider block mb-0.5">
                Location
              </span>
              <div className="flex items-center gap-1 text-[#20292C] font-medium">
                <MapPin className="w-3.5 h-3.5 text-[#8D999C]" />
                <span className="truncate">{task.location_name}</span>
              </div>
              <span className="text-[11px] text-[#667174] pl-4">{task.zone_name}</span>
            </div>

            <div>
              <span className="text-[11px] text-[#8D999C] uppercase tracking-wider block mb-0.5">
                Due Time
              </span>
              <div className="flex items-center gap-1 font-medium text-[#20292C]">
                <Clock className={`w-3.5 h-3.5 ${isOverdue ? 'text-[#D9534F]' : 'text-[#8D999C]'}`} />
                <span className={isOverdue ? 'text-[#D9534F] font-bold' : ''}>
                  {dueFormatted}
                </span>
              </div>
              {task.scheduled_for && (
                <span className="text-[11px] text-[#667174] pl-4">
                  Scheduled shift task
                </span>
              )}
            </div>
          </div>

          <div className="pt-2 border-t border-[#F0F2F1] flex items-center justify-between text-xs text-[#667174]">
            <div className="flex items-center gap-1.5">
              <User className="w-3.5 h-3.5 text-[#8D999C]" />
              <span>Assigned to: <strong className="text-[#20292C]">{task.assigned_to_name}</strong></span>
            </div>
          </div>
        </div>

        {/* Instructions */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <FileText className="w-4 h-4 text-[#33B059]" />
            <h3 className="text-sm font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
              Instructions
            </h3>
          </div>
          <p className="text-xs text-[#20292C] leading-relaxed whitespace-pre-line bg-[#F7F8F6] p-3 rounded-xl border border-[#E4E8E6]">
            {task.instructions}
          </p>
        </div>

        {/* Interactive Checklist */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <CheckSquare className="w-4 h-4 text-[#33B059]" />
              <h3 className="text-sm font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                Checklist ({checklist.filter((c) => c.completed).length}/{checklist.length})
              </h3>
            </div>
            {!canWork && (
              <span className="text-[11px] text-[#8D999C]">
                {task.status === 'submitted' ? 'Submitted' : 'Read only'}
              </span>
            )}
          </div>

          <div className="space-y-2">
            {checklist.map((item) => {
              const isLocked = !canWork;
              return (
                <div
                  key={item.id}
                  onClick={() => !isLocked && handleToggleChecklist(item.id)}
                  className={`flex items-start gap-3 p-3 rounded-xl border transition-all ${
                    isLocked ? 'cursor-default' : 'cursor-pointer active:bg-[#F0F2F1]'
                  } ${
                    item.completed
                      ? 'bg-[#E8F7ED]/50 border-[#BBECCC]'
                      : 'bg-[#F7F8F6] border-[#E4E8E6]'
                  }`}
                >
                  <div className="mt-0.5 flex-shrink-0">
                    {item.completed ? (
                      <CheckSquare className="w-5 h-5 text-[#33B059] fill-[#E8F7ED]" />
                    ) : (
                      <Square className="w-5 h-5 text-[#8D999C]" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <span
                      className={`text-xs block leading-snug ${
                        item.completed ? 'line-through text-[#667174]' : 'text-[#20292C] font-medium'
                      }`}
                    >
                      {item.label}
                    </span>
                    <div className="flex items-center gap-2 mt-1">
                      {item.required ? (
                        <span className="text-[10px] font-bold uppercase tracking-wider text-[#D9534F] bg-[#FCEBEA] px-1.5 py-0.2 rounded">
                          Required
                        </span>
                      ) : (
                        <span className="text-[10px] text-[#8D999C] uppercase tracking-wider">
                          Optional
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Previously Submitted Photos (read-only) — reopened tasks */}
        {isReopened && task.prior_submissions.length > 0 && (
          <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
            <div className="flex items-center gap-2 mb-1.5">
              <ImageIcon className="w-4 h-4 text-[#B87C10]" />
              <h3 className="text-sm font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                Previously Submitted
              </h3>
            </div>
            <p className="text-xs text-[#667174] mb-3">
              These photos were sent with your earlier submission and can't be edited — add new photos below.
            </p>

            <div className="space-y-3">
              {task.prior_submissions.map((sub) => {
                const submittedAt = sub.submitted_at ? new Date(sub.submitted_at) : null;
                const submittedLabel = submittedAt
                  ? `${submittedAt.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${submittedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
                  : '—';
                return (
                  <div
                    key={sub.attempt}
                    className="rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] p-3"
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-xs font-bold text-[#20292C] font-['Space_Grotesk']">
                        Attempt {sub.attempt}
                      </span>
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${submissionStatusChip(sub.status)}`}
                        >
                          {sub.status.replaceAll('_', ' ')}
                        </span>
                        <span className="text-[11px] text-[#8D999C]">{submittedLabel}</span>
                      </div>
                    </div>

                    {sub.review_comment && (
                      <div className="mb-2 bg-white rounded-lg border border-[#E4E8E6] border-l-2 border-l-[#B87C10] p-2">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-[#667174] block mb-0.5">
                          Reviewer note{sub.reviewed_by_name ? ` · ${sub.reviewed_by_name}` : ''}
                        </span>
                        <p className="text-xs text-[#20292C] italic leading-relaxed">
                          "{sub.review_comment}"
                        </p>
                      </div>
                    )}

                    <div className="grid grid-cols-2 gap-3">
                      {sub.photos.map((photo) => (
                        <div
                          key={photo.id}
                          className="relative aspect-video rounded-xl overflow-hidden border border-[#E4E8E6] bg-black/5"
                        >
                          <img
                            src={mediaUrl(photo.url)}
                            alt={photo.filename || 'Previously submitted evidence'}
                            className="w-full h-full object-cover"
                          />
                          <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent p-1.5">
                            <span className="text-[10px] text-white/90 truncate block">
                              {photo.filename}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Photo Evidence Section */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Camera className="w-4 h-4 text-[#33B059]" />
              <h3 className="text-sm font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
                {isReopened ? 'New Photo Evidence' : 'Photo Evidence'} ({evidenceList.length}/{task.verification_config.max_photos})
              </h3>
            </div>
            {task.verification_config.photo_required && (
              <span className="text-[11px] font-bold text-[#33B059] bg-[#E8F7ED] px-2 py-0.5 rounded-full">
                Min {task.verification_config.min_photos} required
              </span>
            )}
          </div>

          <p className="text-xs text-[#667174] mb-3">
            {isReopened
              ? 'Capture new photos showing the corrected work.'
              : 'Capture clear photos of the completed work and restored condition.'}
          </p>

          {/* Photos Grid */}
          <div className="grid grid-cols-2 gap-3 mb-3">
            {evidenceList.map((photo) => (
              <div
                key={photo.id}
                className="relative aspect-video rounded-xl overflow-hidden border border-[#E4E8E6] bg-black/5 group"
              >
                <img
                  src={mediaUrl(photo.url)}
                  alt={photo.filename || 'Task evidence'}
                  className="w-full h-full object-cover"
                />
                {canWork && (
                  <button
                    onClick={() => handleRemovePhoto(photo.id)}
                    aria-label="Remove photo"
                    className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/60 text-white hover:bg-black/80 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
                <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent p-1.5">
                  <span className="text-[10px] text-white/90 truncate block">
                    {photo.filename}
                  </span>
                </div>
              </div>
            ))}

            {/* Add Photo Button (active during in_progress) */}
            {canWork && evidenceList.length < task.verification_config.max_photos && (
              <button
                type="button"
                onClick={() => setShowPhotoOptions(true)}
                disabled={uploadingPhoto}
                className={`aspect-video rounded-xl border-2 border-dashed border-[#D2D8D6] bg-[#F7F8F6] hover:bg-[#F0F2F1] transition-all flex flex-col items-center justify-center cursor-pointer p-2 ${
                  uploadingPhoto ? 'opacity-50 pointer-events-none' : ''
                }`}
              >
                {uploadingPhoto ? (
                  <div className="text-center">
                    <Upload className="w-5 h-5 text-[#33B059] animate-bounce mx-auto mb-1" />
                    <span className="text-[11px] text-[#667174] font-medium">Uploading...</span>
                  </div>
                ) : (
                  <div className="text-center">
                    <Camera className="w-5 h-5 text-[#667174] mx-auto mb-1" />
                    <span className="text-[11px] font-semibold text-[#20292C] block">
                      + Add Photo
                    </span>
                    <span className="text-[10px] text-[#8D999C]">Camera or Gallery</span>
                  </div>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Task Notes for Submission */}
        {canWork && (
          <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
            <label className="block text-xs font-bold text-[#20292C] uppercase tracking-wider mb-1.5 font-['Space_Grotesk']">
              Completion Notes (Optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add any operational remarks for the property manager..."
              rows={2}
              className="w-full p-3 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-xs text-[#20292C] placeholder-[#8D999C] focus:bg-white focus:outline-none focus:border-[#33B059]"
            />
          </div>
        )}

        {/* Task Timeline */}
        <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <History className="w-4 h-4 text-[#33B059]" />
            <h3 className="text-sm font-bold text-[#20292C] uppercase tracking-wider font-['Space_Grotesk']">
              Task History
            </h3>
          </div>

          <div className="space-y-3 relative pl-4 before:content-[''] before:absolute before:top-2 before:bottom-2 before:left-1.5 before:w-0.5 before:bg-[#E4E8E6]">
            {task.history.map((hist) => {
              const eventDate = new Date(hist.timestamp);
              const eventTime = `${eventDate.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${eventDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;

              const labels: Record<string, string> = {
                allocated: 'Allocated to Employee',
                started: 'Task Started',
                submitted: 'Submitted for Review',
                returned: 'Returned for Correction',
                reopened: 'Reopened',
                approved: 'Approved by Manager',
              };

              return (
                <div key={hist.id} className="relative">
                  <span className="absolute -left-[19px] top-1 w-2.5 h-2.5 rounded-full bg-[#33B059] ring-4 ring-white" />
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-[#20292C]">
                      {labels[hist.event_type] || hist.event_type}
                    </span>
                    <span className="text-[11px] text-[#8D999C]">{eventTime}</span>
                  </div>
                  <div className="text-[11px] text-[#667174] mt-0.5">
                    <span>by {hist.actor_name}</span>
                    {hist.notes && (
                      <p className="mt-1 text-[#20292C] bg-[#F7F8F6] p-2 rounded-lg border border-[#E4E8E6]">
                        {hist.notes}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Hidden file inputs: camera capture + gallery picker */}
      <input
        ref={cameraInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        onChange={handlePhotoUpload}
        className="hidden"
      />
      <input
        ref={galleryInputRef}
        type="file"
        accept="image/*"
        onChange={handlePhotoUpload}
        className="hidden"
      />

      {/* Photo Source Chooser Sheet */}
      {showPhotoOptions && (
        <div
          className="fixed inset-0 z-40 flex items-end justify-center bg-black/40"
          onClick={() => setShowPhotoOptions(false)}
        >
          <div
            className="w-full max-w-[420px] bg-white rounded-t-3xl p-5 pb-8 space-y-2.5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-10 h-1 bg-[#E4E8E6] rounded-full mx-auto mb-3" />
            <h4 className="text-sm font-bold text-[#20292C] font-['Space_Grotesk'] mb-3">
              Add Photo Evidence
            </h4>
            <button
              type="button"
              onClick={() => {
                if (Capacitor.isNativePlatform()) {
                  handleNativePhoto('camera');
                } else {
                  setShowPhotoOptions(false);
                  cameraInputRef.current?.click();
                }
              }}
              className="w-full flex items-center gap-3 p-3.5 rounded-xl border border-[#E4E8E6] hover:bg-[#F7F8F6] active:bg-[#F0F2F1] transition-colors text-left"
            >
              <div className="p-2 bg-[#E8F7ED] rounded-lg text-[#33B059]">
                <Camera className="w-5 h-5" />
              </div>
              <div>
                <span className="text-sm font-semibold text-[#20292C] block">Take Photo</span>
                <span className="text-[11px] text-[#8D999C]">Use camera to capture now</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => {
                if (Capacitor.isNativePlatform()) {
                  handleNativePhoto('gallery');
                } else {
                  setShowPhotoOptions(false);
                  galleryInputRef.current?.click();
                }
              }}
              className="w-full flex items-center gap-3 p-3.5 rounded-xl border border-[#E4E8E6] hover:bg-[#F7F8F6] active:bg-[#F0F2F1] transition-colors text-left"
            >
              <div className="p-2 bg-[#EEF3FF] rounded-lg text-[#2B5DD8]">
                <ImageIcon className="w-5 h-5" />
              </div>
              <div>
                <span className="text-sm font-semibold text-[#20292C] block">Choose from Gallery</span>
                <span className="text-[11px] text-[#8D999C]">Select an existing photo</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => setShowPhotoOptions(false)}
              className="w-full p-3 rounded-xl text-xs font-semibold text-[#667174] hover:bg-[#F7F8F6] transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Sticky Bottom Action Area */}
      <div className="fixed md:absolute bottom-0 inset-x-0 p-4 bg-white/95 backdrop-blur border-t border-[#E4E8E6] shadow-lg z-20">
        {canWork && (
          <PrimaryButton
            size="lg"
            loading={actionLoading}
            onClick={handleSubmitForReview}
            icon={<Send className="w-5 h-5" />}
          >
            Submit for Review
          </PrimaryButton>
        )}

        {isSubmitted && (
          <div className="text-center py-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#2B5DD8] bg-[#EEF3FF] px-4 py-2 rounded-full border border-[#C2D4FF]">
              <Clock className="w-4 h-4" />
              Awaiting Property Manager Review
            </span>
          </div>
        )}

        {isCompleted && (
          <div className="text-center py-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#278B46] bg-[#E8F7ED] px-4 py-2 rounded-full border border-[#BBECCC]">
              <CheckCircle2 className="w-4 h-4" />
              Task Completed & Approved
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
