// Android architecture plugin — FINAL (v0.5.0).
//
// ROOT CAUSE (diagnosis closed after the v0.4.1–v0.4.9 builds):
//   On the user's Tecno Spark Slim (Android 15 / HiOS 15, ROM
//   AP5A.240905.015.A2) the app crashed with
//   `signal 11 (SIGSEGV), code 2 (SEGV_ACCERR)` on a React Native
//   thread-pool thread (e.g. pool-3-thread-1) inside the New Architecture
//   (Fabric/JSI) native layer, on Android 15's ART UFFD
//   (userfaultfd-based) GC memory-protection path (v0.4.7 stack showed
//   art::Thread::CreateCallbackWithUffdGc). SEGV_ACCERR = a mapped page
//   whose permissions UFFD protected — a ROM vs. RN New Architecture
//   collision, NOT a 16KB-page issue (on-device page size is 4096) and
//   NOT a JS bug.
//
// THE FIX (verified on-device in v0.4.9):
//   Disable the New Architecture (newArchEnabled=false). With the old
//   (legacy) architecture the app boots, JS runs, the UI renders and the
//   process stays alive. Only that one setting changed between the
//   crashing builds and the working build.
//
// This plugin now applies exactly two gradle.properties mods:
//   1. newArchEnabled=false — the crash fix (final).
//   2. android.targetSdkVersion=34 — app.json's key is silently ignored
//      by Expo SDK 54 prebuild; the Expo gradle plugin only reads this
//      property from android/gradle.properties.
//
// All v0.4.x diagnostic machinery (startup dialogs, logcat capture,
// crash-catcher ContentProvider, custom MainActivity) has been REMOVED —
// the diagnosis is closed. A silent JS-side crash journal/gate
// (src/crashjournal.ts + src/crashgate.tsx, unchanged) still renders a
// screenshot-able screen ONLY if a session ever dies without a clean exit.

const path = require("path");
const { withDangerousMod } = require("expo/config-plugins");

function withTargetSdk34(config) {
  return withDangerousMod(config, [
    "android",
    async (modConfig) => {
      const fs = require("fs");
      const projectRoot =
        (modConfig.modRequest && modConfig.modRequest.projectRoot) ||
        modConfig._internal.projectRoot;
      const gradlePropsPath = path.join(
        projectRoot,
        "android",
        "gradle.properties"
      );
      if (fs.existsSync(gradlePropsPath)) {
        let content = fs.readFileSync(gradlePropsPath, "utf8");
        if (!/android\.targetSdkVersion=/.test(content)) {
          content +=
            "\n# TradeGuard: Expo SDK 54 ignores app.json targetSdkVersion;\n" +
            "# the Expo gradle plugin reads this property instead. See v0.4.7.\n" +
            "android.targetSdkVersion=34\n";
          fs.writeFileSync(gradlePropsPath, content);
          console.log("[tradeguard] android.targetSdkVersion=34 written to gradle.properties");
        } else {
          console.log("[tradeguard] android.targetSdkVersion already present in gradle.properties");
        }
      } else {
        console.warn(
          "[tradeguard] android/gradle.properties not found; targetSdk override skipped"
        );
      }
      return modConfig;
    },
  ]);
}

function withNewArchOff(config) {
  return withDangerousMod(config, [
    "android",
    async (modConfig) => {
      const fs = require("fs");
      const projectRoot =
        (modConfig.modRequest && modConfig.modRequest.projectRoot) ||
        modConfig._internal.projectRoot;
      const gradlePropsPath = path.join(
        projectRoot,
        "android",
        "gradle.properties"
      );
      if (fs.existsSync(gradlePropsPath)) {
        let content = fs.readFileSync(gradlePropsPath, "utf8");
        if (/^newArchEnabled=true/m.test(content)) {
          content = content.replace(/^newArchEnabled=true/m, "newArchEnabled=false");
          fs.writeFileSync(gradlePropsPath, content);
          console.log("[tradeguard] newArchEnabled=false (FINAL FIX: Android 15 UFFD SIGSEGV in RN New Architecture)");
        } else if (/^newArchEnabled=/.test(content)) {
          console.log("[tradeguard] newArchEnabled already set: " + content.match(/^newArchEnabled=.*/m)[0]);
        } else {
          content += "\nnewArchEnabled=false\n";
          fs.writeFileSync(gradlePropsPath, content);
          console.log("[tradeguard] newArchEnabled=false appended");
        }
      } else {
        console.warn("[tradeguard] android/gradle.properties not found; newArch override skipped");
      }
      return modConfig;
    },
  ]);
}

module.exports = function withTradeGuardAndroidArchFix(config) {
  return withNewArchOff(withTargetSdk34(config));
};
