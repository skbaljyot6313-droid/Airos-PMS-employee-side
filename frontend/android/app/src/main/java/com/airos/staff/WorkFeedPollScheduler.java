package com.airos.staff;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;

/**
 * Doze-friendly periodic work-feed poll — the OS-notification fallback
 * for employees whose FCM path is broken (old Google Play services,
 * aggressive OEM killers) and whose GPS tracking service is NOT running.
 *
 * FCM is the primary delivery path; this alarm only supplements it.
 * Interval is inexact-friendly (setAndAllowWhileIdle) — 30 minutes keeps
 * battery cost negligible while still catching allocations the push path
 * missed. While LocationTrackingService runs, its own 30-second poller
 * covers the same feed far faster; both dedupe on notification_uid via
 * the shared seen ledger, so overlap never double-posts.
 *
 * Scheduling requires stored credentials (plugin configure()/start()
 * writes them); a device with no session simply polls nothing — pollOnce
 * returns early without tokens.
 */
public final class WorkFeedPollScheduler {

    static final long POLL_INTERVAL_MS = 30 * 60 * 1000L; // 30 min

    private WorkFeedPollScheduler() {}

    public static void schedule(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(
                Context.ALARM_SERVICE);
        if (am == null) return;
        am.setAndAllowWhileIdle(
                AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + POLL_INTERVAL_MS,
                pendingIntent(ctx));
    }

    public static void cancel(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(
                Context.ALARM_SERVICE);
        if (am != null) am.cancel(pendingIntent(ctx));
    }

    private static PendingIntent pendingIntent(Context ctx) {
        Intent i = new Intent(ctx, WorkFeedPollReceiver.class);
        return PendingIntent.getBroadcast(ctx, 0, i,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }
}
