/**
 * 政府法规源 · 防腐层 (ACL)
 *
 * 上下文: ⑤ 法规监测 Monitoring 的外部依赖
 *
 * ## 为什么需要 ACL
 *
 * `www.agri.cn` 的 HTML 结构是**外部概念** —— 站点改版是常态,
 * 不该渗透进领域层。领域层只知道「给我一份公告列表 / 一份公告正文」,
 * 不知道 URL 长什么样、正文在哪个 `<div>` 里、翻页参数叫什么。
 *
 * ## 纯度边界 (ADR-004 R3)
 *
 * 领域层**不得**出现 fetch()。所有对政府网站的访问必须经过这里。
 * 架构测试会扫 `domain/` 与 `application/`,发现 `fetch(` 即失败。
 *
 * ## 数据源选型依据 (ADR-006 §1)
 *
 * 实测 3 个候选源,结论:
 *   - `www.moa.gov.cn/govpublic/...` → 是司局索引页,不是公告列表 ❌
 *   - `www.moa.gov.cn/xmsyj/...`    → 404 ❌
 *   - `www.agri.cn/zx/hxgg/`        → ✅ 链接路径编码日期,正文可提取,分页到 index_19
 *
 * RSS / JSON / sitemap 全部 404 —— 政府网站没有机器可读接口,只能解析 HTML。
 */

import { extractReleaseLinks, stripTags, type Release } from "../../domain/monitoring/release-detector.service";

/** 主源: 中国农业农村信息网 · 行业信息 · 公告 */
export const PRIMARY_LIST_URL = "https://www.agri.cn/zx/hxgg/";

/** 实测可达的最大分页号 */
export const MAX_PAGE = 19;

/** 抓取配置。 */
export interface FetchOptions {
  /** 超时毫秒 */
  timeoutMs?: number;
  /** 重试次数 */
  attempts?: number;
}

/**
 * 带超时与重试的抓取。
 *
 * ⚠️ 政府网站偶发 5xx 与连接超时是常态,必须重试。
 *    但**失败不能静默** —— 抛出去让上层记 `monitoring_runs` 并告警。
 */
async function fetchText(url: string, opts: FetchOptions = {}): Promise<string> {
  const timeoutMs = opts.timeoutMs ?? 20000;
  const attempts = opts.attempts ?? 3;
  const UA =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";

  let lastErr: unknown;
  for (let i = 0; i < attempts; i++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, {
        headers: { "User-Agent": UA, Accept: "text/html,application/xhtml+xml" },
        signal: ctrl.signal,
        redirect: "follow",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
      const buf = await res.arrayBuffer();
      // 政府网站有 GB2312/GBK 页面 —— 用 UTF-8 解,解不出中文再试 GBK
      const utf8 = new TextDecoder("utf-8").decode(buf);
      if (utf8.includes("�")) {
        try {
          return new TextDecoder("gbk").decode(buf);
        } catch {
          return utf8;
        }
      }
      return utf8;
    } catch (e) {
      lastErr = e;
      if (i < attempts - 1) {
        await new Promise((r) => setTimeout(r, 500 * (i + 1)));
      }
    } finally {
      clearTimeout(timer);
    }
  }
  throw new Error(
    `抓取失败 ${url} (${attempts} 次): ${lastErr instanceof Error ? lastErr.message : String(lastErr)}`
  );
}

/**
 * 抓公告列表(可翻页)。
 *
 * @param pages 要抓的页数(1 = 只首页)
 * @returns 去重后的公告条目(不含正文)
 */
export async function fetchReleaseList(
  pages = 1,
  opts: FetchOptions = {}
): Promise<Release[]> {
  const out: Release[] = [];
  const seen = new Set<string>();

  for (let p = 0; p < Math.min(pages, MAX_PAGE); p++) {
    const url = p === 0 ? PRIMARY_LIST_URL : `${PRIMARY_LIST_URL}index_${p + 1}.htm`;
    const html = await fetchText(url, opts);
    const items = extractReleaseLinks(html, url);
    let added = 0;
    for (const it of items) {
      if (seen.has(it.url)) continue;
      seen.add(it.url);
      out.push(it);
      added++;
    }
    // ⚠️ 翻到空页就停 —— 站点的实际页数可能少于 MAX_PAGE
    if (added === 0) break;
  }
  return out;
}

/**
 * 抓公告正文(纯文本)。
 *
 * ## 抗脆弱策略 (ADR-006 §3)
 *
 * 政府网站正文容器 class 会变。三级降级:
 *   ① 按 id/class 匹配 `content` / `TRS_Editor` / `article`
 *   ② 回退「取最长的一段连续 `<p>`」
 *   ③ 回退「全文去标签」
 *
 * 每次降级都会让正文变脏,但**不会让整条抓取失败** ——
 * 抓不到正文时代码仍能入库,只是影响面判定会标 `determinable=false`。
 */
export async function fetchReleaseBody(
  url: string,
  opts: FetchOptions = {}
): Promise<string> {
  const html = await fetchText(url, opts);

  // ① 容器匹配
  const containerRe =
    /<div[^>]*(?:id|class)=["'][^"']*(?:content|TRS_Editor|article|zhengwen|detail)[^"']*["'][^>]*>([\s\S]*?)<\/div>\s*(?:<\/div>|<div)/i;
  const m1 = html.match(containerRe);
  if (m1) {
    const text = stripTags(m1[1]).trim();
    if (text.length >= 40) return text;
  }

  // ② 最长连续 <p> 块
  const paras = html.match(/<p[^>]*>[\s\S]*?<\/p>/gi) ?? [];
  let best = "";
  let bestLen = 0;
  for (let i = 0; i < paras.length; i++) {
    let acc = "";
    for (let j = i; j < Math.min(i + 12, paras.length); j++) {
      acc += stripTags(paras[j]) + " ";
    }
    const len = acc.trim().length;
    if (len > bestLen) {
      bestLen = len;
      best = acc.trim();
    }
  }
  if (bestLen >= 40) return best;

  // ③ 全文去标签
  const all = stripTags(html).trim();
  return all.length >= 40 ? all : "";
}

/**
 * 抓完整的公告集合(列表 + 正文)。
 *
 * ⚠️ **正文抓取是逐条串行** —— 对政府网站并发压测不礼貌,且容易被封。
 *    一页约 20 条,单页全量抓取约 20-40 秒。
 *
 * @param maxItems 最多抓多少条正文(0 = 只要列表不要正文)
 */
export async function fetchReleases(
  pages = 1,
  maxItems = 0,
  opts: FetchOptions = {}
): Promise<Release[]> {
  const list = await fetchReleaseList(pages, opts);
  if (maxItems <= 0) return list;

  const limited = list.slice(0, maxItems);
  for (const r of limited) {
    try {
      r.body = await fetchReleaseBody(r.url, opts);
    } catch (e) {
      // ⚠️ 单条正文失败**不阻断整批** —— 留空 body,
      //    上层会把它标成 `determinable=false`(影响面未知,不推送)
      r.body = "";
      console.warn(
        `[monitoring] 正文抓取失败 ${r.url}: ${e instanceof Error ? e.message : String(e)}`
      );
    }
  }
  return limited;
}
