import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteStaticCopy } from "vite-plugin-static-copy";

// pliki wasm onnxruntime-web serwowane z /ort/ (patrz src/audio/vad.ts)
export default defineConfig({
  plugins: [
    react(),
    viteStaticCopy({
      targets: [
        {
          src: "node_modules/onnxruntime-web/dist/*.wasm",
          dest: "ort",
        },
        {
          src: "node_modules/onnxruntime-web/dist/*.mjs",
          dest: "ort",
        },
      ],
    }),
  ],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
