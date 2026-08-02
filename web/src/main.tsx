import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'

import { HomePage } from './pages/HomePage'
import { DocumentPage } from './pages/DocumentPage'
import { ChapterPage } from './pages/ChapterPage'
import { SearchPage } from './pages/SearchPage'
import { EntityPage } from './pages/EntityPage'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/doc/:docId" element={<DocumentPage />} />
        <Route path="/doc/:docId/chapter/:chapterId" element={<ChapterPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/entity/:name" element={<EntityPage />} />
        <Route path="*" element={
          <div className="p-8 text-center">
            <h1 className="text-2xl font-bold">404</h1>
            <p className="text-slate-500 mt-2">页面不存在</p>
          </div>
        } />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)