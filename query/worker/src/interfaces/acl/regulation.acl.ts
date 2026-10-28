/**
 * 法规正文防腐层 (ACL)
 *
 * 上下文: ① 法规知识库 Regulation 的外部依赖
 *
 * 正文来自 D1 的 `articles.body`。但**「怎么把 markdown 正文变成可展示的
 * 摘要文本」是外部格式问题**, 不该渗透进领域层 ——
 * 领域层只知道 Evidence.excerpt 是字符串。
 *
 * ## 纯度边界 (ADR-004 R3)
 *
 * 领域层**不得**出现 fetch() / R2 访问。
 */

/**
 * 把 markdown 正文清洗成可读纯文本。
 *
 * ⚠️ 2026-10-27 修: 检索结果的 excerpt 直接塞 markdown 原文, 前端用
 *    `<p>{excerpt}</p>` 渲染 → `### 第三条` / `#### 兽药管理条例` 这种
 *    标记**原样显示**给用户, 很难看。
 *
 *    对策: 去掉 markdown 标记, 只留可读正文。
 *    ⚠️ 必须是「去掉标记但保留换行」—— 不能压成一行, 否则正文会挤成一坨。
 */
export function plainExcerpt(body: string, maxLen = 600): string {
  const s = (body || "")
    // 标题行: `### 第三条` → `第三条`(去掉前导 # 和空格)
    .replace(/^#{1,6}\s*/gm, "")
    // 表格分隔行 `|---|---|` → 去掉整行
    .replace(/^\s*\|[\s|:-]+\|\s*$/gm, "")
    // 行内标记: **粗体** __高亮__ `代码`
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/__(.+?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    // 图片/链接: ![alt](url) → alt, [text](url) → text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    // 引用块 > 和列表符号 -/*/数字.
    .replace(/^\s*>\s?/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    // 水平线
    .replace(/^\s*(-{3,}|\*{3,}|_{3,})\s*$/gm, "")
    // 连续空行压成一个
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return s.length > maxLen ? s.slice(0, maxLen).trim() + "…" : s;
}

/**
 * R2 object key 构造。
 *
 * ⚠️ R2 存的 key 是 **URL-encoded** 形式(中文 → %E5%B0%81...),
 *    而 D1 里 r2_object_key 存的是**原始中文**。
 *    直接用原始中文 key 去 get() 会 404 —— miniflare 不会自动 encode。
 *    实测: 2180 个对象在 R2 里, 但 excerpt 全是空。
 *
 * 对策: 统一走本函数编码后再取。
 * R2 真实环境(Cloudflare)对 key 的编码要求比 miniflare 宽松,
 * 但 encodeURIComponent 对纯 ASCII key 是幂等的, 两边都能用。
 *
 * 注: 2026-10-26 后正文改存 D1, R2 路径已非主路径, 但兼容逻辑保留。
 */
export function r2Key(
  objKey: string | null | undefined,
  fallbackDocId: string,
  kind: "articles" | "chapters"
): string {
  if (!objKey) return `${fallbackDocId}/${kind}/`;
  // 已经是完整 key(含 "/")就直接用
  const key = objKey.includes("/") ? objKey : `${fallbackDocId}/${kind}/${objKey}`;
  // 逐段 encode, 但保留 "/" 分隔符
  return key.split("/").map(encodeURIComponent).join("/");
}
