import React, { act } from 'react';
import TestRenderer from 'react-test-renderer';
import { describe, it, expect, vi } from 'vitest';
import '../../../i18n';
import { ResourceChips } from '../ResourceChips';
import type { TaskResource } from '../../../types';

vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);

const res = (labels: string[]): TaskResource[] =>
  labels.map((label, i) => ({ id: `b${i}`, label, kind: 'bed', status: 'cleaning' }));

const texts = (root: TestRenderer.ReactTestRenderer): string[] => {
  const out: string[] = [];
  const walk = (n: TestRenderer.ReactTestInstance) => {
    n.children.forEach((c) => {
      if (typeof c === 'string') out.push(c);
      else walk(c);
    });
  };
  walk(root.root);
  return out;
};

describe('ResourceChips', () => {
  it('renders every identifier when the list fits', async () => {
    let r!: TestRenderer.ReactTestRenderer;
    await act(async () => {
      r = TestRenderer.create(
        <ResourceChips resources={res(['P2-01', 'P2-03', 'P2-05'])} />,
      );
    });
    const all = texts(r).join(' ');
    expect(all).toContain('P2-01');
    expect(all).toContain('P2-03');
    expect(all).toContain('P2-05');
    expect(all).toContain('3 beds assigned');
  });

  it('collapses long lists behind a +N toggle, keeping all reachable', async () => {
    const labels = Array.from({ length: 12 }, (_, i) => `P2-${String(i + 1).padStart(2, '0')}`);
    let r!: TestRenderer.ReactTestRenderer;
    await act(async () => {
      r = TestRenderer.create(<ResourceChips resources={res(labels)} />);
    });
    // 12 beds > default maxVisible 6 → "+6 more" toggle.
    let all = texts(r).join(' ');
    expect(all).toContain('more');
    expect(all).not.toContain('P2-12');
    const toggle = r.root.findAllByType('button')[0];
    await act(async () => toggle.props.onClick({ stopPropagation: () => {} }));
    all = texts(r).join(' ');
    expect(all).toContain('P2-12'); // full list expanded
    expect(all).toContain('Show less');
  });

  it('dedupes repeated identifiers', async () => {
    let r!: TestRenderer.ReactTestRenderer;
    await act(async () => {
      r = TestRenderer.create(
        <ResourceChips resources={res(['P2-01', 'P2-01', 'P2-03'])} />,
      );
    });
    const all = texts(r).join(' ');
    expect(all.match(/P2-01/g)).toHaveLength(1);
    expect(all).toContain('2 beds assigned');
  });

  it('renders nothing without resources', async () => {
    let r!: TestRenderer.ReactTestRenderer;
    await act(async () => {
      r = TestRenderer.create(<ResourceChips resources={[]} />);
    });
    expect(texts(r)).toEqual([]);
  });
});
