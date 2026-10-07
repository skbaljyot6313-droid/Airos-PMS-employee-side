import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { Eye, EyeOff, ShieldCheck, Lock, User, AlertCircle, ArrowRight } from 'lucide-react';
import { PrimaryButton } from '../../components/common/Buttons';

export const LoginScreen: React.FC = () => {
  const { login, isLoading, authError, clearError } = useAuth();
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
        {/* AiROS Staff Enterprise Header */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-9 h-9 rounded-xl bg-[#33B059] flex items-center justify-center text-white shadow-sm">
              <ShieldCheck className="w-5 h-5 stroke-[2.5]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold tracking-tight text-[#20292C] font-['Space_Grotesk']">
                  AiROS
                </span>
                <span className="text-[11px] font-bold uppercase tracking-wider bg-[#E8F7ED] text-[#278B46] px-2 py-0.5 rounded-full border border-[#BBECCC]">
                  Staff
                </span>
              </div>
            </div>
          </div>
          <h2 className="text-2xl font-bold text-[#20292C] font-['Space_Grotesk'] tracking-tight">
            Sign in to continue
          </h2>
          <p className="text-xs text-[#667174] mt-1">
            Access your assigned field tasks, property checklists, and maintenance operations.
          </p>
        </div>

        {/* API Error Banner */}
        {authError && (
          <div className="mb-5 p-3.5 bg-[#FCEBEA] border border-[#F8C8C6] rounded-xl flex items-start gap-2.5 text-xs text-[#D9534F] leading-relaxed">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <span className="font-semibold block mb-0.5">Authentication Error</span>
              <span>{authError}</span>
            </div>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-[#20292C] mb-1.5 uppercase tracking-wider">
              Username or Email
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#8D999C]">
                <User className="w-4 h-4" />
              </div>
              <input
                type="text"
                value={username}
                onChange={(e) => {
                  clearError();
                  setUsername(e.target.value);
                }}
                placeholder="Enter your employee ID or email"
                autoCapitalize="none"
                required
                className="w-full pl-10 pr-3.5 py-3 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-sm text-[#20292C] placeholder-[#8D999C] focus:bg-white focus:outline-none focus:border-[#33B059] focus:ring-2 focus:ring-[#33B059]/15 transition-all"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#20292C] mb-1.5 uppercase tracking-wider">
              Password
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[#8D999C]">
                <Lock className="w-4 h-4" />
              </div>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => {
                  clearError();
                  setPassword(e.target.value);
                }}
                placeholder="Enter password"
                required
                className="w-full pl-10 pr-11 py-3 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-sm text-[#20292C] placeholder-[#8D999C] focus:bg-white focus:outline-none focus:border-[#33B059] focus:ring-2 focus:ring-[#33B059]/15 transition-all"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-[#8D999C] hover:text-[#20292C] transition-colors"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
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
              Sign In
            </PrimaryButton>
          </div>
        </form>

      </div>

      <div className="text-center text-[11px] text-[#8D999C] py-2">
        AiROS Staff Mobile OS · Authorized Field Personnel Only
      </div>
    </div>
  );
};
