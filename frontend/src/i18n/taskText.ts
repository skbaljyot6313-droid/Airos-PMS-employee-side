/**
 * Dynamic task-text localization.
 *
 * Backend tasks today carry only plain `title`/`description` (plus optional
 * `title_translations`/`description_translations` maps on a few newer rows —
 * supported here when present). This module resolves display/speech text
 * deterministically:
 *
 *   1. Server-provided translated variant for the requested language.
 *   2. A registered task template for the task's `work_type` (structured
 *      interpolation; identifiers like room numbers are never rewritten).
 *   3. The original English/source title and instructions.
 *
 * The resolver is pure and offline — no external translation API. Adding a
 * language or a template is a data change only.
 */
import type { Task } from '../types';
import { isSupportedLanguage, type LanguageCode } from './languages';

type Params = Record<string, string | number>;

type TaskTemplate = Partial<Record<LanguageCode, (p: Params) => string>>;

/**
 * Structured templates keyed on the backend `work_type` vocabulary
 * (`cleaning`, `inspection`, `maintenance`, `laundry`, `setup`, `security`,
 * `other` — free values fall through to `other` / the source description).
 * Interpolated params come from the task record itself; numeric and
 * identifier values pass through verbatim.
 */
export const TASK_TEMPLATES: Record<string, TaskTemplate> = {
  cleaning: {
    en: (p) => `Clean ${p.location}.`,
    hi: (p) => `${p.location} साफ़ करें।`,
    mr: (p) => `${p.location} स्वच्छ करा.`,
  },
  inspection: {
    en: (p) => `Inspect ${p.location} and report any issues.`,
    hi: (p) => `${p.location} की जाँच करें और कोई समस्या हो तो रिपोर्ट करें।`,
    mr: (p) => `${p.location} तपासा आणि काही समस्या असल्यास ती नोंदवा.`,
  },
  laundry: {
    en: (p) => `Collect and process laundry for ${p.location}.`,
    hi: (p) => `${p.location} का लॉन्ड्री इकट्ठा करें और प्रोसेस करें।`,
    mr: (p) => `${p.location} साठी लॉन्ड्री गोळा करा आणि प्रक्रिया करा.`,
  },
  setup: {
    en: (p) => `Set up ${p.location} for the next occupant.`,
    hi: (p) => `अगले अतिथि के लिए ${p.location} तैयार करें।`,
    mr: (p) => `पुढील रहिवाशासाठी ${p.location} तयार करा.`,
  },
  security: {
    en: (p) => `Perform a security check of ${p.location}.`,
    hi: (p) => `${p.location} की सुरक्षा जाँच करें।`,
    mr: (p) => `${p.location} ची सुरक्षा तपासणी करा.`,
  },
};

const normWorkType = (category: string): string =>
  category.trim().toLowerCase().replace(/\s+/g, '_');

const templateParams = (task: Task): Params => ({
  location: task.location_name || task.zone_name || 'the assigned area',
});

/** Optional server-supplied translation maps (additive on the wire). */
interface LocalizedFields {
  title_translations?: Record<string, string> | null;
  description_translations?: Record<string, string> | null;
}

const variant = (map: Record<string, string> | null | undefined, lang: LanguageCode) =>
  map?.[lang]?.trim() || null;

export interface ResolvedTaskText {
  title: string;
  /** Display instructions — translated variant, template, or source text. */
  instructions: string | null;
  /** true when a translated variant/template was used. */
  localized: boolean;
}

/**
 * Resolve on-screen task text for `lang`. Never returns empty fields —
 * falls back to the task's own source strings.
 */
export const resolveTaskText = (task: Task, lang: LanguageCode): ResolvedTaskText => {
  const extra = task as Task & LocalizedFields;
  const titleVariant = variant(extra.title_translations, lang);
  const descVariant = variant(extra.description_translations, lang);

  if (titleVariant || descVariant) {
    return {
      title: titleVariant ?? task.title,
      instructions: descVariant ?? task.instructions,
      localized: true,
    };
  }

  if (lang !== 'en' && task.kind !== 'maintenance') {
    const tpl = TASK_TEMPLATES[normWorkType(task.category)];
    const localized = tpl?.[lang];
    if (localized && !task.instructions) {
      return {
        title: localized(templateParams(task)),
        instructions: null,
        localized: true,
      };
    }
  }

  return { title: task.title, instructions: task.instructions, localized: false };
};

/**
 * Resolve the text spoken for a task in `audioLang`. Order:
 *   1. Server-supplied description variant for the audio language.
 *   2. Known work-type template for the audio language.
 *   3. The task's own title + instructions (source text).
 * A maintenance ticket speaks issue + description. Never returns ''.
 */
export const resolveSpeechText = (task: Task, audioLang: LanguageCode): string => {
  const { title, instructions } = resolveTaskText(task, audioLang);
  const body = instructions && instructions !== title ? `${title}. ${instructions}` : title;
  return body.trim();
};

/** Best-effort language tag for server variant maps (plain codes only). */
export const taskTextLanguage = (code: string): LanguageCode =>
  isSupportedLanguage(code) ? code : 'en';

/**
 * Speech adapter — a maintenance ticket's speakable shape (issue → title,
 * description → instructions). Display text stays the ticket's own fields.
 */
export const ticketToSpeakable = (ticket: {
  id: string;
  issue: string;
  description?: string | null;
  category: string;
  location_name?: string | null;
  zone_name?: string | null;
}): Task =>
  ({
    id: ticket.id,
    kind: 'maintenance',
    title: ticket.issue,
    instructions: ticket.description ?? null,
    category: ticket.category,
    location_name: ticket.location_name ?? '',
    zone_name: ticket.zone_name ?? null,
  }) as Task;
