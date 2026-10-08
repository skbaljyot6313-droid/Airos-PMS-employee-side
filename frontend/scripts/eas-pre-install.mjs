// EAS pre-install hook: materialize the release keystore from EAS secret env
// vars so Gradle's existing keystore.properties signing config works on the
// builder. No-op locally when the secrets are absent (local devs already have
// keystore.properties on disk).
import { appendFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { homedir, platform } from 'node:os';

const androidDir = join(import.meta.dirname, '..', 'android');
const gradleProps = join(androidDir, 'gradle.properties');

// Capacitor 7 plugins compile with source/target 21. EAS images ship at most
// JDK 17, so provision Temurin JDK 21 and point Gradle at it via
// org.gradle.java.home (survives across build phases, unlike env vars).
if (platform() === 'linux') {
  const jdkDir = join(homedir(), 'jdk-21');
  if (!existsSync(join(jdkDir, 'bin', 'javac'))) {
    mkdirSync(jdkDir, { recursive: true });
    const tarPath = join(homedir(), 'jdk21.tar.gz');
    execFileSync('curl', [
      '-fsSL',
      'https://api.adoptium.net/v3/binary/latest/21/ga/linux/x64/jdk/hotspot/normal/eclipse',
      '-o', tarPath,
    ], { stdio: 'inherit' });
    execFileSync('tar', ['-xzf', tarPath, '-C', jdkDir, '--strip-components=1'], { stdio: 'inherit' });
  }
  appendFileSync(gradleProps, `\norg.gradle.java.home=${jdkDir}\n`);
  console.log(`eas-pre-install: Gradle JDK set to ${jdkDir}`);
}

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
