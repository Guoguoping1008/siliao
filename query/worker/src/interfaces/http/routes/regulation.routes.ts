/**
 * ① 法规知识库 路由 —— 接口层
 *
 * 上下文: ① 法规知识库 Regulation (核心域, 只读)
 *
 * 路由:
 *   GET /api/documents                   文档列表
 *   GET /api/documents/:doc_id/chapters  文档下的章节
 *   GET /api/catalog                     目录树(书籍原版层级)
 *   GET /api/chapter/:doc_id/:ch_id      整章 Markdown
 *   GET /api/article/:art_id             单条 Markdown + 章节上下文
 *
 * ⚠️ **路由层不做业务判断** —— 只做「解析参数 → 调应用/仓储 → 包装响应」。
 */

import { json, errorJson, decodeParam } from "../http-utils";
import type { AppDependencies } from "../../composition-root";

export function handleDocuments(app: AppDependencies): Promise<Response> {
  return app.regulations.listDocuments().then((documents) => json({ documents }));
}

export function handleCatalog(app: AppDependencies): Promise<Response> {
  return app.regulations.getCatalog().then((r) => json(r));
}

export function handleChapters(app: AppDependencies, docId: string): Promise<Response> {
  return app.regulations
    .listChapters(decodeParam(docId))
    .then((chapters) => json({ chapters }));
}

export function handleChapter(
  app: AppDependencies,
  docId: string,
  chapterId: string
): Promise<Response> {
  return app.regulations
    .getChapter(decodeParam(docId), decodeParam(chapterId))
    .then((r) => json(r));
}

export function handleArticle(app: AppDependencies, artId: string): Promise<Response> {
  return app.regulations.getArticle(decodeParam(artId)).then((r) => json(r));
}
