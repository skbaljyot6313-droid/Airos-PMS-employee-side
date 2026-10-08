import React from 'react';
import { Loader2 } from 'lucide-react';

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
  const sizeStyles = {
    sm: 'h-10 px-3 text-xs',
    md: 'h-12 px-4 text-sm',
    lg: 'h-14 px-5 text-base',
  };

  return (
    <button
      disabled={disabled || loading}
      className={`relative inline-flex items-center justify-center font-semibold rounded-xl transition-all active:scale-[0.98] select-none
        bg-[#33B059] text-white hover:bg-[#278B46] active:bg-[#22773c]
        disabled:opacity-50 disabled:pointer-events-none disabled:active:scale-100
        shadow-[0_2px_4px_rgba(51,176,89,0.15)]
        ${fullWidth ? 'w-full' : ''}
        ${sizeStyles[size]}
        ${className}
      `}
      {...props}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>Processing...</span>
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
  const sizeStyles = {
    sm: 'h-10 px-3 text-xs',
    md: 'h-12 px-4 text-sm',
    lg: 'h-14 px-5 text-base',
  };

  return (
    <button
      disabled={disabled || loading}
      className={`relative inline-flex items-center justify-center font-medium rounded-xl transition-all active:scale-[0.98] select-none
        bg-white text-[#20292C] border border-[#E4E8E6] hover:bg-[#F7F8F6] active:bg-[#EFEFEF]
        disabled:opacity-50 disabled:pointer-events-none
        ${fullWidth ? 'w-full' : ''}
        ${sizeStyles[size]}
        ${className}
      `}
      {...props}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <Loader2 className="w-5 h-5 animate-spin text-[#667174]" />
          <span>Loading...</span>
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
  const sizeStyles = {
    sm: 'h-10 px-3 text-xs',
    md: 'h-12 px-4 text-sm',
    lg: 'h-14 px-5 text-base',
  };

  return (
    <button
      disabled={disabled || loading}
      className={`relative inline-flex items-center justify-center font-semibold rounded-xl transition-all active:scale-[0.98] select-none
        bg-[#D9534F] text-white hover:bg-[#C9433F] active:bg-[#B33531]
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
          <span>Processing...</span>
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
