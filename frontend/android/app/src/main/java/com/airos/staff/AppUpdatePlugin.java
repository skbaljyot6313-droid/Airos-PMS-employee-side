package com.airos.staff;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.core.content.FileProvider;
import androidx.core.content.pm.PackageInfoCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * AiROS in-app update bridge — downloads the release APK inside the app
 * (no browser/WebView navigation) into an app-private cache dir, validates
 * it is the real com.theairco.airos.employee APK, then hands a FileProvider
 * content:// URI to Android's package installer exactly once.
 */
@CapacitorPlugin(name = "AirosUpdate")
public class AppUpdatePlugin extends Plugin {
    private static final String EXPECTED_PACKAGE = "com.theairco.airos.employee";
    private static final String PREFS = "airos_update";
    private static final String KEY_PATH = "pending_apk_path";
    private static final String KEY_CODE = "pending_apk_version_code";
    private static final String KEY_NAME = "pending_apk_version_name";
    private static final int CONNECT_TIMEOUT_MS = 30000;
    private static final int READ_TIMEOUT_MS = 60000;
    private static final int MAX_REDIRECTS = 5;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private volatile boolean downloading = false;

    private File updatesDir() {
        File dir = new File(getContext().getCacheDir(), "updates");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        return dir;
    }

    private SharedPreferences prefs() {
        return getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** Parse an APK on disk; returns null when it isn't our package. */
    private PackageInfo inspectApk(File apk) {
        try {
            PackageInfo info = getContext().getPackageManager()
                    .getPackageArchiveInfo(apk.getAbsolutePath(), 0);
            if (info == null || !EXPECTED_PACKAGE.equals(info.packageName)) {
                return null;
            }
            return info;
        } catch (Exception e) {
            return null;
        }
    }

    private void savePending(File apk, PackageInfo info) {
        prefs().edit()
                .putString(KEY_PATH, apk.getAbsolutePath())
                .putLong(KEY_CODE, PackageInfoCompat.getLongVersionCode(info))
                .putString(KEY_NAME, info.versionName)
                .apply();
    }

    private void clearPending() {
        String path = prefs().getString(KEY_PATH, null);
        if (path != null) {
            //noinspection ResultOfMethodCallIgnored
            new File(path).delete();
        }
        prefs().edit().remove(KEY_PATH).remove(KEY_CODE).remove(KEY_NAME).apply();
    }

    @PluginMethod
    public void getPendingApk(PluginCall call) {
        JSObject out = new JSObject();
        String path = prefs().getString(KEY_PATH, null);
        if (path != null) {
            File apk = new File(path);
            if (apk.exists() && apk.length() > 0) {
                PackageInfo info = inspectApk(apk);
                if (info != null) {
                    out.put("exists", true);
                    out.put("versionCode", PackageInfoCompat.getLongVersionCode(info));
                    out.put("versionName", info.versionName);
                    out.put("sizeBytes", apk.length());
                    call.resolve(out);
                    return;
                }
            }
        }
        clearPending();
        out.put("exists", false);
        call.resolve(out);
    }

    @PluginMethod
    public void canRequestPackageInstalls(PluginCall call) {
        JSObject out = new JSObject();
        out.put("allowed", Build.VERSION.SDK_INT < Build.VERSION_CODES.O
                || getContext().getPackageManager().canRequestPackageInstalls());
        call.resolve(out);
    }

    @PluginMethod
    public void openInstallPermissionSettings(PluginCall call) {
        Intent intent = new Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:" + getContext().getPackageName()));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getContext().startActivity(intent);
        call.resolve();
    }

    @PluginMethod
    public void deletePendingApk(PluginCall call) {
        clearPending();
        call.resolve();
    }

    @PluginMethod
    public void installApk(PluginCall call) {
        String path = prefs().getString(KEY_PATH, null);
        if (path == null) {
            call.reject("NO_PENDING_APK");
            return;
        }
        File apk = new File(path);
        PackageInfo info = inspectApk(apk);
        if (info == null) {
            clearPending();
            call.reject("INVALID_APK");
            return;
        }
        Uri uri = FileProvider.getUriForFile(
                getContext(),
                getContext().getPackageName() + ".fileprovider",
                apk);
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(uri, "application/vnd.android.package-archive");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        // Some OEM installers ignore FLAG_GRANT_READ_URI_PERMISSION unless
        // the URI is also attached via ClipData.
        intent.setClipData(android.content.ClipData.newRawUri("apk", uri));
        try {
            getContext().startActivity(intent);
        } catch (Exception e) {
            call.reject("INSTALL_LAUNCH_FAILED");
            return;
        }
        call.resolve();
    }

    @PluginMethod
    public void downloadApk(PluginCall call) {
        String url = call.getString("url");
        int expectedCode = call.getInt("expectedVersionCode", -1);
        if (url == null || !url.startsWith("https://")) {
            call.reject("BAD_URL");
            return;
        }
        if (downloading) {
            call.reject("ALREADY_DOWNLOADING");
            return;
        }
        downloading = true;
        executor.execute(() -> {
            File target = new File(updatesDir(), "airos-update-" + expectedCode + ".apk");
            File part = new File(updatesDir(), "airos-update.part");
            HttpURLConnection conn = null;
            try {
                String current = url;
                // Follow HTTPS redirects manually — never save a redirect body.
                for (int hops = 0; ; hops++) {
                    conn = (HttpURLConnection) new URL(current).openConnection();
                    conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
                    conn.setReadTimeout(READ_TIMEOUT_MS);
                    conn.setInstanceFollowRedirects(false);
                    // Defeat transparent gzip: a compressed Content-Length
                    // never matches decompressed bytes and APKs don't
                    // compress anyway.
                    conn.setRequestProperty("Accept-Encoding", "identity");
                    conn.setRequestProperty("User-Agent", "AiROS-Employee-Update");
                    int status = conn.getResponseCode();
                    if (status >= 300 && status < 400) {
                        String next = conn.getHeaderField("Location");
                        conn.disconnect();
                        if (next == null || hops >= MAX_REDIRECTS) {
                            call.reject("BAD_REDIRECT");
                            return;
                        }
                        // Resolve relative Locations against the current URL.
                        URL resolved = new URL(new URL(current), next);
                        if (!"https".equalsIgnoreCase(resolved.getProtocol())) {
                            call.reject("BAD_REDIRECT");
                            return;
                        }
                        current = resolved.toExternalForm();
                        continue;
                    }
                    if (status != 200) {
                        call.reject("HTTP_" + status);
                        return;
                    }
                    break;
                }

                long total = conn.getContentLengthLong();
                long received = 0;
                try (InputStream in = conn.getInputStream();
                     FileOutputStream fos = new FileOutputStream(part)) {
                    byte[] buf = new byte[64 * 1024];
                    int n;
                    long lastEmit = 0;
                    while ((n = in.read(buf)) >= 0) {
                        fos.write(buf, 0, n);
                        received += n;
                        long now = System.currentTimeMillis();
                        if (now - lastEmit > 250) {
                            lastEmit = now;
                            JSObject progress = new JSObject();
                            progress.put("received", received);
                            progress.put("total", total);
                            progress.put("percent",
                                    total > 0 ? (int) (received * 100 / total) : -1);
                            notifyListeners("downloadProgress", progress);
                        }
                    }
                }
                conn.disconnect();
                // Size is advisory — a mismatched/truncated stream is caught
                // by the ZIP magic + package-parse checks below anyway.
                if (received == 0) {
                    //noinspection ResultOfMethodCallIgnored
                    part.delete();
                    call.reject("EMPTY_DOWNLOAD");
                    return;
                }

                // ZIP/APK magic check before trusting the file.
                try (InputStream head = new java.io.FileInputStream(part)) {
                    byte[] magic = new byte[4];
                    if (head.read(magic) < 4 || magic[0] != 'P' || magic[1] != 'K') {
                        //noinspection ResultOfMethodCallIgnored
                        part.delete();
                        call.reject("NOT_AN_APK");
                        return;
                    }
                }
                //noinspection ResultOfMethodCallIgnored
                target.delete();
                //noinspection ResultOfMethodCallIgnored
                part.renameTo(target);

                PackageInfo info = inspectApk(target);
                if (info == null) {
                    //noinspection ResultOfMethodCallIgnored
                    target.delete();
                    call.reject("WRONG_PACKAGE");
                    return;
                }
                long code = PackageInfoCompat.getLongVersionCode(info);
                if (expectedCode > 0 && code != expectedCode) {
                    //noinspection ResultOfMethodCallIgnored
                    target.delete();
                    call.reject("WRONG_VERSION_CODE");
                    return;
                }
                savePending(target, info);

                JSObject progress = new JSObject();
                progress.put("received", received);
                progress.put("total", total);
                progress.put("percent", 100);
                notifyListeners("downloadProgress", progress);

                JSObject out = new JSObject();
                out.put("versionCode", code);
                out.put("versionName", info.versionName);
                out.put("sizeBytes", target.length());
                call.resolve(out);
            } catch (Exception e) {
                //noinspection ResultOfMethodCallIgnored
                part.delete();
                call.reject("DOWNLOAD_ERROR:" + e.getClass().getSimpleName());
            } finally {
                if (conn != null) conn.disconnect();
                downloading = false;
            }
        });
    }
}
