[CmdletBinding()]
param(
  [switch]$Install,
  [switch]$Clean,
  [string]$SdkPath = $env:ANDROID_SDK_ROOT
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Stop-Build([string]$Message) {
  Write-Error $Message
  exit 1
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Stop-Build "Node.js was not found. Install the Node.js LTS release, reopen PowerShell, and retry."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Stop-Build "npm was not found. Install Node.js LTS, reopen PowerShell, and retry."
}
if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
  Stop-Build "Java was not found. Install a compatible JDK (JDK 17 for this Expo/Gradle setup), then reopen PowerShell."
}

if ([string]::IsNullOrWhiteSpace($SdkPath)) {
  $SdkPath = "C:\Android\Sdk"
}
if (-not (Test-Path $SdkPath -PathType Container)) {
  Stop-Build "Android SDK not found at '$SdkPath'. Pass -SdkPath or set ANDROID_SDK_ROOT."
}
$env:ANDROID_HOME = $SdkPath
$env:ANDROID_SDK_ROOT = $SdkPath
$env:Path = "$SdkPath\platform-tools;$SdkPath\cmdline-tools\latest\bin;$env:Path"

Write-Host "== TradeGuard local Android APK build ==" -ForegroundColor Cyan
Write-Host "Repository: $RepoRoot"
Write-Host "Android SDK: $SdkPath"

# EXPO_PUBLIC_* values are inlined into the JavaScript bundle at build time, so
# the backend URL must be set in this shell before Gradle bundles the app.
if ([string]::IsNullOrWhiteSpace($env:EXPO_PUBLIC_API_URL)) {
  Write-Host "API base URL: https://tradeguard-api.fastapicloud.dev (built-in default)" -ForegroundColor Yellow
  Write-Host "  Set `$env:EXPO_PUBLIC_API_URL before running this script to target a different backend." -ForegroundColor Yellow
} else {
  Write-Host "API base URL: $($env:EXPO_PUBLIC_API_URL)" -ForegroundColor Green
}

if (-not (Test-Path (Join-Path $RepoRoot "package-lock.json"))) {
  Stop-Build "package-lock.json is missing; refusing a non-reproducible install."
}
Write-Host "Installing locked JavaScript dependencies..."
npm ci
if ($LASTEXITCODE -ne 0) { Stop-Build "npm ci failed." }

Write-Host "Checking Expo app configuration..."
$ExpoConfig = npx expo config --type public --json
if ($LASTEXITCODE -ne 0) { Stop-Build "Expo configuration validation failed." }
try {
  $Parsed = $ExpoConfig | ConvertFrom-Json
  Write-Host ("Building {0} v{1} (versionCode {2})" -f $Parsed.name, $Parsed.version, $Parsed.android.versionCode)
} catch {
  Stop-Build "Expo returned configuration that could not be parsed."
}

$AndroidDir = Join-Path $RepoRoot "android"
$GradleWrapper = Join-Path $AndroidDir "gradlew.bat"
if (-not (Test-Path $GradleWrapper -PathType Leaf)) {
  Write-Host "Native Android project not found; generating it locally with Expo prebuild..."
  npx expo prebuild --platform android
  if ($LASTEXITCODE -ne 0) { Stop-Build "Expo prebuild failed." }
}
if (-not (Test-Path $GradleWrapper -PathType Leaf)) {
  Stop-Build "Gradle wrapper is missing after prebuild. Check the Expo prebuild output."
}

if ($Clean) {
  Write-Host "Cleaning previous Gradle outputs..."
  Push-Location $AndroidDir
  try {
    .\gradlew.bat clean
    if ($LASTEXITCODE -ne 0) { Stop-Build "Gradle clean failed." }
  } finally { Pop-Location }
}

Write-Host "Building debug APK locally (no EAS build is used)..."
Push-Location $AndroidDir
try {
  .\gradlew.bat assembleDebug
  if ($LASTEXITCODE -ne 0) { Stop-Build "Gradle assembleDebug failed." }
} finally { Pop-Location }

$Apk = Join-Path $AndroidDir "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $Apk -PathType Leaf)) {
  Stop-Build "Gradle reported success, but the expected APK was not found at '$Apk'."
}
$Item = Get-Item $Apk
Write-Host ""
Write-Host "BUILD SUCCESSFUL" -ForegroundColor Green
Write-Host "APK: $($Item.FullName)"
Write-Host ("Size: {0:N1} MB" -f ($Item.Length / 1MB))
Write-Host "Built: $($Item.LastWriteTime)"

if ($Install) {
  $Adb = Join-Path $SdkPath "platform-tools\adb.exe"
  if (-not (Test-Path $Adb -PathType Leaf)) {
    Stop-Build "adb.exe not found at '$Adb'. Build succeeded, but installation was not attempted."
  }
  & $Adb devices
  if ($LASTEXITCODE -ne 0) { Stop-Build "Could not query Android devices." }
  Write-Host "Installing APK on the connected Android device..."
  & $Adb install -r $Apk
  if ($LASTEXITCODE -ne 0) { Stop-Build "APK built, but adb installation failed. Check USB debugging/device authorization." }
  Write-Host "APK installation succeeded." -ForegroundColor Green
}
