// EAS pre-install hook: materialize the release keystore from EAS secret env
// vars so Gradle's existing keystore.properties signing config works on the
// builder. No-op locally when the secrets are absent (local devs already have
// keystore.properties on disk).
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';

const androidDir = join(import.meta.dirname, '..', 'android');
const ksB64 = process.env.AIROS_KEYSTORE_B64;
const storePassword = process.env.AIROS_KEYSTORE_PASSWORD;
const keyAlias = process.env.AIROS_KEY_ALIAS;
const keyPassword = process.env.AIROS_KEY_PASSWORD;

if (ksB64 && storePassword && keyAlias && keyPassword) {
  writeFileSync(join(androidDir, 'app', 'airos-employee-release.keystore'), Buffer.from(ksB64, 'base64'));
  writeFileSync(
    join(androidDir, 'keystore.properties'),
    `storeFile=airos-employee-release.keystore\nstorePassword=${storePassword}\nkeyAlias=${keyAlias}\nkeyPassword=${keyPassword}\n`,
  );
  console.log('eas-pre-install: release signing material written');
} else {
  console.log('eas-pre-install: no keystore env vars, skipping');
}
