import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { Eye, EyeOff, Lock, User, AlertCircle, ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { PrimaryButton } from '../../components/common/Buttons';

export const LoginScreen: React.FC<{ onNavigateRegister?: () => void }> = ({
  onNavigateRegister,
}) => {
  const { login, isLoading, authError, clearError } = useAuth();
  const { t } = useTranslation();
  const [username, setUsername] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [showPassword, setShowPassword] = useState<boolean>(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    try {
      await login(username.trim(), password);
    } catch {
      // Error handled by AuthContext
    }
  };

  return (
    <div className="flex-1 flex flex-col justify-between p-6 bg-white overflow-y-auto">
      <div className="w-full max-w-sm mx-auto my-auto py-6">
        {/* Airco PMS Staff Enterprise Header */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <img src="/airco-pms-logo.svg" alt="Airco PMS" className="w-9 h-9 rounded-xl shadow-sm" />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold tracking-tight text-[#0D1C42] font-['Satoshi']">
                  {t('auth.brand')}
                </span>
                <span className="text-[9px] font-bold uppercase tracking-wider bg-[#F7E9EE] text-[#0D1C42] px-2 py-0.5 rounded-full border border-[#EAD3DB]">
                  {t('auth.staffBadge')}
                </span>
              </div>
            </div>
          </div>
          <h2 className="text-2xl font-bold text-[#0D1C42] font-['Satoshi'] tracking-tight">
            {t('auth.title')}
          </h2>
          <p className="text-xs text-[#667085] mt-1">
            {t('auth.subtitle')}
          </p>
        </div>

        {/* API Error Banner */}
        {authError && (
          <div className="mb-5 p-3.5 bg-[#FAEBEB] border border-[#F0C8C8] rounded-xl flex items-start gap-2.5 text-xs text-[#D64545] leading-relaxed">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-semibold block mb-0.5">{t('auth.errorTitle')}</span>
              <span>{authError}</span>
            </div>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-[#0D1C42] mb-1.5 uppercase tracking-wider">
              {t('auth.identifier')}
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#98A2B3]">
                <User className="w-4 h-4" />
              </div>
              <input
                type="text"
                value={username}
                onChange={(e) => {
                  clearError();
                  setUsername(e.target.value);
                }}
                placeholder={t('auth.identifierPlaceholder')}
                autoCapitalize="none"
                required
                className="w-full pl-10 pr-3.5 py-3 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-sm text-[#0D1C42] placeholder-[#98A2B3] focus:bg-white focus:outline-none focus:border-[#800020] focus:ring-2 focus:ring-[#800020]/15 transition-all"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#0D1C42] mb-1.5 uppercase tracking-wider">
              {t('auth.password')}
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#98A2B3]">
                <Lock className="w-4 h-4" />
              </div>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => {
                  clearError();
                  setPassword(e.target.value);
                }}
                placeholder={t('auth.passwordPlaceholder')}
                required
                className="w-full pl-10 pr-11 py-3 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-sm text-[#0D1C42] placeholder-[#98A2B3] focus:bg-white focus:outline-none focus:border-[#800020] focus:ring-2 focus:ring-[#800020]/15 transition-all"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-[#98A2B3] hover:text-[#0D1C42] transition-colors"
                aria-label={showPassword ? t('auth.hidePassword') : t('auth.showPassword')}
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="pt-2">
            <PrimaryButton
              type="submit"
              loading={isLoading}
              size="lg"
              icon={<ArrowRight className="w-4 h-4" />}
            >
              {t('auth.signIn')}
            </PrimaryButton>
          </div>
        </form>

        {/* Self-registration entry — opens the org-code onboarding flow.
            The login form itself is untouched. */}
        {onNavigateRegister && (
          <button
            type="button"
            onClick={onNavigateRegister}
            className="w-full mt-5 py-3 rounded-xl border border-[#E7E5E4] text-xs font-semibold text-[#0D1C42] hover:border-[#800020] hover:text-[#800020] transition-colors"
          >
            {t('register.cta')}
          </button>
        )}

      </div>

      <div className="text-center text-[9px] text-[#98A2B3] py-2">
        {t('auth.footer')}
      </div>
    </div>
  );
};
