/**
 * 检索 + 图谱 路由 —— 接口层
 *
 * 上下文: ① 法规知识库(检索) / ④ 知识图谱(图谱)
 *
 * 路由:
 *   GET /api/search?q=...    检索条文 (FTS5 + bge hybrid)
 *   GET /api/entity/:name    实体卡 + 关联条文
 *
 * ⚠️ ④ 图谱当前是**空壳** —— `entities` 表实测为空, `/api/entity/:name`
 *    恒返回 `entity_not_found`。前端组件已就位, 等数据。
 */

import { json, decodeParam } from "../http-utils";
import type { AppDependencies } from "../../composition-root";

/** GET /api/search */
export function handleSearch(
  app: AppDependencies,
  params: URLSearchParams
): Promise<Response> {
  return app.retriever
    .search({
      q: params.get("q") ?? "",
      docId: params.get("doc_id") || undefined,
      chapterId: params.get("chapter_id") || undefined,
      debug: params.get("debug") === "1",
    })
    .then((result) => json(result));
}

/** GET /api/entity/:name */
export async function handleEntity(
  app: AppDependencies,
  name: string
): Promise<Response> {
  const ent = await app.graph.findEntityByName(decodeParam(name));
  if (!ent) return json({ error: "entity_not_found" });
  const articles = await app.graph.listEntityArticles(ent.entity_id);
  return json({ entity: ent, articles });
}

/**
 * GET /api/entities —— 实体列表(分页 + 按类型/名称过滤)
 *
 * ## 为什么需要
 *
 * 2026-11-03 实测:图谱有 481 个实体,但前端**没有任何入口**能列出它们 ——
 * 顶栏「实体」硬编码跳 `/entity/农业农村部`,而那个实体**根本不存在**
 * (生产实测 `entities` 表 name='农业农村部' 命中 0 条)。
 * 结果:481 个实体里只有手动拼 URL 才能到达。
 *
 * ⚠️ **limit 必须封顶** —— 仓储里已封顶 200,这里再兜一层。
 */
export async function handleEntityList(
  app: AppDependencies,
  params: URLSearchParams
): Promise<Response> {
  const rawLimit = Number.parseInt(params.get("limit") ?? "50", 10);
  const rawOffset = Number.parseInt(params.get("offset") ?? "0", 10);
  const limit = Number.isFinite(rawLimit) ? Math.min(Math.max(rawLimit, 1), 200) : 50;
  const offset = Number.isFinite(rawOffset) ? Math.max(rawOffset, 0) : 0;

  const entities = await app.graph.listEntities({
    type: params.get("type") || undefined,
    q: params.get("q") || undefined,
    limit,
    offset,
  });
  return json({ entities, count: entities.length, limit, offset });
}
