package com.airos.staff;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;

/**
 * AirosLocation — JS bridge for the background LocationTrackingService.
 *
 * start({apiBase, accessToken, refreshToken, sessionId, intervalSeconds})
 * persists the upload config and launches the foreground service; the
 * service then runs independently of the WebView (survives UI close).
 * The JS layer owns session minting (/location/start) and stopping
 * (/location/stop) — this bridge only drives the native side.
 *
 * updateAuth({accessToken, refreshToken}) pushes fresh credentials after
 * a WebView-side token refresh; the service also self-refreshes on 401.
 */
@CapacitorPlugin(name = "AirosLocation")
public class LocationTrackerPlugin extends Plugin {

    @PluginMethod
    public void start(PluginCall call) {
        String apiBase = call.getString("apiBase");
        String accessToken = call.getString("accessToken");
        String sessionId = call.getString("sessionId");
        if (apiBase == null || accessToken == null || sessionId == null
                || !apiBase.startsWith("https://")
                && !apiBase.startsWith("http://")) {
            call.reject("INVALID_CONFIG");
            return;
        }
        SharedPreferences p = LocationTrackingService.prefs(getContext());
        String oldSession = p.getString(
                LocationTrackingService.KEY_SESSION, null);
        SharedPreferences.Editor e = p.edit()
                .putString(LocationTrackingService.KEY_API_BASE, apiBase)
                .putString(LocationTrackingService.KEY_ACCESS, accessToken)
                .putString(LocationTrackingService.KEY_REFRESH,
                        call.getString("refreshToken"))
                .putString(LocationTrackingService.KEY_SESSION, sessionId)
                .putInt(LocationTrackingService.KEY_INTERVAL,
                        call.getInt("intervalSeconds", 30))
                .remove(LocationTrackingService.KEY_LAST_ERROR);
        // New session → restart the sequence; same session (resume) keeps it.
        if (!sessionId.equals(oldSession)) {
            e.putInt(LocationTrackingService.KEY_SEQ, 0);
        }
        e.apply();

        requestNotificationPermission();
        ContextCompat.startForegroundService(
                getContext(), LocationTrackingService.startIntent(getContext()));
        call.resolve(new JSObject().put("started", true));
    }

    @PluginMethod
    public void stop(PluginCall call) {
        Intent stop = LocationTrackingService.startIntent(getContext());
        stop.setAction(LocationTrackingService.ACTION_STOP);
        getContext().startService(stop);
        // Clear the session only — credentials stay so a restart can
        // reuse them without a WebView round trip.
        LocationTrackingService.prefs(getContext()).edit()
                .remove(LocationTrackingService.KEY_SESSION)
                .apply();
        call.resolve();
    }

    @PluginMethod
    public void updateAuth(PluginCall call) {
        String access = call.getString("accessToken");
        if (access == null) {
            call.reject("INVALID_CONFIG");
            return;
        }
        SharedPreferences.Editor e =
                LocationTrackingService.prefs(getContext()).edit()
                        .putString(LocationTrackingService.KEY_ACCESS, access);
        String refresh = call.getString("refreshToken");
        if (refresh != null) {
            e.putString(LocationTrackingService.KEY_REFRESH, refresh);
        }
        e.apply();
        call.resolve();
    }

    @PluginMethod
    public void getState(PluginCall call) {
        SharedPreferences p = LocationTrackingService.prefs(getContext());
        String session = p.getString(
                LocationTrackingService.KEY_SESSION, null);
        JSObject out = new JSObject();
        out.put("running", LocationTrackingService.RUNNING);
        out.put("sessionId", session);
        out.put("sequenceNumber",
                p.getInt(LocationTrackingService.KEY_SEQ, 0));
        out.put("lastFixAt",
                p.getLong(LocationTrackingService.KEY_LAST_FIX_AT, 0));
        String err = p.getString(LocationTrackingService.KEY_LAST_ERROR, null);
        if (err != null) out.put("lastError", err);
        File queue = new File(getContext().getFilesDir(),
                "location_queue.jsonl");
        out.put("queuedCount", queue.exists() ? countLines(queue) : 0);
        call.resolve(out);
    }

    /** Battery-optimization settings — the service survives Doze better
     *  when exempted, but the exemption is the user's call (Play policy);
     *  we only open the list so they can flip it. */
    @PluginMethod
    public void openBatteryOptimizationSettings(PluginCall call) {
        Intent intent = new Intent(
                Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            getContext().startActivity(intent);
            call.resolve();
        } catch (Exception e) {
            call.reject("NOT_AVAILABLE");
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return;
        Context ctx = getContext();
        if (ActivityCompat.checkSelfPermission(ctx,
                Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED) return;
        if (getActivity() != null) {
            ActivityCompat.requestPermissions(getActivity(),
                    new String[]{Manifest.permission.POST_NOTIFICATIONS}, 0);
        }
    }

    private static int countLines(java.io.File f) {
        int n = 0;
        try (java.io.BufferedReader r =
                     new java.io.BufferedReader(new java.io.FileReader(f))) {
            while (r.readLine() != null) n++;
        } catch (Exception ignored) {
        }
        return n;
    }
}
