#!/usr/bin/env python3
"""Patch the Expo-generated android/app/build.gradle to sign release builds.

The template ships release builds signed with the CI debug keystore
(`signingConfig signingConfigs.debug`), which every previous APK used.
This script injects a dedicated `tgrelease` signing config (the stable
PKCS12 keystore is committed at signing/tradeguard-release.keystore; CI
copies it into place) and points the release buildType at it — without
touching any committed template file.

Env:
  TG_GRADLE_FILE  path to android/app/build.gradle (default: android/app/build.gradle)
  TG_KEYSTORE     keystore path as it should appear in build.gradle,
                  relative to android/app/ (default: ../tradeguard-demo-release.keystore)
  TG_KEYSTORE_PASS  keystore + key password (required)
  TG_KEY_ALIAS    key alias (default: tradeguard)
"""
import os
import re
import sys

gradle_file = os.environ.get("TG_GRADLE_FILE", "android/app/build.gradle")
keystore = os.environ.get("TG_KEYSTORE", "../tradeguard-demo-release.keystore")
key_pass = os.environ.get("TG_KEYSTORE_PASS")
key_alias = os.environ.get("TG_KEY_ALIAS", "tradeguard")

if not key_pass:
    print("::error title=TG-SIGN::TG_KEYSTORE_PASS env var is not set")
    sys.exit(1)

with open(gradle_file, "r", encoding="utf-8") as f:
    src = f.read()

if "tgrelease" in src:
    print("::notice title=TG-SIGN::build.gradle already contains tgrelease config; skipping")
    sys.exit(0)

# 1) Insert the tgrelease signing config into the existing signingConfigs block.
new_config = (
    "    signingConfigs {\n"
    f"        tgrelease {{\n"
    f"            storeFile file('{keystore}')\n"
    "            storeType 'pkcs12'\n"
    f"            storePassword '{key_pass}'\n"
    f"            keyAlias '{key_alias}'\n"
    f"            keyPassword '{key_pass}'\n"
    f"        }}\n"
)
m = re.search(r"^    signingConfigs \{\n", src, flags=re.MULTILINE)
if not m:
    print("::error title=TG-SIGN::could not find signingConfigs block in " + gradle_file)
    sys.exit(1)
patched = src[: m.start()] + new_config + src[m.start() + len("    signingConfigs {\n") :]

# 2) Point the release buildType at tgrelease.
# Search AFTER the 'buildTypes {' marker: the string 'release {' also occurs
# inside the 'tgrelease {' config name inserted above, so a plain find()
# would land in the wrong block.
bt_idx = patched.find("buildTypes {")
if bt_idx == -1:
    print("::error title=TG-SIGN::could not find buildTypes block in " + gradle_file)
    sys.exit(1)
release_idx = patched.find("release {", bt_idx)
if release_idx == -1:
    print("::error title=TG-SIGN::could not find release buildType in " + gradle_file)
    sys.exit(1)
old_sig = "signingConfig signingConfigs.debug"
sig_idx = patched.find(old_sig, release_idx)
if sig_idx == -1:
    print("::error title=TG-SIGN::release buildType does not reference signingConfigs.debug")
    sys.exit(1)
patched = patched[:sig_idx] + "signingConfig signingConfigs.tgrelease" + patched[sig_idx + len(old_sig) :]

with open(gradle_file, "w", encoding="utf-8") as f:
    f.write(patched)

print("::notice title=TG-SIGN::build.gradle patched: release buildType now uses tgrelease keystore " + keystore)
print("OK")
