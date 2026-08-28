## 改了什么

<!-- 1-3 句话概括本 PR 的目的 -->

## 关联任务

<!-- Kanban 卡片 ID,如 t_847af463 -->

## 验收

<!-- 勾选所有适用项 -->
- [ ] `npm run build` 在 web/ 通过
- [ ] `npx tsc --noEmit` 在 query/worker 通过
- [ ] `python evals/eval_retrieval.py` 通过(recall@10 ≥ 80%)
- [ ] `python evals/eval_qa_faithfulness.py` 通过
- [ ] 新增/修改的路由有 miniflare 烟测
- [ ] 文档(README/docs/adr)同步更新

## 测试

<!-- 怎么手动验证 -->

## 截图(如有 UI 改动)

<!-- 粘贴截图 -->

## 风险

<!-- 是否触及 schema/R2 路径/CORS 等关键路径?回滚方案? -->
