/**
 * Android release build — web bundle (production env) + signed APK/AAB.
 *
 * Steps:
 *   1. `vite build` — picks up frontend/.env.production (VITE_API_URL → Railway)
 *   2. Temporarily strips `server.url` from capacitor.config.json so the
 *      release bundles dist/ instead of live-loading the dev server
 *   3. `cap sync android` — copies dist + prod config into the Android project
 *   4. `gradlew assembleRelease bundleRelease` — signed by
 *      android/keystore.properties (gitignored)
 *   5. Restores capacitor.config.json
 *
 * Run from frontend/:  node scripts/build-android-release.mjs
 * Requires: JDK 21 (JAVA_HOME / ANDROID_JAVA_HOME / ~/.jdks/jdk-21*),
 *           Android SDK (local.properties sdk.dir), keystore.properties.
 */
import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ANDROID = path.join(FRONTEND, 'android');
const CONFIG = path.join(FRONTEND, 'capacitor.config.json');
const isWin = process.platform === 'win32';
const gradlew = path.join(ANDROID, isWin ? 'gradlew.bat' : 'gradlew');

function run(cmd, cwd) {
  execSync(cmd, { cwd, stdio: 'inherit', env: process.env, shell: true });
}

// JDK 21 resolution — gradle needs Java 21; a JAVA_HOME pointing at an
// older JDK must be overridden (same discovery order as main.py).
function javaMajor(home) {
  try {
    const out = execSync(`"${path.join(home, 'bin', 'java')}" -version 2>&1`, { encoding: 'utf8' });
    const m = out.match(/version "(\d+)/);
    return m ? Number(m[1]) : 0;
  } catch {
    return 0;
  }
}
const jdks = path.join(process.env.USERPROFILE || process.env.HOME || '', '.jdks');
const jdksJdk21 = fs.existsSync(jdks)
  ? fs.readdirSync(jdks).map((d) => path.join(jdks, d)).find((d) => d.includes('jdk-21'))
  : null;
const candidates = [process.env.ANDROID_JAVA_HOME, jdksJdk21, process.env.JAVA_HOME].filter(Boolean);
const jdk21 = candidates.find((c) => javaMajor(c) >= 21);
if (!jdk21) {
  console.error('No JDK 21+ found — set JAVA_HOME or ANDROID_JAVA_HOME');
  process.exit(1);
}
process.env.JAVA_HOME = jdk21;
console.log(`==> JDK: ${jdk21}`);

const originalConfig = fs.readFileSync(CONFIG, 'utf8');
try {
  console.log('==> vite build (production env)');
  run('npm run build', FRONTEND);

  const cfg = JSON.parse(originalConfig);
  delete cfg.server; // release must bundle dist/, never the dev server
  fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2));

  console.log('==> cap sync android');
  run('npx cap sync android', FRONTEND);

  console.log('==> gradle assembleRelease + bundleRelease');
  run(`"${gradlew}" assembleRelease bundleRelease`, ANDROID);

  const apk = path.join(ANDROID, 'app/build/outputs/apk/release/app-release.apk');
  const aab = path.join(ANDROID, 'app/build/outputs/bundle/release/app-release.aab');
  console.log(`APK: ${apk}`);
  console.log(`AAB: ${aab}`);
} finally {
  fs.writeFileSync(CONFIG, originalConfig);
}
