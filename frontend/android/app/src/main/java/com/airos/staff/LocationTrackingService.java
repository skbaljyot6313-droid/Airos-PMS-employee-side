package com.airos.staff;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.location.Location;
import android.location.LocationManager;
import android.os.Build;
import android.os.IBinder;
import android.os.Looper;

import androidx.core.app.ActivityCompat;
import androidx.core.app.NotificationCompat;

import com.google.android.gms.common.ConnectionResult;
import com.google.android.gms.common.GoogleApiAvailability;
import com.google.android.gms.location.FusedLocationProviderClient;
import com.google.android.gms.location.LocationCallback;
import com.google.android.gms.location.LocationRequest;
import com.google.android.gms.location.LocationResult;
import com.google.android.gms.location.LocationServices;
import com.google.android.gms.location.Priority;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * AiROS background location tracking — a location-type foreground service.
 *
 * Why native: the WebView timer dies with the UI. This service owns a
 * Fused Location Provider subscription (LocationManager fallback when Play
 * Services is absent), a persistent low-importance notification, and an
 * on-disk upload queue so fixes captured while offline are replayed —
 * ordered by captured_at — when connectivity returns.
 *
 * All durable config lives in SharedPreferences: the service can resume
 * after the OS kills/restarts it (START_STICKY) without the WebView.
 *
 * Upload semantics match LOCATION_API.md: POST {apiBase}/location/current
 * with a Bearer token, (tracking_session_id, sequence_number) idempotency,
 * INVALID_TRACKING_SESSION → mint a fresh session and continue,
 * 401 → refresh via /auth/refresh once per drain.
 */
public class LocationTrackingService extends Service {
    static final String PREFS = "airos_location_tracking";
    static final String KEY_API_BASE = "api_base";
    static final String KEY_ACCESS = "access_token";
    static final String KEY_REFRESH = "refresh_token";
    static final String KEY_SESSION = "session_id";
    static final String KEY_SEQ = "sequence_number";
    static final String KEY_INTERVAL = "interval_seconds";
    static final String KEY_LAST_ERROR = "last_error";
    static final String KEY_LAST_FIX_AT = "last_fix_at";

    static final String ACTION_STOP = "com.airos.staff.location.STOP";

    private static final String CHANNEL_ID = "airos_location";
    private static final int NOTIFICATION_ID = 0xA1;
    private static final int DEFAULT_INTERVAL_SECONDS = 30;
    private static final int HTTP_TIMEOUT_MS = 10_000;
    /** ~10 h of 30 s fixes — plenty for a shift's worst dead zone. */
    private static final int MAX_QUEUE_LINES = 1_500;
    /** Per-drain cap — a reconnect burst must not monopolise the worker. */
    private static final int MAX_FLUSH_PER_DRAIN = 100;
    private static final long REFRESH_BACKOFF_MS = 60_000;

    static volatile boolean RUNNING = false;

    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Object queueLock = new Object();
    private FusedLocationProviderClient fused;
    private LocationCallback fusedCallback;
    private LocationManager manager;
    private android.location.LocationListener managerListener;
    private volatile long lastRefreshAttempt = 0;

    public static Intent startIntent(Context ctx) {
        return new Intent(ctx, LocationTrackingService.class);
    }

    public static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }
        // A restarted (null-intent) service with no session is a zombie —
        // shut down rather than track without a backend session.
        if (prefs(this).getString(KEY_SESSION, null) == null) {
            stopSelf();
            return START_NOT_STICKY;
        }
        startForegroundCompat();
        RUNNING = true;
        startUpdates();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        stopUpdates();
        RUNNING = false;
        worker.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // ------------------------------------------------------------------
    // Notification + foreground
    // ------------------------------------------------------------------

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL_ID, "Location tracking",
                    NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("Shown while AiROS records work location.");
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(ch);
        }
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        int icon = getApplicationInfo().icon != 0
                ? getApplicationInfo().icon
                : android.R.drawable.ic_menu_mylocation;
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(icon)
                .setContentTitle("AiROS location tracking")
                .setContentText("Your work location is being recorded.")
                .setOngoing(true)
                .setContentIntent(pi)
                .setCategory(NotificationCompat.CATEGORY_SERVICE)
                .build();
    }

    private void startForegroundCompat() {
        Notification n = buildNotification();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, n,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION);
        } else {
            startForeground(NOTIFICATION_ID, n);
        }
    }

    // ------------------------------------------------------------------
    // Location subscription — fused where available, LocationManager else
    // ------------------------------------------------------------------

    @SuppressLint("MissingPermission")
    private void startUpdates() {
        SharedPreferences p = prefs(this);
        long intervalMs = Math.max(5,
                p.getInt(KEY_INTERVAL, DEFAULT_INTERVAL_SECONDS)) * 1000L;

        boolean fine = ActivityCompat.checkSelfPermission(this,
                Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED;
        boolean coarse = ActivityCompat.checkSelfPermission(this,
                Manifest.permission.ACCESS_COARSE_LOCATION)
                == PackageManager.PERMISSION_GRANTED;
        if (!fine && !coarse) {
            recordError("NO_PERMISSION");
            stopSelf();
            return;
        }

        boolean playServices = GoogleApiAvailability.getInstance()
                .isGooglePlayServicesAvailable(this)
                == ConnectionResult.SUCCESS;
        if (playServices) {
            try {
                fused = LocationServices.getFusedLocationProviderClient(this);
                LocationRequest req = new LocationRequest.Builder(
                        fine ? Priority.PRIORITY_HIGH_ACCURACY
                                : Priority.PRIORITY_BALANCED_POWER_ACCURACY,
                        intervalMs)
                        .setMinUpdateIntervalMillis(Math.min(intervalMs, 15_000L))
                        .build();
                fusedCallback = new LocationCallback() {
                    @Override
                    public void onLocationResult(LocationResult result) {
                        Location loc = result.getLastLocation();
                        if (loc != null) onFix(loc, "fused");
                    }
                };
                fused.requestLocationUpdates(
                        req, fusedCallback, Looper.getMainLooper());
                return;
            } catch (Exception ignored) {
                // fall through to LocationManager
            }
        }
        try {
            manager = (LocationManager) getSystemService(LOCATION_SERVICE);
            String provider = fine
                    && manager.isProviderEnabled(LocationManager.GPS_PROVIDER)
                    ? LocationManager.GPS_PROVIDER
                    : LocationManager.NETWORK_PROVIDER;
            managerListener = loc -> onFix(loc, provider);
            manager.requestLocationUpdates(
                    provider, intervalMs, 0f, managerListener,
                    Looper.getMainLooper());
        } catch (Exception e) {
            recordError("NO_PROVIDER");
            stopSelf();
        }
    }

    private void stopUpdates() {
        try {
            if (fused != null && fusedCallback != null) {
                fused.removeLocationUpdates(fusedCallback);
            }
            if (manager != null && managerListener != null) {
                manager.removeUpdates(managerListener);
            }
        } catch (Exception ignored) {
        }
    }

    // ------------------------------------------------------------------
    // Fix → queue → drain
    // ------------------------------------------------------------------

    private void onFix(Location loc, String source) {
        SharedPreferences p = prefs(this);
        String sid = p.getString(KEY_SESSION, null);
        if (sid == null) {
            stopSelf();
            return;
        }
        int seq = p.getInt(KEY_SEQ, 0) + 1;
        p.edit().putInt(KEY_SEQ, seq).apply();

        JSONObject fix = new JSONObject();
        try {
            fix.put("latitude", loc.getLatitude());
            fix.put("longitude", loc.getLongitude());
            fix.put("accuracy", loc.hasAccuracy() ? loc.getAccuracy() : 0);
            if (loc.hasSpeed()) fix.put("speed_mps", loc.getSpeed());
            if (loc.hasBearing()) fix.put("bearing_deg", loc.getBearing());
            if (loc.hasAltitude()) fix.put("altitude_m", loc.getAltitude());
            fix.put("captured_at", iso8601(
                    loc.getTime() > 0 ? loc.getTime()
                            : System.currentTimeMillis()));
            fix.put("tracking_session_id", sid);
            fix.put("sequence_number", seq);
            fix.put("source", source);
        } catch (JSONException e) {
            return;
        }
        enqueue(fix.toString());
        drainQueue();
    }

    private File queueFile() {
        return new File(getFilesDir(), "location_queue.jsonl");
    }

    private void enqueue(String line) {
        synchronized (queueLock) {
            try (BufferedWriter w = new BufferedWriter(
                    new FileWriter(queueFile(), true))) {
                w.write(line);
                w.newLine();
            } catch (IOException e) {
                recordError("QUEUE_WRITE");
            }
        }
    }

    private void drainQueue() {
        worker.execute(this::drainQueueSync);
    }

    private void drainQueueSync() {
        List<String> lines;
        synchronized (queueLock) {
            lines = readQueue();
            if (lines.isEmpty()) return;
        }
        int sent = 0;
        int i = 0;
        for (; i < lines.size() && sent < MAX_FLUSH_PER_DRAIN; i++) {
            if (postFix(lines.get(i))) {
                sent++;
            } else {
                break; // connectivity/auth failure — retry next fix
            }
        }
        if (sent == 0) return;
        List<String> remaining = new ArrayList<>(
                lines.subList(i, lines.size()));
        synchronized (queueLock) {
            // Anything enqueued mid-drain stays — rewrite the file.
            List<String> appended = readQueue();
            appended.removeAll(lines);
            remaining.addAll(appended);
            writeQueue(remaining);
        }
    }

    private List<String> readQueue() {
        List<String> out = new ArrayList<>();
        File f = queueFile();
        if (!f.exists()) return out;
        try (BufferedReader r = new BufferedReader(new FileReader(f))) {
            String line;
            while ((line = r.readLine()) != null) {
                if (!line.isEmpty()) out.add(line);
            }
        } catch (IOException ignored) {
        }
        // Bound the backlog — keep the NEWEST fixes if the queue explodes.
        if (out.size() > MAX_QUEUE_LINES) {
            out = new ArrayList<>(
                    out.subList(out.size() - MAX_QUEUE_LINES, out.size()));
        }
        return out;
    }

    private void writeQueue(List<String> lines) {
        File f = queueFile();
        try (BufferedWriter w = new BufferedWriter(new FileWriter(f, false))) {
            for (String l : lines) {
                w.write(l);
                w.newLine();
            }
        } catch (IOException ignored) {
        }
    }

    // ------------------------------------------------------------------
    // HTTP — ingest, session re-mint, token refresh
    // ------------------------------------------------------------------

    /** POST one queued fix. True = delivered (drop it); false = keep. */
    private boolean postFix(String line) {
        SharedPreferences p = prefs(this);
        String base = p.getString(KEY_API_BASE, null);
        String token = p.getString(KEY_ACCESS, null);
        if (base == null || token == null) {
            recordError("NO_CONFIG");
            return false;
        }
        HttpResult res = apiPost(base + "/location/current", line, token);
        if (res.status == 401 && tryRefresh(p)) {
            res = apiPost(base + "/location/current", line,
                    p.getString(KEY_ACCESS, null));
        }
        if (res.status == 400
                && "INVALID_TRACKING_SESSION".equals(res.code)) {
            // Session marker expired server-side — mint a fresh one and
            // re-point the queued fix; sequence restarts per session.
            if (remintSession(p)) {
                try {
                    JSONObject fix = new JSONObject(line);
                    fix.put("tracking_session_id",
                            p.getString(KEY_SESSION, ""));
                    fix.put("sequence_number",
                            p.getInt(KEY_SEQ, 0));
                    line = fix.toString();
                } catch (JSONException ignored) {
                }
                res = apiPost(base + "/location/current", line,
                        p.getString(KEY_ACCESS, null));
            }
        }
        if (res.ok()) {
            prefs(this).edit()
                    .putLong(KEY_LAST_FIX_AT, System.currentTimeMillis())
                    .remove(KEY_LAST_ERROR)
                    .apply();
            return true;
        }
        // 4xx contract errors won't heal by retrying — drop poison lines
        // rather than wedge the queue behind them forever.
        if (res.status >= 400 && res.status < 500
                && res.status != 401 && res.status != 429) {
            recordError("HTTP_" + res.status
                    + (res.code != null ? ":" + res.code : ""));
            return true; // consumed — skip it
        }
        recordError(res.status > 0 ? "HTTP_" + res.status : "NETWORK");
        return false;
    }

    /** Re-mint a tracking session server-side; updates prefs + seq. */
    private boolean remintSession(SharedPreferences p) {
        String base = p.getString(KEY_API_BASE, null);
        String token = p.getString(KEY_ACCESS, null);
        if (base == null || token == null) return false;
        HttpResult res = apiPost(base + "/location/start", "{}", token);
        if (res.status == 401 && tryRefresh(p)) {
            res = apiPost(base + "/location/start", "{}",
                    p.getString(KEY_ACCESS, null));
        }
        if (!res.ok()) return false;
        try {
            String sid = new JSONObject(res.body)
                    .getString("tracking_session_id");
            p.edit().putString(KEY_SESSION, sid).putInt(KEY_SEQ, 0).apply();
            return true;
        } catch (JSONException e) {
            return false;
        }
    }

    /** Refresh the access token via /auth/refresh. Throttled — a dead
     *  refresh token must not spin a request per fix. */
    private boolean tryRefresh(SharedPreferences p) {
        long now = System.currentTimeMillis();
        if (now - lastRefreshAttempt < REFRESH_BACKOFF_MS) return false;
        lastRefreshAttempt = now;
        String base = p.getString(KEY_API_BASE, null);
        String refresh = p.getString(KEY_REFRESH, null);
        if (base == null || refresh == null) return false;
        HttpResult res;
        try {
            JSONObject body = new JSONObject();
            body.put("refresh_token", refresh);
            res = apiPost(base + "/auth/refresh", body.toString(), null);
        } catch (JSONException e) {
            return false;
        }
        if (!res.ok()) {
            if (res.status == 401 || res.status == 403) {
                // Refresh is dead — uploads will keep failing until the
                // WebView pushes fresh credentials via updateAuth.
                recordError("AUTH_EXPIRED");
            }
            return false;
        }
        try {
            String access = new JSONObject(res.body)
                    .getString("access_token");
            p.edit().putString(KEY_ACCESS, access).apply();
            return true;
        } catch (JSONException e) {
            return false;
        }
    }

    private static class HttpResult {
        final int status;
        final String body;
        final String code;

        HttpResult(int status, String body) {
            this.status = status;
            this.body = body;
            String c = null;
            try {
                JSONObject err = new JSONObject(body)
                        .optJSONObject("error");
                if (err != null) c = err.optString("code", null);
            } catch (JSONException ignored) {
            }
            this.code = c;
        }

        boolean ok() {
            return status >= 200 && status < 300;
        }
    }

    /** Bare HttpURLConnection POST — JSON in, status+body out. Never throws. */
    private static HttpResult apiPost(String url, String json, String bearer) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setConnectTimeout(HTTP_TIMEOUT_MS);
            conn.setReadTimeout(HTTP_TIMEOUT_MS);
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Accept-Encoding", "identity");
            if (bearer != null) {
                conn.setRequestProperty("Authorization", "Bearer " + bearer);
            }
            conn.setDoOutput(true);
            byte[] payload = json.getBytes(StandardCharsets.UTF_8);
            conn.setFixedLengthStreamingMode(payload.length);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(payload);
            }
            int status = conn.getResponseCode();
            InputStream in = status < 400
                    ? conn.getInputStream() : conn.getErrorStream();
            StringBuilder sb = new StringBuilder();
            if (in != null) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) >= 0) {
                    sb.append(new String(buf, 0, n, StandardCharsets.UTF_8));
                }
                in.close();
            }
            return new HttpResult(status, sb.toString());
        } catch (Exception e) {
            return new HttpResult(-1, "");
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private void recordError(String err) {
        prefs(this).edit().putString(KEY_LAST_ERROR, err).apply();
    }

    private static String iso8601(long epochMs) {
        SimpleDateFormat f = new SimpleDateFormat(
                "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        f.setTimeZone(TimeZone.getTimeZone("UTC"));
        return f.format(new Date(epochMs));
    }
}
