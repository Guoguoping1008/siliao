/**
 * ① 法规知识库 —— D1 仓储实现
 *
 * 上下文: ① 法规知识库 Regulation (核心域, 只读)
 *
 * ⚠️ R1: 这是**唯一**允许直接查 `documents` / `chapters` / `articles` /
 *    `articles_fts` / `catalog` 的地方。其他上下文要读条文原文, 必须经这里。
 *
 * ⚠️ R4: 只读核心域 —— 写操作只有 `ingestRelease`, 由 ⑤ 的领域事件触发。
 */

import type {
  RegulationArticle,
  RegulationChapter,
  RegulationDocument,
  RegulationDocumentSummary,
} from "../../../domain/regulation/regulation-document.aggregate";
import { mapRows, str, strOrNull, int, type DbRow } from "./mappers";

/** D1 prepared statement(可 bind 参数)。 */
export interface D1PreparedStatement {
  all<T = DbRow>(): Promise<{ results: T[] }>;
  first<T = DbRow>(): Promise<T | null>;
}

/** D1 数据库句柄(只声明用到的能力, 便于 mock)。 */
export interface D1Like {
  prepare(query: string): D1PreparedStatement & {
    bind(...values: unknown[]): D1PreparedStatement;
  };
  batch(statements: unknown[]): Promise<unknown[]>;
}

/** 仓储接口(领域层定义, 实现放 infrastructure)。 */
export interface RegulationRepository {
  listDocuments(): Promise<RegulationDocumentSummary[]>;
  getCatalog(): Promise<{ scopes: unknown[]; stats?: unknown } | { error: string; message?: string; scopes: never[] }>;
  listChapters(docId: string): Promise<RegulationChapter[]>;
  getChapter(docId: string, chId: string): Promise<{ chapter: DbRow; markdown: string } | { error: string }>;
  getArticle(artId: string): Promise<{ article: DbRow; markdown: string } | { error: string }>;
}

/** D1 实现的法规仓储。 */
export class D1RegulationRepository implements RegulationRepository {
  constructor(private readonly db: D1Like) {}

  /**
   * 文档列表。
   *
   * ⚠️ 排序不能靠 created_at —— 灌库时所有文档的 created_at 相同(SQLite
   *    同秒插入), ORDER BY created_at DESC 的顺序是**插入顺序的逆序**,
   *    会把「目录/封面」顶到最前面(实测首页第一屏全是 000封面)。
   *    改成: 目录/封面排后面, 其余按 doc_id 排(编号前缀保证法规顺序稳定)。
   */
  async listDocuments(): Promise<RegulationDocumentSummary[]> {
    const rows = await this.db.prepare(
      `SELECT d.doc_id, d.title, d.doc_number, d.issuer, d.effective_date,
              (SELECT COUNT(*) FROM chapters c WHERE c.doc_id = d.doc_id) as chapter_count,
              (SELECT COUNT(*) FROM articles a WHERE a.doc_id = d.doc_id) as article_count
       FROM documents d
       ORDER BY d.is_toc ASC, d.sort_order ASC, d.doc_id ASC`
    ).all();

    return mapRows(rows.results as DbRow[], (r) => ({
      doc_id: String(r.doc_id),
      title: String(r.title),
      // ⚠️ 可空字段**透传原值**, 不用 String() —— null 要保持 null,
      //    否则 JSON 里会出现字符串 "null"(与原实现不一致)。
      doc_number: strOrNull(r.doc_number),
      issuer: strOrNull(r.issuer),
      effective_date: strOrNull(r.effective_date),
      is_toc: int(r.is_toc),
      chapter_count: int(r.chapter_count),
      article_count: int(r.article_count),
    }));
  }

  /**
   * 目录树(书籍原版层级)。
   *
   * ⚠️ 为什么不用 documents 表现场拼: documents 里只有 scope/section 两级,
   *    没有「起始页」也没有原版的二级分类名。目录页是独立信息源。
   */
  async getCatalog(): Promise<{ scopes: unknown[]; stats?: unknown } | { error: string; message?: string; scopes: never[] }> {
    const row = await this.db.prepare(
      `SELECT tree, stats FROM catalog WHERE id = 1`
    ).first<{ tree: string; stats: string | null }>();

    if (!row?.tree) {
      return {
        error: "catalog_not_found",
        message: "目录数据未灌入。跑 build/export/push_catalog.py --remote",
        scopes: [],
      };
    }

    const scopes = JSON.parse(row.tree);
    const stats = row.stats ? JSON.parse(row.stats) : undefined;
    return { scopes, stats };
  }

  /** 文档下的章节。 */
  async listChapters(docId: string): Promise<RegulationChapter[]> {
    const rows = await this.db.prepare(
      `SELECT chapter_id, doc_id, number, title, article_count, sort_order
       FROM chapters WHERE doc_id = ?1
       ORDER BY sort_order ASC`
    ).bind(docId).all();

    return mapRows(rows.results as DbRow[], (r) => ({
      chapter_id: String(r.chapter_id),
      doc_id: String(r.doc_id),
      number: String(r.number),
      title: String(r.title),
      article_count: int(r.article_count),
      sort_order: int(r.sort_order),
    }));
  }

  /**
   * 章节详情(正文按 chapter_id 聚合条文现拼)。
   *
   * ⚠️ 章节正文**不在 chapters 表里**(单独存会让 seed.sql 单条 INSERT
   *    超过 D1 的 SQLITE_TOOBIG, 实测 115KB)—— 按 chapter_id 聚合
   *    本章下所有 articles.body 现拼。
   *
   *    注意: 条文正文本身已以 `### 第一条` 开头, 直接拼会渲染成
   *    「第一条 第一条」重复, 所以只在正文没有标题行时才补 `### {number}`。
   */
  async getChapter(docId: string, chId: string): Promise<{ chapter: DbRow; markdown: string } | { error: string }> {
    const row = await this.db.prepare(
      `SELECT * FROM chapters WHERE doc_id=?1 AND chapter_id=?2`
    ).bind(docId, chId).first();
    if (!row) return { error: "chapter_not_found" };

    const arts = await this.db.prepare(
      `SELECT a.number, a.title, a.body
       FROM articles a
       WHERE a.chapter_id = ?1
       ORDER BY a.sort_order ASC`
    ).bind(chId).all();

    const parts: string[] = [];
    for (const a of arts.results as DbRow[]) {
      const b = String(a.body || "").trim();
      if (!b) continue;
      const label = String(a.number || a.title || "");
      parts.push(b.startsWith("#") ? b : (label ? `### ${label}\n\n${b}` : b));
    }
    const markdown = parts.join("\n\n");
    return { chapter: row, markdown };
  }

  /**
   * 条文详情。
   *
   * ⚠️ 不要写 `a.*, ..., a.doc_id` —— doc_id 在 a.* 里已经有了,
   *    重复列名会让 D1 **静默返回空结果集**(不报错, .first() 就是 null),
   *    症状是所有条文详情都 article_not_found。
   */
  async getArticle(artId: string): Promise<{ article: DbRow; markdown: string } | { error: string }> {
    const row = await this.db.prepare(
      `SELECT a.article_id, a.chapter_id, a.doc_id, a.number, a.title,
              a.r2_object_key, a.vector_id, a.body,
              c.title as chapter_title, c.number as chapter_number
       FROM articles a LEFT JOIN chapters c ON c.chapter_id = a.chapter_id
       WHERE a.article_id=?1`
    ).bind(artId).first();
    if (!row) return { error: "article_not_found" };

    // 正文从 D1 的 articles.body 取(2026-10-26,不再依赖 R2)。
    return { article: row, markdown: String((row as DbRow).body || "") };
  }
}

/** 供 M2 使用的条文读取端口(只暴露需要的最小能力)。 */
export interface ArticleTextReader {
  getArticleBody(articleId: string): Promise<string | null>;
}

/** D1 实现的条文正文读取器 —— 供 ② 合规规则 上下文经 ACL 读取原文。 */
export class D1ArticleTextReader implements ArticleTextReader {
  constructor(private readonly db: D1Like) {}

  async getArticleBody(articleId: string): Promise<string | null> {
    const row = await this.db.prepare(
      `SELECT body FROM articles WHERE article_id = ?1`
    ).bind(articleId).first<{ body: string | null }>();
    return row?.body ?? null;
  }
}
