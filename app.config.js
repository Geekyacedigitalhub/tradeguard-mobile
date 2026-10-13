const fs = require('node:fs');
const path = require('node:path');
const appJson = require('./app.json');

module.exports = ({ config }) => {
  const googleServicesFile = process.env.GOOGLE_SERVICES_JSON
    ? path.resolve(process.env.GOOGLE_SERVICES_JSON)
    : path.resolve(__dirname, 'google-services.json');

  const android = {
    ...(config.android || {}),
    ...(appJson.expo.android || {}),
  };

  // FCM configuration is optional for a local APK build. Keep it enabled
  // automatically when the user has supplied their Firebase file, but do not
  // make an ignored/private file a hard prerequisite for prebuild.
  if (fs.existsSync(googleServicesFile)) {
    android.googleServicesFile = googleServicesFile;
  } else {
    delete android.googleServicesFile;
  }

  return {
    ...config,
    ...appJson.expo,
    android,
  };
};
