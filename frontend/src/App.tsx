import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { HomePage } from './pages/HomePage'
import { SystemStatusPage } from './pages/SystemStatusPage'

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/system-status" element={<SystemStatusPage />} />
      </Routes>
    </AppLayout>
  )
}

export default App
