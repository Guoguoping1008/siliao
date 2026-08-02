/**
 * Mock 后端 — 离线开发用
 *
 * 数据来源: data/markdown/feed-law-2026/(章节切分器真实产物)
 * 切分器按"第X章 / 第X条"切,符合法规知识库的核心要求。
 *
 * 切换到真实后端:  VITE_USE_MOCK=false npm run dev
 */

import type {
  Document, Chapter, ChapterDetail, Article, ArticleDetail, SearchHit,
  Entity,
} from "./api"

const DOC: Document = {
  "doc_id": "feed-law-2026",
  "title": "饲料和饲料添加剂管理条例(2026)",
  "doc_number": "农业农村部令 第78号",
  "issuer": "农业农村部",
  "effective_date": "2026-07-01",
  "chapter_count": 6,
  "article_count": 16
}

const CHAPTERS: ChapterDetail[] = [
  {
    "chapter_id": "ch01",
    "doc_id": "feed-law-2026",
    "number": "第一章",
    "title": "总则",
    "article_count": 4,
    "sort_order": 1,
    "markdown": "# 第一章 总则\n\n> doc_id: feed-law-2026 · chapter_id: ch01 · articles: 4\n\n第一章 总则\n\n第一条 为了加强对饲料和饲料添加剂的管理,保障饲料和饲料添加剂质量安全,促进饲料工业和养殖业健康发展,维护人体健康,根据《农业法》《农产品质量安全法》等法律,制定本条例。\n\n第二条 在中华人民共和国境内从事饲料和饲料添加剂的研制、生产、经营、使用、检验、监督等活动,应当遵守本条例。\n\n第三条 本条例所称饲料,是指经工业化加工、制作的供动物食用的产品,包括单一饲料、添加剂预混合饲料、浓缩饲料、配合饲料和精料补充料。\n\n第四条 国务院农业农村主管部门负责全国饲料和饲料添加剂的监督管理工作。"
  },
  {
    "chapter_id": "ch02",
    "doc_id": "feed-law-2026",
    "number": "第二章",
    "title": "审定与登记",
    "article_count": 3,
    "sort_order": 2,
    "markdown": "# 第二章 审定与登记\n\n> doc_id: feed-law-2026 · chapter_id: ch02 · articles: 3\n\n第二章 审定与登记\n\n第五条 国家实行饲料和饲料添加剂审定制度。从事饲料和饲料添加剂生产的企业,应当取得相应的审定证书。\n\n第六条 申请饲料添加剂审定,应当向国务院农业农村主管部门提交下列材料:\n(一)申请书;\n(二)产品配方;\n(三)生产工艺;\n(四)质量标准及检验方法;\n(五)安全性评价报告。\n\n第七条 国务院农业农村主管部门应当自受理申请之日起 60 日内作出决定。对符合条件的,发给饲料添加剂审定证书。"
  },
  {
    "chapter_id": "ch03",
    "doc_id": "feed-law-2026",
    "number": "第三章",
    "title": "生产与经营",
    "article_count": 3,
    "sort_order": 3,
    "markdown": "# 第三章 生产与经营\n\n> doc_id: feed-law-2026 · chapter_id: ch03 · articles: 3\n\n第三章 生产与经营\n\n第八条 从事饲料生产的企业,应当具备下列条件:\n(一)有与生产规模相适应的厂房、设备和仓储设施;\n(二)有与生产规模相适应的质量检验机构、检验人员和检验设备;\n(三)有健全的质量管理制度;\n(四)法律、行政法规规定的其他条件。\n\n第九条 饲料生产企业应当按照饲料质量标准组织生产,对其生产的产品质量负责。\n\n第十条 经营饲料和饲料添加剂,应当取得相应的经营许可证书。"
  },
  {
    "chapter_id": "ch04",
    "doc_id": "feed-law-2026",
    "number": "第四章",
    "title": "监督管理",
    "article_count": 3,
    "sort_order": 4,
    "markdown": "# 第四章 监督管理\n\n> doc_id: feed-law-2026 · chapter_id: ch04 · articles: 3\n\n第四章 监督管理\n\n第十一条 县级以上人民政府农业农村主管部门负责本行政区域内的饲料和饲料添加剂监督管理工作。\n\n第十二条 县级以上人民政府农业农村主管部门在进行监督检查时,有权采取下列措施:\n(一)进入生产经营场所实施现场检查;\n(二)对生产、经营、使用的产品进行抽样检验;\n(三)查阅、复制有关的合同、票据、账簿以及其他有关资料。\n\n第十三条 禁止生产、经营、使用未取得审定证书的饲料添加剂。"
  },
  {
    "chapter_id": "ch05",
    "doc_id": "feed-law-2026",
    "number": "第五章",
    "title": "法律责任",
    "article_count": 2,
    "sort_order": 5,
    "markdown": "# 第五章 法律责任\n\n> doc_id: feed-law-2026 · chapter_id: ch05 · articles: 2\n\n第五章 法律责任\n\n第十四条 违反本条例规定,未取得审定证书生产饲料添加剂的,由县级以上地方人民政府农业农村主管部门责令停止生产,没收违法所得和违法生产的产品,并处违法生产的产品货值金额 3 倍以上 5 倍以下的罚款。\n\n第十五条 违反本条例规定,生产、经营假饲料或者假饲料添加剂的,依照《农产品质量安全法》的有关规定处罚。"
  },
  {
    "chapter_id": "ch06",
    "doc_id": "feed-law-2026",
    "number": "第六章",
    "title": "附则",
    "article_count": 1,
    "sort_order": 6,
    "markdown": "# 第六章 附则\n\n> doc_id: feed-law-2026 · chapter_id: ch06 · articles: 1\n\n第六章 附则\n\n第十六条 本条例自 2026 年 7 月 1 日起施行。"
  }
]

const ARTICLES: ArticleDetail[] = [
  {
    "article_id": "art001",
    "chapter_id": "ch01",
    "doc_id": "feed-law-2026",
    "number": "第一条",
    "chapter_number": "第一章",
    "chapter_title": "总则",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch01 · article_id: art001 · number: 第一条 -->\n\n第一条 为了加强对饲料和饲料添加剂的管理,保障饲料和饲料添加剂质量安全,促进饲料工业和养殖业健康发展,维护人体健康,根据《农业法》《农产品质量安全法》等法律,制定本条例。"
  },
  {
    "article_id": "art002",
    "chapter_id": "ch01",
    "doc_id": "feed-law-2026",
    "number": "第二条",
    "chapter_number": "第一章",
    "chapter_title": "总则",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch01 · article_id: art002 · number: 第二条 -->\n\n第二条 在中华人民共和国境内从事饲料和饲料添加剂的研制、生产、经营、使用、检验、监督等活动,应当遵守本条例。"
  },
  {
    "article_id": "art003",
    "chapter_id": "ch01",
    "doc_id": "feed-law-2026",
    "number": "第三条",
    "chapter_number": "第一章",
    "chapter_title": "总则",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch01 · article_id: art003 · number: 第三条 -->\n\n第三条 本条例所称饲料,是指经工业化加工、制作的供动物食用的产品,包括单一饲料、添加剂预混合饲料、浓缩饲料、配合饲料和精料补充料。"
  },
  {
    "article_id": "art004",
    "chapter_id": "ch01",
    "doc_id": "feed-law-2026",
    "number": "第四条",
    "chapter_number": "第一章",
    "chapter_title": "总则",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch01 · article_id: art004 · number: 第四条 -->\n\n第四条 国务院农业农村主管部门负责全国饲料和饲料添加剂的监督管理工作。"
  },
  {
    "article_id": "art005",
    "chapter_id": "ch02",
    "doc_id": "feed-law-2026",
    "number": "第五条",
    "chapter_number": "第二章",
    "chapter_title": "审定与登记",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch02 · article_id: art005 · number: 第五条 -->\n\n第五条 国家实行饲料和饲料添加剂审定制度。从事饲料和饲料添加剂生产的企业,应当取得相应的审定证书。"
  },
  {
    "article_id": "art006",
    "chapter_id": "ch02",
    "doc_id": "feed-law-2026",
    "number": "第六条",
    "chapter_number": "第二章",
    "chapter_title": "审定与登记",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch02 · article_id: art006 · number: 第六条 -->\n\n第六条 申请饲料添加剂审定,应当向国务院农业农村主管部门提交下列材料:\n(一)申请书;\n(二)产品配方;\n(三)生产工艺;\n(四)质量标准及检验方法;\n(五)安全性评价报告。"
  },
  {
    "article_id": "art007",
    "chapter_id": "ch02",
    "doc_id": "feed-law-2026",
    "number": "第七条",
    "chapter_number": "第二章",
    "chapter_title": "审定与登记",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch02 · article_id: art007 · number: 第七条 -->\n\n第七条 国务院农业农村主管部门应当自受理申请之日起 60 日内作出决定。对符合条件的,发给饲料添加剂审定证书。"
  },
  {
    "article_id": "art008",
    "chapter_id": "ch03",
    "doc_id": "feed-law-2026",
    "number": "第八条",
    "chapter_number": "第三章",
    "chapter_title": "生产与经营",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch03 · article_id: art008 · number: 第八条 -->\n\n第八条 从事饲料生产的企业,应当具备下列条件:\n(一)有与生产规模相适应的厂房、设备和仓储设施;\n(二)有与生产规模相适应的质量检验机构、检验人员和检验设备;\n(三)有健全的质量管理制度;\n(四)法律、行政法规规定的其他条件。"
  },
  {
    "article_id": "art009",
    "chapter_id": "ch03",
    "doc_id": "feed-law-2026",
    "number": "第九条",
    "chapter_number": "第三章",
    "chapter_title": "生产与经营",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch03 · article_id: art009 · number: 第九条 -->\n\n第九条 饲料生产企业应当按照饲料质量标准组织生产,对其生产的产品质量负责。"
  },
  {
    "article_id": "art010",
    "chapter_id": "ch03",
    "doc_id": "feed-law-2026",
    "number": "第十条",
    "chapter_number": "第三章",
    "chapter_title": "生产与经营",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch03 · article_id: art010 · number: 第十条 -->\n\n第十条 经营饲料和饲料添加剂,应当取得相应的经营许可证书。"
  },
  {
    "article_id": "art011",
    "chapter_id": "ch04",
    "doc_id": "feed-law-2026",
    "number": "第十一条",
    "chapter_number": "第四章",
    "chapter_title": "监督管理",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch04 · article_id: art011 · number: 第十一条 -->\n\n第十一条 县级以上人民政府农业农村主管部门负责本行政区域内的饲料和饲料添加剂监督管理工作。"
  },
  {
    "article_id": "art012",
    "chapter_id": "ch04",
    "doc_id": "feed-law-2026",
    "number": "第十二条",
    "chapter_number": "第四章",
    "chapter_title": "监督管理",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch04 · article_id: art012 · number: 第十二条 -->\n\n第十二条 县级以上人民政府农业农村主管部门在进行监督检查时,有权采取下列措施:\n(一)进入生产经营场所实施现场检查;\n(二)对生产、经营、使用的产品进行抽样检验;\n(三)查阅、复制有关的合同、票据、账簿以及其他有关资料。"
  },
  {
    "article_id": "art013",
    "chapter_id": "ch04",
    "doc_id": "feed-law-2026",
    "number": "第十三条",
    "chapter_number": "第四章",
    "chapter_title": "监督管理",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch04 · article_id: art013 · number: 第十三条 -->\n\n第十三条 禁止生产、经营、使用未取得审定证书的饲料添加剂。"
  },
  {
    "article_id": "art014",
    "chapter_id": "ch05",
    "doc_id": "feed-law-2026",
    "number": "第十四条",
    "chapter_number": "第五章",
    "chapter_title": "法律责任",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch05 · article_id: art014 · number: 第十四条 -->\n\n第十四条 违反本条例规定,未取得审定证书生产饲料添加剂的,由县级以上地方人民政府农业农村主管部门责令停止生产,没收违法所得和违法生产的产品,并处违法生产的产品货值金额 3 倍以上 5 倍以下的罚款。"
  },
  {
    "article_id": "art015",
    "chapter_id": "ch05",
    "doc_id": "feed-law-2026",
    "number": "第十五条",
    "chapter_number": "第五章",
    "chapter_title": "法律责任",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch05 · article_id: art015 · number: 第十五条 -->\n\n第十五条 违反本条例规定,生产、经营假饲料或者假饲料添加剂的,依照《农产品质量安全法》的有关规定处罚。"
  },
  {
    "article_id": "art016",
    "chapter_id": "ch06",
    "doc_id": "feed-law-2026",
    "number": "第十六条",
    "chapter_number": "第六章",
    "chapter_title": "附则",
    "markdown": "<!-- doc_id: feed-law-2026 · chapter_id: ch06 · article_id: art016 · number: 第十六条 -->\n\n第十六条 本条例自 2026 年 7 月 1 日起施行。"
  }
]

const ENTITIES: Entity[] = [
  {
    "entity_id": "ent_001",
    "name": "农业农村部",
    "type": "AGENCY",
    "description": "国务院农业农村主管部门,负责全国饲料和饲料添加剂的监督管理工作。"
  },
  {
    "entity_id": "ent_002",
    "name": "饲料添加剂审定证书",
    "type": "CERTIFICATE",
    "description": "国家对饲料添加剂实行审定制度。申请饲料添加剂审定应当向农业农村部提交申请书、产品配方等材料。"
  },
  {
    "entity_id": "ent_003",
    "name": "饲料生产企业",
    "type": "PARTY",
    "description": "从事饲料生产的企业,应当具备厂房、设备、质量检验机构等条件。"
  }
]

const ENTITY_ARTICLES: Record<string, string[]> = {
  "ent_001": [
    "art001",
    "art004",
    "art011",
    "art013"
  ],
  "ent_002": [
    "art005",
    "art006",
    "art007"
  ],
  "ent_003": [
    "art008",
    "art009"
  ]
}

// 把 ARTICLE markdown 切成 excerpt(前 200 字符,剔除 markdown 注释行)
function excerptOf(md: string): string {
  return md
    .split("\n")
    .filter(l => !l.startsWith("<!--"))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 200)
}

export const mockApi = {
  async listDocuments(): Promise<Document[]> {
    await new Promise(r => setTimeout(r, 50))
    return [DOC]
  },

  async listChapters(docId: string): Promise<Chapter[]> {
    await new Promise(r => setTimeout(r, 50))
    return CHAPTERS
      .filter(c => c.doc_id === docId)
      .map(({ markdown, ...rest }) => rest)
      .sort((a, b) => a.sort_order - b.sort_order)
  },

  async getChapter(docId: string, chapterId: string): Promise<ChapterDetail> {
    await new Promise(r => setTimeout(r, 50))
    const c = CHAPTERS.find(c => c.doc_id === docId && c.chapter_id === chapterId)
    if (!c) throw new Error(`chapter not found: ${chapterId}`)
    return c
  },

  async getArticle(articleId: string): Promise<ArticleDetail> {
    await new Promise(r => setTimeout(r, 50))
    const a = ARTICLES.find(a => a.article_id === articleId)
    if (!a) throw new Error(`article not found: ${articleId}`)
    return a
  },

  async search(q: string): Promise<SearchHit[]> {
    await new Promise(r => setTimeout(r, 80))
    const query = q.toLowerCase()
    const hits: SearchHit[] = []
    for (const a of ARTICLES) {
      const text = a.markdown.toLowerCase()
      if (text.includes(query)) {
        hits.push({
          ...a,
          excerpt: excerptOf(a.markdown),
          relevance: (text.match(new RegExp(query, "g")) || []).length,
        })
      }
    }
    return hits.sort((a, b) => (b.relevance || 0) - (a.relevance || 0))
  },

  async getEntity(name: string): Promise<{ entity: Entity; articles: Article[] }> {
    await new Promise(r => setTimeout(r, 50))
    const ent = ENTITIES.find(e => e.name === name)
    if (!ent) throw new Error(`entity not found: ${name}`)
    const articleIds = ENTITY_ARTICLES[ent.entity_id] || []
    const arts = ARTICLES.filter(a => articleIds.includes(a.article_id))
      .map(({ markdown, ...rest }) => rest)
    return { entity: ent, articles: arts }
  },
}
