import React, { useState } from 'react';
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  Building2,
  ShieldCheck,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { PrimaryButton, SecondaryButton } from '../../components/common/Buttons';
import {
  submitRegistrationApi,
  verifyCodeApi,
  DepartmentOption,
  RegistrationPayload,
} from '../../api/registration';
import { ApiError } from '../../types';

type Step = 'organization' | 'personal' | 'employment' | 'account';
const STEPS: Step[] = ['organization', 'personal', 'employment', 'account'];
const DEPT_OTHER = '__other__';

interface VerifiedOrg {
  org: string;
  property: string | null;
  departments: DepartmentOption[];
}

interface FormState {
  full_name: string;
  username: string;
  email: string;
  phone: string;
  date_of_birth: string;
  gender: string;
  designation: string;
  department: string;
  employment_type: string;
  joining_date: string;
  reporting_manager: string;
  salary: string;
  salary_frequency: '' | 'monthly' | 'daily' | 'hourly';
  password: string;
  confirm_password: string;
  organization_code: string;
}

const EMPTY: FormState = {
  full_name: '', username: '', email: '', phone: '',
  date_of_birth: '', gender: '', designation: '', department: '',
  employment_type: '', joining_date: '', reporting_manager: '',
  salary: '', salary_frequency: '', password: '', confirm_password: '',
  organization_code: '',
};

const INPUT =
  'w-full px-3.5 py-3 rounded-xl border border-[#E7E5E4] bg-[#FFFCFA] text-sm ' +
  'text-[#0D1C42] placeholder-[#98A2B3] focus:bg-white focus:outline-none ' +
  'focus:border-[#800020] focus:ring-2 focus:ring-[#800020]/15 transition-all';
const LABEL =
  'block text-xs font-semibold text-[#0D1C42] mb-1.5 uppercase tracking-wider';
const ERR = 'text-[11px] text-[#D64545] mt-1';

interface FieldProps {
  label: string;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
}
const Field: React.FC<FieldProps> = ({ label, error, required, children }) => (
  <div>
    <label className={LABEL}>
      {label}
      {required && <span className="text-[#800020]"> *</span>}
    </label>
    {children}
    {error && <p className={ERR}>{error}</p>}
  </div>
);

export const RegisterScreen: React.FC<{ onBack: () => void }> = ({ onBack }) => {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>('organization');
  const [form, setForm] = useState<FormState>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verified, setVerified] = useState<VerifiedOrg | null>(null);
  const [deptOther, setDeptOther] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const [done, setDone] = useState<string | null>(null); // org name on success

  const set = (k: keyof FormState) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
    setErrors((prev) => {
      if (!prev[k]) return prev;
      const next = { ...prev };
      delete next[k];
      return next;
    });
    setServerError(null);
  };

  const setCode = (e: React.ChangeEvent<HTMLInputElement>) => {
    const code = e.target.value.toUpperCase().slice(0, 12);
    setForm((f) => ({ ...f, organization_code: code }));
    // Editing the code invalidates the previous verification — the org
    // card and department options belong to the OLD code.
    setVerified(null);
    setDeptOther(false);
    setErrors((p) => {
      const n = { ...p };
      delete n.organization_code;
      return n;
    });
    setServerError(null);
  };

  // ------------------------- validation -----------------------------
  const validate = (s: Step): boolean => {
    const e: Record<string, string> = {};
    const req = (k: keyof FormState) => {
      if (!form[k].trim()) e[k] = t('register.required');
    };
    if (s === 'organization') {
      if (!/^[A-Za-z0-9]{12}$/.test(form.organization_code.trim()))
        e.organization_code = t('register.errCode');
    }
    if (s === 'personal') {
      req('full_name');
      req('username');
      req('email');
      if (form.username && !/^[a-zA-Z0-9._-]{3,100}$/.test(form.username.trim()))
        e.username = t('register.errUsername');
      if (form.email && !/^\S+@\S+\.\S+$/.test(form.email.trim()))
        e.email = t('register.errEmail');
      if (form.phone && !/^\+?[0-9 -]{7,16}$/.test(form.phone.trim()))
        e.phone = t('register.errPhone');
      if (form.date_of_birth && !/^\d{4}-\d{2}-\d{2}$/.test(form.date_of_birth))
        e.date_of_birth = t('register.errDate');
    }
    if (s === 'employment') {
      req('designation');
      if (form.joining_date && !/^\d{4}-\d{2}-\d{2}$/.test(form.joining_date))
        e.joining_date = t('register.errDate');
      if (form.salary && !/^[0-9,.\s₹$-]+$/.test(form.salary.trim()))
        e.salary = t('register.errSalary');
    }
    if (s === 'account') {
      if (form.password.length < 8) e.password = t('register.errPassword');
      if (form.confirm_password !== form.password)
        e.confirm_password = t('register.errConfirm');
    }
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  // -------------------- code verification ---------------------------
  const verify = async () => {
    if (!validate('organization') || verifying) return;
    setVerifying(true);
    setServerError(null);
    try {
      const res = await verifyCodeApi(form.organization_code.trim());
      if (!res.valid) {
        setErrors({ organization_code: t('register.errCode') });
        return;
      }
      setVerified({
        org: res.organization_name ?? '',
        property: res.property_name,
        departments: res.departments ?? [],
      });
      setStep('personal');
    } catch (err) {
      setServerError((err as ApiError).message || t('register.errGeneric'));
    } finally {
      setVerifying(false);
    }
  };

  const next = () => {
    if (!validate(step)) return;
    setStep(STEPS[STEPS.indexOf(step) + 1]);
  };
  const back = () => {
    const i = STEPS.indexOf(step);
    if (i === 0) onBack();
    else setStep(STEPS[i - 1]);
  };

  // ------------------------- submit ---------------------------------
  const submit = async () => {
    if (!validate('account') || submitting) return;
    setSubmitting(true);
    setServerError(null);
    try {
      const payload: RegistrationPayload = {
        organization_code: form.organization_code.trim().toUpperCase(),
        full_name: form.full_name.trim(),
        username: form.username.trim(),
        email: form.email.trim(),
        designation: form.designation.trim(),
        password: form.password,
        confirm_password: form.confirm_password,
        ...(form.phone.trim() && { phone: form.phone.trim() }),
        ...(form.date_of_birth && { date_of_birth: form.date_of_birth }),
        ...(form.gender && { gender: form.gender }),
        ...(form.department.trim() && { department: form.department.trim() }),
        ...(form.employment_type && { employment_type: form.employment_type }),
        ...(form.joining_date && { joining_date: form.joining_date }),
        ...(form.reporting_manager.trim() && {
          reporting_manager: form.reporting_manager.trim(),
        }),
        ...(form.salary.trim() && { salary: form.salary.trim() }),
        ...(form.salary_frequency && {
          salary_frequency: form.salary_frequency,
        }),
      };
      const res = await submitRegistrationApi(payload);
      const org = res.organization_name || verified?.org || '';
      const prop = res.property_name || verified?.property || '';
      setDone(prop ? `${org} · ${prop}` : org);
    } catch (err) {
      const apiErr = err as ApiError;
      if (apiErr.code === 'INVALID_ORGANIZATION_CODE') {
        // Code rotated/invalidated after the initial verify — restart.
        setVerified(null);
        setStep('organization');
        setErrors({ organization_code: apiErr.message });
      } else if (apiErr.fieldErrors?.length) {
        // Server-side field errors jump back to the step owning them.
        const mapped: Record<string, string> = {};
        for (const fe of apiErr.fieldErrors) {
          if (fe.field) mapped[fe.field] = fe.message;
        }
        setErrors(mapped);
        if (mapped.organization_code) {
          setVerified(null);
          setStep('organization');
        } else if (
          mapped.full_name || mapped.username || mapped.email || mapped.phone
        )
          setStep('personal');
        else if (
          mapped.designation || mapped.department || mapped.salary ||
          mapped.joining_date
        )
          setStep('employment');
        else setServerError(apiErr.message);
      } else {
        setServerError(apiErr.message || t('register.errGeneric'));
      }
    } finally {
      setSubmitting(false);
    }
  };

  // ------------------------- success --------------------------------
  if (done !== null) {
    return (
      <div className="flex-1 flex flex-col p-6 bg-white overflow-y-auto">
        <div className="w-full max-w-sm mx-auto my-auto py-6 text-center">
          <div className="w-16 h-16 rounded-full bg-[#EDF7EE] flex items-center justify-center mx-auto mb-4">
            <CheckCircle2 className="w-8 h-8 text-[#386641]" />
          </div>
          <h2 className="text-xl font-bold text-[#0D1C42] font-['Satoshi'] tracking-tight mb-2">
            {t('register.successTitle')}
          </h2>
          <p className="text-sm text-[#667085] leading-relaxed mb-1">
            {t('register.successBody')}
          </p>
          {done && (
            <p className="text-xs font-semibold text-[#800020] mt-2">
              {done}
            </p>
          )}
          <div className="mt-8">
            <PrimaryButton onClick={onBack}>{t('register.backToLogin')}</PrimaryButton>
          </div>
        </div>
      </div>
    );
  }

  const stepIndex = STEPS.indexOf(step);

  return (
    <div className="flex-1 flex flex-col p-6 bg-white overflow-y-auto">
      <div className="w-full max-w-sm mx-auto my-auto py-4">
        {/* Header */}
        <div className="mb-6">
          <button
            type="button"
            onClick={back}
            className="flex items-center gap-1.5 text-xs font-semibold text-[#667085] mb-4"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            {stepIndex === 0 ? t('register.backToLogin') : t('register.back')}
          </button>
          <h2 className="text-2xl font-bold text-[#0D1C42] font-['Satoshi'] tracking-tight">
            {t('register.title')}
          </h2>
          <p className="text-xs text-[#667085] mt-1">{t('register.subtitle')}</p>
        </div>

        {/* Progress */}
        <div className="flex items-center gap-1.5 mb-6">
          {STEPS.map((s, i) => (
            <div
              key={s}
              className={`h-1 flex-1 rounded-full transition-colors ${
                i <= stepIndex ? 'bg-[#800020]' : 'bg-[#E7E5E4]'
              }`}
            />
          ))}
        </div>
        <p className="text-[10px] font-bold uppercase tracking-wider text-[#98A2B3] mb-4">
          {t(`register.step_${step}`)} · {stepIndex + 1}/{STEPS.length}
        </p>

        {serverError && (
          <div className="mb-4 p-3.5 bg-[#FAEBEB] border border-[#F0C8C8] rounded-xl text-xs text-[#D64545] leading-relaxed">
            {serverError}
          </div>
        )}

        {/* Verified-org ribbon on every step after the code check */}
        {verified && step !== 'organization' && (
          <div className="mb-4 p-3 rounded-xl bg-[#EDF7EE] border border-[#C8E6CE] flex items-center gap-2.5">
            <ShieldCheck className="w-4 h-4 text-[#386641] flex-shrink-0" />
            <p className="text-[11px] font-semibold text-[#386641] leading-snug">
              {t('register.joining')}{' '}
              {verified.property
                ? `${verified.org} · ${verified.property}`
                : verified.org}
            </p>
          </div>
        )}

        {/* --------------------- Steps --------------------- */}
        {step === 'organization' && (
          <div className="space-y-4">
            <div className="p-4 rounded-xl bg-[#F7E9EE] border border-[#EAD3DB] flex items-start gap-3">
              <Building2 className="w-5 h-5 text-[#800020] flex-shrink-0 mt-0.5" />
              <p className="text-xs text-[#0D1C42] leading-relaxed">
                {t('register.codeHint')}
              </p>
            </div>
            <Field label={t('register.code')} required error={errors.organization_code}>
              <input
                className={`${INPUT} text-center tracking-[0.3em] font-mono uppercase`}
                value={form.organization_code}
                onChange={setCode}
                placeholder={t('register.codePh')}
                autoCapitalize="characters"
                maxLength={12}
              />
            </Field>
          </div>
        )}

        {step === 'personal' && (
          <div className="space-y-4">
            <Field label={t('register.fullName')} required error={errors.full_name}>
              <input className={INPUT} value={form.full_name} onChange={set('full_name')}
                placeholder={t('register.fullNamePh')} />
            </Field>
            <Field label={t('register.username')} required error={errors.username}>
              <input className={INPUT} value={form.username} onChange={set('username')}
                autoCapitalize="none" placeholder={t('register.usernamePh')} />
            </Field>
            <Field label={t('register.email')} required error={errors.email}>
              <input className={INPUT} type="email" inputMode="email"
                value={form.email} onChange={set('email')}
                autoCapitalize="none" placeholder={t('register.emailPh')} />
            </Field>
            <Field label={t('register.phone')} error={errors.phone}>
              <input className={INPUT} type="tel" inputMode="tel"
                value={form.phone} onChange={set('phone')}
                placeholder={t('register.phonePh')} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('register.dob')} error={errors.date_of_birth}>
                <input className={INPUT} type="date" value={form.date_of_birth}
                  onChange={set('date_of_birth')} />
              </Field>
              <Field label={t('register.gender')}>
                <select className={INPUT} value={form.gender} onChange={set('gender')}>
                  <option value="">—</option>
                  <option value="male">{t('register.genderMale')}</option>
                  <option value="female">{t('register.genderFemale')}</option>
                  <option value="other">{t('register.genderOther')}</option>
                  <option value="prefer_not_to_say">{t('register.genderPreferNot')}</option>
                </select>
              </Field>
            </div>
          </div>
        )}

        {step === 'employment' && (
          <div className="space-y-4">
            <Field label={t('register.designation')} required error={errors.designation}>
              <input className={INPUT} value={form.designation} onChange={set('designation')}
                placeholder={t('register.designationPh')} />
            </Field>
            <Field label={t('register.department')} error={errors.department}>
              {verified && verified.departments.length > 0 ? (
                <>
                  <select
                    className={INPUT}
                    value={deptOther ? DEPT_OTHER : form.department}
                    onChange={(e) => {
                      if (e.target.value === DEPT_OTHER) {
                        setDeptOther(true);
                        setForm((f) => ({ ...f, department: '' }));
                      } else {
                        setDeptOther(false);
                        set('department')(e);
                      }
                    }}
                  >
                    <option value="">{t('register.departmentSelect')}</option>
                    {verified.departments.map((d) => (
                      <option key={d.uid} value={d.name}>{d.name}</option>
                    ))}
                    <option value={DEPT_OTHER}>{t('register.departmentOther')}</option>
                  </select>
                  {deptOther && (
                    <input
                      className={`${INPUT} mt-2`}
                      value={form.department}
                      onChange={set('department')}
                      placeholder={t('register.departmentPh')}
                    />
                  )}
                </>
              ) : (
                <input className={INPUT} value={form.department} onChange={set('department')}
                  placeholder={t('register.departmentPh')} />
              )}
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('register.employmentType')}>
                <select className={INPUT} value={form.employment_type}
                  onChange={set('employment_type')}>
                  <option value="">—</option>
                  <option value="full_time">{t('register.etFull')}</option>
                  <option value="part_time">{t('register.etPart')}</option>
                  <option value="contract">{t('register.etContract')}</option>
                  <option value="intern">{t('register.etIntern')}</option>
                  <option value="temporary">{t('register.etTemporary')}</option>
                </select>
              </Field>
              <Field label={t('register.joiningDate')} error={errors.joining_date}>
                <input className={INPUT} type="date" value={form.joining_date}
                  onChange={set('joining_date')} />
              </Field>
            </div>
            <Field label={t('register.reportingManager')} error={errors.reporting_manager}>
              <input className={INPUT} value={form.reporting_manager}
                onChange={set('reporting_manager')}
                placeholder={t('register.reportingManagerPh')} />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('register.salary')} error={errors.salary}>
                <input className={INPUT} inputMode="decimal" value={form.salary}
                  onChange={set('salary')} placeholder={t('register.salaryPh')} />
              </Field>
              <Field label={t('register.salaryFrequency')}>
                <select className={INPUT} value={form.salary_frequency}
                  onChange={set('salary_frequency')}>
                  <option value="">—</option>
                  <option value="monthly">{t('register.freqMonthly')}</option>
                  <option value="daily">{t('register.freqDaily')}</option>
                  <option value="hourly">{t('register.freqHourly')}</option>
                </select>
              </Field>
            </div>
          </div>
        )}

        {step === 'account' && (
          <div className="space-y-4">
            <Field label={t('register.password')} required error={errors.password}>
              <div className="relative">
                <input className={`${INPUT} pr-11`}
                  type={showPw ? 'text' : 'password'} value={form.password}
                  onChange={set('password')} placeholder={t('register.passwordPh')} />
                <button type="button" onClick={() => setShowPw(!showPw)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center text-[#98A2B3]">
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </Field>
            <Field label={t('register.confirmPassword')} required
              error={errors.confirm_password}>
              <input className={INPUT} type="password" value={form.confirm_password}
                onChange={set('confirm_password')}
                placeholder={t('register.confirmPasswordPh')} />
            </Field>
            <p className="text-[11px] text-[#98A2B3] leading-relaxed">
              {t('register.passwordHint')}
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="mt-8">
          {step === 'organization' ? (
            <PrimaryButton onClick={() => void verify()} loading={verifying}
              size="lg" icon={<ArrowRight className="w-4 h-4" />}>
              {t('register.verify')}
            </PrimaryButton>
          ) : step === 'account' ? (
            <PrimaryButton onClick={() => void submit()} loading={submitting}
              size="lg" icon={<ArrowRight className="w-4 h-4" />}>
              {t('register.submit')}
            </PrimaryButton>
          ) : (
            <PrimaryButton onClick={next} size="lg"
              icon={<ArrowRight className="w-4 h-4" />}>
              {t('register.next')}
            </PrimaryButton>
          )}
          {stepIndex > 0 && (
            <div className="mt-3">
              <SecondaryButton onClick={back}>{t('register.back')}</SecondaryButton>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
