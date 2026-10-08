// Release version bumper — app.json is the single authoritative source.
//
//   node scripts/bump-version.mjs <version> [latestReleasedCode]
//
// <version>            semver like 1.0.1 (required)
// [latestReleasedCode] version_code of the currently released APK, from
//                      GET /mobile/version (optional; when omitted the
//                      repo's own versionCode is used as the baseline)
//
// Writes expo.version and expo.android.versionCode = max(baseline, repo)+1
// so a production build can never ship an equal/lower versionCode.
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const appJsonPath = join(import.meta.dirname, '..', 'app.json');
const appJson = JSON.parse(readFileSync(appJsonPath, 'utf8'));

const version = process.argv[2];
const releasedCode = Number.parseInt(process.argv[3] ?? '', 10);

if (!/^\d+\.\d+\.\d+$/.test(version ?? '')) {
  console.error(`bump-version: invalid version '${version}' — expected X.Y.Z`);
  process.exit(1);
}

const repoCode = appJson.expo.android?.versionCode ?? 0;
const baseline = Math.max(repoCode, Number.isFinite(releasedCode) ? releasedCode : 0);
const nextCode = baseline + 1;

appJson.expo.version = version;
appJson.expo.android = { ...(appJson.expo.android ?? {}), versionCode: nextCode };
writeFileSync(appJsonPath, `${JSON.stringify(appJson, null, 2)}\n`);
console.log(`bump-version: version=${version} versionCode=${nextCode} (baseline ${baseline})`);
