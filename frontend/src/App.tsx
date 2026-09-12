import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { EquipmentDetailPage } from './pages/EquipmentDetailPage'
import { EquipmentListPage } from './pages/EquipmentListPage'
import { HomePage } from './pages/HomePage'
import { InspectionDetailPage } from './pages/InspectionDetailPage'
import { InspectionFormPage } from './pages/InspectionFormPage'
import { InspectionHistoryPage } from './pages/InspectionHistoryPage'
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
        {/* Frozen permanent QR route (Phase 2) — never encodes a
            checklist/inspection ID. Inspection entry points are separate
            nested routes below. */}
        <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
        <Route path="/vehicle/:vehicleId/inspect" element={<InspectionFormPage />} />
        <Route path="/vehicle/:vehicleId/inspections" element={<InspectionHistoryPage />} />
        <Route path="/equipment" element={<EquipmentListPage />} />
        <Route path="/equipment/:equipmentId" element={<EquipmentDetailPage />} />
        <Route path="/equipment/:equipmentId/inspect" element={<InspectionFormPage />} />
        <Route path="/equipment/:equipmentId/inspections" element={<InspectionHistoryPage />} />
        <Route path="/inspections/:inspectionId" element={<InspectionDetailPage />} />
      </Routes>
    </AppLayout>
  )
}

export default App
