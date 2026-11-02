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
  /**
   * ⚠️ **必填,不能是 undefined** —— 前端 `EntityGraph` 直接 `a.number.replace(...)`,
   *    undefined 会抛 TypeError 让整个实体页崩掉。
   *    非「第X条」型条文(如申报指南的「（二）…»)在库里是空串,不是 null。
   */
  number: string;
  title?: string;
  chapter_id?: string;
  chapter_number?: string;
  chapter_title?: string;
  /** ⚠️ 前端 `EntityGraph` 用它拼 `/doc/:docId/chapter/:chapterId` 链接 —— 缺了会跳到 /doc/undefined。 */
  doc_id?: string;
}

/** 仓储接口。 */
export interface GraphRepository {
  findEntityByName(name: string): Promise<GraphEntity | null>;
  listEntityArticles(entityId: string): Promise<EntityArticleRef[]>;
  /** 列出实体(分页 + 按类型过滤) —— 给前端「实体列表页」用。 */
  listEntities(opts?: ListEntitiesOptions): Promise<GraphEntity[]>;
}

/** 实体列表查询参数。 */
export interface ListEntitiesOptions {
  /** 按类型过滤(如 SUBSTANCE / LAW)。空 = 不过滤。 */
  type?: string;
  /** 按名称前缀/包含过滤(大小写不敏感)。空 = 不过滤。 */
  q?: string;
  /** 条数上限 —— 默认 50,最大 200。 */
  limit?: number;
  /** 偏移量 —— 默认 0。 */
  offset?: number;
}

/** D1 行 → 实体。 */
function toEntity(r: DbRow): GraphEntity {
  return {
    entity_id: String(r.entity_id),
    name: String(r.name),
    type: String(r.type),
    // ⚠️ 必须归一化成空串 —— `str(null)` 返回 undefined,
    //    前端拿到 undefined 会显示 "undefined" 或直接崩。
    //    与 listEntityArticles 的 number 契约同源。
    description: str(r.description) ?? "",
    doc_id: str(r.doc_id),
  };
}

/** D1 实现的图谱仓储。 */
export class D1GraphRepository implements GraphRepository {
  constructor(private readonly db: D1Like) {}

  async findEntityByName(name: string): Promise<GraphEntity | null> {
    const q = (name || "").trim();
    if (!q) return null;

    // ── 1. 精确匹配 ──
    const row = await this.db
      .prepare(`SELECT * FROM entities WHERE name=?1`)
      .bind(q)
      .first();
    if (row) return toEntity(row as DbRow);

    // ── 2. 别名匹配 ──
    // ⚠️ **别名必须唯一指向一个实体** —— `entity_aliases.alias` 是主键,
    //    一对多的别名在灌库时就被剔除了(见 migrate_graph.sql 的说明)。
    //    所以这里查到就是唯一的,不需要「候选唯一才采用」的二次判断。
    //
    // ⚠️ **为什么需要别名** —— 实体名取自《品种目录》的通用名称,
    //    权威但不好念:「L-抗坏血酸(维生素C)」 vs 用户搜的「维生素C」。
    //    实测生产 `GET /api/entity/维生素C` 返回 entity_not_found。
    const aliasRow = await this.db
      .prepare(
        `SELECT e.* FROM entity_aliases a
         JOIN entities e ON e.entity_id = a.entity_id
         WHERE a.alias = ?1`
      )
      .bind(q)
      .first();
    if (aliasRow) return toEntity(aliasRow as DbRow);

    return null;
  }

  async listEntityArticles(entityId: string): Promise<EntityArticleRef[]> {
    const rows = await this.db.prepare(
      `SELECT a.article_id, a.number, a.title, a.chapter_id, a.doc_id,
              c.number as chapter_number, c.title as chapter_title
       FROM entity_articles ea
       JOIN articles a ON a.article_id = ea.article_id
       JOIN chapters c ON c.chapter_id = a.chapter_id
       WHERE ea.entity_id=?1
       LIMIT 50`
    ).bind(entityId).all();

    return mapRows(rows.results as DbRow[], (r) => ({
      article_id: String(r.article_id),
      // ⚠️ `number` 可能是空串(非「第X条」型条文,如申报指南的「（二）…」)
      //    但**不能是 undefined** —— 前端 `EntityGraph` 直接 `a.number.replace(...)`,
      //    undefined 会抛 TypeError 让整个页面崩掉。
      number: str(r.number) ?? "",
      title: str(r.title),
      chapter_id: str(r.chapter_id),
      chapter_number: str(r.chapter_number),
      chapter_title: str(r.chapter_title),
      doc_id: str(r.doc_id),
    }));
  }

  async listEntities(opts: ListEntitiesOptions = {}): Promise<GraphEntity[]> {
    // ⚠️ limit 必须封顶 —— 否则一个不带 limit 的请求就能把 481 行全拉走
    const limit = Math.min(Math.max(opts.limit ?? 50, 1), 200);
    const offset = Math.max(opts.offset ?? 0, 0);

    const where: string[] = [];
    const binds: string[] = [];
    if (opts.type) {
      binds.push(opts.type);
      where.push(`type = ?${binds.length}`);
    }
    if (opts.q) {
      binds.push(opts.q);
      // ⚠️ **不能用 LIKE 搜中文** —— SQLite 的 `LIKE` 只对 ASCII 有效,
      //    测中文永远返回 false。实测生产 `?q=维生素` → 0 条,
      //    而 `?q=L-赖氨酸` 能中 —— 因为前半段有 ASCII 字符。
      //
      //    `instr()` 是**二进制**子串查找,不受字符集影响 —— 中文能用。
      where.push(`instr(name, ?${binds.length}) > 0`);
    }
    const whereSql = where.length ? `WHERE ${where.join(" AND ")}` : "";

    binds.push(String(limit));
    const limitIdx = binds.length;
    binds.push(String(offset));
    const offsetIdx = binds.length;

    const rows = await this.db
      .prepare(
        `SELECT * FROM entities ${whereSql}
         ORDER BY type = 'SUBSTANCE' DESC, name ASC
         LIMIT ?${limitIdx} OFFSET ?${offsetIdx}`
      )
      .bind(...binds)
      .all();

    return mapRows(rows.results as DbRow[], toEntity);
  }
}
