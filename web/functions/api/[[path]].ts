// Cloudflare Pages Function:代理 /api/* → Worker
// 不在 _redirects 写死 worker URL(因每账户换人URL 变),
// 改在 Pages Dashboard → siliao-web → Settings → Environment variables
// 配 API_BASE = https://siliao-api.<你的 account subdomain>.workers.dev
//
// [2026-10-06 玄穹 CEO 部署修复]
// 之前 web/public/_redirects 写死了 siliao-api.workers.dev (错的占位),
// 部署后 /api/* 跨域或 404。改用 Functions 后,Pages 自带同源,自动免 CORS。

interface PagesEnv {
  API_BASE?: string;  // e.g. https://siliao-api.<sub>.workers.dev
}

export const onRequest: PagesFunction<PagesEnv> = async (context) => {
  const { request, env, params } = context;

  const base = (env.API_BASE || "").replace(/\/$/, "");
  if (!base) {
    return new Response(
      JSON.stringify({
        error: "API_BASE env var not set on Pages project siliao-web",
        hint: "Cloudflare Dashboard → Pages → siliao-web → Settings → Environment variables → API_BASE",
      }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    );
  }

  // 透传 path + query string
  const url = new URL(request.url);
  const splat = (params.path as string[]) || [];
  const target = `${base}/api/${splat.join("/")}${url.search}`;

  // 复制请求头(去掉 hop-by-hop)
  const fwdHeaders = new Headers(request.headers);
  ["host", "cf-connecting-ip", "cf-ray", "cf-worker", "cf-cache-status"].forEach((h) =>
    fwdHeaders.delete(h),
  );

  const init: RequestInit = {
    method: request.method,
    headers: fwdHeaders,
    redirect: "follow",
  };
  // GET/HEAD 不能有 body
  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
    init.duplex = "half";
  }

  const upstream = await fetch(target, init);

  // 透传响应,加 CORS(其实 Pages 同源不需要,但保险)
  const respHeaders = new Headers(upstream.headers);
  respHeaders.set("Access-Control-Allow-Origin", url.origin);
  respHeaders.set("X-Proxied-By", "siliao-pages-functions");

  return new Response(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
};

// CORS preflight 兜底
export const onRequestOptions: PagesFunction = async () => {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type,Authorization",
      "Access-Control-Max-Age": "86400",
    },
  });
};