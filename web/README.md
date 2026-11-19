# Web App

This directory contains the Vue 3 frontend application.

Common commands:

```bash
npm install
npm run dev
npm run build
```

## Deploying below a path

Build with `VITE_APP_BASE_PATH=/dcla/ npm run build` to serve the Digital Capability Learning Agent (DCLA) below that path. The default remains `/`. Browser assets, router history, API calls, SSE and login redirects share Vite’s base path. The reverse proxy must route `/dcla/api/` to the backend `/api/`, keep SSE unbuffered, and scope the session cookie to `/dcla/`.
