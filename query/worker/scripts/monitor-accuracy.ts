/**
 * 误报率量化探针:抓 N 页,统计影响面推断的命中分布。
 *
 * ⚠️ 开发期探针,打外部网站,不进 CI。
 *    用法: npx tsx scripts/monitor-accuracy.ts [页数]
 */
import { fetchReleases } from "../src/interfaces/acl/moa-source.acl";
import {
  inferImpactScope,
  releaseKeyOf,
} from "../src/domain/monitoring/release-detector.service";

const pages = Number(process.argv[2] ?? 2);
console.log(`=== 抓 ${pages} 页全量正文,统计影响面命中 ===\n`);

const rels = await fetchReleases(pages, 999);
console.log(`共 ${rels.length} 条\n`);

const tally = new Map<string, number>();
const details: string[] = [];
let determinable = 0;

for (const r of rels) {
  const scope = inferImpactScope({ ...r, releaseKey: releaseKeyOf(r) });
  if (scope.determinable) determinable++;
  for (const a of scope.affectedAssets) {
    tally.set(a, (tally.get(a) ?? 0) + 1);
  }
  details.push(
    `${(scope.determinable ? "✔" : "·")} ${(r.title || "").slice(0, 40).padEnd(42)} ` +
      `[${scope.affectedAssets.join(",") || "-"}] ` +
      `词:${scope.matchedKeywords.slice(0, 4).join("/") || "-"} ` +
      `bodyLen=${r.body.length}`
  );
}

console.log(details.join("\n"));
console.log(`\n=== 命中统计 (${rels.length} 条, 可判定 ${determinable} 条) ===`);
for (const [k, v] of [...tally.entries()].sort((a, b) => b[1] - a[1])) {
  console.log(`  ${k.padEnd(22)} ${v}`);
}
console.log(
  `\n可判定率: ${((determinable / rels.length) * 100).toFixed(1)}%  ` +
    `误报嫌疑(可判定但命中词少): 见上面命中词只有 1 个且是泛词的`
);
