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
