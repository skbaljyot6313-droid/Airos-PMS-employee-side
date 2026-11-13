import React from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft } from 'lucide-react';

interface ScreenHeaderProps {
  title: string;
  subtitle?: string;
  onBack?: () => void;
  rightElement?: React.ReactNode;
}

export const ScreenHeader: React.FC<ScreenHeaderProps> = ({
  title,
  subtitle,
  onBack,
  rightElement,
}) => {
  const { t } = useTranslation();
  return (
    <div className="bg-surface border-b border-line px-4 pt-2.5 pb-2.5 sticky top-0 z-20">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          {onBack && (
            <button
              onClick={onBack}
              aria-label={t('common.goBack')}
              className="p-2 -ml-2 rounded-lg text-ink hover:bg-soft transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
          )}
          <div className="min-w-0">
            <h1 className="text-lg font-semibold tracking-tight text-ink truncate font-['Space_Grotesk']">
              {title}
            </h1>
            {subtitle && (
              <p className="text-xs text-sub truncate mt-0.5">{subtitle}</p>
            )}
          </div>
        </div>
        {rightElement && <div className="flex-shrink-0">{rightElement}</div>}
      </div>
    </div>
  );
};
