import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { Task, TaskBucket } from '../../types';
import { fetchTasksApi, taskBucket } from '../../api/tasks';
import { errorMessage } from '../../api/client';
import { TaskCard } from '../../components/tasks/TaskCard';
import { EmptyState, ErrorState, LoadingState } from '../../components/common/FeedbackStates';
import { RefreshCw, MapPin, Building2 } from 'lucide-react';

interface TasksScreenProps {
  onSelectTask: (taskId: string) => void;
  onTasksCountChange?: (count: number) => void;
}

export const TasksScreen: React.FC<TasksScreenProps> = ({ onSelectTask, onTasksCountChange }) => {
  const { employee, company } = useAuth();
  const [activeBucket, setActiveBucket] = useState<TaskBucket>('to_do');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const loadTasks = useCallback(async (isRefresh = false) => {
    try {
      if (isRefresh) setRefreshing(true);
      else setLoading(true);
      setError(null);

      // Fetch all tasks for current employee
      const data = await fetchTasksApi();
      setTasks(data);

      const todoCount = data.filter((t) => taskBucket(t.status) === 'to_do').length;
      if (onTasksCountChange) {
        onTasksCountChange(todoCount);
      }
    } catch (err: unknown) {
      setError(errorMessage(err, 'Unable to load your operational tasks.'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [onTasksCountChange]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  // Filter tasks into the active bucket
  const filteredTasks = tasks.filter((t) => taskBucket(t.status) === activeBucket);

  const todoCount = tasks.filter((t) => taskBucket(t.status) === 'to_do').length;
  const inReviewCount = tasks.filter((t) => taskBucket(t.status) === 'in_review').length;
  const doneCount = tasks.filter((t) => taskBucket(t.status) === 'done').length;

  // Greeting based on current time
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const firstName = employee?.name ? employee.name.split(' ')[0] : 'Staff';

  return (
    <div className="flex-1 flex flex-col bg-[#F7F8F6] overflow-y-auto">
      {/* Top Staff Header */}
      <div className="bg-white border-b border-[#E4E8E6] px-5 pt-4 pb-3 sticky top-0 z-20 shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
        <div className="flex items-start justify-between gap-3 mb-2">
          <div>
            <span className="text-xs font-semibold text-[#667174] uppercase tracking-wider block">
              {greeting}, {firstName}
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-[#20292C] font-['Space_Grotesk']">
              Your Tasks
            </h1>
          </div>

          <button
            onClick={() => loadTasks(true)}
            disabled={refreshing}
            className="p-2.5 rounded-xl border border-[#E4E8E6] bg-[#F7F8F6] text-[#20292C] hover:bg-[#EFEFEF] active:scale-95 transition-all"
            aria-label="Refresh tasks"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-[#33B059]' : 'text-[#667174]'}`} />
          </button>
        </div>

        {/* Workplace Coverage Chip */}
        <div className="flex items-center gap-2 text-[11px] text-[#667174] bg-[#F7F8F6] px-3 py-1.5 rounded-lg border border-[#E4E8E6] mb-3">
          <Building2 className="w-3.5 h-3.5 text-[#8D999C] flex-shrink-0" />
          <span className="font-medium text-[#20292C] truncate">
            {company?.brand_name || company?.name || 'Company'}
          </span>
          <span className="text-[#8D999C]">·</span>
          <MapPin className="w-3.5 h-3.5 text-[#8D999C] flex-shrink-0" />
          <span className="truncate">
            {employee?.zone_name || 'Zone not assigned'}
          </span>
        </div>

        {/* 3 High-Level Buckets */}
        <div className="flex items-center gap-2 bg-[#F0F2F1] p-1 rounded-xl">
          <button
            onClick={() => setActiveBucket('to_do')}
            className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${
              activeBucket === 'to_do'
                ? 'bg-white text-[#20292C] shadow-sm'
                : 'text-[#667174] hover:text-[#20292C]'
            }`}
          >
            <span>To Do</span>
            <span
              className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                activeBucket === 'to_do'
                  ? 'bg-[#33B059] text-white'
                  : 'bg-[#E4E8E6] text-[#667174]'
              }`}
            >
              {todoCount}
            </span>
          </button>

          <button
            onClick={() => setActiveBucket('in_review')}
            className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${
              activeBucket === 'in_review'
                ? 'bg-white text-[#20292C] shadow-sm'
                : 'text-[#667174] hover:text-[#20292C]'
            }`}
          >
            <span>In Review</span>
            {inReviewCount > 0 && (
              <span
                className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                  activeBucket === 'in_review'
                    ? 'bg-[#2B5DD8] text-white'
                    : 'bg-[#E4E8E6] text-[#667174]'
                }`}
              >
                {inReviewCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveBucket('done')}
            className={`flex-1 py-1.5 px-2 rounded-lg text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${
              activeBucket === 'done'
                ? 'bg-white text-[#20292C] shadow-sm'
                : 'text-[#667174] hover:text-[#20292C]'
            }`}
          >
            <span>Completed</span>
            {doneCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.2 rounded-full font-bold bg-[#E4E8E6] text-[#667174]">
                {doneCount}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Task List Content */}
      <div className="flex-1 p-4">
        {loading ? (
          <LoadingState message="Loading your assigned tasks..." />
        ) : error ? (
          <ErrorState message={error} onRetry={() => loadTasks(false)} />
        ) : filteredTasks.length === 0 ? (
          <EmptyState
            type="tasks"
            title={
              activeBucket === 'to_do'
                ? 'No tasks right now'
                : activeBucket === 'in_review'
                ? 'No tasks in review'
                : 'No completed tasks'
            }
            description={
              activeBucket === 'to_do'
                ? "You're all caught up with your assigned work for this shift."
                : activeBucket === 'in_review'
                ? 'Tasks submitted for supervisor approval will appear here.'
                : 'Finished and approved tasks will be recorded here.'
            }
            actionLabel="Refresh list"
            onAction={() => loadTasks(true)}
          />
        ) : (
          <div className="space-y-3 pb-8">
            {filteredTasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onClick={() => onSelectTask(task.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
