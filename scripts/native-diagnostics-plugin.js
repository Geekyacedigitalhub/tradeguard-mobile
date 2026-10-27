// Native diagnostics plugin (v0.4.5). Plain JS on purpose — Expo config
// plugins are loaded with plain require(), which cannot load .ts files.
//
// Seven install-and-report cycles have failed to produce a single piece of
// on-device data, and every diagnostic we ship lives in JavaScript. If the JS
// bundle never executes on the device, no JS diagnostic can ever be seen —
// so this plugin injects diagnostics into the NATIVE layer, where they work
// regardless of what JS is doing:
//
// 1. MainActivity shows a native dialog at every launch that proves the
//    Android process is alive, reports the device, lists the JS bundle files
//    (size + MD5, so we can verify exactly which bundle is on the phone),
//    lists the app Documents directory, dumps the JS crash journal as seen
//    FROM NATIVE (the journal is written by JS via expo-file-system), shows
//    any native crash captured from an earlier launch, and after 15s reports
//    whether JS started writing the journal during this launch.
// 2. A ContentProvider (runs before Application.onCreate) installs a default
//    uncaught-exception handler that writes any native crash stack to
//    files/tradeguard-native-crash.txt, where the next launch's dialog
//    shows it. This is the data channel for "app bounces instantly" deaths.
//
// This is a DIAGNOSTIC build: the dialog is dismissible with one tap and the
// app otherwise behaves exactly like the template.

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
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.method.ScrollingMovementMethod
import android.widget.ScrollView
import android.widget.TextView

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
  // NATIVE DIAGNOSTICS (v0.4.5)
  // Proves which layer is alive and reads the JS crash journal directly
  // from native — works even if JavaScript never executes at all.
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

    val dialog = AlertDialog.Builder(this)
        .setTitle("TradeGuard v0.4.5 - native diagnostics")
        .setView(sv)
        .setCancelable(false)
        .setButton(AlertDialog.BUTTON_POSITIVE, "OK - continue to app") { d, _ -> d.dismiss() }
        .create()
    dialog.show()

    val handler = Handler(Looper.getMainLooper())
    fun update(text: String) {
      handler.post { tv.text = text }
    }

    thread(start = true) {
      var base = ""
      try {
        val sb = StringBuilder()
        sb.append("1) NATIVE LAYER IS RUNNING - the Android process started and this activity is alive.\\n\\n")
        sb.append("device: ").append(Build.MANUFACTURER).append(" ").append(Build.MODEL)
            .append("  android API ").append(Build.VERSION.SDK_INT).append("\\n")
        try {
          val ai = packageManager.getPackageInfo(packageName, 0)
          sb.append("app: ").append(ai.versionName).append(" (versionCode ").append(ai.versionCode).append(")\\n")
        } catch (e: Exception) {
          sb.append("app: version info unavailable\\n")
        }
        sb.append("\\n2) JS BUNDLES INSIDE THIS APK:\\n").append(bundleReport())
        val docs = getFilesDir()
        sb.append("3) APP FILES DIR (expo-file-system writes here): ").append(docs.absolutePath).append("\\n")
        val marker = File(docs, "tradeguard-native-boot.txt")
        try {
          marker.appendText("boot " + fmtTs() + " pid=" + android.os.Process.myPid() + "\\n")
        } catch (e: Exception) {
          sb.append("   marker write failed: ").append(e.message).append("\\n")
        }
        sb.append("   native marker: tradeguard-native-boot.txt (one line per launch)\\n")
        sb.append("   files in this dir:\\n")
        val files = docs.listFiles()
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
        val journal = File(docs, "tradeguard-crash-journal.txt")
        val journalMtimeAtStart = if (journal.exists()) journal.lastModified() else 0L
        sb.append("\\n4) JS CRASH JOURNAL AT BOOT: ")
        if (journal.exists()) {
          sb.append("PRESENT size=").append(journal.length()).append("\\n")
          try {
            sb.append(journal.readText().takeLast(600))
          } catch (e: Exception) {
            sb.append("(read failed: ").append(e.message).append(")")
          }
        } else {
          sb.append("NOT PRESENT (no JS session has ever completed journal init on this install)")
        }
        sb.append("\\n\\n5) NATIVE CRASH CAPTURED FROM AN EARLIER LAUNCH (if any):\\n")
        val crashFile = File(docs, "tradeguard-native-crash.txt")
        sb.append(if (crashFile.exists()) crashFile.readText().take(1500) else "(none captured)")
        base = sb.toString()
        update(base)

        // Give JS 15 seconds to start and write/refresh the journal.
        Thread.sleep(15000)
        val jsWrote = journal.exists() &&
            (journalMtimeAtStart == 0L || journal.lastModified() > journalMtimeAtStart)
        update(base + "\\n\\n6) JS STARTUP CHECK (after 15s): " +
            if (jsWrote) {
              "JS IS RUNNING - the journal file was written/updated during this launch."
            } else {
              "JS DID NOT WRITE THE JOURNAL within 15s of native startup - the JS bundle likely never executed, or file I/O from JS failed."
            })
      } catch (e: Exception) {
        val extra = "\\n\\nDIAGNOSTICS ERROR: " + (e.stackTraceToString().take(900) ?: e.toString())
        try { update((if (base.isNotEmpty()) base else tv.text) + extra) } catch (_: Exception) {}
      }
    }
  }
}

// Runs BEFORE Application.onCreate and MainActivity — the earliest native
// code we can run. Captures native (non-JS) crashes so the NEXT launch's
// dialog can show the exact exception that killed the app.
class TradeGuardCrashCatcher : ContentProvider() {
  override fun onCreate(): Boolean {
    val ctx = context?.applicationContext
    if (ctx != null && !TradeGuardCrashCatcher.installed) {
      TradeGuardCrashCatcher.installed = true
      try {
        val docs = ctx.getFilesDir()
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
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
