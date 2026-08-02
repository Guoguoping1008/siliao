import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import './index.css'

function Home() {
  return (
    <div className="min-h-screen bg-slate-50 p-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-primary">农业饲料法规知识库</h1>
        <p className="text-slate-600 mt-2">基于《中国农业饲料法规 2026 版》</p>
      </header>
      <div className="bg-white rounded-lg shadow p-6 max-w-2xl">
        <h2 className="text-xl font-semibold mb-3">在线检索</h2>
        <form action="/api/search" method="get" className="flex gap-2">
          <input name="q" placeholder="例如:饲料添加剂审定" className="flex-1 border rounded px-3 py-2" />
          <button className="bg-primary text-white px-4 py-2 rounded">搜索</button>
        </form>
        <p className="text-xs text-slate-500 mt-2">搜索结果按章节展示,点击跳转到原文</p>
      </div>
      <nav className="mt-8 flex gap-4">
        <Link to="/chapters" className="text-primary hover:underline">章节目录</Link>
        <Link to="/qa" className="text-primary hover:underline">问答</Link>
      </nav>
    </div>
  )
}

function Placeholder({ title }: { title: string }) {
  return (
    <div className="min-h-screen bg-slate-50 p-8">
      <Link to="/" className="text-primary text-sm">← 返回首页</Link>
      <h1 className="text-2xl font-bold mt-4">{title}</h1>
      <p className="text-slate-500 mt-2">此页面将在阶段 F 后续迭代中补完。</p>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/chapters" element={<Placeholder title="章节目录" />} />
        <Route path="/qa" element={<Placeholder title="问答" />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)