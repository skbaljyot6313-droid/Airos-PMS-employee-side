import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TaskResource } from '../../types';

/**
 * Compact resource-identity chips — "P2-01 … P2-10" — for grouped tasks.
 * The complete identifier list is always reachable: ≤ `maxVisible` render
 * inline; beyond that the row collapses to `maxVisible` + a "+N" toggle
 * that expands in place. Order comes from the backend (natural sort);
 * labels are deduped by id/label and never rewritten or truncated.
 */
interface ResourceChipsProps {
  resources: TaskResource[];
  maxVisible?: number;
}

export const ResourceChips: React.FC<ResourceChipsProps> = ({
  resources,
  maxVisible = 6,
}) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const unique = resources.filter(
    (r, i) => resources.findIndex((o) => o.id === r.id || o.label === r.label) === i,
  );
  if (!unique.length) return null;

  const overflow = unique.length - maxVisible;
  const collapsed = overflow > 0 && !expanded;
  const shown = collapsed ? unique.slice(0, maxVisible) : unique;
  const kind = unique[0].kind;

  return (
    <div className="mb-1.5" onClick={(e) => e.stopPropagation()}>
      <div className="text-[10px] font-medium text-mute mb-1">
        {t(`tasks.resources.${kind}`, { count: unique.length })}
      </div>
      <div className="flex flex-wrap gap-1">
        {shown.map((r) => (
          <span
            key={`${r.kind}-${r.id || r.label}`}
            className="inline-flex items-center px-1.5 py-0.5 rounded-md bg-soft border border-line text-[11px] font-medium text-ink/80 whitespace-nowrap"
          >
            {r.label}
          </span>
        ))}
        {collapsed && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(true);
            }}
            aria-expanded="false"
            className="inline-flex items-center px-1.5 py-0.5 rounded-md bg-[#E8F7ED] text-[11px] font-semibold text-[#33B059]"
          >
            +{overflow} {t('tasks.resources.more')}
          </button>
        )}
        {expanded && overflow > 0 && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(false);
            }}
            aria-expanded="true"
            className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[11px] font-medium text-mute hover:text-sub"
          >
            {t('tasks.resources.less')}
          </button>
        )}
      </div>
    </div>
  );
};
