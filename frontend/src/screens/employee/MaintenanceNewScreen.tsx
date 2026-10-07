import React, { useState, useEffect, useRef } from 'react';
import { Capacitor } from '@capacitor/core';
import { Camera as CapCamera, CameraResultType, CameraSource } from '@capacitor/camera';
import { useAuth } from '../../context/AuthContext';
import { EligibleLocation, MaintenanceCategory, MaintenancePriority, MaintenanceTarget, MaintenanceTicket } from '../../types';
import { fetchEligibleLocationsApi, createMaintenanceTicketApi } from '../../api/maintenance';
import { uploadMediaApi } from '../../api/media';
import { mediaUrl, errorMessage } from '../../api/client';
import { ScreenHeader } from '../../components/common/ScreenHeader';
import { PrimaryButton, SecondaryButton } from '../../components/common/Buttons';
import { PriorityBadge } from '../../components/common/PriorityBadge';
import { LoadingState, ErrorState } from '../../components/common/FeedbackStates';
import {
  MapPin,
  Camera,
  Upload,
  X,
  CheckCircle2,
  AlertTriangle,
  Zap,
  Droplets,
  Hammer,
  Wind,
  Paintbrush,
  Armchair,
  Tv,
  Wifi,
  Waves,
  Sparkles,
  ShieldAlert,
  HelpCircle,
  Building,
  Check,
  ArrowRight,
  Send,
  Image as ImageIcon,
} from 'lucide-react';

interface MaintenanceNewScreenProps {
  onBack: () => void;
  onSuccess: (ticketId: string) => void;
  // When provided, the target unit is locked — raised from the zone workspace
  target?: MaintenanceTarget;
}

const CATEGORIES: { name: MaintenanceCategory; icon: React.ReactNode; issues: string[] }[] = [
  {
    name: 'HVAC',
    icon: <Wind className="w-5 h-5" />,
    issues: ['AC not cooling', 'AC leaking water', 'Thermostat display broken', 'Unusual noise / rattling', 'Heater not turning on'],
  },
  {
    name: 'Plumbing',
    icon: <Droplets className="w-5 h-5" />,
    issues: ['Leaking sink drain', 'Toilet running continuously', 'Low water pressure', 'Clogged shower drain', 'Faucets dripping'],
  },
  {
    name: 'Electrical',
    icon: <Zap className="w-5 h-5" />,
    issues: ['Flickering light fixture', 'Power outlet dead', 'Breaker tripped', 'Exposed wiring', 'Switch not responding'],
  },
  {
    name: 'Carpentry',
    icon: <Hammer className="w-5 h-5" />,
    issues: ['Door won’t latch or lock', 'Closet sliding door off track', 'Loose cabinet hinge', 'Window won’t close tightly'],
  },
  {
    name: 'Furniture',
    icon: <Armchair className="w-5 h-5" />,
    issues: ['Wobbly desk or chair', 'Broken bed frame / slat', 'Damaged nightstand', 'Sofa upholstery torn'],
  },
  {
    name: 'Appliance',
    icon: <Tv className="w-5 h-5" />,
    issues: ['Mini-fridge warm', 'TV not powering on', 'Microwave inoperative', 'Coffee maker malfunction'],
  },
  {
    name: 'Painting',
    icon: <Paintbrush className="w-5 h-5" />,
    issues: ['Scuffed wall paint', 'Water stain discoloration', 'Peeling paint / plaster chip'],
  },
  {
    name: 'Internet',
    icon: <Wifi className="w-5 h-5" />,
    issues: ['No Wi-Fi signal in room', 'Access point flashing red', 'Ethernet jack loose'],
  },
  {
    name: 'Water / Drainage',
    icon: <Waves className="w-5 h-5" />,
    issues: ['Balcony drain backed up', 'Floor drain foul odor', 'Exterior runoff pooling'],
  },
  {
    name: 'Cleaning Equipment',
    icon: <Sparkles className="w-5 h-5" />,
    issues: ['Vacuum cleaner belt snapped', 'Floor buffer motor stalled', 'Cart wheel broken'],
  },
  {
    name: 'Civil',
    icon: <Building className="w-5 h-5" />,
    issues: ['Cracked ceramic tile', 'Loose stair tread nosing', 'Ceiling tile fallen / sagging'],
  },
  {
    name: 'Safety',
    icon: <ShieldAlert className="w-5 h-5" />,
    issues: ['Smoke detector low battery chirp', 'Emergency exit sign dark', 'Fire door closer missing'],
  },
  {
    name: 'Other',
    icon: <HelpCircle className="w-5 h-5" />,
    issues: ['General maintenance request', 'Unlisted facility issue'],
  },
];

export const MaintenanceNewScreen: React.FC<MaintenanceNewScreenProps> = ({
  onBack,
  onSuccess,
  target,
}) => {
  const { user } = useAuth();
  const [locations, setLocations] = useState<EligibleLocation[]>([]);
  const [loadingLocations, setLoadingLocations] = useState<boolean>(!target);
  const [error, setError] = useState<string | null>(null);

  // Guided Form state — location step is skipped when a workspace target is locked
  const [step, setStep] = useState<number>(target ? 2 : 1);
  const firstStep = target ? 2 : 1;
  const totalSteps = target ? 3 : 4;
  const stepNumber = target ? step - 1 : step;
  const [selectedLocation, setSelectedLocation] = useState<EligibleLocation | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<MaintenanceCategory | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<string>('');
  const [customDescription, setCustomDescription] = useState<string>('');
  const [priority, setPriority] = useState<MaintenancePriority>('medium');
  const [photos, setPhotos] = useState<string[]>([]);
  const [uploadingPhoto, setUploadingPhoto] = useState<boolean>(false);
  const [showPhotoOptions, setShowPhotoOptions] = useState<boolean>(false);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);

  const [submitting, setSubmitting] = useState<boolean>(false);
  const [submissionResult, setSubmissionResult] = useState<MaintenanceTicket | null>(null);

  useEffect(() => {
    if (target) return;
    async function loadLocations() {
      try {
        setLoadingLocations(true);
        const data = await fetchEligibleLocationsApi();
        setLocations(data);
      } catch (err: unknown) {
        setError(errorMessage(err, 'Unable to load eligible workplace locations.'));
      } finally {
        setLoadingLocations(false);
      }
    }
    loadLocations();
  }, [target]);

  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const inputEl = e.target;
    const file = inputEl.files?.[0];
    if (!file) return;

    try {
      setUploadingPhoto(true);
      const reader = new FileReader();
      reader.onload = async (event) => {
        try {
          const dataUrl = event.target?.result as string;
          const uploaded = await uploadMediaApi(dataUrl, file.name);
          setPhotos((prev) => [...prev, uploaded.path]);
        } catch {
          setError('Failed to upload maintenance photo.');
        } finally {
          setUploadingPhoto(false);
          inputEl.value = '';
        }
      };
      reader.readAsDataURL(file);
    } catch {
      setUploadingPhoto(false);
    }
  };

  const handleNativePhoto = async (source: 'camera' | 'gallery') => {
    setShowPhotoOptions(false);
    try {
      setUploadingPhoto(true);
      setError(null);
      const photo = await CapCamera.getPhoto({
        resultType: CameraResultType.DataUrl,
        source: source === 'camera' ? CameraSource.Camera : CameraSource.Photos,
        quality: 85,
      });
      if (photo.dataUrl) {
        const uploaded = await uploadMediaApi(photo.dataUrl, `maintenance_${Date.now()}.${photo.format || 'jpeg'}`);
        setPhotos((prev) => [...prev, uploaded.path]);
      }
    } catch (err: unknown) {
      if (!/cancel/i.test(errorMessage(err, ''))) {
        setError(errorMessage(err, 'Failed to capture photo.'));
      }
    } finally {
      setUploadingPhoto(false);
    }
  };

  const handleRemovePhoto = (index: number) => {
    setPhotos((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async () => {
    if ((!selectedLocation && !target) || !selectedCategory || !selectedIssue) {
      setError('Please complete all required fields.');
      return;
    }
    if (!user?.property_uid) {
      setError('Your account is not linked to a property — contact your manager.');
      return;
    }

    // Exactly one backend target field — mapped from the locked resource
    // kind, or from the eligible-location pick when not workspace-raised.
    const targetFields: Record<string, string> = {};
    if (target) {
      if (target.kind === 'room') targetFields.room_uid = target.uid;
      else if (target.kind === 'dorm') targetFields.dorm_uid = target.uid;
      else if (target.kind === 'bed') targetFields.bed_uid = target.uid;
      else if (target.kind === 'washroom') targetFields.washroom_uid = target.uid;
      else if (target.kind === 'fixture') {
        if (!target.washroom_uid) {
          setError('This fixture is missing its washroom reference — cannot submit.');
          return;
        }
        targetFields.washroom_uid = target.washroom_uid;
        targetFields.washroom_fixture_uid = target.uid;
      }
    } else if (selectedLocation) {
      if (selectedLocation.kind === 'room') targetFields.room_uid = selectedLocation.id;
      else targetFields.dorm_uid = selectedLocation.id;
    }

    try {
      setSubmitting(true);
      setError(null);
      const ticket = await createMaintenanceTicketApi({
        property_uid: user.property_uid,
        ...targetFields,
        category: selectedCategory,
        issue: selectedIssue === 'Other' ? (customDescription.trim() || 'General maintenance issue') : selectedIssue,
        description: selectedIssue === 'Other' ? undefined : customDescription.trim() || undefined,
        priority,
        attachment_urls: photos,
      });

      setSubmissionResult(ticket);
    } catch (err: unknown) {
      setError(errorMessage(err, 'Unable to submit maintenance ticket.'));
    } finally {
      setSubmitting(false);
    }
  };

  if (loadingLocations) {
    return (
      <div className="flex-1 flex flex-col bg-[#F7F8F6]">
        <ScreenHeader title="Raise Maintenance" onBack={onBack} />
        <LoadingState message="Loading your permitted coverage locations..." />
      </div>
    );
  }

  // Success view
  if (submissionResult) {
    return (
      <div className="flex-1 flex flex-col bg-[#F7F8F6]">
        <ScreenHeader title="Ticket Recorded" onBack={() => onSuccess(submissionResult.id)} />
        <div className="flex-1 p-6 flex flex-col justify-center items-center text-center">
          <div className="w-16 h-16 rounded-full bg-[#E8F7ED] border border-[#BBECCC] text-[#33B059] flex items-center justify-center mb-4">
            <CheckCircle2 className="w-8 h-8 stroke-[2.5]" />
          </div>

          <h2 className="text-xl font-bold text-[#20292C] font-['Space_Grotesk'] mb-1">
            Maintenance Request Submitted
          </h2>
          <p className="text-xs text-[#667174] max-w-xs mb-6">
            The issue has been registered in the AiROS operations system and dispatched.
          </p>

          <div className="w-full max-w-sm bg-white rounded-2xl p-4 border border-[#E4E8E6] text-left space-y-3 mb-6 shadow-sm">
            <div className="flex items-center justify-between border-b border-[#F0F2F1] pb-2">
              <span className="text-xs text-[#8D999C]">Ticket ID</span>
              <span className="font-mono text-xs font-bold text-[#20292C] bg-[#F0F2F1] px-2 py-0.5 rounded">
                {submissionResult.ticket_number || submissionResult.id}
              </span>
            </div>
            <div className="flex items-center justify-between border-b border-[#F0F2F1] pb-2">
              <span className="text-xs text-[#8D999C]">Issue</span>
              <span className="text-xs font-medium text-[#20292C] truncate max-w-[200px]">
                {submissionResult.issue}
              </span>
            </div>
            <div className="flex items-center justify-between border-b border-[#F0F2F1] pb-2">
              <span className="text-xs text-[#8D999C]">Location</span>
              <span className="text-xs font-medium text-[#20292C]">
                {submissionResult.location_name}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-[#8D999C]">Assigned Tech</span>
              <span className="text-xs font-bold text-[#278B46]">
                {submissionResult.assigned_to_name || 'Queued / Unassigned'}
              </span>
            </div>
          </div>

          <div className="w-full max-w-sm space-y-2">
            <PrimaryButton onClick={() => onSuccess(submissionResult.id)}>
              View Ticket
            </PrimaryButton>
            <SecondaryButton onClick={onBack}>
              Back to Zone
            </SecondaryButton>
          </div>
        </div>
      </div>
    );
  }

  const currentCategoryObj = CATEGORIES.find((c) => c.name === selectedCategory);

  // Shared photo card — rendered on the issue step (capture early) and the
  // review step; `photos` state is shared between both.
  const photoSection = (
    <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
      <label className="block text-xs font-bold text-[#20292C] uppercase tracking-wider mb-2 font-['Space_Grotesk']">
        Attach Photos (Optional)
      </label>

      <div className="grid grid-cols-2 gap-3 mb-2">
        {photos.map((url, i) => (
          <div key={i} className="relative aspect-video rounded-xl overflow-hidden border border-[#E4E8E6]">
            <img src={mediaUrl(url)} alt="Evidence" className="w-full h-full object-cover" />
            <button
              onClick={() => handleRemovePhoto(i)}
              className="absolute top-1 right-1 p-1 bg-black/60 rounded-full text-white hover:bg-black/80"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}

        <button
          type="button"
          onClick={() => setShowPhotoOptions(true)}
          disabled={uploadingPhoto}
          className="aspect-video rounded-xl border-2 border-dashed border-[#D2D8D6] bg-[#F7F8F6] hover:bg-[#F0F2F1] flex flex-col items-center justify-center cursor-pointer p-2 text-center transition-colors"
        >
          {uploadingPhoto ? (
            <Upload className="w-5 h-5 text-[#33B059] animate-bounce" />
          ) : (
            <>
              <Camera className="w-5 h-5 text-[#667174] mb-1" />
              <span className="text-[11px] font-semibold text-[#20292C]">+ Add Photo</span>
              <span className="text-[10px] text-[#8D999C]">Camera or Gallery</span>
            </>
          )}
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex-1 flex flex-col bg-[#F7F8F6] overflow-y-auto">
      <ScreenHeader
        title="Raise Maintenance"
        subtitle={target ? target.path.join(' · ') : `Step ${stepNumber} of ${totalSteps} · Guided Request`}
        onBack={step > firstStep ? () => setStep(step - 1) : onBack}
      />

      <div className="p-4 space-y-4 pb-28">
        {error && (
          <div className="bg-[#FCEBEA] border border-[#F8C8C6] p-3 rounded-xl text-xs text-[#D9534F] flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)}><X className="w-4 h-4" /></button>
          </div>
        )}

        {/* Locked target banner — unit was selected in the zone workspace */}
        {target && (
          <div className="bg-white rounded-2xl p-3.5 border border-[#E4E8E6] flex items-center gap-3 shadow-sm">
            <div className="p-2 rounded-xl bg-[#E8F7ED] text-[#33B059] flex-shrink-0">
              <MapPin className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <span className="text-[10px] font-bold text-[#8D999C] uppercase tracking-wider block">
                Location
              </span>
              <span className="text-xs font-semibold text-[#20292C] block truncate">
                {target.path.join(' · ')}
              </span>
            </div>
          </div>
        )}

        {/* STEP 1: LOCATION (skipped when raised from a workspace unit) */}
        {!target && step === 1 && (
          <div className="space-y-3">
            <div>
              <h2 className="text-base font-bold text-[#20292C] font-['Space_Grotesk']">
                Where is the problem located?
              </h2>
              <p className="text-xs text-[#667174]">
                Select an area within your assigned operational coverage.
              </p>
            </div>

            <div className="space-y-2">
              {locations.map((loc) => {
                const isSelected = selectedLocation?.id === loc.id;
                return (
                  <div
                    key={loc.id}
                    onClick={() => {
                      setSelectedLocation(loc);
                      setStep(2);
                    }}
                    className={`p-3.5 rounded-xl border flex items-center justify-between cursor-pointer transition-all active:scale-[0.99] ${
                      isSelected
                        ? 'border-[#33B059] bg-[#E8F7ED]'
                        : 'border-[#E4E8E6] bg-white hover:border-[#D2D8D6]'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`p-2 rounded-xl ${isSelected ? 'bg-[#33B059] text-white' : 'bg-[#F0F2F1] text-[#667174]'}`}>
                        <MapPin className="w-4 h-4" />
                      </div>
                      <div>
                        <span className="text-sm font-semibold text-[#20292C] block">
                          {loc.name}
                        </span>
                        <span className="text-xs text-[#667174]">{loc.zone_name}</span>
                      </div>
                    </div>
                    {isSelected && <Check className="w-4 h-4 text-[#33B059] stroke-[3]" />}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* STEP 2: CATEGORY */}
        {step === 2 && (
          <div className="space-y-3">
            <div>
              <h2 className="text-base font-bold text-[#20292C] font-['Space_Grotesk']">
                What category of maintenance is needed?
              </h2>
              <p className="text-xs text-[#667174]">
                At {target?.name || selectedLocation?.name}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2.5">
              {CATEGORIES.map((cat) => {
                const isSelected = selectedCategory === cat.name;
                return (
                  <button
                    key={cat.name}
                    type="button"
                    onClick={() => {
                      setSelectedCategory(cat.name);
                      setSelectedIssue('');
                      setStep(3);
                    }}
                    className={`p-3.5 rounded-xl border text-left flex items-center gap-3 transition-all active:scale-[0.98] ${
                      isSelected
                        ? 'border-[#33B059] bg-[#E8F7ED] text-[#278B46]'
                        : 'border-[#E4E8E6] bg-white hover:bg-[#F7F8F6] text-[#20292C]'
                    }`}
                  >
                    <div className={`p-2 rounded-lg ${isSelected ? 'bg-[#33B059] text-white' : 'bg-[#F0F2F1] text-[#667174]'}`}>
                      {cat.icon}
                    </div>
                    <span className="text-xs font-semibold">{cat.name}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* STEP 3: ISSUE & DETAILS */}
        {step === 3 && currentCategoryObj && (
          <div className="space-y-4">
            <div>
              <h2 className="text-base font-bold text-[#20292C] font-['Space_Grotesk']">
                Select the specific issue
              </h2>
              <p className="text-xs text-[#667174]">
                {selectedCategory} · {target?.name || selectedLocation?.name}
              </p>
            </div>

            {/* Picklist */}
            <div className="space-y-2">
              {currentCategoryObj.issues.map((iss) => {
                const isSelected = selectedIssue === iss;
                return (
                  <div
                    key={iss}
                    onClick={() => setSelectedIssue(iss)}
                    className={`p-3 rounded-xl border flex items-center justify-between cursor-pointer transition-all ${
                      isSelected
                        ? 'border-[#33B059] bg-[#E8F7ED]'
                        : 'border-[#E4E8E6] bg-white hover:bg-[#F7F8F6]'
                    }`}
                  >
                    <span className={`text-xs font-medium ${isSelected ? 'text-[#20292C] font-semibold' : 'text-[#667174]'}`}>
                      {iss}
                    </span>
                    {isSelected && <Check className="w-4 h-4 text-[#33B059] stroke-[3]" />}
                  </div>
                );
              })}

              <div
                onClick={() => setSelectedIssue('Other')}
                className={`p-3 rounded-xl border flex items-center justify-between cursor-pointer transition-all ${
                  selectedIssue === 'Other'
                    ? 'border-[#33B059] bg-[#E8F7ED]'
                    : 'border-[#E4E8E6] bg-white hover:bg-[#F7F8F6]'
                }`}
              >
                <span className="text-xs font-medium text-[#20292C]">Other custom issue</span>
                {selectedIssue === 'Other' && <Check className="w-4 h-4 text-[#33B059] stroke-[3]" />}
              </div>
            </div>

            {/* Free-text description */}
            <div className="bg-white rounded-2xl p-4 border border-[#E4E8E6] shadow-sm">
              <label className="block text-xs font-semibold text-[#20292C] uppercase tracking-wider mb-1">
                Description / Additional Notes
              </label>
              <textarea
                value={customDescription}
                onChange={(e) => setCustomDescription(e.target.value)}
                placeholder="Describe exact location, symptoms, or warnings for the technician..."
                rows={3}
                className="w-full p-3 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-xs text-[#20292C] focus:bg-white focus:outline-none focus:border-[#33B059]"
              />
            </div>

            {/* Photos — capture evidence right alongside the issue details */}
            {photoSection}

            <PrimaryButton
              disabled={!selectedIssue}
              onClick={() => setStep(4)}
              icon={<ArrowRight className="w-4 h-4" />}
            >
              Continue to Priority & Photos
            </PrimaryButton>
          </div>
        )}

        {/* STEP 4: PRIORITY, PHOTOS & REVIEW */}
        {step === 4 && (
          <div className="space-y-4">
            <div>
              <h2 className="text-base font-bold text-[#20292C] font-['Space_Grotesk']">
                Priority & Photographic Evidence
              </h2>
              <p className="text-xs text-[#667174]">
                Review and dispatch to property maintenance.
              </p>
            </div>

            {/* Photos — same shared card; anything added on the issue step shows here */}
            {photoSection}

            {/* Summary Review Card */}
            <div className="bg-[#F7F8F6] rounded-2xl p-4 border border-[#E4E8E6] space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-[#8D999C]">Location:</span>
                <span className="font-semibold text-[#20292C] text-right">
                  {target ? target.path.join(' · ') : selectedLocation?.name}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8D999C]">Category:</span>
                <span className="font-semibold text-[#20292C]">{selectedCategory}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8D999C]">Issue:</span>
                <span className="font-semibold text-[#20292C]">{selectedIssue}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8D999C]">Priority:</span>
                <PriorityBadge priority={priority} size="sm" />
              </div>
            </div>

            <PrimaryButton
              loading={submitting}
              onClick={handleSubmit}
              size="lg"
              icon={<Send className="w-4 h-4" />}
            >
              Submit Maintenance Request
            </PrimaryButton>
          </div>
        )}
      </div>

      {/* Hidden file inputs: camera capture + gallery picker (web fallback) */}
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
          className="fixed md:absolute inset-0 z-40 flex items-end justify-center bg-black/40"
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
    </div>
  );
};
