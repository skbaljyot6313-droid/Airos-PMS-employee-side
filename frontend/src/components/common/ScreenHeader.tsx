import React from 'react';
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
  return (
    <div className="bg-white border-b border-[#E4E8E6] px-4 pt-3 pb-3.5 sticky top-0 z-20">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          {onBack && (
            <button
              onClick={onBack}
              aria-label="Go back"
              className="p-2 -ml-2 rounded-xl text-[#20292C] hover:bg-[#F7F8F6] active:bg-[#ECEEED] transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
          )}
          <div className="min-w-0">
            <h1 className="text-xl font-bold tracking-tight text-[#20292C] truncate font-['Space_Grotesk']">
              {title}
            </h1>
            {subtitle && (
              <p className="text-xs text-[#667174] truncate mt-0.5">{subtitle}</p>
            )}
          </div>
        </div>
        {rightElement && <div className="flex-shrink-0">{rightElement}</div>}
      </div>
    </div>
  );
};
