/**
 * 合规校验入参校验 —— 领域层纯逻辑
 *
 * 上下文: ② 合规规则 Compliance
 *
 * ## 为什么校验放在 domain 层
 *
 * 用量判定是**确定性**的 —— 参数错必须**明确报错**, 不能像 LLM 抽取那样
 * 静默给个错结论(「200 是 mg/kg 还是 g/kg?」LLM 会猜)。
 *
 * 把校验规则放在领域层, 可以脱离 HTTP 层单测。
 *
 * ⚠️ 纯度保证 (ADR-004 R3/R5): 零框架依赖, 零 I/O, 无 fetch()。
 */

/** 允许的单位。 */
export const ALLOWED_UNITS = ["mg/kg", "g/kg", "IU/kg", "IU/g", "万IU/kg", "%"] as const;

/** 合规校验的原始入参。 */
export interface ComplianceBody {
  substance?: string;
  species?: string;
  stage?: string | null;
  value?: number;
  unit?: string;
}

/**
 * 校验入参。
 *
 * @returns 错误描述; 通过则返回 null
 */
export function validateComplianceBody(body: ComplianceBody | null): string | null {
  if (!body || typeof body !== "object") {
    return "请求体必须是 JSON 对象";
  }
  if (typeof body.substance !== "string" || !body.substance.trim()) {
    return "缺少 substance(物质名)";
  }
  if (typeof body.species !== "string" || !body.species.trim()) {
    return "缺少 species(动物种类)";
  }
  if (typeof body.value !== "number" || !Number.isFinite(body.value)) {
    return "value 必须是数字(用量数值)";
  }
  if (body.value < 0) {
    return "value 不能为负数";
  }
  if (typeof body.unit !== "string" || !body.unit.trim()) {
    return "缺少 unit(单位)";
  }
  if (!ALLOWED_UNITS.includes(body.unit.trim() as (typeof ALLOWED_UNITS)[number])) {
    return `unit 必须是以下之一: ${ALLOWED_UNITS.join(", ")}`;
  }
  if (body.stage !== undefined && body.stage !== null && typeof body.stage !== "string") {
    return "stage 必须是字符串或 null";
  }
  return null;
}
