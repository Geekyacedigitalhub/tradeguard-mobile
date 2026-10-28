// Native diagnostics plugin (v0.4.7). Plain JS on purpose — Expo config
// plugins are loaded with plain require(), which cannot load .ts files.
//
// WHY v0.4.7 exists:
//   v0.4.6 "fixed" the suspected 16KB-page crash via app.json
//   "targetSdkVersion": 34 — but that key is SILENTLY IGNORED in Expo SDK
//   54 (prebuild never writes android.targetSdkVersion into
//   android/gradle.properties, which is the only file the Expo gradle
//   plugin reads it from). The v0.4.6 APK therefore still targeted API 35
//   and crashed exactly like before.
//
// This build:
//  1. ACTUAL FIX: a dangerous mod appends android.targetSdkVersion=34 to
//     android/gradle.properties during prebuild — the Expo gradle plugin
//     maps that property into the version catalog used for
//     targetSdkVersion (verified in ExpoAutolinkingSettingsExtension.kt +
//     ExpoRootProjectPlugin.kt).
//  2. VERIFICATION on device: the dialog shows packageInfo.targetSdkVersion
//     so we can SEE which targetSdk the installed APK actually carries.
//  3. ROBUST CRASH CAPTURE: the ContentProvider (runs before
//     Application.onCreate) does a synchronous `logcat -d` dump at startup
//     (captures the PREVIOUS launch's crash — the logd ring buffer persists
//     across process deaths) and another at +5s (captures late crashes in
//     THIS launch). The dialog is filled IMMEDIATELY from the file — no
//     "collecting..." wait, so the data is visible within ~1s even if the
//     process dies seconds later.
//  4. CI: the workflow prints the aapt targetSdkVersion as an annotation
//     so the fix is verifiable without device access.

const path = require("path");
const { withMainActivity, withAndroidManifest, withDangerousMod } =
  require("expo/config-plugins");

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
            "\n# TradeGuard: 16KB-page mitigation (Android 15). RN 0.81 native\n" +
            "# libraries are not 16KB-page aligned; targeting API 34 lets the\n" +
            "# loader accept them. See v0.4.7 commit.\n" +
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

function withTradeGuardDiagnosticsMainActivity(config) {
  return withMainActivity(config, (modRequest) => {
    const pkg =
      (config.pkg && config.pkg.android && config.pkg.android.package) ||
      "com.geekyacedigitalhub.tradeguard2";
    if (modRequest.modResults.language === "kt") {
      modRequest.modResults.contents = MAIN_ACTIVITY_KOTLIN.split(
        "com.geekyacedigitalhub.tradeguard2"
      ).join(pkg);
    } else {
      console.warn(
        "[tradeguard-diagnostics] MainActivity is not Kotlin; skipping native diagnostics injection"
      );
    }
    return modRequest;
  });
}

function withTradeGuardCrashCatcherProvider(config) {
  return withAndroidManifest(config, (modRequest) => {
    const pkg =
      (config.pkg && config.pkg.android && config.pkg.android.package) ||
      "com.geekyacedigitalhub.tradeguard2";
    const application = modRequest.modResults.manifest.application;
    const providerElement = {
      $: {
        "android:name": `${pkg}.TradeGuardCrashCatcher`,
        "android:authorities": `${pkg}.crashcatcher`,
        "android:exported": "false",
        "android:initOrder": "100"
      }
    };
    if (Array.isArray(application)) {
      for (const app of application) {
        if (!app || typeof app !== "object") continue;
        const providers = Array.isArray(app.provider) ? app.provider : [];
        const exists = providers.some(
          (p) => p && p.$ && p.$["android:name"] === `${pkg}.TradeGuardCrashCatcher`
        );
        if (!exists) {
          providers.push(providerElement);
          app.provider = providers;
        }
        break; // the template generates a single <application> element
      }
    }
    return modRequest;
  });
}

module.exports = function withTradeGuardNativeDiagnostics(config) {
  return withTargetSdk34(
    withTradeGuardCrashCatcherProvider(
      withTradeGuardDiagnosticsMainActivity(config)
    )
  );
};

const MAIN_ACTIVITY_KOTLIN = `
package com.geekyacedigitalhub.tradeguard2

import android.app.AlertDialog
import android.content.ContentProvider
import android.content.DialogInterface
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.method.ScrollingMovementMethod
import android.widget.ScrollView
import android.widget.TextView

import androidx.appcompat.app.AlertDialog

import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import com.facebook.react.defaults.DefaultReactActivityDelegate

import expo.modules.ReactActivityDelegateWrapper

import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

class MainActivity : ReactActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    // Set the theme to AppTheme BEFORE onCreate to support
    // coloring the background, status bar, and navigation bar.
    // This is required for expo-splash-screen.
    setTheme(R.style.AppTheme)
    super.onCreate(null)
    showNativeDiagnostics()
  }

  /**
   * Returns the name of the main component registered from JavaScript. This is used to schedule
   * rendering of the component.
   */
  override fun getMainComponentName(): String = "main"

  /**
   * Returns the instance of the [ReactActivityDelegate]. We use [DefaultReactActivityDelegate]
   * which allows you to enable New Architecture with a single boolean flags [fabricEnabled]
   */
  override fun createReactActivityDelegate(): ReactActivityDelegate {
    return ReactActivityDelegateWrapper(
          this,
          BuildConfig.IS_NEW_ARCHITECTURE_ENABLED,
          object : DefaultReactActivityDelegate(
              this,
              mainComponentName,
              fabricEnabled
          ){})
  }

  /**
    * Align the back button behavior with Android S
    * where moving root activities to background instead of finishing activities.
    */
  override fun invokeDefaultOnBackPressed() {
      if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.R) {
          if (!moveTaskToBack(false)) {
              // For non-root activities, use the default implementation to finish them.
              super.invokeDefaultOnBackPressed()
          }
          return
      }

      // Use the default back button implementation on Android S
      // because it's doing more than [Activity.moveTaskToBack] in fact.
      super.invokeDefaultOnBackPressed()
  }

  // ---------------------------------------------------------------------
  // NATIVE DIAGNOSTICS (v0.4.7)
  // The dialog is filled IMMEDIATELY from the logcat file that
  // TradeGuardCrashCatcher wrote at process start (before this activity).
  // ---------------------------------------------------------------------

  private fun fmtTs(): String =
      SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS z", Locale.US).format(Date())

  private fun fmtTsOf(millis: Long): String =
      SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date(millis))

  private fun md5Hex(bytes: ByteArray): String {
    val digest = MessageDigest.getInstance("MD5").digest(bytes)
    val sb = StringBuilder()
    for (b in digest) sb.append(String.format(Locale.US, "%02x", b))
    return sb.toString()
  }

  private fun bundleReport(): String {
    val out = StringBuilder()
    for (n in listOf("index.android.bundle", "index.android.bundle.hbc", "index.android.bundle.map")) {
      try {
        assets.open(n).use { input ->
          val b = input.readBytes()
          out.append("  ").append(n).append("  size=").append(b.size)
              .append("  md5=").append(md5Hex(b)).append("\\n")
        }
      } catch (e: Exception) {
        out.append("  ").append(n).append("  (not present)\\n")
      }
    }
    return out.toString()
  }

  private fun kernelPageSize(): String {
    return try {
      val p = Runtime.getRuntime().exec(arrayOf("getconf", "PAGESIZE"))
      val out = p.inputStream.bufferedReader().readText().trim()
      p.waitFor()
      out
    } catch (e: Exception) {
      "unavailable (\${e.message})"
    }
  }

  /** logcat -d dumps the ring buffer and exits; no root needed. */
  private fun dumpLogcat(): String {
    return try {
      val p = Runtime.getRuntime().exec(arrayOf("logcat", "-d", "-v", "threadtime", "-t", "2500"))
      val text = p.inputStream.bufferedReader().readText()
      p.waitFor()
      text
    } catch (e: Exception) {
      "(logcat failed: \${e.message})"
    }
  }

  /** Keep only the lines that explain a native/JS crash. */
  private fun filterLog(text: String): String {
    val needles = listOf(
      "FATAL", "Fatal", "SIGSEGV", "SIGABRT", "SIGBUS", "signal", "Abort message",
      "DEBUG", "AndroidRuntime", "Exception", "UnsatisfiedLink", "dlopen",
      "cannot load", "linker", "libreact", "libhermes", "hermes", "Hermes",
      "ReactNative", "reactnative", "react_runtime", "expo", "libc++",
      "page size", "16KB", "JNI", "abort", "backtrace", ">>> "
    )
    val lines = text.lines().filter { l ->
      needles.any { n -> l.contains(n) }
    }
    if (lines.isEmpty()) return "(no crash-related lines in the log buffer)"
    return lines.joinToString("\\n").takeLast(1300)
  }

  private fun showSmallDialog(title: String, body: String) {
    val tv = TextView(this).apply {
      isVerticalScrollBarEnabled = true
      movementMethod = ScrollingMovementMethod()
      setTypeface(Typeface.MONOSPACE)
      textSize = 11f
      setPadding(28, 28, 28, 28)
    }
    tv.text = body
    val sv = ScrollView(this)
    sv.addView(tv)
    val d = AlertDialog.Builder(this)
        .setTitle(title)
        .setView(sv)
        .setCancelable(true)
        .setPositiveButton("Close", object : DialogInterface.OnClickListener {
          override fun onClick(dialog: DialogInterface?, which: Int) {
            dialog?.dismiss()
          }
        })
        .create()
    d.show()
  }

  private fun showNativeDiagnostics() {
    val tv = TextView(this).apply {
      isVerticalScrollBarEnabled = true
      movementMethod = ScrollingMovementMethod()
      setTypeface(Typeface.MONOSPACE)
      textSize = 11f
      setPadding(28, 28, 28, 28)
    }
    val sv = ScrollView(this)
    sv.addView(tv)

    val builder = AlertDialog.Builder(this)
        .setTitle("TradeGuard v0.4.7 - native diagnostics")
        .setView(sv)
        .setCancelable(false)
        .setPositiveButton(
            "OK - continue to app",
            object : DialogInterface.OnClickListener {
              override fun onClick(dialog: DialogInterface?, which: Int) {
                dialog?.dismiss()
              }
            }
        )
    val dialog = builder.create()

    // Fill IMMEDIATELY (synchronous, fast) so the data is on screen even if
    // the process dies a few seconds later.
    try {
      val filesDir = getFilesDir()
      val logcatFile = File(filesDir, "tradeguard-logcat-last.txt")
      val prevLog = if (logcatFile.exists()) logcatFile.readText() else "(no logcat captured yet - first launch?)"
      val sb = StringBuilder()
      sb.append("KERNEL PAGE SIZE: ").append(kernelPageSize())
          .append(" bytes  (16384 = 16KB device)\\n")
      try {
        val ai = packageManager.getPackageInfo(packageName, 0)
        sb.append("app: ").append(ai.versionName).append(" (versionCode ").append(ai.versionCode)
            .append(", targetSdk ").append(ai.targetSdkVersion).append(")\\n")
      } catch (e: Exception) {
        sb.append("app: version info unavailable\\n")
      }
      sb.append("device: ").append(Build.MANUFACTURER).append(" ").append(Build.MODEL)
          .append("  android API ").append(Build.VERSION.SDK_INT).append("\\n")
      sb.append("\\n1) JS BUNDLES INSIDE THIS APK:\\n").append(bundleReport())
      sb.append("2) APP FILES DIR: ").append(filesDir.absolutePath).append("\\n")
      sb.append("   files in this dir:\\n")
      val files = filesDir.listFiles()
      if (files == null) {
        sb.append("     (listing failed - permissions?)\\n")
      } else if (files.isEmpty()) {
        sb.append("     (empty)\\n")
      } else {
        for (f in files) {
          sb.append("     ").append(f.name).append("  size=").append(f.length())
              .append("  mtime=").append(fmtTsOf(f.lastModified())).append("\\n")
        }
      }
      val journal = File(filesDir, "tradeguard-crash-journal.txt")
      sb.append("\\n3) JS CRASH JOURNAL AT BOOT: ")
      if (journal.exists()) {
        sb.append("PRESENT size=").append(journal.length()).append("\\n")
        try {
          sb.append(journal.readText().takeLast(400))
        } catch (e: Exception) {
          sb.append("(read failed: ").append(e.message).append(")")
        }
      } else {
        sb.append("NOT PRESENT (JS never initialized on this install)")
      }
      sb.append("\\n\\n4) LOGCAPTURED SINCE LAST CRASH (filtered for crash lines):\\n")
      sb.append(filterLog(prevLog))
      tv.text = sb.toString()
    } catch (e: Exception) {
      tv.text = "DIAGNOSTICS ERROR: " + e.stackTraceToString().take(900)
    }
    dialog.show()

    val handler = Handler(Looper.getMainLooper())
    val filesDir2 = getFilesDir()
    val journal = File(filesDir2, "tradeguard-crash-journal.txt")
    val journalMtimeAtStart = if (journal.exists()) journal.lastModified() else 0L

    // Second logcat dump at +5s: catches a crash in THIS launch (e.g. right
    // after the OK tap) so the next launch's dialog shows it.
    thread(start = true) {
      try {
        Thread.sleep(5000)
        File(filesDir2, "tradeguard-logcat-last.txt").writeText(dumpLogcat())
      } catch (_: Exception) {
      }
      try {
        Thread.sleep(10000)
        val jsWrote = journal.exists() &&
            (journalMtimeAtStart == 0L || journal.lastModified() > journalMtimeAtStart)
        val thisLog = try { File(filesDir2, "tradeguard-logcat-last.txt").readText() } catch (e: Exception) { "(no logcat)" }
        val second = StringBuilder()
        second.append("JS STARTUP CHECK (after 15s): ")
        second.append(
            if (jsWrote) {
              "JS IS RUNNING - the journal file was written/updated during this launch."
            } else {
              "JS DID NOT WRITE THE JOURNAL within 15s - the JS bundle likely never executed, or file I/O from JS failed."
            }
        )
        second.append("\\n\\nLOGCAPTURED DURING THIS LAUNCH (filtered):\\n")
        second.append(filterLog(thisLog))
        handler.post {
          showSmallDialog("TradeGuard v0.4.7 - diagnostics update", second.toString())
        }
      } catch (_: Exception) {
      }
    }
  }
}

// Runs BEFORE Application.onCreate and MainActivity — the earliest native
// code in the process. Two jobs:
//  A) Synchronous logcat dump at process start: the logd ring buffer
//     persists across process deaths, so this captures the PREVIOUS
//     launch's crash (FATAL / SIGSEGV / SIGABRT / linker lines). The
//     activity's dialog reads this file immediately.
//  B) Default uncaught-exception handler: saves Java crashes (native
//     signal crashes bypass it — those come from logcat).
class TradeGuardCrashCatcher : ContentProvider() {
  override fun onCreate(): Boolean {
    val ctx = context?.applicationContext
    if (ctx != null && !TradeGuardCrashCatcher.installed) {
      TradeGuardCrashCatcher.installed = true
      try {
        val docs = ctx.getFilesDir()
        val logcatFile = File(docs, "tradeguard-logcat-last.txt")
        try {
          logcatFile.writeText(runtimeLogcat())
        } catch (_: Exception) {
        }
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler(object : Thread.UncaughtExceptionHandler {
          override fun uncaughtException(t: Thread, e: Throwable) {
          try {
            val sb = StringBuilder()
            sb.append("captured at ")
                .append(SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS z", Locale.US).format(Date()))
                .append("\\nthread: ").append(t.name).append("\\n\\n")
            sb.append(e).append("\\n")
            sb.append(e.stackTraceToString())
            File(docs, "tradeguard-native-crash.txt").writeText(sb.toString())
          } catch (_: Exception) {
          }
              // Keep the default system behavior after capturing.
              if (prev != null) {
                try {
                  prev.uncaughtException(t, e)
                } catch (_: Exception) {
                }
              }
          }
        })
      } catch (_: Exception) {
      }
    }
    return true
  }

  private fun runtimeLogcat(): String {
    return try {
      val p = Runtime.getRuntime().exec(arrayOf("logcat", "-d", "-v", "threadtime", "-t", "2500"))
      val text = p.inputStream.bufferedReader().readText()
      p.waitFor()
      text
    } catch (e: Exception) {
      "(logcat failed)"
    }
  }

  override fun query(
      uri: android.net.Uri,
      projection: Array<out String>?,
      selection: String?,
      selectionArgs: Array<out String>?,
      sortOrder: String?
  ): android.database.Cursor? = null

  override fun getType(uri: android.net.Uri): String? = null

  override fun insert(uri: android.net.Uri, values: android.content.ContentValues?): android.net.Uri? = null

  override fun delete(uri: android.net.Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0

  override fun update(
      uri: android.net.Uri,
      values: android.content.ContentValues?,
      selection: String?,
      selectionArgs: Array<out String>?
  ): Int = 0

  companion object {
    @Volatile
    var installed = false
  }
}
`;
