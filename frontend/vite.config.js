import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 本機開發：前端 5173 → 後端 8000（uvicorn app:app --port 8000）
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/health": "http://localhost:8000" } },
});
