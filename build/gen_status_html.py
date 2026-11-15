#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 docs/project-status-2026-11-15.md 生成 HTML 版。

为什么复用 11-09 版的样式块:
  那份 HTML 的样式已经过「手机可看 / 深浅色自适应 / 离线双击能开」验证,
  重新抄一份样式只会制造漂移。直接抽取 <style>...</style> 复用。

用法:
  python build/gen_status_html.py
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "docs", "project-status-2026-11-09.html")
OUT = os.path.join(ROOT, "docs", "project-status-2026-11-15.html")


def extract_style(path: str) -> str:
    with io.open(path, "r", encoding="utf-8") as f:
        html = f.read()
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    if not m:
        raise SystemExit("no <style> block found in template")
    return m.group(1).strip()


STYLE = extract_style(TEMPLATE)

BODY = r"""
<header>
  <h1>饲料法规 RAG 项目 · 现状报告</h1>
  <div class="sub">
    <b>报告日期</b> 2026-11-15　·　<b>测量方式</b> 生产环境实测 + 本地门禁实跑 + D1 远程直查（非文档复述）<br>
    <b>代码基线</b> <code>deploy/c-b-hybrid @ b22d118</code>（= <code>origin/deploy/c-b-hybrid</code>，工作区干净）<br>
    <b>生产</b> 前端 https://siliao-web.pages.dev · API https://siliao-api.guoguoping.workers.dev<br>
    <b>语料</b> <code>minimax/</code> 1021 页 → 196 文档 / 529 章 / 3145 条文
  </div>
</header>

<nav class="toc">
  <a href="#s1">结论速览</a>
  <a href="#s2">三个真实问题</a>
  <a href="#s3">生产实测</a>
  <a href="#s4">门禁现状</a>
  <a href="#s5">代码结构</a>
  <a href="#s6">未完成功能</a>
  <a href="#s7">下一步</a>
  <a href="#s8">已踩过的坑</a>
  <a href="#s9">资源快照</a>
</nav>

<section id="s1">
  <div class="card-t">一 · 结论速览</div>
  <div class="tw"><table>
    <tr><th>维度</th><th>状态</th><th>本次实测依据</th></tr>
    <tr><td>① 法规检索</td><td><span class="tag t-ok">生产可用</span></td><td><code>/api/search</code> 200 · 命中含「猪150~300mg/kg」原文表格 · 4.7s</td></tr>
    <tr><td>③ 知识问答</td><td><span class="tag t-warn">可用但延迟劣化 + 偶发 524</span></td><td>6/6 次 200，但延迟 15/32/43/78/78/82s；另有 1 次 524</td></tr>
    <tr><td>④ 知识图谱</td><td><span class="tag t-ok">生产可用</span></td><td>481 实体 / 1951 关联 / 117 别名 · 中文搜索 15 条</td></tr>
    <tr><td>② 用量合规速查</td><td><span class="tag t-bad">闸门未开</span></td><td>37 规则 + 387 目录 <b>双表全 <code>pending</code></b> → 一律 <code>not_covered</code></td></tr>
    <tr><td>⑤ 法规监测</td><td><span class="tag t-ok">已上线且健康</span></td><td>Cron 每天 3 次，连续 8 次 <code>status=ok</code>，0 失败</td></tr>
    <tr><td>③ 多轮会话</td><td><span class="tag t-ok">生产可用</span></td><td><code>/api/qa/conversation</code> 200 · 55s</td></tr>
  </table></div>
  <div class="lead">
    <b>一句话</b>：检索、图谱、监测三块完全健康，指标与基线严丝合缝；问答能答对但延迟中位数已到 <b>60s</b>、偶发撞 Cloudflare 100s 上限（524）；合规速查是<b>两道闸门</b>全关，不是一道 —— <b>37 条规则 + 387 条物质目录都要放行</b>，人工量比文档记的「1-2 小时」多一截。
  </div>
</section>

<section id="s2">
  <div class="card-t">二 · 本次实测挖出的真实问题</div>

  <h3>2.1 <span class="tag t-bad">P0 · 业务阻断</span> 合规速查是<b>两道闸门</b>，不是一道</h3>
  <p>文档 <code>docs/unfinished-features.md</code> 写的是「37 条规则人工校核（1-2 小时）」。本次直查 D1 发现<b>第二道闸门被漏记</b>：</p>
  <pre>compliance_rules    : 37 条 | pending 37 | reviewed 0
substance_catalog   : 387 条 | pending 387          ← 这道闸门没人提</pre>
  <p><code>build/export/apply_review_checklist.py</code> 开头的表格已经把话说白了：</p>
  <pre>&gt; 判定引擎要同时拿到规则和物质目录，两道闸门<b>任一没开都恒返回 not_covered</b>。
&gt; 实测证据(2026-11-03):只把 1 条规则置 reviewed → 判定<b>仍是</b> not_covered;
&gt; 规则 + 目录<b>同时</b>置 reviewed → 13/13 全部命中判定。</pre>
  <div class="note">
    <b>含义</b>：只校核 37 条规则，② 依然全线 <code>not_covered</code>。<b>目录那 387 条也得放行</b>（脚本的 <code>--approve-catalog</code> 开关一次性全放行，⚠️ 需已核过名称/别名）。
  </div>
  <p>生产实测（参数齐全，<code>value</code> 必须数字 + <code>unit</code> 必填）：</p>
  <pre>POST /api/compliance/usage
{"substance":"维生素C","species":"猪","value":200,"unit":"mg/kg"}
→ {"status":"not_covered","matchedSubstance":null,
   "coverageGap":{"reason":"规则库未覆盖该物质/动物组合, 需人工确认",
                  "relatedArticles":[...《饲料和饲料添加剂管理条例》第二十五条...]}}</pre>
  <p>value=150 / 200 / 500 三档<b>返回完全一致</b> —— 闸门在匹配之前就拦住了，符合设计。返回体诚实地附了 <code>coverageGap.reason</code> + 回落条文原文，<b>没有静默失败</b>，这点做得对。</p>
  <p><b>校核工具已就绪</b>（实测存在）：</p>
  <pre>build/export/make_review_checklist.py  → review_checklist.csv / .md
build/export/apply_review_checklist.py → 回写 D1（默认 dry-run，必须 --apply）</pre>
  <div class="ok-box"><b>但清单还是空的</b>：<code>review_checklist.csv</code> 37 行的 <code>decision</code> 列 <b>100% 为空字符串</b>，即<b>一条都没校核过</b>。</div>

  <h3>2.2 <span class="tag t-warn">P1 · 体验劣化 + 偶发失败</span> 问答延迟中位数 60s，已撞到 100s 天花板</h3>
  <p>本次生产实测（非流式，<code>POST /api/qa</code>，同一问题「维生素C 限量」跑 6 次）：</p>
  <pre>try1  200  14.95s
try2  200  31.99s
try3  200  78.52s
try4  200  78.32s
try5  200  82.37s
try6  200  42.74s
                    中位数 ≈ 60s   最大 82s</pre>
  <p><b>6/6 成功，但波动 5.5 倍</b>（15s ~ 82s）。文档记的「37-63s」已经不够用了 —— 实测已经出现 78s / 82s。</p>
  <div class="note">
    <b>更要紧的是：本轮还实测到 1 次 <code>524</code></b>：<br>
    <code>{"error":"llm_error","status":524,"body":"error code: 524\n"}</code><br>
    524 = Cloudflare Worker 硬上限（100s）。<b>这意味着推理段再长一点，问答会直接失败，不是慢，是没答案。</b> 这是本次实测与文档最大的差异 —— 文档只说「慢」，没说「会挂」。
  </div>
  <p><b>答案质量本身是对的</b>（实测输出，引用的限量值与语料一致）：</p>
  <pre>L-抗坏血酸(维生素C)在配合饲料或全混合日粮中的推荐添加量(以维生素计)为:
猪150～300 mg/kg,家禽50～200 mg/kg,犊牛125～500 mg/kg;
罗非鱼、鲶鱼鱼苗300 mg/kg、鱼种200 mg/kg……</pre>
  <div class="ok-box"><b>流式路径（SSE）实测 23.3s 返回</b> —— 说明慢的是 reasoning 段的等待，不是检索或拼装。流式能把「首字节时间」变成体感问题，<b>这是快档里性价比最高的一招</b>。</div>

  <h3>2.3 <span class="tag t-idle">P2</span> 部署卫生</h3>
  <ul>
    <li><code>git status</code> 干净，<code>HEAD == origin/deploy/c-b-hybrid == b22d118</code>，无未跟踪文件</li>
    <li>根目录两个 docx 均已跟踪（各 1 份），此前记录的「重复副本」问题已不存在</li>
    <li><code>.gitignore</code> 无 <code>docx</code> 规则 —— 但目前不构成问题（两个都是要交付的正式件）</li>
  </ul>
</section>

<section id="s3">
  <div class="card-t">三 · 生产实测明细（2026-11-15 21:5x）</div>
  <h3>3.1 端点矩阵</h3>
  <div class="tw"><table>
    <tr><th>端点</th><th>方法</th><th>结果</th></tr>
    <tr><td><code>/api/documents</code></td><td>GET</td><td><span class="tag t-ok">200</span> · 61177 B · 2.4s</td></tr>
    <tr><td><code>/api/catalog</code></td><td>GET</td><td><span class="tag t-ok">200</span> · 62559 B · 1.5s</td></tr>
    <tr><td><code>/api/search?q=维生素C</code></td><td>GET</td><td><span class="tag t-ok">200</span> · 4.7s · 命中含原文表格</td></tr>
    <tr><td><code>/api/entities?q=维生素</code></td><td>GET</td><td><span class="tag t-ok">200</span> · 中文命中（L-抗坏血酸(维生素C)等）</td></tr>
    <tr><td><code>/api/qa</code></td><td>POST</td><td><span class="tag t-warn">200 ×6（15~82s）</span> · <span class="tag t-bad">1× 524</span></td></tr>
    <tr><td><code>/api/qa</code>（SSE）</td><td>POST</td><td><span class="tag t-ok">200</span> · 23.3s</td></tr>
    <tr><td><code>/api/compliance/usage</code></td><td>POST</td><td><span class="tag t-bad">200 <code>not_covered</code></span> · 闸门未开</td></tr>
    <tr><td><code>/api/compliance/recipe</code></td><td>POST</td><td><span class="tag t-idle">404</span>（C2 未实现）</td></tr>
    <tr><td><code>/api/compliance/label</code></td><td>POST</td><td><span class="tag t-idle">404</span>（C3 未实现）</td></tr>
    <tr><td><code>/api/calendar</code></td><td>GET</td><td><span class="tag t-idle">404</span>（未实现）</td></tr>
    <tr><td><code>/api/monitoring/releases</code></td><td>GET</td><td><span class="tag t-ok">200</span> · 5 条已抓公告</td></tr>
    <tr><td><code>/api/monitoring/impact</code></td><td>GET</td><td><span class="tag t-ok">200</span> · 按资产分组的影响面</td></tr>
    <tr><td><code>/api/monitoring/runs</code></td><td>GET</td><td><span class="tag t-ok">200</span> · 连续 8 次 <code>ok</code></td></tr>
    <tr><td><code>/api/monitoring/subscriptions</code></td><td>GET</td><td><span class="tag t-ok">200</span> · 空表（订阅了但无推送通道）</td></tr>
  </table></div>
  <p>前端页面 <code>/</code> <code>/qa</code> <code>/compliance</code> <code>/entities</code> 全部 200。</p>

  <h3>3.2 D1 远程直查（<code>wrangler d1 execute --remote</code>）</h3>
  <pre>articles              3145   (正文 1.22 MB 存在 articles.body)
chapters               529
documents              196
entities               481   (387 物质 + 94 概念)
entity_articles       1951
entity_aliases         117
substance_catalog      387   review_status: pending 387  ← 第二道闸门
compliance_rules        37   review_status: pending 37    ← 第一道闸门
rule_sets                1
regulation_releases      5
qa_sessions              4
qa_messages              8</pre>
  <p>表清单（24 张）：<code>articles</code> <code>articles_fts*</code> <code>catalog</code> <code>chapters</code> <code>compliance_rules</code> <code>documents</code> <code>entities</code> <code>entity_aliases</code> <code>entity_articles</code> <code>index_meta</code> <code>monitoring_runs</code> <code>qa_messages</code> <code>qa_sessions</code> <code>regulation_releases</code> <code>rule_sets</code> <code>subscriptions</code> <code>substance_catalog</code> + FTS 影子表。</p>

  <h3>3.3 基础设施</h3>
  <div class="tw"><table>
    <tr><th>项</th><th>状态</th><th>实测</th></tr>
    <tr><td>前端 https://siliao-web.pages.dev</td><td><span class="tag t-ok">200</span></td><td>1.8s</td></tr>
    <tr><td>API 代理链路</td><td><span class="tag t-ok">正常</span></td><td>响应头 <code>X-Proxied-By: siliao-pages-functions</code> · Pages → Worker 通</td></tr>
    <tr><td>Worker 直连 workers.dev</td><td><span class="tag t-idle">本机超时</span></td><td><b>本机直连 21s 无响应</b> —— 走 Pages 代理一切正常，判断为本机出网路径问题，<b>不是生产故障</b></td></tr>
    <tr><td>bge 语义服务 ns.hbnongfengyuan.cn</td><td><span class="tag t-ok">200</span></td><td><code>BAAI/bge-m3</code> · dim 1024 · corpus 3145 · cache_loaded true · uptime 564149s（约 6.5 天）</td></tr>
    <tr><td>检索降级标记</td><td><span class="tag t-ok">degraded:false</span></td><td>语义召回在生效</td></tr>
    <tr><td>⑤ Cron</td><td><span class="tag t-ok">健康</span></td><td>连续 8 次 <code>status=ok</code> · found=5 · bodiesFail=0 · new=0 · rev=0</td></tr>
  </table></div>
</section>

<section id="s4">
  <div class="card-t">四 · 门禁现状（本地实跑）</div>
  <div class="tw"><table>
    <tr><th>门禁</th><th>结果</th><th>对比文档记录</th></tr>
    <tr><td>worker 单测</td><td><span class="tag t-ok">309/309</span>（20 个测试文件）</td><td>254 → <b>+55</b></td></tr>
    <tr><td>worker typecheck</td><td><span class="tag t-ok">干净</span>（<code>tsc --noEmit</code> 无输出）</td><td>持平</td></tr>
    <tr><td>web 单测</td><td><span class="tag t-ok">34/34</span>（4 个测试文件）</td><td>持平</td></tr>
    <tr><td>检索 eval（带公网 bge）</td><td><span class="tag t-ok">recall@10 76.0% / MRR 0.647</span></td><td><b>与基线完全吻合</b></td></tr>
    <tr><td>├ 业务 query（20）</td><td><span class="tag t-ok">recall@10 80.0% / MRR 0.717</span></td><td>持平</td></tr>
    <tr><td>├ 语料派生（30）</td><td><span class="tag t-ok">recall@10 73.3% / MRR 0.600</span></td><td>持平</td></tr>
    <tr><td>└ negative 严格精度</td><td><span class="tag t-ok">100%（0/4 真命中）</span></td><td>持平</td></tr>
    <tr><td>引用准确率 eval</td><td><span class="tag t-ok">100%</span>（阈值 95%）· 无引用占比 0%</td><td>持平</td></tr>
    <tr><td>架构测试</td><td><span class="tag t-ok">含在 309 内 · 19 条</span></td><td>持平</td></tr>
  </table></div>
  <div class="note">
    ⚠️ 检索 eval <b>必须带 <code>BGE_SERVER_URL=https://ns.hbnongfengyuan.cn</code></b>。脚本默认指向 <code>127.0.0.1:8080</code>，本地没起 bge 时会<b>静默退化为纯 FTS5</b>（MRR 0.544），看起来像指标掉了，实际是没测到 hybrid。本次已带公网地址跑，指标与基线严丝合缝。
  </div>
  <p><b>CI workflow 清单</b>：<code>ci.yml</code>（web-test / web-build / worker-typecheck / worker-test / eval）、<code>deploy.yml</code>（push <code>main</code> 与 <code>deploy/**</code> 自动部署 Worker + Pages）、<code>api-contract.yml</code>（<b>手动触发</b>，打生产后要记得跑）、<code>seed-compliance.yml</code>（<b>手动触发 / push <code>seed/compliance</code></b>，D1 写权限用）。</p>
</section>

<section id="s5">
  <div class="card-t">五 · 代码结构（ADR-004 DDD 落地态）</div>
  <div class="flow">query/worker/src/
├── index.ts                        (只做「Request 交给路由层」)
├── interfaces/
│   ├── http/routes/                regulation / inquiry / compliance / retrieval / monitoring
│   ├── acl/                        llm · llm-stream · embedding · regulation · moa-source
│   └── composition-root.ts
├── application/
│   ├── inquiry/                    inquiry · conversation · qa-stream · prompt-builder
│   ├── compliance/                 compliance-check.usecase
│   └── monitoring/                 monitoring.usecase · monitoring.repository
├── domain/                         ① regulation ② compliance ③ inquiry ④(空壳) ⑤ monitoring
└── infrastructure/
    ├── persistence/d1/             6 个 repository impl + mappers
    └── persistence/retrieval/      hybrid-retriever.adapter</div>
  <p><b>五条强制依赖规则</b>由架构测试守护：上下文间只经 ACL、依赖方向单一、外部系统一律 ACL、只读核心域、领域服务不依赖框架。</p>
  <div class="tw"><table>
    <tr><th>ADR</th><th>主题</th><th>状态</th></tr>
    <tr><td>0001</td><td>检索后端选型 FTS5（trigram）</td><td><span class="tag t-ok">Accepted</span></td></tr>
    <tr><td>0002</td><td>Unlimited-OCR 横评试点延期</td><td><span class="tag t-idle">—</span></td></tr>
    <tr><td>0003</td><td>语料重建 + bigram RRF + 标题加权</td><td><span class="tag t-ok">Accepted</span></td></tr>
    <tr><td>0004</td><td>DDD 限界上下文与分层</td><td><span class="tag t-warn">Proposed（待业务方确认后转 Accepted）</span></td></tr>
    <tr><td>0005</td><td>方案文档 vs 实现对照</td><td><span class="tag t-acc">提案</span></td></tr>
    <tr><td>0006</td><td>M4 监测数据源选型与实现路径</td><td><span class="tag t-ok">Accepted（实现中）</span></td></tr>
  </table></div>
  <div class="note">⚠️ ADR-004 仍是 <b>Proposed</b>。它是整个代码结构的宪法，建议顺手转 Accepted。</div>
</section>

<section id="s6">
  <div class="card-t">六 · 未完成功能（实测复核）</div>
  <div class="tw"><table>
    <tr><th>#</th><th>功能</th><th>状态</th><th>阻塞</th><th>工作量</th></tr>
    <tr><td>1</td><td>D1 灌库（C1 合规规则）</td><td><span class="tag t-ok">已完成</span></td><td>—</td><td>37 规则 + 387 目录</td></tr>
    <tr><td>2</td><td>C1.5 会话表建表</td><td><span class="tag t-ok">已完成</span></td><td>—</td><td>生产实测 200</td></tr>
    <tr><td>11</td><td>④ 知识图谱</td><td><span class="tag t-ok">已补齐</span></td><td>—</td><td>481 实体 / 1951 关联</td></tr>
    <tr><td>8</td><td>⑤ 法规监测</td><td><span class="tag t-ok">已上线 11-11</span></td><td>—</td><td>领域层 + ACL + D1 + 7 端点 + Cron</td></tr>
    <tr><td><b>3</b></td><td><b>37 条规则校核</b></td><td><span class="tag t-warn">等人</span></td><td><b>等人</b></td><td><b>1-2 小时</b></td></tr>
    <tr><td><b>3b</b></td><td><b>🆕 387 条物质目录放行</b></td><td><span class="tag t-warn">等人</span></td><td><b>等人</b></td><td><b>脚本一键，但需先核过名称/别名</b></td></tr>
    <tr><td>5</td><td>组合/条件规则抽取</td><td><span class="tag t-idle">未开工</span></td><td>可做</td><td>1-2 天</td></tr>
    <tr><td>4</td><td>禁用规则抽取</td><td><span class="tag t-idle">未开工</span></td><td>可做</td><td>2-3 天</td></tr>
    <tr><td>9</td><td>合规日历</td><td><span class="tag t-idle">未开工</span></td><td>可做</td><td>2-3 天</td></tr>
    <tr><td>10</td><td>版本追溯 + 领域标记</td><td><span class="tag t-idle">未开工</span></td><td>可做</td><td>2-3 天</td></tr>
    <tr><td>6</td><td>C2 配方批量审查</td><td><span class="tag t-idle">未开工</span></td><td>可做</td><td>5-8 天</td></tr>
    <tr><td>7</td><td>C3 标签审查（GB 10648）</td><td><span class="tag t-idle">未开工</span></td><td>可做</td><td>5-8 天</td></tr>
  </table></div>
  <p><b>依赖链</b>：#4 禁用规则 → #6 C2 配方审查（缺禁用规则做不出「禁用成分标红」）。</p>
  <p><b>⑤ 监测的剩余缺口（诚实列）</b>：<code>RegulationReleaseDetected</code> <b>无消费者</b>（① 入库路径 <code>ingestRelease</code> 未开）· <b>无推送通道</b>（订阅表建了只落库不发通知）· 只到<b>公告级 diff</b>（条文级未做）· 关键词表需人工维护（实测已漏过 1 次）· 无爬虫健康外部告警。</p>
  <p><b>明确不做（数据源不存在，不是没排期）</b>：企业资质审查 · 抽检「同类产品风险提示」 · 合规日历·换证年检提醒 · 真正的历史版本回溯 · 「物质→可用替代品」映射 · 跨模块 Planner。</p>
</section>

<section id="s7">
  <div class="card-t">七 · 下一步（双档）</div>
  <h3>快档（半天到一天，低风险）</h3>
  <div class="tw"><table>
    <tr><th>项</th><th>做法</th><th>收益</th><th>代价 / 债</th></tr>
    <tr><td><b>A1 · 前端走 SSE</b></td><td>前端问答默认用流式端点</td><td>首字节从 60s → ~23s，体感提升最明显</td><td>需前端改造 + SSE 中断重试；<b>债</b>：流式与非流式两套渲染路径</td></tr>
    <tr><td><b>A2 · reasoning 熔断</b></td><td><code>reasoning_content</code> 超阈值/超时 → 降级非 reasoning 模型</td><td>直接压住 524（实测已发生）</td><td><b>债</b>：降级后质量未验证，需重跑引用准确率 eval</td></tr>
    <tr><td><b>A3 · P95 指标 + 超时告警</b></td><td>采集 <code>elapsed_ms</code> 分位数，超阈值告警</td><td>让劣化<b>可观测</b>，不再静默</td><td>无</td></tr>
    <tr><td><b>A4 · ADR-004 转 Accepted</b></td><td>改 ADR 状态</td><td>架构宪法落地</td><td>无</td></tr>
    <tr><td><b>A5 · 文档同步</b></td><td>README / project-status 停在 11-09</td><td>消除认知偏差</td><td>无</td></tr>
  </table></div>
  <h3>对档（1-2 周）</h3>
  <div class="tw"><table>
    <tr><th>项</th><th>做法</th><th>收益</th><th>代价 / 债</th></tr>
    <tr><td><b>B1 · 双闸门开闸</b></td><td>37 条规则逐条校核 + 387 目录核名放行</td><td>② 正式上线，三态可实测</td><td>人工量比文档记的多一截（目录那 387 条）</td></tr>
    <tr><td><b>B2 · 换非 reasoning 模型</b></td><td>MiniMax 非 thinking 版，延迟回 10-15s</td><td>根治延迟</td><td><b>必须重跑引用准确率 eval 确认质量不降</b></td></tr>
    <tr><td><b>B3 · #10 版本追溯 + 领域标记</b></td><td>加 <code>domain</code> 字段 + <code>supersedes_doc_id</code></td><td>支持「只查兽药法规」；32 份兽药法规可过滤</td><td>schema 变更 → 需单独 migration（<b>绝不能重跑 schema.sql</b>）</td></tr>
    <tr><td><b>B4 · #5 + #4 规则抽取</b></td><td>组合/条件 + 禁用规则</td><td>覆盖 39 个含「禁用」条款的文件</td><td>抽取必须走 <code>review_status</code> 闸门（假阳性：「不得在饲料生产过程中进行维修、焊接」不是禁用物质）</td></tr>
  </table></div>
  <div class="lead">
    <b>我建议的顺序</b>：先 <b>A1 + A2 + A3</b>（半天，纯工程，无人工依赖），同时把 <b>B1</b> 的校核清单发给业务方。A1 是唯一能把「60s 体感」变成「23s 体感」的改动，代价最小；A2 直接消除 524 这个<b>真失败</b>。B1 是 ② 上线的唯一门槛，但卡在人，越早发起越好。
  </div>
</section>

<section id="s8">
  <div class="card-t">八 · 已踩过的坑（别重蹈）</div>
  <ol>
    <li><b><code>return promise</code> 不会进 try/catch</b> —— 必须 <code>return await promise</code>。抽路由层时丢了 await，生产报 1101，根因是 D1 报错被掩盖成 Worker 崩溃。</li>
    <li><b><code>.gitignore</code> 行内注释不生效</b> —— <code>Images/   # 说明</code> 整行都是匹配模式，曾提交 510 张扫描图（3.2GB）。注释必须单独占一行。</li>
    <li><b>不能重跑 <code>schema.sql</code></b> —— 生产库 3145 条条文，wrangler 4.127+ 对「schema 变了」的库报 <code>D1_RESET_DO</code>，<b>会清空远端表</b>。用 <code>migrate_c1.sql</code> / <code>migrate_c15.sql</code> 单独跑。</li>
    <li><b>不要用 wrangler OAuth token 跑 CI</b> —— 1 小时过期且 refresh_token 每次轮换。</li>
    <li><b>SQLite 的 <code>LIKE</code> 对中文无效</b> —— 实测 <code>?q=维生素</code> → 0 条。改用 <code>instr()</code> → 15 条。<b>换回 LIKE 不会报错，只是永远搜不到东西。</b></li>
    <li><b>eval 不指定公网 BGE 地址会静默退化</b> —— 看着像指标掉了，实际没测到 hybrid。</li>
    <li><b>reasoning 模型 <code>max_tokens</code> 与 <code>content</code> 共用配额</b> —— 给太小答案整段变空，给太大延迟劣化到 40-60s，<b>再大就撞 100s 变 524</b>。</li>
    <li><b>合规速查是两道闸门</b> —— 只校核规则不放行目录，判定恒为 <code>not_covered</code>。</li>
    <li><b><code>/api/qa</code> 的 body 字段是 <code>q</code></b>（别名 <code>question</code> / <code>ask</code>），且 <code>stream</code> 可选。<b>写错字段名会静默返回 400 <code>missing_query</code></b>，不会报错提示。</li>
    <li><b><code>/api/compliance/usage</code> 必须 <code>value</code> 数字 + <code>unit</code> 必填</b> —— 缺一个都是 400。</li>
  </ol>
</section>

<section id="s9">
  <div class="card-t">九 · 资源快照</div>
  <div class="tw"><table>
    <tr><th>项</th><th>值</th></tr>
    <tr><td>语料 <code>minimax/</code></td><td>1021 页 → 4.8 MB</td></tr>
    <tr><td><code>data/</code>（摄入产物 + 旧产物）</td><td>2.8 GB（大部分是已废的 raw/markdown）</td></tr>
    <tr><td><code>evals/bge_m3_cache.json</code></td><td>69 MB</td></tr>
    <tr><td><code>evals/tfidf_cache.json</code></td><td>19 MB</td></tr>
    <tr><td><code>evals/articles_cache.json</code></td><td>3.4 MB</td></tr>
    <tr><td>D1 <code>articles.body</code> 正文</td><td>1.22 MB（不依赖 R2）</td></tr>
    <tr><td>bge 服务</td><td><code>https://ns.hbnongfengyuan.cn</code> · BAAI/bge-m3 · dim 1024 · corpus 3145</td></tr>
    <tr><td>LLM</td><td>MiniMax-M3.1-Flash（reasoning 模型，OpenAI 兼容端点）</td></tr>
    <tr><td>tag</td><td><code>v1.0.0-production</code> @ <code>b4645d7</code>（纯 RAG 基线，M1~M4 均在其后）</td></tr>
  </table></div>
</section>

<footer>
  饲料法规 RAG 项目 · 现状报告 · 2026-11-15<br>
  测量方式：生产环境实测 + 本地门禁实跑 + D1 远程直查（非文档复述）<br>
  代码基线 deploy/c-b-hybrid @ b22d118
</footer>
"""

HTML = (
    "<!DOCTYPE html>\n"
    '<html lang="zh-CN">\n'
    "<head>\n"
    '<meta charset="UTF-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    "<title>饲料法规 RAG 项目 · 现状报告 2026-11-15</title>\n"
    "<style>\n" + STYLE + "\n</style>\n"
    "</head>\n"
    "<body>\n"
    '<div class="wrap">\n' + BODY + "\n</div>\n"
    "</body>\n"
    "</html>\n"
)

with io.open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)

print("[OK] ->", OUT, len(HTML), "chars")
