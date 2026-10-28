/**
 * D1 数据映射器 —— infrastructure 层
 *
 * 上下文: ① 法规知识库 / ④ 知识图谱
 *
 * D1 返回的行是 `Record<string, unknown>`, 需要显式映射成领域层的类型。
 * 这一层是**唯一**允许知道数据库列名的地方。
 *
 * ⚠️ R1: 跨上下文禁止直接 JOIN 对方表。这里只映射本上下文拥有的表。
 */

/** D1 查询结果的行类型。 */
export type DbRow = Record<string, unknown>;

/** D1 查询结果集。 */
export interface DbResultSet<T = DbRow> {
  results: T[];
  success?: boolean;
  meta?: Record<string, unknown>;
}

/** 从行里取字符串(可为 null/undefined)。 */
export function str(v: unknown): string | undefined {
  return v === null || v === undefined ? undefined : String(v);
}

/** 从行里取数字。 */
export function num(v: unknown): number | undefined {
  if (v === null || v === undefined) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

/** 从行里取整数(默认 0)。 */
export function int(v: unknown, fallback = 0): number {
  return num(v) ?? fallback;
}

/**
 * 把 D1 行数组映射成领域对象数组。
 *
 * 纯函数 —— 可单测, 不用起 D1。
 */
export function mapRows<T>(
  rows: DbRow[] | undefined,
  mapper: (row: DbRow) => T
): T[] {
  if (!rows) return [];
  return rows.map(mapper);
}
