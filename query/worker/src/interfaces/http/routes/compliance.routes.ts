/**
 * ② 合规规则 路由 —— 接口层
 *
 * 上下文: ② 合规规则 Compliance (核心域, 只读)
 *
 * 路由:
 *   POST /api/compliance/usage  用量合规判定
 *
 * ⚠️ **入参校验在 domain 层** —— 用量判定是确定性的, 参数错必须明确报错(400),
 *    不能像 LLM 抽取那样静默给个错结论(「200 是 mg/kg 还是 g/kg?」LLM 会猜)。
 */

import { json, errorJson } from "../http-utils";
import { validateComplianceBody } from "../../../domain/compliance/compliance-request.vo";
import type { AppDependencies } from "../../composition-root";

export async function handleComplianceUsage(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const body = await req.json<{
    substance?: string;
    species?: string;
    stage?: string | null;
    value?: number;
    unit?: string;
  }>();

  const err = validateComplianceBody(body);
  if (err) {
    return errorJson("invalid_request", err);
  }

  return json(
    await app.complianceCheck.check({
      substance: body.substance!.trim(),
      species: body.species!.trim(),
      stage: body.stage ?? null,
      value: body.value!,
      unit: body.unit!.trim(),
    })
  );
}
