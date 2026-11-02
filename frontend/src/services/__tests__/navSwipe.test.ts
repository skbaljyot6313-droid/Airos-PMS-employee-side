import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createEdgeSwipe } from '../navSwipe';

const W = 400; // fake viewport width
const mk = (calls: { back?: () => void; fwd?: () => void } = {}) => ({
  onBack: vi.fn(calls.back),
  onForward: vi.fn(calls.fwd),
});
const mkSwipe = () => createEdgeSwipe(cb, { width: () => W });
let cb = mk();

const down = (x: number, y = 100, t = 0, target: object | null = null) =>
  ({ x, y, t, target });
const up = down;

describe('createEdgeSwipe', () => {
  beforeEach(() => { cb = mk(); });

  it('left-edge rightward swipe fires onBack', () => {
    const s = mkSwipe();
    s.down(down(10)); s.up(up(90));
    expect(cb.onBack).toHaveBeenCalledTimes(1);
    expect(cb.onForward).not.toHaveBeenCalled();
  });

  it('right-edge leftward swipe fires onForward', () => {
    const s = mkSwipe();
    s.down(down(395)); s.up(up(320));
    expect(cb.onForward).toHaveBeenCalledTimes(1);
    expect(cb.onBack).not.toHaveBeenCalled();
  });

  it('ignores swipes that start mid-screen', () => {
    const s = mkSwipe();
    s.down(down(200)); s.up(up(320));
    expect(cb.onBack).not.toHaveBeenCalled();
    expect(cb.onForward).not.toHaveBeenCalled();
  });

  it('short drags below threshold do nothing', () => {
    const s = mkSwipe();
    s.down(down(10)); s.up(up(40));
    expect(cb.onBack).not.toHaveBeenCalled();
  });

  it('vertical-dominant movement cancels the gesture', () => {
    const s = mkSwipe();
    s.down(down(10, 0));
    s.move({ x: 20, y: 80, t: 5 });
    s.up(up(100, 90));
    expect(cb.onBack).not.toHaveBeenCalled();
  });

  it('slow gestures over the time cap are ignored', () => {
    const s = mkSwipe();
    s.down(down(10, 100, 0)); s.up(up(90, 100, 2000));
    expect(cb.onBack).not.toHaveBeenCalled();
  });

  it('blocked targets (input/button/toast) never start a gesture', () => {
    const blocked = { closest: () => ({}) };
    const s = mkSwipe();
    s.down(down(10, 100, 0, blocked)); s.up(up(90, 100, 10));
    expect(cb.onBack).not.toHaveBeenCalled();
  });

  it('back at empty history and forward at empty history are safe no-ops upstream', () => {
    // createEdgeSwipe only fires the callback — upstream guards handle
    // empty stacks; here we just confirm exactly one fire per gesture.
    const s = mkSwipe();
    s.down(down(10)); s.up(up(90));
    s.down(down(395)); s.up(up(300));
    expect(cb.onBack).toHaveBeenCalledTimes(1);
    expect(cb.onForward).toHaveBeenCalledTimes(1);
  });
});
