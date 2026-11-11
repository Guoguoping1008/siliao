/**
 * 逐条打印「可判定」公告的正文,人工核对影响面推断准不准。
 * ⚠️ 开发期探针,不进 CI。
 */
import { fetchReleases } from "../src/interfaces/acl/moa-source.acl";
import { inferImpactScope, releaseKeyOf } from "../src/domain/monitoring/release-detector.service";

const pages = Number(process.argv[2] ?? 3);
const rels = await fetchReleases(pages, 999);

for (const r of rels) {
  const scope = inferImpactScope({ ...r, releaseKey: releaseKeyOf(r) });
  if (!scope.determinable) continue;
  console.log("\n" + "=".repeat(78));
  console.log(`【${r.title.slice(0, 60)}】`);
  console.log(`命中词: ${scope.matchedKeywords.join(" / ")}`);
  console.log(`推断资产: ${scope.affectedAssets.join(", ")}`);
  console.log("--- 正文 ---");
  console.log(r.body.slice(0, 700));
}
