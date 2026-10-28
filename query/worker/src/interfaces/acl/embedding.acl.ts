/**
 * Embedding 防腐层 (ACL)
 *
 * 上下文: ① 法规知识库 Regulation 的检索子域
 *
 * bge-m3 语义层跑在外部服务器(生产 https://ns.hbnongfengyuan.cn),
 * Workers 边缘跑不了 Python/sentence_transformers, 所以只能 fetch。
 *
 * ## 接口契约
 *
 *   POST {BGE_SERVER_URL}/v1/search
 *   body: {"query": str, "top_k": 20, "doc_id"?: str}
 *   reply: {"hits": [{article_id, doc_id, score, excerpt}, ...]}
 *
 * ## 纯度边界 (ADR-004 R3)
 *
 * 领域层**不得**出现 fetch()。
 */

/** bge 召回的一行。 */
export interface EmbeddingHit {
  article_id: string;
  score: number;
  doc_id?: string;
  excerpt?: string;
}

/** bge 服务返回体。 */
export interface BgeSearchResponse {
  hits?: EmbeddingHit[];
}

/**
 * 调用 bge-m3 语义检索。
 *
 * 失败会抛异常 —— 由调用方决定是否降级(生产上是静默退化为纯 FTS5, 不破生产)。
 *
 * @param baseUrl  bge 服务地址
 * @param query   用户查询
 * @param topK    召回条数
 * @param docId   可选的文档过滤
 */
export async function embeddingSearch(
  baseUrl: string,
  query: string,
  topK = 20,
  docId = ""
): Promise<EmbeddingHit[]> {
  const resp = await fetch(`${baseUrl}/v1/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK, doc_id: docId }),
    cf: { cacheTtl: 0, cacheEverything: false }, // 不缓存, query 多变
  });
  if (!resp.ok) {
    throw new Error(`bge_server ${resp.status}`);
  }
  const data = (await resp.json()) as BgeSearchResponse;
  return data.hits || [];
}
