import React, { act } from 'react';
import TestRenderer from 'react-test-renderer';
import { afterEach, expect, it, vi } from 'vitest';

const { fetchTasks, realtime } = vi.hoisted(() => ({
  fetchTasks: vi.fn(),
  realtime: { callback: (() => {}) as () => void },
}));

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({ employee: { id: 'employee-1', name: 'Worker' }, company: null }),
}));
vi.mock('../tasks', () => ({ fetchTasksApi: fetchTasks, taskBucket: () => 'to_do' }));
vi.mock('../../services/realtime', () => ({
  subscribeRealtimeEvents: (_prefixes: string[], callback: () => void) => {
    realtime.callback = callback;
    return () => {};
  },
}));
vi.mock('../../utils/perf', () => ({ perfMarkOnce: vi.fn() }));

import { TasksScreen } from '../../screens/employee/TasksScreen';

let renderer: TestRenderer.ReactTestRenderer | undefined;

afterEach(async () => {
  await act(async () => renderer?.unmount());
  renderer = undefined;
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

it('coalesces refresh bursts without losing an invalidation during an active load', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  let finishFirst!: (tasks: []) => void;
  fetchTasks.mockReturnValueOnce(new Promise<[]>((resolve) => { finishFirst = resolve; }))
    .mockResolvedValue([]);
  await act(async () => {
    renderer = TestRenderer.create(<TasksScreen onSelectTask={() => {}} />);
  });
  expect(fetchTasks).toHaveBeenCalledTimes(1);
  await act(async () => {
    realtime.callback();
    realtime.callback();
    realtime.callback();
  });
  expect(fetchTasks).toHaveBeenCalledTimes(1);
  await act(async () => finishFirst([]));
  expect(fetchTasks).toHaveBeenCalledTimes(2);
  await act(async () => realtime.callback());
  expect(fetchTasks).toHaveBeenCalledTimes(3);
});

it('does not replay pending refresh work after the screen unmounts', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  let finish!: (tasks: []) => void;
  fetchTasks.mockReturnValueOnce(new Promise<[]>((resolve) => { finish = resolve; }));
  await act(async () => {
    renderer = TestRenderer.create(<TasksScreen onSelectTask={() => {}} />);
  });
  await act(async () => realtime.callback());
  await act(async () => renderer?.unmount());
  renderer = undefined;
  await act(async () => finish([]));
  expect(fetchTasks).toHaveBeenCalledTimes(1);
});
