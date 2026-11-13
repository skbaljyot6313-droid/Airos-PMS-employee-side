package com.airos.staff;

import android.content.BroadcastReceiver;
import android.content.BroadcastReceiver.PendingResult;
import android.content.Context;
import android.content.Intent;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * One-shot work-feed poll fired by WorkFeedPollScheduler (and re-armed
 * after every run — setAndAllowWhileIdle is a one-shot alarm).
 *
 * Runs the SAME poll the tracking service performs every 30 s, just on
 * a 30-minute cadence, so an employee with GPS tracking disabled still
 * gets OS notifications via the polling fallback. The poll no-ops
 * instantly when no credentials are stored. POST_NOTIFICATIONS and the
 * notification channel are handled inside the shared surface path.
 */
public class WorkFeedPollReceiver extends BroadcastReceiver {

    private static final ExecutorService EXEC =
            Executors.newSingleThreadExecutor();

    @Override
    public void onReceive(Context context, Intent intent) {
        // Re-arm first — a dead poll must never starve future polls.
        WorkFeedPollScheduler.schedule(context);
        // Tracking already polls every 30 s while running — skip to keep
        // this strictly a fallback for the tracking-off case.
        if (LocationTrackingService.RUNNING) return;
        PendingResult pr = goAsync();
        EXEC.execute(() -> {
            try {
                LocationTrackingService.pollOnce(context);
            } catch (Throwable ignored) {
            } finally {
                pr.finish();
            }
        });
    }
}
