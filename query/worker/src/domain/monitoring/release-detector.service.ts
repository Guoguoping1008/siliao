/**
 * ⑤ 法规监测 · 领域层 —— 变更检测的纯判定逻辑
 *
 * 上下文: ⑤ 法规监测 Monitoring (支撑域)
 *
 * ## 纯度边界 (ADR-004 R5 + R3)
 *
 * 本文件**零 I/O、零框架依赖**。不 import Workers / D1 类型,不做 fetch。
 * 所有外部交互(抓政府网站)在 `interfaces/acl/moa-source.acl.ts`。
 *
 * ## 为什么判定逻辑值得单独成文件
 *
 * 「这份公告是不是变更?变更影响到什么?」是**业务规则**,不是技术细节:
 * - 「影响面算不出就必须标未知,不推送」是 ADR-004 写死的不变量
 * - 「不自动改数据」是因为 ② 合规规则有「未审核不参与判定」的闸门,
 *   自动改规则会绕过它
 *
 * 这些判定如果散在爬虫脚本里,就没有地方能单测,也没地方能审。
 */

/** 一条被抓到的法规发布。 */
export interface Release {
  /** 权威唯一标识 —— 公告号(如「第1025号」)。抓不到时回退为 URL。 */
  releaseKey: string;
  /** 公告标题 */
  title: string;
  /** 完整 URL */
  url: string;
  /** 路径里解析出的发布日期(YYYY-MM-DD),抓不到则 null */
  publishedAt: string | null;
  /** 正文纯文本(已去标签)。抓不到正文时为空串。 */
  body: string;
}

/** 正文指纹 —— 用于判断「同一份公告是否被改过」。 */
export function fingerprint(body: string): string {
  // 归一化: 去空白 + 只留数字字母汉字,避免排版变化造成假阳性
  const normalized = body.replace(/[\s　]+/g, "").replace(/[^\p{L}\p{N}]/gu, "");
  if (!normalized) return "";
  // FNV-1a 32bit —— 够用且无需依赖
  let h = 0x811c9dc5;
  for (let i = 0; i < normalized.length; i++) {
    h ^= normalized.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

/** 从标题里抽公告号,抽不到返回 null。 */
export function extractAnnouncementNo(title: string): string | null {
  // 形如「第1025号」「第 1025 号」「公告第1080号」
  const m = title.match(/第\s*(\d{3,5})\s*号/);
  return m ? `第${m[1]}号` : null;
}

/** 从 URL 路径抽发布日期(YYYY-MM-DD)。 */
export function extractPublishedAt(url: string): string | null {
  // 形如 /202611/t20261109_8882458.htm → 2026-11-09
  const m = url.match(/\/t(\d{4})(\d{2})(\d{2})_/);
  if (!m) return null;
  const [, y, mo, d] = m;
  return `${y}-${mo}-${d}`;
}

/**
 * 影响面推断 —— 关键词 → 受影响的合规资产。
 *
 * ⚠️ **这是启发式推断,不是结论。** 命中只说明「可能受影响」,
 * 最终判定仍要人工校核(ADR-006 §4)。
 */
export interface ImpactScope {
  /** 是否命中了任何受控关键词 */
  impacted: boolean;
  /** 命中的关键词 */
  matchedKeywords: string[];
  /** 受影响的资产类型 */
  affectedAssets: ImpactAsset[];
  /** 影响面是否可判定 */
  determinable: boolean;
}

export type ImpactAsset =
  | "limit_rules" // ② 的限量规则(安全使用规范修订)
  | "substance_catalog" // ② 的物质目录(品种目录/原料目录修订)
  | "prohibition_rules" // ② 的禁用规则(新增禁用物质)
  | "label_rules" // ③ 的标签审查(GB 10648 相关)
  | "species_scope"; // 适用范围变化(某物质扩大/缩小适用范围)

/**
 * 受控关键词表。
 *
 * ⚠️ 这张表需要人工维护 —— ADR-006 的还债触发器:
 *    关键词表命中率 < 50%(抽查 20 条公告)→ 扩表。
 */
const KEYWORD_RULES: Array<{ keyword: string; asset: ImpactAsset }> = [
  { keyword: "饲料添加剂安全使用规范", asset: "limit_rules" },
  { keyword: "最高限量", asset: "limit_rules" },
  { keyword: "限量", asset: "limit_rules" },
  { keyword: "推荐添加量", asset: "limit_rules" },
  { keyword: "使用量", asset: "limit_rules" },

  { keyword: "饲料添加剂品种目录", asset: "substance_catalog" },
  { keyword: "饲料原料目录", asset: "substance_catalog" },
  { keyword: "增补", asset: "substance_catalog" },
  { keyword: "修订", asset: "substance_catalog" },

  { keyword: "禁止使用", asset: "prohibition_rules" },
  { keyword: "不得使用", asset: "prohibition_rules" },
  { keyword: "禁止在饲料", asset: "prohibition_rules" },
  { keyword: "不得在饲料", asset: "prohibition_rules" },
  { keyword: "禁用的", asset: "prohibition_rules" },

  { keyword: "标签", asset: "label_rules" },
  { keyword: "GB 10648", asset: "label_rules" },
  { keyword: "GB10648", asset: "label_rules" },

  { keyword: "适用范围", asset: "species_scope" },
  { keyword: "扩大适用", asset: "species_scope" },
  { keyword: "适用范围扩大", asset: "species_scope" },
];

/**
 * 推断影响面。
 *
 * @param release 待判定的公告
 * @returns 影响面。`determinable=false` 时**不得推送**(ADR-004 不变量)。
 */
export function inferImpactScope(release: Release): ImpactScope {
  const haystack = `${release.title}\n${release.body}`;
  const matchedKeywords: string[] = [];
  const affectedAssets = new Set<ImpactAsset>();

  for (const rule of KEYWORD_RULES) {
    if (haystack.includes(rule.keyword)) {
      matchedKeywords.push(rule.keyword);
      affectedAssets.add(rule.asset);
    }
  }

  // ⚠️ 判定「影响面可判定」的条件:
  //    ① 抓到了正文(没正文 → 看不到「限量改了」这种关键信息,不能算可判定)
  //    ② 命中了至少一个受控关键词
  //    两个条件缺一不可 —— 否则一律 `determinable=false`,不推送。
  const hasBody = release.body.trim().length >= 40;
  const impacted = matchedKeywords.length > 0;
  const determinable = hasBody && impacted;

  return {
    impacted,
    matchedKeywords,
    affectedAssets: [...affectedAssets],
    determinable,
  };
}

/** 变更类型。 */
export type ChangeType = "new" | "revised" | "unchanged";

/** 已入库的发布记录(用于判重)。 */
export interface KnownRelease {
  releaseKey: string;
  fingerprint: string;
}

/**
 * 判定一个抓到的公告相对于已知状态是什么变更。
 *
 * 三级判定(ADR-006 §4):
 *   ① 公告号相同 + 指纹不同 → `revised`(公告被修订)
 *   ② 公告号未知           → `new`
 *   ③ 公告号相同 + 指纹相同 → `unchanged`
 */
export function classifyChange(
  release: Release,
  known: KnownRelease[]
): ChangeType {
  const fp = fingerprint(release.body);
  const existing = known.find((k) => k.releaseKey === release.releaseKey);
  if (!existing) return "new";
  // 指纹为空(没抓到正文)时**不能判为 revised** —— 会把「抓取失败」误报成「公告被改」
  if (!fp || !existing.fingerprint) return "unchanged";
  return fp === existing.fingerprint ? "unchanged" : "revised";
}

/**
 * 生成一条发布记录的稳定主键。
 *
 * 优先用公告号(权威唯一);抓不到则回退完整 URL。
 * ⚠️ 不用标题 —— 标题会改,标题做主键会导致同一份公告被当成两份。
 */
export function releaseKeyOf(release: Release): string {
  return extractAnnouncementNo(release.title) ?? release.url;
}

/**
 * 从列表页 HTML 里提取公告条目。
 *
 * ⚠️ **刻意不依赖列表页的结构** —— 只匹配 URL 里的日期路径模式
 *    `t\d{8}_\d+\.htm`。这是 ADR-006 §3 的抗脆弱核心:
 *    列表页 HTML 改版只会影响标题提取,不会导致「一条都抓不到」。
 *
 * ⚠️ **但日期路径模式本身不够严** —— 实测真实列表页里,页脚导航链接
 *    「关于我们」「网站声明」「联系我们」的 URL 形如
 *    `/dbxx/202311/t20231108_8053689.htm`,**同样匹配日期路径**。
 *    纯日期模式会把它们当成公告抓进来。
 *    所以额外要求 **路径中含公告栏目段**(如 `/zx/hxgg/`)。
 *    这不是「依赖结构」—— 栏目段比 class/id 稳定得多,改版时几乎不动。
 *
 * @param html 列表页 HTML
 * @param baseUrl 列表页 URL(用于拼接相对路径 + 推导栏目段)
 */
export function extractReleaseLinks(html: string, baseUrl: string): Release[] {
  const out: Release[] = [];
  const seen = new Set<string>();

  // 从 baseUrl 推导栏目段,如 "https://www.agri.cn/zx/hxgg/" → "/zx/hxgg/"
  const section = sectionPrefix(baseUrl);

  // 匹配 <a href="....">标题</a>,只取 href 符合日期路径的
  const re = /<a[^>]+href=["']([^"']*t\d{8}_\d+\.htm)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) {
    const href = m[1];
    const title = stripTags(m[2]).trim();
    // 「阅读更多 >」这类锚文本不是标题
    if (!title || title.startsWith("阅读更多") || title.length < 4) continue;

    const url = absoluteUrl(href, baseUrl);
    // ⚠️ 必须落在公告栏目段内 —— 否则页脚「关于我们」之类会被当成公告
    if (section && !url.includes(section)) continue;
    if (seen.has(url)) continue;
    seen.add(url);

    out.push({
      releaseKey: "",
      title,
      url,
      publishedAt: extractPublishedAt(url),
      body: "",
    });
  }
  return out;
}

/**
 * 从列表页 URL 推导栏目段。
 *
 * `https://www.agri.cn/zx/hxgg/` → `/zx/hxgg/`
 * `https://www.agri.cn/zx/hxgg/index_2.htm` → `/zx/hxgg/`
 *
 * ⚠️ 末段是**目录名**(hxgg)时不能切 —— 切了会得到 `/zx/`,
 *    过滤不掉页脚链接(`/dbxx/...)。只有末段是**文件名**时才切。
 */
export function sectionPrefix(listUrl: string): string {
  try {
    const u = new URL(listUrl);
    const segs = u.pathname.split("/").filter(Boolean);
    if (segs.length === 0) return "";
    const last = segs[segs.length - 1];
    // 末段像文件名(index.htm / index_2.htm / xxx.htm)→ 切掉
    const dir = /\.htm(l)?$/i.test(last) ? segs.slice(0, -1) : segs;
    if (dir.length === 0) return "";
    return "/" + dir.join("/") + "/";
  } catch {
    return "";
  }
}

/** 拼接相对 URL。 */
export function absoluteUrl(href: string, baseUrl: string): string {
  if (/^https?:\/\//i.test(href)) return href;
  try {
    return new URL(href, baseUrl).toString();
  } catch {
    return href;
  }
}

/** 去 HTML 标签。 */
export function stripTags(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, " ");
}
