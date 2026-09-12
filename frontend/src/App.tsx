import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { EquipmentDetailPage } from './pages/EquipmentDetailPage'
import { EquipmentListPage } from './pages/EquipmentListPage'
import { HomePage } from './pages/HomePage'
import { SystemStatusPage } from './pages/SystemStatusPage'
import { VehicleDetailPage } from './pages/VehicleDetailPage'
import { VehicleListPage } from './pages/VehicleListPage'

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/system-status" element={<SystemStatusPage />} />
        <Route path="/vehicles" element={<VehicleListPage />} />
        <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
        <Route path="/equipment" element={<EquipmentListPage />} />
        <Route path="/equipment/:equipmentId" element={<EquipmentDetailPage />} />
      </Routes>
    </AppLayout>
  )
}

export default App
