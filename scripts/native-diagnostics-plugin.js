// Native diagnostics plugin (v0.4.6). Plain JS on purpose — Expo config
// plugins are loaded with plain require(), which cannot load .ts files.
//
// STATE OF PLAY after the v0.4.5 on-device screenshot:
//   - native layer IS alive (dialog renders on the phone)
//   - the app then dies with NO Java exception captured ("keeps stopping")
//     => the death is a native signal (SIGSEGV/SIGABRT) inside the
//        React Native / Hermes native layer
//   - device is Android 15 (API 35) on a 16KB-capable kernel — if the RN
//        .so files are not 16KB-page aligned, the dynamic linker aborts
//        exactly like this (and it explains why plain-Kotlin apps work)
//
// What this build does:
//  1. Shows the device's KERNEL PAGE SIZE (getconf PAGESIZE) — 16384 means
//     the device runs 16KB pages and unaligned .so files cannot load.
//  2. Dumps `logcat -d` at launch (captures the PREVIOUS launch's crash
//     lines — FATAL / signal / linker / dlopen / Hermes / ReactNative) and
//     shows the filtered lines in the dialog.
//  3. Dumps logcat again after 15s (captures THIS launch's crash if the
//     app dies right after the OK tap) and, if still alive, shows a small
//     second dialog with the JS-startup check + the captured log lines.
//  4. Keeps the bundle fingerprint (size + MD5), files dir listing, JS
//     journal read, and the Java-crash catcher from v0.4.5.
//
// The companion app.json change (targetSdkVersion 34) is the likely FIX:
// the 16KB-page requirement is enforced for apps targeting API 35+;
// targeting 34 makes the linker accept pre-16KB-aligned libraries.

const { withMainActivity, withAndroidManifest } = require("expo/config-plugins");

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
  return withTradeGuardCrashCatcherProvider(
    withTradeGuardDiagnosticsMainActivity(config)
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
  // NATIVE DIAGNOSTICS (v0.4.6)
  // v0.4.5 proved the native layer is alive and the death is a NATIVE
  // signal (no Java exception captured). This build captures the kernel
  // page size and the device logcat so we can see the exact abort.
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
    try {
      val p = Runtime.getRuntime().exec(arrayOf("getconf", "PAGESIZE"))
      val out = p.inputStream.bufferedReader().readText().trim()
      p.waitFor()
      return out
    } catch (e: Exception) {
      return "unavailable (\${e.message})"
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
    tv.text = "Collecting diagnostics...\\n(device, bundle, logcat)\\nplease wait a few seconds"
    val sv = ScrollView(this)
    sv.addView(tv)

    val builder = AlertDialog.Builder(this)
        .setTitle("TradeGuard v0.4.6 - native diagnostics")
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
    dialog.show()

    val handler = Handler(Looper.getMainLooper())
    fun update(text: String) {
      handler.post { tv.text = text }
    }

    thread(start = true) {
      var base = ""
      try {
        val filesDir = getFilesDir()
        val logcatFile = File(filesDir, "tradeguard-logcat-last.txt")

        // 0) Capture the PREVIOUS launch's logcat BEFORE overwriting the file.
        val prevLog = if (logcatFile.exists()) logcatFile.readText() else "(no logcat captured yet)"
        val prevLogFiltered = filterLog(prevLog)

        val sb = StringBuilder()
        sb.append("KERNEL PAGE SIZE: ").append(kernelPageSize())
            .append(" bytes  (16384 = 16KB device - RN .so files must be 16KB-aligned)\\n")
        sb.append("\\n1) NATIVE LAYER IS RUNNING - the Android process started and this activity is alive.\\n")
        sb.append("device: ").append(Build.MANUFACTURER).append(" ").append(Build.MODEL)
            .append("  android API ").append(Build.VERSION.SDK_INT).append("\\n")
        try {
          val ai = packageManager.getPackageInfo(packageName, 0)
          sb.append("app: ").append(ai.versionName).append(" (versionCode ").append(ai.versionCode).append(")\\n")
        } catch (e: Exception) {
          sb.append("app: version info unavailable\\n")
        }
        sb.append("\\n2) JS BUNDLES INSIDE THIS APK:\\n").append(bundleReport())
        sb.append("3) APP FILES DIR: ").append(filesDir.absolutePath).append("\\n")
        val marker = File(filesDir, "tradeguard-native-boot.txt")
        try {
          marker.appendText("boot " + fmtTs() + " pid=" + android.os.Process.myPid() + "\\n")
        } catch (e: Exception) {
          sb.append("   marker write failed: ").append(e.message).append("\\n")
        }
        sb.append("   native marker: tradeguard-native-boot.txt (one line per launch)\\n")
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
        val journalMtimeAtStart = if (journal.exists()) journal.lastModified() else 0L
        sb.append("\\n4) JS CRASH JOURNAL AT BOOT: ")
        if (journal.exists()) {
          sb.append("PRESENT size=").append(journal.length()).append("\\n")
          try {
            sb.append(journal.readText().takeLast(500))
          } catch (e: Exception) {
            sb.append("(read failed: ").append(e.message).append(")")
          }
        } else {
          sb.append("NOT PRESENT (no JS session has ever completed journal init on this install)")
        }
        sb.append("\\n\\n5) LOGCAT FROM PREVIOUS LAUNCHES (filtered for crash lines):\\n")
        sb.append(prevLogFiltered)
        sb.append("\\n\\n6) JAVA CRASH CAPTURED FROM AN EARLIER LAUNCH (if any):\\n")
        val crashFile = File(filesDir, "tradeguard-native-crash.txt")
        sb.append(if (crashFile.exists()) crashFile.readText().take(800) else "(none captured - consistent with a NATIVE signal crash, not a Java exception)")
        base = sb.toString()

        // Save a fresh logcat dump NOW so the next launch can show it.
        try { logcatFile.writeText(dumpLogcat()) } catch (_: Exception) {}

        update(base)

        // Give JS 15 seconds to start. If the app dies right after the OK
        // tap, this thread dies with it - but the dump saved above plus the
        // logd ring buffer let the NEXT launch's dialog show the crash.
        Thread.sleep(15000)

        // Second dump: captures THIS launch's crash (e.g. right after OK).
        val thisLog = dumpLogcat()
        try { logcatFile.writeText(thisLog) } catch (_: Exception) {}
        val jsWrote = journal.exists() &&
            (journalMtimeAtStart == 0L || journal.lastModified() > journalMtimeAtStart)

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
          showSmallDialog("TradeGuard v0.4.6 - diagnostics update", second.toString())
        }
      } catch (e: Exception) {
        val extra = "\\n\\nDIAGNOSTICS ERROR: " + (e.stackTraceToString().take(900) ?: e.toString())
        try { update((if (base.isNotEmpty()) base else tv.text.toString()) + extra) } catch (_: Exception) {}
      }
    }
  }
}

// Runs BEFORE Application.onCreate and MainActivity — the earliest native
// code we can run. Captures Java (non-native-signal) crashes so the NEXT
// launch's dialog can show the exact exception that killed the app.
class TradeGuardCrashCatcher : ContentProvider() {
  override fun onCreate(): Boolean {
    val ctx = context?.applicationContext
    if (ctx != null && !TradeGuardCrashCatcher.installed) {
      TradeGuardCrashCatcher.installed = true
      try {
        val docs = ctx.getFilesDir()
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
