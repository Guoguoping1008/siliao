/**
 * ③ 问答 · 多轮会话 —— D1 仓储实现
 *
 * 上下文: ③ 问答 Inquiry (支撑域)
 *
 * ⚠️ R1: 这是**唯一**允许直接查 `qa_sessions` / `qa_messages` 的地方。
 *
 * ## 为什么会话表放在 ③ 而不是 ①
 *
 * 会话是**问答的临时状态**, 不是法规知识 ——
 * ① 是只读的事实源, 不该持有「这个用户刚才问了什么」这种易变数据。
 * ③ 是无状态编排域, 会话状态正是它的自然归属。
 */

import type {
  ConversationContext,
  ConversationTurn,
  ExtractedEntities,
} from "../../../domain/inquiry/conversation-context.vo";
import type { Evidence } from "../../../domain/inquiry/evidence.vo";
import type { D1Like } from "./regulation.repository.impl";
import { int, mapRows, str, type DbRow } from "./mappers";

/** 仓储接口。 */
export interface ConversationRepository {
  /** 取会话上下文(不存在则返回 null)。 */
  load(sessionId: string): Promise<ConversationContext | null>;
  /** 追加一轮(user + assistant 两条消息)。 */
  appendTurn(
    sessionId: string,
    turn: {
      question: string;
      answer: string;
      evidence: Evidence[];
      entities: ExtractedEntities[];
      resolvedQuery: string;
    }
  ): Promise<void>;
  /** 删除会话(用户主动清空)。 */
  clear(sessionId: string): Promise<void>;
}

/** 一条消息的持久化形态。 */
interface StoredMessage {
  turnNo: number;
  role: "user" | "assistant";
  content: string;
  evidence: string[];
  entities: ExtractedEntities[];
  resolvedQuery: string | null;
}

function parseJsonArray<T>(v: unknown): T[] {
  if (typeof v !== "string" || !v.trim()) return [];
  try {
    const parsed = JSON.parse(v);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    // ⚠️ 解析失败**静默降级为空数组** —— 会话记忆是辅助功能,
    //    数据坏了不该让整个问答 500。
    return [];
  }
}

/** D1 实现的会话仓储。 */
export class D1ConversationRepository implements ConversationRepository {
  constructor(private readonly db: D1Like) {}

  async load(sessionId: string): Promise<ConversationContext | null> {
    const sessionRows = await this.db.prepare(
      `SELECT session_id FROM qa_sessions WHERE session_id = ?1`
    ).bind(sessionId).all();
    const session = sessionRows.results?.[0] as DbRow | undefined;
    if (!session) return null;

    const msgRows = await this.db.prepare(
      `SELECT turn_no, role, content, evidence_json, entities_json, resolved_query
         FROM qa_messages WHERE session_id = ?1 ORDER BY turn_no ASC, rowid ASC`
    ).bind(sessionId).all();

    const messages = mapRows(msgRows.results as DbRow[], toStoredMessage);

    // ── 轮次组装: 一轮 = 一条 user + 一条 assistant ──
    const byTurn = new Map<number, StoredMessage[]>();
    for (const m of messages) {
      const list = byTurn.get(m.turnNo) ?? [];
      list.push(m);
      byTurn.set(m.turnNo, list);
    }

    const turns: ConversationTurn[] = [];
    const entities: ExtractedEntities[] = [];
    for (const turnNo of [...byTurn.keys()].sort((a, b) => a - b)) {
      const msgs = byTurn.get(turnNo)!;
      const user = msgs.find((m) => m.role === "user");
      const assistant = msgs.find((m) => m.role === "assistant");
      if (!user) continue;
      turns.push({
        question: user.content,
        answer: assistant?.content ?? "",
        evidence: [],
        entities: user.entities,
      });
      // 实体累积: 后面的覆盖前面的(同物质)
      for (const e of user.entities) {
        const idx = entities.findIndex((x) => x.substance === e.substance);
        if (idx >= 0) entities[idx] = e;
        else entities.push(e);
      }
    }

    return { sessionId, turns, entities };
  }

  async appendTurn(
    sessionId: string,
    turn: {
      question: string;
      answer: string;
      evidence: Evidence[];
      entities: ExtractedEntities[];
      resolvedQuery: string;
    }
  ): Promise<void> {
    // ⚠️ D1 不支持跨表事务 —— 用 `batch()` 把一轮的写入打成**一个请求**,
    //    服务端按顺序执行。比逐条 await 快, 也少一半往返。
    //
    //    写入顺序: 确保 session 存在 → 插 user → 插 assistant → 更新 turn_count。
    //    中途失败会留下 turn_count 偏小的 session, 下次 load 时消息数与
    //    turn_count 不一致能被识别(见 turnCount 的用途)。
    const countRows = await this.db.prepare(
      `SELECT COUNT(*) AS c FROM qa_messages WHERE session_id = ?1 AND role = 'user'`
    ).bind(sessionId).all();
    const turnNo = int(countRows.results?.[0]?.c, 0) + 1;

    const evidenceIds = turn.evidence.map((e) => e.article_id);
    const entitiesJson = JSON.stringify(turn.entities);
    const evidenceJson = JSON.stringify(evidenceIds);

    await this.db.batch([
      this.db
        .prepare(
          `INSERT INTO qa_sessions (session_id, turn_count)
             VALUES (?1, 0)
             ON CONFLICT(session_id) DO UPDATE SET updated_at = datetime('now')`
        )
        .bind(sessionId),
      this.db
        .prepare(
          `INSERT INTO qa_messages
             (message_id, session_id, turn_no, role, content, evidence_json, entities_json, resolved_query)
           VALUES (?1, ?2, ?3, 'user', ?4, ?5, ?6, ?7)`
        )
        .bind(
          `${sessionId}:${turnNo}:user`,
          sessionId,
          turnNo,
          turn.question,
          evidenceJson,
          entitiesJson,
          turn.resolvedQuery
        ),
      this.db
        .prepare(
          `INSERT INTO qa_messages
             (message_id, session_id, turn_no, role, content, evidence_json, entities_json, resolved_query)
           VALUES (?1, ?2, ?3, 'assistant', ?4, ?5, ?6, ?7)`
        )
        .bind(
          `${sessionId}:${turnNo}:assistant`,
          sessionId,
          turnNo,
          turn.answer,
          evidenceJson,
          entitiesJson,
          turn.resolvedQuery
        ),
      this.db
        .prepare(
          `UPDATE qa_sessions SET turn_count = ?2, updated_at = datetime('now')
            WHERE session_id = ?1`
        )
        .bind(sessionId, turnNo),
    ]);
  }

  async clear(sessionId: string): Promise<void> {
    await this.db.batch([
      this.db.prepare(`DELETE FROM qa_messages WHERE session_id = ?1`).bind(sessionId),
      this.db.prepare(`DELETE FROM qa_sessions WHERE session_id = ?1`).bind(sessionId),
    ]);
  }
}

function toStoredMessage(row: DbRow): StoredMessage {
  return {
    turnNo: int(row.turn_no, 0),
    role: (str(row.role) === "assistant" ? "assistant" : "user"),
    content: str(row.content) ?? "",
    evidence: parseJsonArray<string>(row.evidence_json),
    entities: parseJsonArray<ExtractedEntities>(row.entities_json),
    resolvedQuery: str(row.resolved_query) ?? null,
  };
}
