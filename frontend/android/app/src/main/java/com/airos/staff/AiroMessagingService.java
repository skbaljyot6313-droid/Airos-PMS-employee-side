package com.airos.staff;

import androidx.annotation.NonNull;

import com.capacitorjs.plugins.pushnotifications.MessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

/**
 * FCM entry point — replaces the Capacitor plugin's MessagingService in the
 * manifest (which is why this class subclasses it: super calls still forward
 * messages and token events into the WebView unchanged).
 *
 * The backend sends DATA-ONLY messages now, so Android never displays a
 * notification on its own — every tray entry is posted here (or by the
 * work-feed poller's dead-push backstop) through the shared seen ledger in
 * LocationTrackingService.surfaceWorkNotification. That makes a swipe
 * dismissal permanent: a routine sync can never resurrect the uid.
 */
public class AiroMessagingService extends MessagingService {

    @Override
    public void onCreate() {
        super.onCreate();
        // The tracking service may never have run — the work channel
        // must exist before any FCM-surfaced tray entry is posted.
        LocationTrackingService.ensureChannels(getApplicationContext());
    }

    @Override
    public void onMessageReceived(@NonNull RemoteMessage remoteMessage) {
        // Plugin behaviour first — JS pushNotificationReceived listeners and
        // foreground handling keep working exactly as before.
        super.onMessageReceived(remoteMessage);

        Map<String, String> data = remoteMessage.getData();
        if (data == null) return;
        String uid = data.get("notification_uid");
        if (uid == null || uid.isEmpty()) return;

        LocationTrackingService.surfaceWorkNotification(
                getApplicationContext(),
                uid,
                data.getOrDefault("title", "Airco PMS"),
                data.getOrDefault("body", ""),
                data.getOrDefault("task_uid", ""),
                data.getOrDefault("ticket_uid", ""));
    }
}
