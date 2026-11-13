package com.airos.staff;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Re-arms the periodic work-feed poll after device reboot — alarms do
 * not survive a restart. GPS tracking itself intentionally does NOT
 * restart here (session semantics are owned by the app/login flow);
 * the notification poll is independent of it by design.
 */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null
                || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            return;
        }
        WorkFeedPollScheduler.schedule(context);
    }
}
