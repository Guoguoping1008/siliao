import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'

import { HomePage } from './pages/HomePage'
import { DocumentPage } from './pages/DocumentPage'
import { ChapterPage } from './pages/ChapterPage'
import { SearchPage } from './pages/SearchPage'
import { EntityPage } from './pages/EntityPage'
import { QAPage } from './pages/QAPage'
import { ErrorBoundary } from './components/ErrorBoundary'
import { NotFound } from './components/NotFound'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/doc/:docId" element={<DocumentPage />} />
          <Route path="/doc/:docId/chapter/:chapterId" element={<ChapterPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/entity/:name" element={<EntityPage />} />
          <Route path="/qa" element={<QAPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>
)