// PostCSS 配置 —— **必须有这个文件**,否则 Tailwind 不生效。
//
// ⚠️ 2026-10-27 修: 项目一直缺 postcss.config.js, 于是 Vite 找不到
//    Tailwind 插件, `@tailwind base/components/utilities` 三行**原样输出**
//    到产物 CSS 里 —— 线上页面完全没有样式(CSS 只有 146 字节)。
//    症状: 页面能开、能用, 但排版全乱(没有 Tailwind 预检和工具类)。
//
// 为什么之前没暴露: e2e 测的是 mock 模式, 断言只看文本内容, 不看样式;
// dist 里的 CSS 有 146 字节也不影响功能断言。
//
// Vite 内置了 postcss, 只要给它一个含 tailwindcss 插件的配置即可。
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
