/**
 * 召回率验证:用**已知的历史变更公告**验证影响面推断没漏报。
 *
 * 这几条是从搜索里实抓到的真变更公告,它们的「应该被命中」是确定的:
 *   第1025号 —— 修订《饲料添加剂安全使用规范》维生素D3 鲑科鱼 60000 IU/kg
 *   第1028号 —— 修订《饲料原料目录》增补 83 种原料
 *   第1027号 —— 制定《发酵饲料管理规定》
 *
 * ⚠️ 开发期探针,不进 CI(URL 是硬编码的,站点可能删帖)。
 */
import { fetchReleaseBody } from "../src/interfaces/acl/moa-source.acl";
import { inferImpactScope, releaseKeyOf, type Release } from "../src/domain/monitoring/release-detector.service";

const CASES = [
  {
    no: "第1025号",
    url: "https://www.agri.cn/zx/hxgg/202606/t20260604_8841931.htm",
    expect: ["limit_rules"],
    why: "修订《饲料添加剂安全使用规范》维生素D3 鲑科鱼 60000 IU/kg",
  },
  {
    no: "第1028号",
    url: "https://www.agri.cn/zx/hxgg/202606/t20260611_8843653.htm",
    expect: ["substance_catalog"],
    why: "修订《饲料原料目录》增补 83 种饲料原料、修订 173 种",
  },
  {
    no: "第1027号",
    url: "https://www.agri.cn/zx/hxgg/202606/t20260611_8843636.htm",
    expect: [], // 《发酵饲料管理规定》是新规,不在现有关键词表里 —— 看它是否至少命中领域
    why: "制定《发酵饲料管理规定》",
  },
];

let hit = 0;
for (const c of CASES) {
  const body = await fetchReleaseBody(c.url);
  const rel: Release = {
    releaseKey: "",
    title: `中华人民共和国农业农村部公告 ${c.no}`,
    url: c.url,
    publishedAt: null,
    body,
  };
  const scope = inferImpactScope(rel);
  const ok = c.expect.every((a) => scope.affectedAssets.includes(a));
  if (ok) hit++;
  console.log(`\n${ok ? "✅" : "❌"} ${c.no} — ${c.why}`);
  console.log(`   正文 ${body.length} 字`);
  console.log(`   命中词: ${scope.matchedKeywords.join(" / ") || "-"}`);
  console.log(`   推断资产: ${scope.affectedAssets.join(", ") || "-"}  (期望含 ${c.expect.join(",") || "无"})`);
  console.log(`   determinable=${scope.determinable}`);
}
console.log(`\n=== 召回 ${hit}/${CASES.length} ===`);
