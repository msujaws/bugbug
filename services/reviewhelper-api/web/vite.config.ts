import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The app is served by FastAPI under /dashboard (see app/main.py).
export default defineConfig({
  base: "/dashboard/",
  plugins: [react()],
  build: { outDir: "dist" },
});
