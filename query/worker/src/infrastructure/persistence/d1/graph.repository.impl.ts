/**
 * ④ 知识图谱 —— D1 仓储实现
 *
 * 上下文: ④ 知识图谱 Graph (支撑域)
 *
 * ## 现状
 *
 * `entities` / `entity_articles` 表**已建但为空** —— 生产查「抗生素」返回
 * `entity_not_found`。前端 EntityPage / EntityGraph 组件已就位, 等数据。
 *
 * ## ⚠️ 待修正的跨上下文外键 (ADR-004 第 6 节)
 *
 * `entity_articles` 对 `articles` 有 FOREIGN KEY, 这是**跨上下文外键, 违反 R1**。
 *
 * 修正方案: 图谱上下文改为存 `article_ref`(逻辑引用, **不带 FK**),
 * 由 ACL 在读取时解析。这样 ④ 可以独立演进, 且将来 ① 换存储不影响 ④。
 *
 * M1 阶段**不改 schema**(零行为变更原则), 但此处已按目标形态写好接口,
 * 迁移时只需换实现。
 */

import { mapRows, str, type DbRow } from "./mappers";
import type { D1Like } from "./regulation.repository.impl";

/** 实体。 */
export interface GraphEntity {
  entity_id: string;
  name: string;
  /** LAW / AGENCY / CERTIFICATE 等 */
  type: string;
  description?: string;
  doc_id?: string;
}

/** 实体关联的条文(轻量引用)。 */
export interface EntityArticleRef {
  article_id: string;
  number?: string;
  title?: string;
  chapter_id?: string;
  chapter_number?: string;
  chapter_title?: string;
}

/** 仓储接口。 */
export interface GraphRepository {
  findEntityByName(name: string): Promise<GraphEntity | null>;
  listEntityArticles(entityId: string): Promise<EntityArticleRef[]>;
}

/** D1 实现的图谱仓储。 */
export class D1GraphRepository implements GraphRepository {
  constructor(private readonly db: D1Like) {}

  async findEntityByName(name: string): Promise<GraphEntity | null> {
    const row = await this.db.prepare(
      `SELECT * FROM entities WHERE name=?1`
    ).bind(name).first();
    if (!row) return null;
    const r = row as DbRow;
    return {
      entity_id: String(r.entity_id),
      name: String(r.name),
      type: String(r.type),
      description: str(r.description),
      doc_id: str(r.doc_id),
    };
  }

  async listEntityArticles(entityId: string): Promise<EntityArticleRef[]> {
    const rows = await this.db.prepare(
      `SELECT a.article_id, a.number, a.title, a.chapter_id,
              c.number as chapter_number, c.title as chapter_title
       FROM entity_articles ea
       JOIN articles a ON a.article_id = ea.article_id
       JOIN chapters c ON c.chapter_id = a.chapter_id
       WHERE ea.entity_id=?1
       LIMIT 50`
    ).bind(entityId).all();

    return mapRows(rows.results as DbRow[], (r) => ({
      article_id: String(r.article_id),
      number: str(r.number),
      title: str(r.title),
      chapter_id: str(r.chapter_id),
      chapter_number: str(r.chapter_number),
      chapter_title: str(r.chapter_title),
    }));
  }
}
