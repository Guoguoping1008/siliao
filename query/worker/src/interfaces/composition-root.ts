/**
 * Composition Root —— 组装根
 *
 * Workers 没有 DI 容器, 所以依赖装配**手写**在这里。
 * 这反而是好事: 依赖关系一眼可见, 没有魔法。
 *
 * ⚠️ 所有具体实现的 new 都在这个文件里。领域层与应用层只见到接口。
 */

import { D1Like } from "../infrastructure/persistence/d1/regulation.repository.impl";
import {
  D1GraphRepository,
  GraphRepository,
} from "../infrastructure/persistence/d1/graph.repository.impl";
import {
  D1RegulationRepository,
  RegulationRepository,
} from "../infrastructure/persistence/d1/regulation.repository.impl";
import {
  EmbeddingEnv,
  HybridRetriever,
} from "../infrastructure/persistence/retrieval/hybrid-retriever.adapter";
import { InquiryService } from "../application/inquiry/inquiry.service";
import {
  ComplianceCheckService,
  type ComplianceRuleSource,
} from "../application/compliance/compliance-check.usecase";
import { ComplianceRuleSet } from "../domain/compliance/compliance-rule-set.aggregate";
import type { RelatedArticle } from "../domain/compliance/compliance-rule-set.aggregate";
import { LlmEnv } from "../interfaces/acl/llm.acl";
import {
  D1ComplianceRepository,
  type ComplianceRepository,
} from "../infrastructure/persistence/d1/compliance.repository.impl";

/** Worker 运行时环境。 */
export interface Env {
  /** D1 绑定 */
  DB: D1Like;
  /** R2 绑定(可选 —— 本账户未开通, 正文已改存 D1) */
  INDEX_BUCKET?: unknown;
  /** Vectorize 绑定(已绑定, 暂未启用) */
  VECTOR?: unknown;
  /** Workers AI 绑定 */
  AI?: unknown;
  /** LLM 配置 */
  LLM_API_BASE?: string;
  LLM_MODEL?: string;
  LLM_API_KEY?: string;
  DEEPSEEK_API_BASE?: string;
  DEEPSEEK_MODEL?: string;
  DEEPSEEK_API_KEY?: string;
  /** bge 语义层地址(可空 = 不启用语义路) */
  BGE_SERVER_URL?: string;
}

/** 组装好的应用依赖。 */
export interface AppDependencies {
  regulations: RegulationRepository;
  graph: GraphRepository;
  retriever: HybridRetriever;
  inquiry: InquiryService;
  compliance: ComplianceRepository;
  complianceCheck: ComplianceCheckService;
}

/**
 * 组装全部依赖。
 *
 * 每次请求调一次 —— Workers 的 isolate 生命周期短, 这样最简单也最安全。
 */
export function createApp(env: Env): AppDependencies {
  const db = env.DB;

  const regulations = new D1RegulationRepository(db);
  const graph = new D1GraphRepository(db);
  const retriever = new HybridRetriever(db, { BGE_SERVER_URL: env.BGE_SERVER_URL });
  const inquiry = new InquiryService(retriever, {
    LLM_API_BASE: env.LLM_API_BASE,
    LLM_MODEL: env.LLM_MODEL,
    LLM_API_KEY: env.LLM_API_KEY,
    DEEPSEEK_API_BASE: env.DEEPSEEK_API_BASE,
    DEEPSEEK_MODEL: env.DEEPSEEK_MODEL,
    DEEPSEEK_API_KEY: env.DEEPSEEK_API_KEY,
  });

  // ── ② 合规规则 ──
  const compliance = new D1ComplianceRepository(db);
  const ruleSource: ComplianceRuleSource = {
    async listRules(ruleSetVersion?: string) {
      const rules = await compliance.listRules(ruleSetVersion);
      return new ComplianceRuleSet(ruleSetVersion ?? "current", rules);
    },
    async listCatalog(reviewedOnly?: boolean) {
      return compliance.listCatalog(reviewedOnly);
    },
  };
  const complianceCheck = new ComplianceCheckService(ruleSource, {
    async search({ q }) {
      const { hits } = await retriever.search({ q });
      return {
        hits: hits.map((h) => ({
          articleId: h.article_id,
          chapterTitle: h.chapter_title,
          articleNumber: h.article_number,
          excerpt: h.excerpt,
        })) as RelatedArticle[],
      };
    },
  });

  return { regulations, graph, retriever, inquiry, compliance, complianceCheck };
}
