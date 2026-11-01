/**
 * HTTP 工具 —— 接口层
 *
 * 上下文: 贯穿所有上下文(纯传输层关注点)
 *
 * ## CORS
 *
 * ⚠️ `Access-Control-Allow-Origin: *` 是**有意的** ——
 *    本项目是**公开只读法规检索**, 没有用户数据、没有鉴权,
 *    前端与 API 分属两个域名(Pages / Workers)。
 *    限定 origin 反而会让第三方部署的前端打不通。
 *
 * ⚠️ 但 `Allow-Methods` **不含 DELETE** —— 历史上没这个需求。
 *    C1.5 加了 `DELETE /api/qa/conversation`(清空会话)后必须补上,
 *    否则浏览器**预检**会拒掉, 表现为「DELETE 请求没发出去」。
 */

/** CORS 响应头。 */
export const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

/** 构造 JSON 响应。 */
export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

/** 构造错误响应(统一 `{ error, message }` 形状)。 */
export function errorJson(
  code: string,
  message: string,
  status = 400
): Response {
  return json({ error: code, message }, status);
}

/**
 * 从 URL 路径里取路由参数。
 *
 * ⚠️ **必须 decodeURIComponent** —— `url.pathname` **不做** percent-decode,
 *    中文 article_id 会带着 `%E5%B0%81...` 的编码形式进来。
 *    不 decode 的话查 D1 一条都查不到
 *    (症状: 所有条文/章节详情都 not_found)。
 *
 * decodeURIComponent 对已解码的普通 ASCII id 也是安全的(无 % 就原样返回)。
 */
export function decodeParam(s: string): string {
  return decodeURIComponent(s);
}
