/**
 * 端到端探针:真实抓取 + 变更判定 + 影响面推断
 *
 * ⚠️ 这是**开发期探针**,不是门禁 —— 它打外部网站,不能进 CI。
 *    用法: npx tsx scripts/monitor-probe.ts [页数] [最大正文数]
 */
import {
  fetchReleases,
  fetchReleaseList,
} from "../src/interfaces/acl/moa-source.acl";
import {
  classifyChange,
  fingerprint,
  inferImpactScope,
  releaseKeyOf,
} from "../src/domain/monitoring/release-detector.service";

const pages = Number(process.argv[2] ?? 1);
const maxItems = Number(process.argv[3] ?? 3);

console.log(`=== 探针: 抓 ${pages} 页, 正文 ${maxItems} 条 ===\n`);

const t0 = Date.now();
const list = await fetchReleaseList(pages);
console.log(`[列表] 抓到 ${list.length} 条, 用时 ${Date.now() - t0}ms`);
for (const r of list.slice(0, 8)) {
  console.log(`   ${r.publishedAt ?? "?"} | ${r.title.slice(0, 42)}`);
}

console.log(`\n=== 抓正文(${maxItems} 条) ===`);
const withBody = await fetchReleases(pages, maxItems);
for (const r of withBody) {
  const scope = inferImpactScope({ ...r, releaseKey: releaseKeyOf(r) });
  const fp = fingerprint(r.body);
  console.log(
    `\n  ${r.title.slice(0, 50)}\n` +
      `    URL      ${r.url}\n` +
      `    主键     ${releaseKeyOf(r)}\n` +
      `    日期     ${r.publishedAt}\n` +
      `    正文     ${r.body.length} 字, 指纹 ${fp}\n` +
      `    变更     ${classifyChange({ ...r, releaseKey: releaseKeyOf(r) }, [])}\n` +
      `    影响面   determinable=${scope.determinable} assets=[${scope.affectedAssets.join(",")}]\n` +
      `    命中词   ${scope.matchedKeywords.slice(0, 8).join(" / ")}`
  );
  if (r.body) {
    console.log(`    正文首   ${r.body.slice(0, 160)}`);
  }
}
console.log(`\n=== 总用时 ${Date.now() - t0}ms ===`);
