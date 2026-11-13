import React from 'react';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode;
  loading?: boolean;
  icon?: React.ReactNode;
  variant?: 'primary' | 'secondary' | 'danger' | 'outline' | 'subtle';
  size?: 'sm' | 'md' | 'lg';
  fullWidth?: boolean;
}

export const PrimaryButton: React.FC<ButtonProps> = ({
  children,
  loading = false,
  icon,
  size = 'md',
  fullWidth = true,
  disabled,
  className = '',
  ...props
}) => {
  const { t } = useTranslation();
  const sizeStyles = {
    sm: 'h-9 px-3 text-xs',
    md: 'h-10 px-4 text-sm',
    lg: 'h-11 px-5 text-base',
  };

  return (
    <button
      disabled={disabled || loading}
      className={`relative inline-flex items-center justify-center font-semibold rounded-xl transition-all active:scale-[0.98] select-none
        bg-acc text-white hover:bg-[#227541] active:bg-[#1d6337]
        disabled:opacity-50 disabled:pointer-events-none disabled:active:scale-100
        ${fullWidth ? 'w-full' : ''}
        ${sizeStyles[size]}
        ${className}
      `}
      {...props}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>{t('common.processing')}</span>
        </span>
      ) : (
        <span className="flex items-center justify-center gap-2">
          {icon}
          <span>{children}</span>
        </span>
      )}
    </button>
  );
};

export const SecondaryButton: React.FC<ButtonProps> = ({
  children,
  loading = false,
  icon,
  size = 'md',
  fullWidth = true,
  disabled,
  className = '',
  ...props
}) => {
  const { t } = useTranslation();
  const sizeStyles = {
    sm: 'h-9 px-3 text-xs',
    md: 'h-10 px-4 text-sm',
    lg: 'h-11 px-5 text-base',
  };

  return (
    <button
      disabled={disabled || loading}
      className={`relative inline-flex items-center justify-center font-medium rounded-xl transition-all active:scale-[0.98] select-none
        bg-surface text-ink border border-line hover:bg-soft active:bg-line
        disabled:opacity-50 disabled:pointer-events-none
        ${fullWidth ? 'w-full' : ''}
        ${sizeStyles[size]}
        ${className}
      `}
      {...props}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-sub" />
          <span>{t('common.loading')}</span>
        </span>
      ) : (
        <span className="flex items-center justify-center gap-2">
          {icon}
          <span>{children}</span>
        </span>
      )}
    </button>
  );
};

export const DangerButton: React.FC<ButtonProps> = ({
  children,
  loading = false,
  icon,
  size = 'md',
  fullWidth = true,
  disabled,
  className = '',
  ...props
}) => {
  const { t } = useTranslation();
  const sizeStyles = {
    sm: 'h-9 px-3 text-xs',
    md: 'h-10 px-4 text-sm',
    lg: 'h-11 px-5 text-base',
  };

  return (
    <button
      disabled={disabled || loading}
      className={`relative inline-flex items-center justify-center font-semibold rounded-xl transition-all active:scale-[0.98] select-none
        bg-dng text-white hover:bg-[#B2373E] active:bg-[#9C2F36]
        disabled:opacity-50 disabled:pointer-events-none
        ${fullWidth ? 'w-full' : ''}
        ${sizeStyles[size]}
        ${className}
      `}
      {...props}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>{t('common.processing')}</span>
        </span>
      ) : (
        <span className="flex items-center justify-center gap-2">
          {icon}
          <span>{children}</span>
        </span>
      )}
    </button>
  );
};
