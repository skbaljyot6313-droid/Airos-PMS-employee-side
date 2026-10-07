/**
 * AiROS Staff — Design Tokens
 * Follows enterprise SaaS + operational clarity principles
 */

export const colors = {
  // Primary operational green
  primary: '#33B059',
  primaryDark: '#278B46',
  primaryLight: '#E8F7ED',
  primaryMuted: '#D0EED9',

  // Dark palette
  dark: '#20292C',
  deepBackground: '#121517',
  secondaryDark: '#0F171A',
  softDark: '#151314',

  // Surfaces & text (light surface preference)
  background: '#F7F8F6',
  surface: '#FFFFFF',
  surfaceSubtle: '#F0F2F1',
  textPrimary: '#20292C',
  textSecondary: '#667174',
  textMuted: '#8D999C',
  border: '#E4E8E6',
  borderDark: '#D2D8D6',

  // Functional semantics
  success: '#33B059',
  successLight: '#E8F7ED',
  warning: '#D89B28',
  warningLight: '#FDF6E8',
  error: '#D9534F',
  errorLight: '#FCEBEA',
  info: '#4D7CFE',
  infoLight: '#EEF3FF',

  // Overdue
  overdue: '#D9534F',
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
