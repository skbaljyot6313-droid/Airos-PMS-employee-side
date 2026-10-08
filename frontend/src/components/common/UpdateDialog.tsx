import React from 'react';
import { Download, ShieldAlert } from 'lucide-react';
import { PrimaryButton, SecondaryButton } from './Buttons';
import { UpdateState } from '../../services/updateService';

interface UpdateDialogProps {
  state: UpdateState;
  onLater: () => void;
}

/**
 * Release dialog — two modes driven entirely by backend release metadata:
 *   optional → dismissible, "Update now" / "Later"
 *   required → force_update or installed < minimum; no dismiss path
 * "Update now" hands the APK URL to Android (system browser handles the
 * download + package-installer flow — the app never sideloads silently).
 */
export const UpdateDialog: React.FC<UpdateDialogProps> = ({ state, onLater }) => {
  if (state.kind === 'none' || !state.info) return null;
  const required = state.kind === 'required';
  const { info } = state;

  const openDownload = () => {
    window.open(info.download_url, '_system');
  };

  return (
    <div
      className="absolute inset-0 z-[100] flex items-center justify-center bg-black/50 p-6"
      role="dialog"
      aria-modal="true"
      aria-label={required ? 'Update required' : 'Update available'}
      onClick={required ? undefined : onLater}
    >
      <div
        className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-col items-center text-center">
          <div
            className={`w-12 h-12 rounded-2xl flex items-center justify-center mb-4 ${
              required
                ? 'bg-[#FCEBEA] text-[#D9534F]'
                : 'bg-[#E8F7ED] text-[#33B059]'
            }`}
          >
            {required ? (
              <ShieldAlert className="w-6 h-6" />
            ) : (
              <Download className="w-6 h-6" />
            )}
          </div>

          <h2 className="text-lg font-semibold text-[#20292C] font-['Space_Grotesk']">
            {required ? 'Update required' : 'Update available'}
          </h2>
          <p className="mt-1 text-sm text-[#667174]">
            {required
              ? 'Your version of AiROS Employee is no longer supported. Please update to continue.'
              : 'A new version of AiROS Employee is available.'}
          </p>
          <p className="mt-3 text-xs font-medium text-[#8D999C]">
            Version {info.latest_version}
          </p>
          {info.release_notes && (
            <p className="mt-2 text-xs text-[#667174] leading-relaxed max-h-24 overflow-y-auto">
              {info.release_notes}
            </p>
          )}
        </div>

        <div className="mt-6 flex flex-col gap-2">
          <PrimaryButton onClick={openDownload} icon={<Download className="w-4 h-4" />}>
            Update now
          </PrimaryButton>
          {!required && (
            <SecondaryButton onClick={onLater}>Later</SecondaryButton>
          )}
        </div>
      </div>
    </div>
  );
};
