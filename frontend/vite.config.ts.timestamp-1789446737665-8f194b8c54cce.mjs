// vite.config.ts
import { defineConfig } from "file:///C:/Users/Administrator/Desktop/diet-diary-improve/work-v0.8/diet-diary/frontend/node_modules/vite/dist/node/index.js";
import react from "file:///C:/Users/Administrator/Desktop/diet-diary-improve/work-v0.8/diet-diary/frontend/node_modules/@vitejs/plugin-react/dist/index.js";
var vite_config_default = defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      "/api": "http://localhost:8000",
      "/uploads": "http://localhost:8000"
    }
  },
  build: {
    outDir: "dist",
    target: "es2018",
    cssCodeSplit: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/react/") || id.includes("node_modules/react-dom/") || id.includes("node_modules/react-router-dom/") || id.includes("node_modules/react-router/")) {
            return "react";
          }
          if (id.includes("node_modules/antd/") || id.includes("node_modules/@ant-design/") || id.includes("node_modules/rc-")) {
            return "antd";
          }
          if (id.includes("node_modules/echarts/") || id.includes("node_modules/echarts-for-react/") || id.includes("node_modules/zrender/")) {
            return "echarts";
          }
          if (id.includes("node_modules/@zxing/")) {
            return "zxing";
          }
          if (id.includes("node_modules/dayjs/")) {
            return "dayjs";
          }
        }
      }
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJDOlxcXFxVc2Vyc1xcXFxBZG1pbmlzdHJhdG9yXFxcXERlc2t0b3BcXFxcZGlldC1kaWFyeS1pbXByb3ZlXFxcXHdvcmstdjAuOFxcXFxkaWV0LWRpYXJ5XFxcXGZyb250ZW5kXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCJDOlxcXFxVc2Vyc1xcXFxBZG1pbmlzdHJhdG9yXFxcXERlc2t0b3BcXFxcZGlldC1kaWFyeS1pbXByb3ZlXFxcXHdvcmstdjAuOFxcXFxkaWV0LWRpYXJ5XFxcXGZyb250ZW5kXFxcXHZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9DOi9Vc2Vycy9BZG1pbmlzdHJhdG9yL0Rlc2t0b3AvZGlldC1kaWFyeS1pbXByb3ZlL3dvcmstdjAuOC9kaWV0LWRpYXJ5L2Zyb250ZW5kL3ZpdGUuY29uZmlnLnRzXCI7aW1wb3J0IHsgZGVmaW5lQ29uZmlnIH0gZnJvbSAndml0ZSc7XG5pbXBvcnQgcmVhY3QgZnJvbSAnQHZpdGVqcy9wbHVnaW4tcmVhY3QnO1xuXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoe1xuICBwbHVnaW5zOiBbcmVhY3QoKV0sXG4gIHNlcnZlcjoge1xuICAgIGhvc3Q6IHRydWUsXG4gICAgcHJveHk6IHtcbiAgICAgICcvYXBpJzogJ2h0dHA6Ly9sb2NhbGhvc3Q6ODAwMCcsXG4gICAgICAnL3VwbG9hZHMnOiAnaHR0cDovL2xvY2FsaG9zdDo4MDAwJyxcbiAgICB9LFxuICB9LFxuICBidWlsZDoge1xuICAgIG91dERpcjogJ2Rpc3QnLFxuICAgIHRhcmdldDogJ2VzMjAxOCcsXG4gICAgY3NzQ29kZVNwbGl0OiB0cnVlLFxuICAgIGNodW5rU2l6ZVdhcm5pbmdMaW1pdDogMTIwMCxcbiAgICByb2xsdXBPcHRpb25zOiB7XG4gICAgICBvdXRwdXQ6IHtcbiAgICAgICAgbWFudWFsQ2h1bmtzKGlkKSB7XG4gICAgICAgICAgaWYgKFxuICAgICAgICAgICAgaWQuaW5jbHVkZXMoJ25vZGVfbW9kdWxlcy9yZWFjdC8nKSB8fFxuICAgICAgICAgICAgaWQuaW5jbHVkZXMoJ25vZGVfbW9kdWxlcy9yZWFjdC1kb20vJykgfHxcbiAgICAgICAgICAgIGlkLmluY2x1ZGVzKCdub2RlX21vZHVsZXMvcmVhY3Qtcm91dGVyLWRvbS8nKSB8fFxuICAgICAgICAgICAgaWQuaW5jbHVkZXMoJ25vZGVfbW9kdWxlcy9yZWFjdC1yb3V0ZXIvJylcbiAgICAgICAgICApIHtcbiAgICAgICAgICAgIHJldHVybiAncmVhY3QnO1xuICAgICAgICAgIH1cbiAgICAgICAgICBpZiAoXG4gICAgICAgICAgICBpZC5pbmNsdWRlcygnbm9kZV9tb2R1bGVzL2FudGQvJykgfHxcbiAgICAgICAgICAgIGlkLmluY2x1ZGVzKCdub2RlX21vZHVsZXMvQGFudC1kZXNpZ24vJykgfHxcbiAgICAgICAgICAgIGlkLmluY2x1ZGVzKCdub2RlX21vZHVsZXMvcmMtJylcbiAgICAgICAgICApIHtcbiAgICAgICAgICAgIHJldHVybiAnYW50ZCc7XG4gICAgICAgICAgfVxuICAgICAgICAgIGlmIChcbiAgICAgICAgICAgIGlkLmluY2x1ZGVzKCdub2RlX21vZHVsZXMvZWNoYXJ0cy8nKSB8fFxuICAgICAgICAgICAgaWQuaW5jbHVkZXMoJ25vZGVfbW9kdWxlcy9lY2hhcnRzLWZvci1yZWFjdC8nKSB8fFxuICAgICAgICAgICAgaWQuaW5jbHVkZXMoJ25vZGVfbW9kdWxlcy96cmVuZGVyLycpXG4gICAgICAgICAgKSB7XG4gICAgICAgICAgICByZXR1cm4gJ2VjaGFydHMnO1xuICAgICAgICAgIH1cbiAgICAgICAgICBpZiAoaWQuaW5jbHVkZXMoJ25vZGVfbW9kdWxlcy9AenhpbmcvJykpIHtcbiAgICAgICAgICAgIHJldHVybiAnenhpbmcnO1xuICAgICAgICAgIH1cbiAgICAgICAgICBpZiAoaWQuaW5jbHVkZXMoJ25vZGVfbW9kdWxlcy9kYXlqcy8nKSkge1xuICAgICAgICAgICAgcmV0dXJuICdkYXlqcyc7XG4gICAgICAgICAgfVxuICAgICAgICB9LFxuICAgICAgfSxcbiAgICB9LFxuICB9LFxufSk7XG4iXSwKICAibWFwcGluZ3MiOiAiO0FBQSthLFNBQVMsb0JBQW9CO0FBQzVjLE9BQU8sV0FBVztBQUVsQixJQUFPLHNCQUFRLGFBQWE7QUFBQSxFQUMxQixTQUFTLENBQUMsTUFBTSxDQUFDO0FBQUEsRUFDakIsUUFBUTtBQUFBLElBQ04sTUFBTTtBQUFBLElBQ04sT0FBTztBQUFBLE1BQ0wsUUFBUTtBQUFBLE1BQ1IsWUFBWTtBQUFBLElBQ2Q7QUFBQSxFQUNGO0FBQUEsRUFDQSxPQUFPO0FBQUEsSUFDTCxRQUFRO0FBQUEsSUFDUixRQUFRO0FBQUEsSUFDUixjQUFjO0FBQUEsSUFDZCx1QkFBdUI7QUFBQSxJQUN2QixlQUFlO0FBQUEsTUFDYixRQUFRO0FBQUEsUUFDTixhQUFhLElBQUk7QUFDZixjQUNFLEdBQUcsU0FBUyxxQkFBcUIsS0FDakMsR0FBRyxTQUFTLHlCQUF5QixLQUNyQyxHQUFHLFNBQVMsZ0NBQWdDLEtBQzVDLEdBQUcsU0FBUyw0QkFBNEIsR0FDeEM7QUFDQSxtQkFBTztBQUFBLFVBQ1Q7QUFDQSxjQUNFLEdBQUcsU0FBUyxvQkFBb0IsS0FDaEMsR0FBRyxTQUFTLDJCQUEyQixLQUN2QyxHQUFHLFNBQVMsa0JBQWtCLEdBQzlCO0FBQ0EsbUJBQU87QUFBQSxVQUNUO0FBQ0EsY0FDRSxHQUFHLFNBQVMsdUJBQXVCLEtBQ25DLEdBQUcsU0FBUyxpQ0FBaUMsS0FDN0MsR0FBRyxTQUFTLHVCQUF1QixHQUNuQztBQUNBLG1CQUFPO0FBQUEsVUFDVDtBQUNBLGNBQUksR0FBRyxTQUFTLHNCQUFzQixHQUFHO0FBQ3ZDLG1CQUFPO0FBQUEsVUFDVDtBQUNBLGNBQUksR0FBRyxTQUFTLHFCQUFxQixHQUFHO0FBQ3RDLG1CQUFPO0FBQUEsVUFDVDtBQUFBLFFBQ0Y7QUFBQSxNQUNGO0FBQUEsSUFDRjtBQUFBLEVBQ0Y7QUFDRixDQUFDOyIsCiAgIm5hbWVzIjogW10KfQo=
