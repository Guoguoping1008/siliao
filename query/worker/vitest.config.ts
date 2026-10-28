import { defineConfig } from "vitest/config";

/**
 * Worker 单元测试配置。
 *
 * ⚠️ 与 web/ 的 vitest 配置**故意分开**:
 *    web/ 是 jsdom 环境(React 组件测试), worker/ 是纯 node 环境
 *    (领域层纯函数测试, 不需要 DOM)。
 *
 * 测试范围: src 下的 test/spec 文件
 *   - 覆盖 domain/ (纯函数, 100% 可测)
 *   - 覆盖 application/ (可注入 mock)
 *   - 覆盖 infrastructure/ 的纯逻辑部分 (mapper / 融合)
 */
export default defineConfig({
  test: {
    environment: "node",
    globals: true,
    include: ["src/**/*.{test,spec}.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/domain/**", "src/application/**"],
      exclude: ["node_modules/", "dist/", "**/*.d.ts"],
    },
  },
});
