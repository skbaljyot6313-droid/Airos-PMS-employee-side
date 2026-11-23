import React, { useState, useEffect, useRef } from 'react';
import { Capacitor } from '@capacitor/core';
import { Camera as CapCamera, CameraResultType, CameraSource } from '@capacitor/camera';
import { Task, EvidenceItem } from '../../types';
import { getTaskDetailApi, submitTaskApi, startTaskApi } from '../../api/tasks';
import { uploadMediaApi } from '../../api/media';
import { mediaUrl, errorMessage } from '../../api/client';
import { subscribeRealtimeEvents } from '../../services/realtime';
import { ScreenHeader } from '../../components/common/ScreenHeader';
import { StatusBadge } from '../../components/common/StatusBadge';
import { PriorityBadge } from '../../components/common/PriorityBadge';
import { PrimaryButton, SecondaryButton } from '../../components/common/Buttons';
import { LoadingState, ErrorState } from '../../components/common/FeedbackStates';
import { useTranslation } from 'react-i18next';
import { SpeakButton } from '../../components/common/SpeakButton';
import { ResourceChips } from '../../components/tasks/ResourceChips';
import { resolveTaskText } from '../../i18n/taskText';
import { currentUiLanguage } from '../../i18n';
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
  const { t } = useTranslation();
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
      setError(errorMessage(err, t('tasks.loadDetailError')));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTask();
  }, [taskId]);

  // Realtime invalidation — a task event re-pulls the authoritative record.
  useEffect(
    () =>
      subscribeRealtimeEvents(['task.'], () => {
        void loadTask();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [taskId],
  );

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
          setActionError(errorMessage(uploadErr, t('tasks.photoUploadFailed')));
        } finally {
          setUploadingPhoto(false);
          inputEl.value = '';
        }
      };
      reader.readAsDataURL(file);
    } catch (err: unknown) {
      setActionError(errorMessage(err, t('tasks.photoProcessFailed')));
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
        setActionError(errorMessage(err, t('tasks.photoCaptureFailed')));
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
      setActionError(t('tasks.checklistRequiredError'));
      return;
    }

    // 2. Validate photos
    const minPhotos = task.verification_config.min_photos;
    if (task.verification_config.photo_required && evidenceList.length < minPhotos) {
      setActionError(
        t('tasks.photoRequiredError', { count: minPhotos })
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
      setActionError(errorMessage(err, t('tasks.submitFailed')));
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex flex-col bg-[#FFFCFA]">
        <ScreenHeader title={t('tasks.detailsTitle')} onBack={onBack} />
        <LoadingState message={t('tasks.loadDetail')} />
      </div>
    );
  }

  if (error || !task) {
    return (
      <div className="flex-1 flex flex-col bg-[#FFFCFA]">
        <ScreenHeader title={t('tasks.detailsTitle')} onBack={onBack} />
        <ErrorState message={error || t('tasks.notFound')} onRetry={loadTask} />
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
    if (status === 'approved') return 'bg-[#F7E9EE] text-[#0D1C42] border-[#EAD3DB]';
    if (status === 'disapproved' || status === 'rejected')
      return 'bg-[#FAEBEB] text-[#D64545] border-[#F0C8C8]';
    return 'bg-[#EAF1FB] text-[#3478D4] border-[#C2D4FF]';
  };

  const resolvedText = resolveTaskText(task, currentUiLanguage());
  const dueDate = task.due_at ? new Date(task.due_at) : null;
  const dueFormatted = dueDate
    ? `${dueDate.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${dueDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
    : task.due_date
    ? new Date(task.due_date + 'T00:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' })
    : '—';

  return (
    <div className="flex-1 flex flex-col bg-[#FFFCFA] overflow-y-auto">
      <ScreenHeader
        title={task.ticket_number || task.title}
        subtitle={`${task.category} · ${task.location_name}`}
        onBack={onBack}
        rightElement={
          <div className="flex items-center gap-1 flex-shrink-0">
            <SpeakButton task={task} />
            <StatusBadge status={isOverdue ? 'overdue' : task.status} size="sm" />
          </div>
        }
      />

      <div className="p-4 space-y-4 pb-28">
        {/* Reopened / Rework Banner */}
        {task.status === 'reopened' && task.reopen_reason && (
          <div className="bg-[#FDF6E8] border border-[#FDF3E2] rounded-2xl p-4 shadow-sm">
            <div className="flex items-start gap-2.5">
              <div className="p-2 bg-[#FDF3E2]/50 rounded-xl text-[#A56514]">
                <RotateCcw className="w-5 h-5 stroke-[2.25]" />
              </div>
              <div className="flex-1">
                <h4 className="text-sm font-bold text-[#A56514] font-['Satoshi']">
                  {t('tasks.returnedTitle')}
                </h4>
                <p className="text-xs text-[#0D1C42] font-medium mt-1 leading-relaxed">
                  {task.reopen_reason}
                </p>
                <p className="text-[9px] text-[#667085] mt-2 font-medium">
                  {t('tasks.returnedDesc')}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Expired Banner */}
        {isExpired && (
          <div className="bg-[#FAEBEB] border border-[#F0C8C8] rounded-2xl p-4 text-xs text-[#D64545] flex items-center gap-2.5">
            <AlertTriangle className="w-5 h-5 flex-shrink-0" />
            <div>
              <span className="font-bold block">{t('tasks.expiredTitle')}</span>
              <span>{t('tasks.expiredDesc')}</span>
            </div>
          </div>
        )}

        {/* Success Confirmation Banner */}
        {submitSuccess && (
          <div className="bg-[#F7E9EE] border border-[#EAD3DB] rounded-2xl p-4 text-xs text-[#0D1C42] flex items-start gap-3 shadow-sm">
            <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div>
              <span className="font-bold text-sm block font-['Satoshi'] mb-0.5">
                {t('tasks.submittedTitle')}
              </span>
              <span>
                {t('tasks.submittedDesc')}
              </span>
            </div>
          </div>
        )}

        {/* Action Error Banner */}
        {actionError && (
          <div className="bg-[#FAEBEB] border border-[#F0C8C8] rounded-2xl p-3.5 text-xs text-[#D64545] flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div className="flex-1">{actionError}</div>
            <button onClick={() => setActionError(null)} className="text-[#D64545]">
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Task Title & Meta Card */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[9px] font-bold uppercase tracking-wider text-[#667085]">
              {task.category}
            </span>
            <PriorityBadge priority={task.priority} />
          </div>

          <h2 className="text-[13px] font-bold text-[#0D1C42] font-['Satoshi'] leading-tight">
            {resolvedText.title}
          </h2>

          {/* Every physical resource covered — beds, fixtures, … */}
          {task.resources && task.resources.length > 0 && (
            <ResourceChips resources={task.resources} maxVisible={10} />
          )}

          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-[#F6F4F2] text-xs">
            <div>
              <span className="text-[9px] text-[#98A2B3] uppercase tracking-wider block mb-0.5">
                {t('tasks.location')}
              </span>
              <div className="flex items-center gap-1 text-[#0D1C42] font-medium">
                <MapPin className="w-3.5 h-3.5 text-[#98A2B3]" />
                <span className="truncate">{task.location_name}</span>
              </div>
              <span className="text-[9px] text-[#667085] pl-4">{task.zone_name}</span>
            </div>

            <div>
              <span className="text-[9px] text-[#98A2B3] uppercase tracking-wider block mb-0.5">
                {t('tasks.dueTime')}
              </span>
              <div className="flex items-center gap-1 font-medium text-[#0D1C42]">
                <Clock className={`w-3.5 h-3.5 ${isOverdue ? 'text-[#D64545]' : 'text-[#98A2B3]'}`} />
                <span className={isOverdue ? 'text-[#D64545] font-bold' : ''}>
                  {dueFormatted}
                </span>
              </div>
              {task.scheduled_for && (
                <span className="text-[9px] text-[#667085] pl-4">
                  {t('tasks.scheduledShift')}
                </span>
              )}
            </div>
          </div>

          <div className="pt-2 border-t border-[#F6F4F2] flex items-center justify-between text-xs text-[#667085]">
            <div className="flex items-center gap-1.5">
              <User className="w-3.5 h-3.5 text-[#98A2B3]" />
              <span>{t('tasks.assignedTo')}: <strong className="text-[#0D1C42]">{task.assigned_to_name}</strong></span>
            </div>
          </div>
        </div>

        {/* Instructions */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <FileText className="w-4 h-4 text-[#800020]" />
            <h3 className="text-sm font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
              {t('tasks.instructions')}
            </h3>
          </div>
          <p className="text-xs text-[#0D1C42] leading-relaxed whitespace-pre-line bg-[#FFFCFA] p-3 rounded-xl border border-[#E7E5E4]">
            {resolvedText.instructions ?? task.instructions}
          </p>
        </div>

        {/* Interactive Checklist */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <CheckSquare className="w-4 h-4 text-[#800020]" />
              <h3 className="text-sm font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                {t('tasks.checklist')} ({checklist.filter((c) => c.completed).length}/{checklist.length})
              </h3>
            </div>
            {!canWork && (
              <span className="text-[9px] text-[#98A2B3]">
                {task.status === 'submitted' ? t('tasks.submittedChip') : t('tasks.readOnly')}
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
                    isLocked ? 'cursor-default' : 'cursor-pointer active:bg-[#F6F4F2]'
                  } ${
                    item.completed
                      ? 'bg-[#F7E9EE]/50 border-[#EAD3DB]'
                      : 'bg-[#FFFCFA] border-[#E7E5E4]'
                  }`}
                >
                  <div className="mt-0.5 flex-shrink-0">
                    {item.completed ? (
                      <CheckSquare className="w-5 h-5 text-[#800020] fill-[#F7E9EE]" />
                    ) : (
                      <Square className="w-5 h-5 text-[#98A2B3]" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <span
                      className={`text-xs block leading-snug ${
                        item.completed ? 'line-through text-[#667085]' : 'text-[#0D1C42] font-medium'
                      }`}
                    >
                      {item.label}
                    </span>
                    <div className="flex items-center gap-2 mt-1">
                      {item.required ? (
                        <span className="text-[9px] font-bold uppercase tracking-wider text-[#D64545] bg-[#FAEBEB] px-1.5 py-0.2 rounded">
                          {t('common.required')}
                        </span>
                      ) : (
                        <span className="text-[9px] text-[#98A2B3] uppercase tracking-wider">
                          {t('common.optional')}
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
          <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm">
            <div className="flex items-center gap-2 mb-1.5">
              <ImageIcon className="w-4 h-4 text-[#A56514]" />
              <h3 className="text-sm font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                {t('tasks.previouslySubmitted')}
              </h3>
            </div>
            <p className="text-xs text-[#667085] mb-3">
              {t('tasks.previouslySubmittedDesc')}
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
                    className="rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] p-3"
                  >
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-xs font-bold text-[#0D1C42] font-['Satoshi']">
                        {t('tasks.attempt')} {sub.attempt}
                      </span>
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${submissionStatusChip(sub.status)}`}
                        >
                          {sub.status.replaceAll('_', ' ')}
                        </span>
                        <span className="text-[9px] text-[#98A2B3]">{submittedLabel}</span>
                      </div>
                    </div>

                    {sub.review_comment && (
                      <div className="mb-2 bg-white rounded-lg border border-[#E7E5E4] border-l-2 border-l-[#A56514] p-2">
                        <span className="text-[9px] font-bold uppercase tracking-wider text-[#667085] block mb-0.5">
                          {t('tasks.reviewerNote')}{sub.reviewed_by_name ? ` · ${sub.reviewed_by_name}` : ''}
                        </span>
                        <p className="text-xs text-[#0D1C42] italic leading-relaxed">
                          "{sub.review_comment}"
                        </p>
                      </div>
                    )}

                    <div className="grid grid-cols-2 gap-3">
                      {sub.photos.map((photo) => (
                        <div
                          key={photo.id}
                          className="relative aspect-video rounded-xl overflow-hidden border border-[#E7E5E4] bg-black/5"
                        >
                          <img
                            src={mediaUrl(photo.url)}
                            alt={photo.filename || t('tasks.priorEvidenceAlt')}
                            className="w-full h-full object-cover"
                          />
                          <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent p-1.5">
                            <span className="text-[9px] text-white/90 truncate block">
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
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Camera className="w-4 h-4 text-[#800020]" />
              <h3 className="text-sm font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
                {isReopened ? t('tasks.newPhotoEvidence') : t('tasks.photoEvidence')} ({evidenceList.length}/{task.verification_config.max_photos})
              </h3>
            </div>
            {task.verification_config.photo_required && (
              <span className="text-[9px] font-bold text-[#800020] bg-[#F7E9EE] px-2 py-0.5 rounded-full">
                {t('tasks.minPhotosRequired', { count: task.verification_config.min_photos })}
              </span>
            )}
          </div>

          <p className="text-xs text-[#667085] mb-3">
            {isReopened
              ? t('tasks.capturePhotosNew')
              : t('tasks.capturePhotos')}
          </p>

          {/* Photos Grid */}
          <div className="grid grid-cols-2 gap-3 mb-3">
            {evidenceList.map((photo) => (
              <div
                key={photo.id}
                className="relative aspect-video rounded-xl overflow-hidden border border-[#E7E5E4] bg-black/5 group"
              >
                <img
                  src={mediaUrl(photo.url)}
                  alt={photo.filename || t('tasks.evidenceAlt')}
                  className="w-full h-full object-cover"
                />
                {canWork && (
                  <button
                    onClick={() => handleRemovePhoto(photo.id)}
                    aria-label={t('common.removePhoto')}
                    className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/60 text-white hover:bg-black/80 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
                <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent p-1.5">
                  <span className="text-[9px] text-white/90 truncate block">
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
                className={`aspect-video rounded-xl border-2 border-dashed border-[#D6D3D1] bg-[#FFFCFA] hover:bg-[#F6F4F2] transition-all flex flex-col items-center justify-center cursor-pointer p-2 ${
                  uploadingPhoto ? 'opacity-50 pointer-events-none' : ''
                }`}
              >
                {uploadingPhoto ? (
                  <div className="text-center">
                    <Upload className="w-5 h-5 text-[#800020] animate-bounce mx-auto mb-1" />
                    <span className="text-[9px] text-[#667085] font-medium">{t('common.uploading')}</span>
                  </div>
                ) : (
                  <div className="text-center">
                    <Camera className="w-5 h-5 text-[#667085] mx-auto mb-1" />
                    <span className="text-[9px] font-semibold text-[#0D1C42] block">
                      {t('common.addPhoto')}
                    </span>
                    <span className="text-[9px] text-[#98A2B3]">{t('common.cameraOrGallery')}</span>
                  </div>
                )}
              </button>
            )}
          </div>
        </div>

        {/* Task Notes for Submission */}
        {canWork && (
          <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm">
            <label className="block text-xs font-bold text-[#0D1C42] uppercase tracking-wider mb-1.5 font-['Satoshi']">
              {t('tasks.completionNotes')}
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t('tasks.completionNotesPlaceholder')}
              rows={2}
              className="w-full p-3 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-xs text-[#0D1C42] placeholder-[#98A2B3] focus:bg-white focus:outline-none focus:border-[#800020]"
            />
          </div>
        )}

        {/* Task Timeline */}
        <div className="bg-white rounded-2xl p-4 border border-[#E7E5E4] shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <History className="w-4 h-4 text-[#800020]" />
            <h3 className="text-sm font-bold text-[#0D1C42] uppercase tracking-wider font-['Satoshi']">
              {t('tasks.taskHistory')}
            </h3>
          </div>

          <div className="space-y-3 relative pl-4 before:content-[''] before:absolute before:top-2 before:bottom-2 before:left-1.5 before:w-0.5 before:bg-[#E7E5E4]">
            {task.history.map((hist) => {
              const eventDate = new Date(hist.timestamp);
              const eventTime = `${eventDate.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${eventDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;

              const labels: Record<string, string> = {
                allocated: t('tasks.history.allocated'),
                started: t('tasks.history.started'),
                submitted: t('tasks.history.submitted'),
                returned: t('tasks.history.returned'),
                reopened: t('tasks.history.reopened'),
                approved: t('tasks.history.approved'),
              };

              return (
                <div key={hist.id} className="relative">
                  <span className="absolute -left-[19px] top-1 w-2.5 h-2.5 rounded-full bg-[#800020] ring-4 ring-white" />
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-[#0D1C42]">
                      {labels[hist.event_type] || hist.event_type}
                    </span>
                    <span className="text-[9px] text-[#98A2B3]">{eventTime}</span>
                  </div>
                  <div className="text-[9px] text-[#667085] mt-0.5">
                    <span>{t('common.by')} {hist.actor_name}</span>
                    {hist.notes && (
                      <p className="mt-1 text-[#0D1C42] bg-[#FFFCFA] p-2 rounded-lg border border-[#E7E5E4]">
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
            className="w-full max-w-[420px] bg-white rounded-t-3xl p-5 pb-[max(2rem,calc(env(safe-area-inset-bottom,0px)+1rem))] space-y-2.5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="w-10 h-1 bg-[#E7E5E4] rounded-full mx-auto mb-3" />
            <h4 className="text-sm font-bold text-[#0D1C42] font-['Satoshi'] mb-3">
              {t('common.addPhotoEvidence')}
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
              className="w-full flex items-center gap-3 p-3.5 rounded-xl border border-[#E7E5E4] hover:bg-[#FFFCFA] active:bg-[#F6F4F2] transition-colors text-left"
            >
              <div className="p-2 bg-[#F7E9EE] rounded-lg text-[#800020]">
                <Camera className="w-5 h-5" />
              </div>
              <div>
                <span className="text-sm font-semibold text-[#0D1C42] block">{t('common.takePhoto')}</span>
                <span className="text-[9px] text-[#98A2B3]">{t('common.takePhotoSub')}</span>
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
              className="w-full flex items-center gap-3 p-3.5 rounded-xl border border-[#E7E5E4] hover:bg-[#FFFCFA] active:bg-[#F6F4F2] transition-colors text-left"
            >
              <div className="p-2 bg-[#EAF1FB] rounded-lg text-[#3478D4]">
                <ImageIcon className="w-5 h-5" />
              </div>
              <div>
                <span className="text-sm font-semibold text-[#0D1C42] block">{t('common.chooseGallery')}</span>
                <span className="text-[9px] text-[#98A2B3]">{t('common.chooseGallerySub')}</span>
              </div>
            </button>
            <button
              type="button"
              onClick={() => setShowPhotoOptions(false)}
              className="w-full p-3 rounded-xl text-xs font-semibold text-[#667085] hover:bg-[#FFFCFA] transition-colors"
            >
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}

      {/* Sticky Bottom Action Area */}
      <div className="fixed md:absolute bottom-0 inset-x-0 px-[var(--app-px)] pt-3 pb-[calc(env(safe-area-inset-bottom,0px)+0.75rem)] bg-white/95 backdrop-blur border-t border-[#E7E5E4] shadow-lg z-20">
        {canWork && (
          <PrimaryButton
            size="lg"
            loading={actionLoading}
            onClick={handleSubmitForReview}
            icon={<Send className="w-5 h-5" />}
          >
            {t('tasks.submitForReview')}
          </PrimaryButton>
        )}

        {isSubmitted && (
          <div className="text-center py-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#3478D4] bg-[#EAF1FB] px-4 py-2 rounded-full border border-[#C2D4FF]">
              <Clock className="w-4 h-4" />
              {t('tasks.awaitingReview')}
            </span>
          </div>
        )}

        {isCompleted && (
          <div className="text-center py-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#0D1C42] bg-[#F7E9EE] px-4 py-2 rounded-full border border-[#EAD3DB]">
              <CheckCircle2 className="w-4 h-4" />
              {t('tasks.taskApproved')}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
