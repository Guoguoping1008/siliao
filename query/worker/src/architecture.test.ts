/**
 * 架构测试 —— 自动守护 ADR-004 的依赖规则
 *
 * 目的: 让 R1-R5 **不靠人的自觉维持**。DDD 最常见的失败模式是
 * 「目录分了, 依赖还是乱的」—— 这份测试就是那道闸门。
 *
 * 规则:
 *   R3 + R5  领域层不得出现 fetch() / Workers / D1 类型
 *   R5       领域层不得 import infrastructure / interfaces
 *   R2       领域层不得 import application(依赖方向单一)
 *   R1       infrastructure 不得跨上下文直接查别人的表
 *   分层     application 不得 import infrastructure(经 composition root 注入)
 */

import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync, realpathSync } from "node:fs";
import { join, relative, sep, dirname } from "node:path";

const SRC = join(process.cwd(), "src");

/** 递归列出某目录下的 .ts 文件(排除测试文件自身)。 */
function listTs(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...listTs(full));
    } else if (entry.endsWith(".ts") && !entry.endsWith(".test.ts")) {
      out.push(full);
    }
  }
  return out;
}

/** 读文件并抽出 import 路径。 */
function importsOf(file: string): string[] {
  const src = readFileSync(file, "utf-8");
  const out: string[] = [];
  const re = /from\s+["']([^"']+)["']/g;
  for (const m of src.matchAll(re)) out.push(m[1]);
  return out;
}

/** 文件内容(用于扫 fetch / 类型关键字)。 */
function contentOf(file: string): string {
  return readFileSync(file, "utf-8");
}

/**
 * 把 import 路径解析成**规范化**的绝对路径。
 *
 * ⚠️ 必须用 realpath 规范化 —— 否则 `../../../domain/inquiry/evidence.vo`
 *    这类带 `..` 的相对路径不会被归一, 导致 `includes("interfaces")`
 *    之类的目录判断误命中。
 */
function resolveTarget(fromFile: string, spec: string): string | null {
  if (!spec.startsWith(".")) return null;
  let p = join(dirname(fromFile), spec);
  if (!p.endsWith(".ts")) p += ".ts";
  try {
    return realpathSync(p);
  } catch {
    return null;
  }
}

/**
 * 剥掉注释后的**代码**内容。
 *
 * ⚠️ 必须剥注释 —— 否则「纯度保证: 无 fetch()」这类**说明性注释**
 *    会被当成真的 fetch 调用, 规则测试自己就假阳性了。
 */
function codeOf(file: string): string {
  const src = readFileSync(file, "utf-8");
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")   // 块注释
    .replace(/^[ \t]*\/\/.*$/gm, "")   // 行注释
    .replace(/\/\/.*$/gm, "");         // 行尾注释
}

/**
 * 判断一个文件里有没有**真正的 HTTP 调用**。
 *
 * ⚠️ 不能用裸 `fetch(` 判定 —— `async fetch(req: Request, env: Env)` 是
 *    **Workers 要求的入口签名**, 不是 HTTP 调用。
 *    真正的 HTTP 调用形态:
 *      · `await fetch(...)`      —— 带 await
 *      · `fetch("http://...")`   —— 首参是字符串/模板串
 *      · `return fetch(...)`     —— 返回值位置
 *
 * @returns 命中的位置; 没命中返回 null
 */
function findHttpCalls(code: string): RegExpMatchArray | null {
  return code.match(
    /(?:^|[^\w.])(?:await\s+|return\s+)?fetch\s*\(\s*(?:[`"']|\/)/gm
  );
}

/** 判断目标文件是否位于 src 下的某个目录。 */
function isUnder(file: string, dirName: string): boolean {
  const rel = relative(SRC, file);
  return rel.split(sep).includes(dirName);
}

const domainFiles = listTs(join(SRC, "domain"));
const appFiles = listTs(join(SRC, "application"));
const infraFiles = listTs(join(SRC, "infrastructure"));

describe("架构规则 R3/R5 · 领域层纯净性", () => {
  it("领域层不出现 fetch()", () => {
    const offenders: string[] = [];
    for (const f of domainFiles) {
      if (findHttpCalls(codeOf(f))) {
        offenders.push(relative(SRC, f));
      }
    }
    expect(offenders).toEqual([]);
  });

  it("领域层不 import Workers / D1 类型", () => {
    const banned = ["@cloudflare/workers-types", "D1Database", "R2Bucket"];
    const offenders: string[] = [];
    for (const f of domainFiles) {
      const c = codeOf(f);
      for (const b of banned) {
        if (c.includes(b)) offenders.push(`${relative(SRC, f)} → ${b}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("领域层不 import infrastructure(依赖方向单一)", () => {
    const offenders: string[] = [];
    for (const f of domainFiles) {
      for (const spec of importsOf(f)) {
        const t = resolveTarget(f, spec);
        if (t && isUnder(t, "infrastructure")) {
          offenders.push(`${relative(SRC, f)} → ${spec}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("领域层不 import interfaces(防腐层在领域层之外)", () => {
    const offenders: string[] = [];
    for (const f of domainFiles) {
      for (const spec of importsOf(f)) {
        const t = resolveTarget(f, spec);
        if (t && isUnder(t, "interfaces")) {
          offenders.push(`${relative(SRC, f)} → ${spec}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("领域层不 import application(R2: 依赖方向单一)", () => {
    const offenders: string[] = [];
    for (const f of domainFiles) {
      for (const spec of importsOf(f)) {
        const t = resolveTarget(f, spec);
        if (t && isUnder(t, "application")) {
          offenders.push(`${relative(SRC, f)} → ${spec}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("领域层文件存在(不是空壳)", () => {
    expect(domainFiles.length).toBeGreaterThanOrEqual(5);
  });
});

describe("架构规则 R2 · 应用层依赖方向", () => {
  it("应用层不 import infrastructure(经 composition root 注入)", () => {
    const offenders: string[] = [];
    for (const f of appFiles) {
      for (const spec of importsOf(f)) {
        const t = resolveTarget(f, spec);
        if (t && isUnder(t, "infrastructure")) {
          offenders.push(`${relative(SRC, f)} → ${spec}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("应用层不出现 fetch()(外部调用走 ACL)", () => {
    const offenders: string[] = [];
    for (const f of appFiles) {
      if (findHttpCalls(codeOf(f))) {
        offenders.push(relative(SRC, f));
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("架构规则 R1 · 跨上下文表访问", () => {
  it("② 合规规则上下文不得直接查 articles 表(须经 ACL)", () => {
    // M2 尚未实现 compliance/ 目录; 一旦建起来, 这里会生效
    const offenders: string[] = [];
    for (const f of infraFiles) {
      const c = contentOf(f);
      if (c.includes("compliance") && /FROM\s+articles/i.test(c)) {
        offenders.push(relative(SRC, f));
      }
    }
    expect(offenders).toEqual([]);
  });

  it("仓储实现的文件名以 .repository.impl.ts 结尾", () => {
    const repoFiles = infraFiles.filter((f) =>
      contentOf(f).includes("implements RegulationRepository") ||
      contentOf(f).includes("implements GraphRepository")
    );
    expect(repoFiles.length).toBeGreaterThan(0);
    for (const f of repoFiles) {
      expect(f).toMatch(/\.repository\.impl\.ts$/);
    }
  });
});

describe("架构规则 · 分层存在性", () => {
  it("四层目录都存在", () => {
    for (const d of ["domain", "application", "interfaces", "infrastructure"]) {
      expect(statSync(join(SRC, d)).isDirectory()).toBe(true);
    }
  });

  it("interfaces 下有 composition-root(手写组装根)", () => {
    expect(statSync(join(SRC, "interfaces", "composition-root.ts")).isFile()).toBe(true);
  });

  it("interfaces/http 下有 router(路由层已抽离)", () => {
    expect(statSync(join(SRC, "interfaces", "http", "router.ts")).isFile()).toBe(true);
  });

  it("⚠️ M3 · index.ts 只做入口 —— 行数控制在 150 以内", () => {
    const lines = readFileSync(join(SRC, "index.ts"), "utf-8").split("\n").length;
    expect(lines).toBeLessThan(150);
  });

  it("⚠️ M3 · index.ts 不含路由逻辑(只挂载 router)", () => {
    const code = codeOf(join(SRC, "index.ts"));
    // 路由匹配、SQL、业务判断都不该出现在入口
    expect(code).not.toMatch(/\.match\(\s*\/\^/);
    expect(code).not.toMatch(/\bSELECT\b/i);
    // ⚠️ `async fetch(req: Request, env: Env)` 是 **Workers 要求的入口签名**,
    //    不是 HTTP 调用 —— 用 findHttpCalls 判定(见该函数注释)。
    expect(findHttpCalls(code)).toBeNull();
  });

  it("⚠️ M3 · 全部 SQL 在 infrastructure(其他层不出现 SQL 语句)", () => {
    const offenders: string[] = [];
    for (const f of [...domainFiles, ...appFiles, ...listTs(join(SRC, "interfaces"))]) {
      const c = codeOf(f);
      if (/\b(SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b/i.test(c)) {
        offenders.push(relative(SRC, f));
      }
    }
    expect(offenders).toEqual([]);
  });

  it("⚠️ 接口层不 import domain 的实现细节 —— 只经应用层/仓储端口", () => {
    // interfaces/http 可以 import domain 的**纯函数**(如入参校验),
    // 但不得 import infrastructure(那是 composition-root 的活)
    const offenders: string[] = [];
    for (const f of listTs(join(SRC, "interfaces", "http"))) {
      for (const spec of importsOf(f)) {
        const t = resolveTarget(f, spec);
        if (t && isUnder(t, "infrastructure")) {
          offenders.push(`${relative(SRC, f)} → ${spec}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("⚠️ 路由层不出现 fetch()(外部调用走 ACL)", () => {
    const offenders: string[] = [];
    for (const f of listTs(join(SRC, "interfaces", "http"))) {
      if (findHttpCalls(codeOf(f))) {
        offenders.push(relative(SRC, f));
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("架构规则 · ACL 边界", () => {
  it("⚠️ 流式 LLM 调用只在 llm-stream.acl.ts(不在 application/routes)", () => {
    // SSE 帧解析是**外部协议细节** —— 放 application 会让应用层知道
    // 上游的 SSE 格式, 换供应商就得改业务层。
    const aclDir = join(SRC, "interfaces", "acl");
    const offenders: string[] = [];
    for (const f of [...appFiles, ...listTs(join(SRC, "interfaces", "http"))]) {
      const c = codeOf(f);
      // 直接解析上游 SSE 帧 = 泄漏了传输协议
      if (/data:\s*\$\{|startsWith\(\s*["']data:|parseSSEDelta/.test(c)) {
        offenders.push(relative(SRC, f));
      }
    }
    expect(offenders).toEqual([]);
    expect(statSync(join(aclDir, "llm-stream.acl.ts")).isFile()).toBe(true);
  });
});
