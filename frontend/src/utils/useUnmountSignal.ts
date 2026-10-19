/**
 * Unmount-scoped AbortSignal — screens pass it to detail fetches so a
 * navigation away cancels in-flight requests instead of dead-setting
 * state. List fetches deliberately go through the shared swr/dataCache
 * layer instead (one screen must not cancel a request another screen is
 * waiting on); callers filter the {status:0,code:'CANCELLED'} error.
 */

import { useEffect, useRef } from 'react';

export function useUnmountSignal(): AbortSignal {
  const controllerRef = useRef<AbortController>(new AbortController());
  useEffect(
    () => () => controllerRef.current.abort(),
    []
  );
  return controllerRef.current.signal;
}
