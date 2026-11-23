/**
 * Airco PMS Staff — Design Tokens
 * Follows enterprise SaaS + operational clarity principles
 */

export const colors = {
  // Primary operational green
  primary: '#800020',
  primaryDark: '#800020',
  primaryLight: '#F7E9EE',
  primaryMuted: '#D0EED9',

  // Dark palette
  dark: '#0D1C42',
  deepBackground: '#121517',
  secondaryDark: '#0F171A',
  softDark: '#151314',

  // Surfaces & text (light surface preference)
  background: '#FFFCFA',
  surface: '#FFFFFF',
  surfaceSubtle: '#F6F4F2',
  textPrimary: '#0D1C42',
  textSecondary: '#667085',
  textMuted: '#98A2B3',
  border: '#E7E5E4',
  borderDark: '#CDC9C7',

  // Functional semantics
  success: '#16865B',
  successLight: '#F7E9EE',
  warning: '#D89B28',
  warningLight: '#FDF3E2',
  error: '#D64545',
  errorLight: '#FAEBEB',
  info: '#4D7CFE',
  infoLight: '#EAF1FB',

  // Overdue
  overdue: '#D64545',
  overdueBg: '#FFF1F0',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
  huge: 40,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  pill: 9999,
} as const;

export const typography = {
  fontFamily: '"Space Grotesk", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  fontFamilyMono: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
  sizes: {
    tiny: '11px',
    secondary: '13px',
    body: '14px',
    cardTitle: '16px',
    sectionTitle: '18px',
    screenTitle: '26px',
  },
} as const;
