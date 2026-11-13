/**
 * Centralized task localization + speech-text service.
 *
 * `getLocalizedTask(task, lang)` resolves display text; `resolveSpeechText`
 * resolves what the speaker reads. Resolution order:
 *
 *   1. Server-provided translated variant maps (`title_translations` /
 *      `description_translations`) — honored verbatim when present.
 *   2. Structured templates for recognized system tasks (work_type ×
 *      location context × resource list). Bed identifiers, room numbers
 *      and names pass through unchanged.
 *   3. The task's own source strings — free-form admin text is NEVER
 *      fake-translated; it falls through intact with `localized` flags
 *      honestly reporting which piece stayed in the source language.
 *
 * Display identifiers always stay verbatim ("P2-05"); the speech layer
 * transliterates them so "P2-05" is heard as an identifier, not math —
 * Hindi/Marathi use Devanagari letter/digit names (पी टू ज़ीरो फाइव /
 * पी टू झिरो फाइव), English de-hyphenates ("P2 05").
 *
 * Resolved text is memoized per task+language so list re-renders and
 * repeated language switches never recompute.
 */
import type { Task, TaskResource } from '../types';
import { isSupportedLanguage, type LanguageCode } from './languages';

type Params = Record<string, string | number>;
type LangMap<T> = Partial<Record<LanguageCode, T>>;

// ---------------------------------------------------------------------------
// Resource-list joining (display keeps verbatim labels)
// ---------------------------------------------------------------------------

const CONJUNCTION: Record<LanguageCode, string> = { en: 'and', hi: 'और', mr: 'आणि' };

/** "a, b and c" — localized final conjunction. */
export const joinLabels = (labels: string[], lang: LanguageCode): string => {
  if (labels.length <= 1) return labels[0] ?? '';
  return `${labels.slice(0, -1).join(', ')} ${CONJUNCTION[lang]} ${labels[labels.length - 1]}`;
};

// ---------------------------------------------------------------------------
// Identifier → speech formatter
// ---------------------------------------------------------------------------

const DEVANAGARI_LETTER: Record<string, string> = {
  A: 'ए', B: 'बी', C: 'सी', D: 'डी', E: 'ई', F: 'एफ़', G: 'जी', H: 'एच',
  I: 'आई', J: 'जे', K: 'के', L: 'एल', M: 'एम', N: 'एन', O: 'ओ', P: 'पी',
  Q: 'क्यू', R: 'आर', S: 'एस', T: 'टी', U: 'यू', V: 'वी', W: 'डब्ल्यू',
  X: 'एक्स', Y: 'वाई', Z: 'ज़ेड',
};

const DIGIT_WORDS: Record<LanguageCode, string[]> = {
  en: ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'],
  hi: ['ज़ीरो', 'वन', 'टू', 'थ्री', 'फ़ोर', 'फ़ाइव', 'सिक्स', 'सेवन', 'एट', 'नाइन'],
  mr: ['झिरो', 'वन', 'टू', 'थ्री', 'फोर', 'फाइव', 'सिक्स', 'सेव्हन', 'एट', 'नाइन'],
};

const TOKEN_SPLIT = /([A-Za-z]+|[0-9]+)/g;

/**
 * Render an alphanumeric identifier ("P2-05", "Bed 03", "A12-B") so a TTS
 * engine speaks it as an identifier rather than a number or expression.
 * hi/mr: letter names + digit names in Devanagari. en: hyphens become
 * spaces and mixed groups get a word boundary ("P2-05" → "P2 05").
 */
export const identifierForSpeech = (id: string, lang: LanguageCode): string => {
  if (lang === 'en') {
    // Keep letter+digit chunks together — just drop separators so the id
    // is spoken as an identifier, never as an expression ("P2-05" → "P2 05").
    return id.replace(/[^A-Za-z0-9]+/g, ' ').trim();
  }
  const tokens = id.trim().split(TOKEN_SPLIT).filter(Boolean);
  const words: string[] = [];
  for (const tok of tokens) {
    if (/^[A-Za-z]+$/.test(tok)) {
      for (const ch of tok.toUpperCase()) {
        words.push(DEVANAGARI_LETTER[ch] ?? ch);
      }
    } else if (/^[0-9]+$/.test(tok)) {
      for (const ch of tok) {
        words.push(DIGIT_WORDS[lang][Number(ch)]);
      }
    }
    // separators → pause handled by surrounding spaces
  }
  return words.join(' ');
};

/** Identifier list rendered for speech in the given language. */
export const joinLabelsForSpeech = (labels: string[], lang: LanguageCode): string =>
  joinLabels(labels.map((l) => identifierForSpeech(l, lang)), lang);

// ---------------------------------------------------------------------------
// Location context
// ---------------------------------------------------------------------------

type LocationKind = 'beds' | 'room' | 'dorm' | 'washroom' | 'area';

interface TaskContext {
  workType: string;
  kind: LocationKind;
  room?: string;
  dorm?: string;
  washroom?: string;
  fixture?: string;
  zone?: string;
  /** Verbatim resource labels (sorted by backend). */
  resources: TaskResource[];
}

const strip = (v: string | null | undefined): string | undefined => {
  const s = v?.trim();
  return s ? s : undefined;
};

const stripDormPrefix = (name: string): string =>
  name.replace(/^dorm(itory)?\s*/i, '').trim() || name;

const ctxFor = (task: Task): TaskContext => {
  const resources = task.resources ?? [];
  const beds = resources.filter((r) => r.kind === 'bed');
  const ctx: TaskContext = {
    workType: (task.work_type ?? task.category ?? '')
      .trim().toLowerCase().replace(/\s+/g, '_'),
    kind: 'area',
    room:
      strip(task.room_number) ??
      strip(task.location_name?.match(/^room\s+(.+)$/i)?.[1]),
    dorm: strip(task.dorm_name) ? stripDormPrefix(strip(task.dorm_name)!) : undefined,
    washroom: strip(task.washroom_name),
    fixture: strip(task.washroom_fixture_label),
    zone: strip(task.zone_name ?? undefined),
    resources,
  };
  if (beds.length) ctx.kind = 'beds';
  else if (ctx.room) ctx.kind = 'room';
  else if (ctx.dorm) ctx.kind = 'dorm';
  else if (ctx.washroom) ctx.kind = 'washroom';
  return ctx;
};

/** Localized short place name — used inside sentences. */
const placeName = (ctx: TaskContext, lang: LanguageCode): string => {
  switch (ctx.kind) {
    case 'beds':
    case 'dorm': {
      const name = ctx.dorm ?? '';
      return lang === 'en' ? `Dorm ${name}` : `डॉर्म ${name}`;
    }
    case 'room':
      return lang === 'en' ? `Room ${ctx.room}` : `रूम ${ctx.room}`;
    case 'washroom':
      return lang === 'en' ? `washroom ${ctx.washroom}` : `वॉशरूम ${ctx.washroom}`;
    default:
      if (ctx.zone) return lang === 'en' ? `the ${ctx.zone} zone` : `${ctx.zone} झोन`;
      return lang === 'en' ? 'the common area' : lang === 'hi' ? 'कॉमन एरिया' : 'कॉमन एरिया';
  }
};

// ---------------------------------------------------------------------------
// Templates — work_type × location context, per language
// ---------------------------------------------------------------------------

interface Shape {
  title: (c: TaskContext, lang: LanguageCode) => string;
  description: (c: TaskContext, lang: LanguageCode) => string;
}

/** Resource labels for display (verbatim) or speech (transliterated). */
const listFor = (c: TaskContext, lang: LanguageCode, speech: boolean): string => {
  const labels = c.resources.map((r) => r.label);
  return speech ? joinLabelsForSpeech(labels, lang) : joinLabels(labels, lang);
};

const TEMPLATES: Record<string, Shape> = {
  cleaning: {
    title: (c, lang) => {
      if (c.kind === 'beds') {
        return lang === 'en' ? `Bed cleaning — ${placeName(c, lang)}`
          : lang === 'hi' ? `बेड सफ़ाई — ${placeName(c, lang)}`
          : `बेड स्वच्छता — ${placeName(c, lang)}`;
      }
      return lang === 'en' ? `Cleaning — ${titleCase(placeName(c, lang))}`
        : `${placeName(c, lang)} ${lang === 'hi' ? 'सफ़ाई' : 'स्वच्छता'}`;
    },
    description: (c, lang) => {
      if (c.kind === 'beds') {
        return lang === 'en'
          ? `Clean beds ${listFor(c, lang, false)} in ${placeName(c, lang)}.`
          : lang === 'hi'
            ? `${placeName(c, lang)} में बेड ${listFor(c, lang, false)} की सफ़ाई करें।`
            : `${placeName(c, lang)} मधील बेड ${listFor(c, lang, false)} स्वच्छ करा.`;
      }
      return lang === 'en'
        ? `Clean ${placeName(c, lang)}.`
        : lang === 'hi'
          ? `${placeName(c, lang)} साफ़ करें।`
          : `${placeName(c, lang)} स्वच्छ करा.`;
    },
  },
  inspection: {
    title: (c, lang) =>
      lang === 'en' ? `Inspection — ${titleCase(placeName(c, lang))}`
      : `${placeName(c, lang)} ${lang === 'hi' ? 'निरीक्षण' : 'तपासणी'}`,
    description: (c, lang) =>
      lang === 'en'
        ? `Inspect ${placeName(c, lang)} and report any issues.`
        : lang === 'hi'
          ? `${placeName(c, lang)} की जाँच करें और कोई समस्या हो तो रिपोर्ट करें।`
          : `${placeName(c, lang)} तपासा आणि काही समस्या असल्यास ती नोंदवा.`,
  },
  checklist: {
    title: (c, lang) =>
      lang === 'en' ? `Checklist — ${titleCase(placeName(c, lang))}`
      : `${placeName(c, lang)} ${lang === 'hi' ? 'चेकलिस्ट' : 'तपासणीसूची'}`,
    description: (c, lang) =>
      lang === 'en'
        ? `Complete the checklist for ${placeName(c, lang)}.`
        : lang === 'hi'
          ? `${placeName(c, lang)} की चेकलिस्ट पूरी करें।`
          : `${placeName(c, lang)} साठीची तपासणीसूची पूर्ण करा.`,
  },
  operations: {
    title: (c, lang) =>
      lang === 'en' ? `Operations — ${titleCase(placeName(c, lang))}`
      : `${placeName(c, lang)} ऑपरेशन्स`,
    description: (c, lang) =>
      lang === 'en'
        ? `Carry out the assigned work at ${placeName(c, lang)}.`
        : lang === 'hi'
          ? `${placeName(c, lang)} पर दिया गया कार्य करें।`
          : `${placeName(c, lang)} येथे दिलेले काम करा.`,
  },
};
// housekeeping follows the cleaning shape
TEMPLATES.housekeeping = TEMPLATES.cleaning;

function titleCase(s: string): string {
  return s.replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Resolution
// ---------------------------------------------------------------------------

export interface LocalizedTaskText {
  title: string;
  /** Localized or source description; null when the task has none. */
  description: string | null;
  /** true when any piece came from variants/templates (not source). */
  localized: boolean;
  /** true when `description` is a localized string. */
  descriptionLocalized: boolean;
}

/** Back-compat shape for existing callers/tests. */
export interface ResolvedTaskText {
  title: string;
  instructions: string | null;
  localized: boolean;
}

interface LocalizedFields {
  title_translations?: Record<string, string> | null;
  description_translations?: Record<string, string> | null;
}

const variant = (map: Record<string, string> | null | undefined, lang: LanguageCode) =>
  map?.[lang]?.trim() || null;

// Small bounded memo — language switching and list re-renders never
// recompute. Keyed on identity + language + source text.
const MAX_CACHE = 300;
const cache = new Map<string, LocalizedTaskText>();
const cacheKey = (task: Task, lang: LanguageCode) => {
  const extra = task as Task & LocalizedFields;
  // Everything compute() reads — collisions would leak another task's text.
  return `${task.id}|${lang}|${JSON.stringify({
    t: task.title,
    i: task.instructions,
    k: task.kind,
    w: task.work_type,
    c: task.category,
    r: task.room_number,
    d: task.dorm_name,
    ws: task.washroom_name,
    f: task.washroom_fixture_label,
    z: task.zone_name,
    res: task.resources?.map((r) => `${r.kind}:${r.label}`),
    tv: extra.title_translations,
    dv: extra.description_translations,
  })}`;
};

const memoized = (task: Task, lang: LanguageCode, make: () => LocalizedTaskText): LocalizedTaskText => {
  const key = cacheKey(task, lang);
  const hit = cache.get(key);
  if (hit) {
    cache.delete(key);
    cache.set(key, hit); // refresh recency
    return hit;
  }
  const val = make();
  cache.set(key, val);
  if (cache.size > MAX_CACHE) {
    const oldest = cache.keys().next().value;
    if (oldest) cache.delete(oldest);
  }
  return val;
};

const compute = (task: Task, lang: LanguageCode): LocalizedTaskText => {
  const extra = task as Task & LocalizedFields;
  const titleVariant = variant(extra.title_translations, lang);
  const descVariant = variant(extra.description_translations, lang);

  if (titleVariant || descVariant) {
    return {
      title: titleVariant ?? task.title,
      description: descVariant ?? task.instructions,
      localized: true,
      descriptionLocalized: !!descVariant,
    };
  }

  // Maintenance tickets & manual tasks keep their authored text — the
  // backend has no translations for free-form ticket/issue content.
  if (task.kind === 'maintenance') {
    return {
      title: task.title,
      description: task.instructions,
      localized: false,
      descriptionLocalized: false,
    };
  }

  const ctx = ctxFor(task);
  const shape = TEMPLATES[ctx.workType];

  // English is the source language — original strings are already correct.
  // A template only fills a missing description with structured text
  // (e.g. a grouped bed task gains the explicit "Clean beds …" sentence).
  if (lang === 'en') {
    if (!shape || task.instructions) {
      return {
        title: task.title,
        description: task.instructions,
        localized: false,
        descriptionLocalized: false,
      };
    }
    return {
      title: task.title,
      description: shape.description(ctx, 'en'),
      localized: true,
      descriptionLocalized: true,
    };
  }

  if (!shape) {
    return {
      title: task.title,
      description: task.instructions,
      localized: false,
      descriptionLocalized: false,
    };
  }
  return {
    title: shape.title(ctx, lang),
    description: shape.description(ctx, lang),
    localized: true,
    descriptionLocalized: true,
  };
};

/** The centralized task localization service. */
export const getLocalizedTask = (task: Task, lang: LanguageCode): LocalizedTaskText =>
  memoized(task, lang, () => compute(task, lang));

/**
 * Back-compat wrapper — display text for `lang`. Never returns empty
 * fields; falls back to the task's own source strings.
 */
export const resolveTaskText = (task: Task, lang: LanguageCode): ResolvedTaskText => {
  const r = getLocalizedTask(task, lang);
  return { title: r.title, instructions: r.description, localized: r.localized };
};

// ---------------------------------------------------------------------------
// Speech
// ---------------------------------------------------------------------------

/** Speech-shape templates produce complete sentences with identifiers in
 *  speakable form. Display templates are reused with speech=true. */
const speechFor = (task: Task, lang: LanguageCode): string | null => {
  if (task.kind === 'maintenance') return null;
  const ctx = ctxFor(task);
  const shape = TEMPLATES[ctx.workType];
  if (!shape) return null;
  if (ctx.kind !== 'beds' || !ctx.resources.length) return null;
  // Bed tasks: speak each identifier in its spoken form.
  if (ctx.workType === 'cleaning' || ctx.workType === 'housekeeping') {
    const list = joinLabelsForSpeech(ctx.resources.map((r) => r.label), lang);
    const place = ctx.dorm
      ? lang === 'en'
        ? `Dorm ${identifierForSpeech(ctx.dorm, lang)}`
        : `डॉर्म ${identifierForSpeech(ctx.dorm, lang)}`
      : placeName(ctx, lang);
    return lang === 'en'
      ? `Clean beds ${list} in ${place}.`
      : lang === 'hi'
        ? `${place} में बेड ${list} की सफ़ाई करें।`
        : `${place} मधील बेड ${list} स्वच्छ करा.`;
  }
  return null;
};

/**
 * Text spoken for a task in `audioLang`. Order:
 *   1. Bed/resource tasks → full sentence naming each identifier.
 *   2. Server variants / structured templates via getLocalizedTask.
 *   3. The task's own title + instructions.
 * Never returns ''.
 */
export const resolveSpeechText = (task: Task, audioLang: LanguageCode): string => {
  const spoken = speechFor(task, audioLang);
  if (spoken) return spoken;

  const { title, description, descriptionLocalized } = getLocalizedTask(
    task,
    audioLang,
  );
  // A localized description is already a complete imperative sentence —
  // speaking title+description would repeat the same instruction twice.
  if (descriptionLocalized && description) return description.trim();
  const body = description && description !== title ? `${title}. ${description}` : title;
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

/** Test seam — drop memoized resolutions. */
export const _clearTaskTextCache = (): void => cache.clear();
