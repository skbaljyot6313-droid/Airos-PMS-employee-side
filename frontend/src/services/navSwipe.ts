/** Edge-swipe navigation gesture recognizer — pure, DOM-independent so it
 * can be unit-tested. The caller binds the returned handlers to window
 * pointer events.
 *
 * Rules:
 *  - A gesture must START inside an edge zone (left = back, right = fwd).
 *  - Vertical movement wins: as soon as |dy| > |dx| the gesture is dead.
 *  - The swipe must complete within `maxMs` and exceed `threshold`.
 *  - Gestures starting on interactive/self-gesturing elements are ignored.
 */

export interface NavSwipeCallbacks {
  onBack: () => void;
  onForward: () => void;
}

export interface SwipePoint {
  x: number;
  y: number;
  t: number;
  /** DOM target for exclusion checks — accepts null in tests. */
  target?: { closest?: (sel: string) => unknown } | null;
}

const BLOCKED_SELECTOR =
  'input,textarea,select,button,[role="button"],form,[role="status"],[data-no-nav-swipe]';

export function createEdgeSwipe(
  cb: NavSwipeCallbacks,
  opts: { edge?: number; threshold?: number; maxMs?: number; width?: () => number } = {},
) {
  const EDGE = opts.edge ?? 28;
  const THRESH = opts.threshold ?? 64;
  const MAX_MS = opts.maxMs ?? 800;
  const widthOf = opts.width ?? (() => window.innerWidth);
  let g: { x: number; y: number; t: number } | null = null;

  const down = (p: SwipePoint) => {
    const w = widthOf();
    if (p.x > EDGE && p.x < w - EDGE) { g = null; return; }
    if (p.target?.closest?.(BLOCKED_SELECTOR)) { g = null; return; }
    g = { x: p.x, y: p.y, t: p.t };
  };

  const move = (p: SwipePoint) => {
    if (g && Math.abs(p.y - g.y) > Math.abs(p.x - g.x)) g = null;
  };

  const up = (p: SwipePoint): 'back' | 'forward' | null => {
    if (!g) return null;
    const dx = p.x - g.x;
    let result: 'back' | 'forward' | null = null;
    if (p.t - g.t < MAX_MS) {
      if (g.x <= EDGE && dx > THRESH) result = 'back';
      else if (g.x >= widthOf() - EDGE && dx < -THRESH) result = 'forward';
    }
    g = null;
    if (result === 'back') cb.onBack();
    if (result === 'forward') cb.onForward();
    return result;
  };

  const cancel = () => { g = null; };

  return { down, move, up, cancel };
}
