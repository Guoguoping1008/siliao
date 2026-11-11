/**
 * ⑤ 法规监测 · 领域层单测
 *
 * ⚠️ **测试用例基于真实抓下来的 HTML 样本**(`test-fixtures/`),
 *    不是手工构造的字符串 —— 构造的样本会让「解析器在真站点上失效」
 *    这种问题逃过测试。样本抓取日期见文件 mtime。
 *
 * 覆盖 ADR-006 的核心不变量:
 *   - 变更检测三级判定
 *   - 影响面算不出必须标 determinable=false
 *   - 抓不到正文时**不能**判为 revised(会把「抓取失败」误报成「公告被改」)
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  classifyChange,
  extractAnnouncementNo,
  extractPublishedAt,
  extractReleaseLinks,
  fingerprint,
  inferImpactScope,
  releaseKeyOf,
  stripTags,
  type Release,
} from "./release-detector.service";

const FIXTURES = join(__dirname, "../../../test-fixtures");
const listHtml = readFileSync(join(FIXTURES, "list.html"), "utf-8");
const articleHtml = readFileSync(join(FIXTURES, "article_1025.html"), "utf-8");

describe("⑤ 领域层 · 链接提取(真实 HTML 样本)", () => {
  const items = extractReleaseLinks(listHtml, "https://www.agri.cn/zx/hxgg/");

  it("从真实列表页抓到公告条目", () => {
    // 实测真实首页就是 10 条公告(第 11 条在第 2 页)
    expect(items.length).toBeGreaterThanOrEqual(10);
  });

  it("抓到的是真公告而不是「阅读更多」", () => {
    for (const it of items) {
      expect(it.title).not.toContain("阅读更多");
      expect(it.title.length).toBeGreaterThan(4);
    }
  });

  it("⚠️ 页脚导航链接不被当成公告(真实 bug 回归)", () => {
    // 实测真实列表页里「关于我们」「网站声明」「联系我们」的 URL 形如
    // /dbxx/202311/t20231108_8053689.htm —— 同样匹配日期路径模式,
    // 只靠日期模式会把它们抓进来。
    const titles = items.map((i) => i.title);
    for (const junk of ["关于我们", "网站声明", "联系我们"]) {
      expect(titles).not.toContain(junk);
    }
    // 且每条都必须落在公告栏目段内
    for (const it of items) {
      expect(it.url).toContain("/zx/hxgg/");
    }
  });

  it("每条都带绝对 URL", () => {
    for (const it of items) {
      expect(it.url.startsWith("https://")).toBe(true);
    }
  });

  it("URL 去重", () => {
    const urls = items.map((i) => i.url);
    expect(new Set(urls).size).toBe(urls.length);
  });

  it("至少一条标题含公告号(权威主键可用)", () => {
    const withNo = items.filter((i) => extractAnnouncementNo(i.title));
    expect(withNo.length).toBeGreaterThan(0);
  });

  it("至少一条能解析出发布日期", () => {
    const withDate = items.filter((i) => i.publishedAt);
    expect(withDate.length).toBeGreaterThan(0);
  });
});

describe("⑤ 领域层 · 公告号与日期解析", () => {
  it("抽公告号(无空格)", () => {
    expect(extractAnnouncementNo("中华人民共和国农业农村部公告 第1025号")).toBe("第1025号");
  });

  it("抽公告号(有空格)", () => {
    expect(extractAnnouncementNo("农业农村部公告 第 1080 号")).toBe("第1080号");
  });

  it("没有公告号返回 null", () => {
    expect(extractAnnouncementNo("关于印发某规划的通知")).toBeNull();
  });

  it("从路径抽发布日期", () => {
    expect(extractPublishedAt("https://www.agri.cn/zx/hxgg/202606/t20260604_8841931.htm")).toBe(
      "2026-06-04"
    );
  });

  it("路径不含日期返回 null", () => {
    expect(extractPublishedAt("https://www.agri.cn/zx/hxgg/index.htm")).toBeNull();
  });
});

describe("⑤ 领域层 · 指纹", () => {
  it("相同正文同指纹", () => {
    expect(fingerprint("鱼类 3000 IU/kg")).toBe(fingerprint("鱼类 3000 IU/kg"));
  });

  it("排版差异(空白/全角空格)不改变指纹", () => {
    expect(fingerprint("鱼类 3000 IU/kg")).toBe(fingerprint("鱼类　3000  IU/kg"));
  });

  it("内容变化指纹变化", () => {
    expect(fingerprint("鱼类 3000 IU/kg")).not.toBe(fingerprint("鲑科鱼 60000 IU/kg"));
  });

  it("空正文返回空串(不能与任何正文相等)", () => {
    expect(fingerprint("")).toBe("");
    expect(fingerprint("   ")).toBe("");
  });
});

describe("⑤ 领域层 · 变更判定(ADR-006 §4)", () => {
  const base: Release = {
    releaseKey: "第1025号",
    title: "中华人民共和国农业农村部公告 第1025号",
    url: "https://www.agri.cn/zx/hxgg/202606/t20260604_8841931.htm",
    publishedAt: "2026-06-04",
    body: "将鱼类 3000 IU/kg 修改为鲑科鱼 60000 IU/kg、其他鱼 3000 IU/kg",
  };

  it("未知公告号 → new", () => {
    expect(classifyChange(base, [])).toBe("new");
  });

  it("同公告号 + 同指纹 → unchanged", () => {
    const known = [{ releaseKey: "第1025号", fingerprint: fingerprint(base.body) }];
    expect(classifyChange(base, known)).toBe("unchanged");
  });

  it("同公告号 + 不同指纹 → revised", () => {
    const known = [{ releaseKey: "第1025号", fingerprint: "deadbeef" }];
    expect(classifyChange(base, known)).toBe("revised");
  });

  it("⚠️ 抓不到正文时不能判 revised(会把抓取失败误报成公告被改)", () => {
    const noBody = { ...base, body: "" };
    const known = [{ releaseKey: "第1025号", fingerprint: "deadbeef" }];
    expect(classifyChange(noBody, known)).toBe("unchanged");
  });

  it("⚠️ 已知记录没指纹时也不能判 revised", () => {
    const known = [{ releaseKey: "第1025号", fingerprint: "" }];
    expect(classifyChange(base, known)).toBe("unchanged");
  });
});

describe("⑤ 领域层 · 影响面推断(ADR-004 不变量)", () => {
  it("抓到 D3 鲑科鱼限量修订 → 命中 limit_rules", () => {
    const rel: Release = {
      releaseKey: "第1025号",
      title: "中华人民共和国农业农村部公告 第1025号",
      url: "https://www.agri.cn/zx/hxgg/202606/t20260604_8841931.htm",
      publishedAt: "2026-06-04",
      body: "修订《饲料添加剂安全使用规范》维生素D3最高限量,将鱼类3000 IU/kg修改为鲑科鱼60000 IU/kg",
    };
    const scope = inferImpactScope(rel);
    expect(scope.determinable).toBe(true);
    expect(scope.affectedAssets).toContain("limit_rules");
    expect(scope.impacted).toBe(true);
  });

  it("⚠️ 没抓到正文 → 影响面不可判定,不得推送", () => {
    const rel: Release = {
      releaseKey: "第X号",
      title: "中华人民共和国农业农村部公告 第X号",
      url: "https://www.agri.cn/zx/hxgg/202611/t20261109_1.htm",
      publishedAt: "2026-11-09",
      body: "",
    };
    const scope = inferImpactScope(rel);
    expect(scope.determinable).toBe(false);
  });

  it("正文够长但没命中关键词 → 不可判定", () => {
    const rel: Release = {
      releaseKey: "第Y号",
      title: "全国执业兽医资格考试委员会公告",
      url: "https://www.agri.cn/zx/hxgg/202611/t20261109_2.htm",
      publishedAt: "2026-11-09",
      body: "本年度全国执业兽医资格考试相关事宜通知如下,请各考点按照规定组织考试工作安排。",
    };
    const scope = inferImpactScope(rel);
    expect(scope.impacted).toBe(false);
    expect(scope.determinable).toBe(false);
  });

  it("目录修订 → 命中 substance_catalog", () => {
    const rel: Release = {
      releaseKey: "第1028号",
      title: "中华人民共和国农业农村部公告 第1028号",
      url: "https://www.agri.cn/zx/hxgg/202606/t20260611_8843653.htm",
      publishedAt: "2026-06-04",
      body: "对《饲料原料目录》进行修订,增补83种饲料原料,修订173种饲料原料",
    };
    const scope = inferImpactScope(rel);
    expect(scope.affectedAssets).toContain("substance_catalog");
  });

  it("禁用相关 → 命中 prohibition_rules", () => {
    const rel: Release = {
      releaseKey: "第Z号",
      title: "农业农村部公告",
      url: "https://www.agri.cn/zx/hxgg/202611/t20261109_3.htm",
      publishedAt: "2026-11-09",
      body: "禁止在饲料中使用某某物质,不得在饲料中添加,现予公告。",
    };
    const scope = inferImpactScope(rel);
    expect(scope.affectedAssets).toContain("prohibition_rules");
  });

  it("标签相关 → 命中 label_rules", () => {
    const rel: Release = {
      releaseKey: "第W号",
      title: "关于修改饲料标签要求的通知",
      url: "https://www.agri.cn/zx/hxgg/202611/t20261109_4.htm",
      publishedAt: "2026-11-09",
      body: "按照GB 10648饲料标签标准的要求,对标签标示内容作出修订。",
    };
    const scope = inferImpactScope(rel);
    expect(scope.affectedAssets).toContain("label_rules");
  });
});

describe("⑤ 领域层 · 主键", () => {
  it("优先用公告号", () => {
    const rel: Release = {
      releaseKey: "",
      title: "中华人民共和国农业农村部公告 第1025号",
      url: "https://www.agri.cn/zx/hxgg/202606/t20260604_8841931.htm",
      publishedAt: "2026-06-04",
      body: "x",
    };
    expect(releaseKeyOf(rel)).toBe("第1025号");
  });

  it("⚠️ 没公告号时回退 URL(不用标题 —— 标题会改)", () => {
    const rel: Release = {
      releaseKey: "",
      title: "某通知",
      url: "https://www.agri.cn/zx/hxgg/202611/t20261109_9.htm",
      publishedAt: "2026-11-09",
      body: "x",
    };
    expect(releaseKeyOf(rel)).toBe("https://www.agri.cn/zx/hxgg/202611/t20261109_9.htm");
  });
});

describe("⑤ 领域层 · 正文样本可解析(真实文章页)", () => {
  it("真实文章页的正文长度合理(说明样本不是空壳)", () => {
    const text = stripTags(articleHtml);
    expect(text.length).toBeGreaterThan(1000);
  });

  it("真实文章页含 D3 限量修订的关键信息", () => {
    const text = stripTags(articleHtml);
    expect(text).toContain("鲑科鱼");
  });
});

describe("⑤ 领域层 · 抗脆弱(ADR-006 §3)", () => {
  it("列表页结构变了但 URL 模式还在 → 仍能抓到条目", () => {
    // 模拟改版:剥掉所有 class/id,只留 href 与文本
    const mangled = listHtml.replace(/class="[^"]*"/g, "").replace(/id="[^"]*"/g, "");
    const items = extractReleaseLinks(mangled, "https://www.agri.cn/zx/hxgg/");
    expect(items.length).toBeGreaterThanOrEqual(10);
  });

  it("完全不含日期路径的链接不被抓(避免把导航链接当公告)", () => {
    const junk = '<a href="./index.htm">首页</a><a href="https://www.agri.cn/">部网站</a>';
    expect(extractReleaseLinks(junk, "https://www.agri.cn/zx/hxgg/")).toHaveLength(0);
  });
});
