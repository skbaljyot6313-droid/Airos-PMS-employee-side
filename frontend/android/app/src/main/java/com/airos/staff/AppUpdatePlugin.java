package com.airos.staff;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

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
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
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
    private static final String TAG = "AirosUpdate";
    private static final String EXPECTED_PACKAGE = "com.theairco.airos.employee";
    private static final String PREFS = "airos_update";
    private static final String KEY_PATH = "pending_apk_path";
    private static final String KEY_CODE = "pending_apk_version_code";
    private static final String KEY_NAME = "pending_apk_version_name";
    private static final int CONNECT_TIMEOUT_MS = 30000;
    private static final int READ_TIMEOUT_MS = 60000;
    private static final int MAX_REDIRECTS = 5;
    /** The APK may only come from Expo's artifact hosts or our own
     *  release storage/API — the backend URL is treated as untrusted
     *  input until it lands on one of these. The APK signature and
     *  versionCode checks below remain the real install gates. */
    private static final Set<String> TRUSTED_HOSTS = new HashSet<>(Arrays.asList(
            "expo.dev", "eascdn.net", "storage.googleapis.com",
            "supabase.co", "up.railway.app"));

    /** Every rejection is logged to logcat — the JS layer only ever sees
     *  the code, so without this a failed download is undiagnosable. */
    private static void deny(PluginCall call, String code) {
        Log.w(TAG, "update request rejected: " + code);
        call.reject(code);
    }

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

    private static boolean trustedHost(String urlStr) {
        try {
            String host = new URL(urlStr).getHost();
            if (host == null) return false;
            host = host.toLowerCase(Locale.US);
            for (String h : TRUSTED_HOSTS) {
                if (host.equals(h) || host.endsWith("." + h)) return true;
            }
            return false;
        } catch (Exception e) {
            return false;
        }
    }

    /** Our own installed versionCode — the downloaded APK must exceed it. */
    private long installedCode() {
        try {
            PackageInfo info = getContext().getPackageManager()
                    .getPackageInfo(getContext().getPackageName(), 0);
            return PackageInfoCompat.getLongVersionCode(info);
        } catch (Exception e) {
            return -1;
        }
    }

    /** Keep at most one pending update — wipe anything else in updates/. */
    private void cleanStale() {
        String keep = prefs().getString(KEY_PATH, null);
        File[] files = updatesDir().listFiles();
        if (files == null) return;
        for (File f : files) {
            if (keep == null || !f.getAbsolutePath().equals(keep)) {
                //noinspection ResultOfMethodCallIgnored
                f.delete();
            }
        }
    }

    /** True when the APK is signed by the same certificate as the
     *  installed app. A signature mismatch makes Android reject the
     *  install silently, so such files are worthless — callers must
     *  drop them and re-download instead of retrying forever. */
    private boolean signatureMatchesInstalled(PackageInfo apkInfo) {
        try {
            PackageInfo installed;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                installed = getContext().getPackageManager().getPackageInfo(
                        getContext().getPackageName(),
                        PackageManager.GET_SIGNING_CERTIFICATES);
                if (installed.signingInfo == null || apkInfo.signingInfo == null) {
                    return false;
                }
                android.content.pm.Signature[] a =
                        installed.signingInfo.getApkContentsSigners();
                android.content.pm.Signature[] b =
                        apkInfo.signingInfo.getApkContentsSigners();
                return a != null && b != null
                        && a.length == b.length && a.length > 0
                        && a[0].equals(b[0]);
            }
            installed = getContext().getPackageManager().getPackageInfo(
                    getContext().getPackageName(), PackageManager.GET_SIGNATURES);
            return installed.signatures != null && apkInfo.signatures != null
                    && installed.signatures.length > 0
                    && installed.signatures[0].equals(apkInfo.signatures[0]);
        } catch (Exception e) {
            return false;
        }
    }

    /** Parse an APK on disk; returns null when it isn't our package. */
    private PackageInfo inspectApk(File apk) {
        try {
            int flags = Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
                    ? PackageManager.GET_SIGNING_CERTIFICATES
                    : PackageManager.GET_SIGNATURES;
            PackageInfo info = getContext().getPackageManager()
                    .getPackageArchiveInfo(apk.getAbsolutePath(), flags);
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
                if (info != null && !signatureMatchesInstalled(info)) {
                    Log.w(TAG, "pending APK signer differs from installed app — dropping");
                    clearPending();
                    out.put("exists", false);
                    call.resolve(out);
                    return;
                }
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
            deny(call,"NO_PENDING_APK");
            return;
        }
        File apk = new File(path);
        PackageInfo info = inspectApk(apk);
        if (info == null) {
            clearPending();
            deny(call,"INVALID_APK");
            return;
        }
        if (!signatureMatchesInstalled(info)) {
            clearPending();
            deny(call,"SIGNATURE_MISMATCH");
            return;
        }
        long installed = installedCode();
        if (installed > 0
                && PackageInfoCompat.getLongVersionCode(info) <= installed) {
            clearPending();
            deny(call,"NOT_AN_UPGRADE");
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
            deny(call,"INSTALL_LAUNCH_FAILED");
            return;
        }
        call.resolve();
    }

    @PluginMethod
    public void downloadApk(PluginCall call) {
        String url = call.getString("url");
        int expectedCode = call.getInt("expectedVersionCode", -1);
        if (url == null || !url.startsWith("https://") || !trustedHost(url)) {
            deny(call,"UNTRUSTED_URL");
            return;
        }
        if (downloading) {
            deny(call,"ALREADY_DOWNLOADING");
            return;
        }
        downloading = true;
        executor.execute(() -> {
            cleanStale();
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
                            deny(call,"BAD_REDIRECT");
                            return;
                        }
                        // Resolve relative Locations against the current URL.
                        URL resolved = new URL(new URL(current), next);
                        if (!"https".equalsIgnoreCase(resolved.getProtocol())
                                || !trustedHost(resolved.toExternalForm())) {
                            deny(call,"UNTRUSTED_REDIRECT");
                            return;
                        }
                        current = resolved.toExternalForm();
                        continue;
                    }
                    if (status != 200) {
                        deny(call,"HTTP_" + status);
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
                    deny(call,"EMPTY_DOWNLOAD");
                    return;
                }

                // ZIP/APK magic check before trusting the file.
                try (InputStream head = new java.io.FileInputStream(part)) {
                    byte[] magic = new byte[4];
                    if (head.read(magic) < 4 || magic[0] != 'P' || magic[1] != 'K') {
                        //noinspection ResultOfMethodCallIgnored
                        part.delete();
                        deny(call,"NOT_AN_APK");
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
                    deny(call,"WRONG_PACKAGE");
                    return;
                }
                if (!signatureMatchesInstalled(info)) {
                    //noinspection ResultOfMethodCallIgnored
                    target.delete();
                    deny(call,"WRONG_SIGNATURE");
                    return;
                }
                long code = PackageInfoCompat.getLongVersionCode(info);
                if (expectedCode > 0 && code != expectedCode) {
                    //noinspection ResultOfMethodCallIgnored
                    target.delete();
                    deny(call,"WRONG_VERSION_CODE");
                    return;
                }
                // Downgrade guard — never install a build that isn't newer.
                long installed = installedCode();
                if (installed > 0 && code <= installed) {
                    //noinspection ResultOfMethodCallIgnored
                    target.delete();
                    deny(call,"NOT_AN_UPGRADE");
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
                deny(call,"DOWNLOAD_ERROR:" + e.getClass().getSimpleName());
            } finally {
                if (conn != null) conn.disconnect();
                downloading = false;
            }
        });
    }
}
