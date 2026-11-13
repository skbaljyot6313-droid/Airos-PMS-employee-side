import React from 'react';
import { useTranslation } from 'react-i18next';
import { Download, ShieldAlert, Loader2, Settings2 } from 'lucide-react';
import { PrimaryButton, SecondaryButton } from './Buttons';
import {
  beginUpdate,
  openInstallPermissionSettings,
  retryUpdate,
  UpdateFlow,
  UpdateState,
} from '../../services/updateService';

interface UpdateDialogProps {
  state: UpdateState;
  flow: UpdateFlow;
  onLater: () => void;
}

/**
 * Update dialog — driven by release metadata (UpdateState) and the
 * download/install pipeline (UpdateFlow). "Update now" downloads the APK
 * inside the app and hands it to Android's package installer — no browser,
 * no WebView navigation, no repeated downloads (the pending file is reused).
 */
export const UpdateDialog: React.FC<UpdateDialogProps> = ({ state, flow, onLater }) => {
  const { t } = useTranslation();
  if (state.kind === 'none' || !state.info) return null;
  const required = state.kind === 'required';
  const { info } = state;
  const dismissible = !required && flow.phase !== 'downloading';

  const body = (() => {
    switch (flow.phase) {
      case 'downloading':
        return {
          title: t('update.downloadingTitle'),
          text: t('update.downloadingText'),
        };
      case 'needs_permission':
        return {
          title: t('update.permissionTitle'),
          text: t('update.permissionText'),
        };
      case 'error':
        return {
          title: t('update.errorTitle'),
          text: t('update.errorText'),
        };
      case 'installing':
      case 'ready':
        return {
          title: t('update.installingTitle'),
          text: t('update.installingText'),
        };
      default:
        return required
          ? {
              title: t('update.requiredTitle'),
              text: t('update.requiredText'),
            }
          : {
              title: t('update.availableTitle'),
              text: t('update.availableText'),
            };
    }
  })();

  return (
    <div
      className="absolute inset-0 z-[100] flex items-center justify-center bg-black/50 p-6"
      role="dialog"
      aria-modal="true"
      aria-label={body.title}
      onClick={dismissible ? onLater : undefined}
    >
      <div
        className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-col items-center text-center">
          <div
            className={`w-12 h-12 rounded-2xl flex items-center justify-center mb-4 ${
              required && flow.phase === 'idle'
                ? 'bg-[#FCEBEA] text-[#D9534F]'
                : 'bg-[#E8F7ED] text-[#33B059]'
            }`}
          >
            {flow.phase === 'downloading' ? (
              <Loader2 className="w-6 h-6 animate-spin" />
            ) : required && flow.phase === 'idle' ? (
              <ShieldAlert className="w-6 h-6" />
            ) : (
              <Download className="w-6 h-6" />
            )}
          </div>

          <h2 className="text-lg font-semibold text-[#20292C] font-['Space_Grotesk']">
            {body.title}
          </h2>
          <p className="mt-1 text-sm text-[#667174]">{body.text}</p>
          <p className="mt-3 text-xs font-medium text-[#8D999C]">
            {t('update.version', { version: info.latest_version })}
          </p>
          {flow.phase === 'error' && flow.error && (
            <p className="mt-1 text-[11px] font-mono text-[#B3BABC]">
              {/failed to fetch|network|timeout|econn|socket|resolve|refused|abort/i.test(
                flow.error
              )
                ? 'connection_error'
                : flow.error.slice(0, 120)}
            </p>
          )}

          {flow.phase === 'downloading' && (
            <div className="w-full mt-4">
              <div className="h-2 w-full rounded-full bg-[#F0F2F1] overflow-hidden">
                {flow.progress === null ? (
                  <div className="h-full w-1/3 rounded-full bg-[#33B059] animate-pulse" />
                ) : (
                  <div
                    className="h-full rounded-full bg-[#33B059] transition-all duration-300"
                    style={{ width: `${flow.progress}%` }}
                  />
                )}
              </div>
              {flow.progress !== null && (
                <p className="mt-2 text-xs text-[#8D999C]">{flow.progress}%</p>
              )}
            </div>
          )}
        </div>

        <div className="mt-6 flex flex-col gap-2">
          {flow.phase === 'idle' && (
            <PrimaryButton
              onClick={() => void beginUpdate(info)}
              icon={<Download className="w-4 h-4" />}
            >
              {t('update.updateNow')}
            </PrimaryButton>
          )}
          {flow.phase === 'needs_permission' && (
            <PrimaryButton
              onClick={() => void openInstallPermissionSettings()}
              icon={<Settings2 className="w-4 h-4" />}
            >
              {t('update.openSettings')}
            </PrimaryButton>
          )}
          {flow.phase === 'error' && (
            <PrimaryButton onClick={retryUpdate} icon={<Download className="w-4 h-4" />}>
              {t('common.tryAgain')}
            </PrimaryButton>
          )}
          {(flow.phase === 'idle' || flow.phase === 'error') && !required && (
            <SecondaryButton onClick={onLater}>{t('update.later')}</SecondaryButton>
          )}
        </div>
      </div>
    </div>
  );
};
