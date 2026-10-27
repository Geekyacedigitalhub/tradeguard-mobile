// App entry point (package.json "main").
// Order matters: bootstrap.ts fires the js_started beacon BEFORE the router
// and any app module load, so the beacon is sent even if loading the router
// crashes the app.
import "./bootstrap";
import "expo-router/entry";
