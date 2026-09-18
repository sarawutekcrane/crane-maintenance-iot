import { Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { AssetPartsPage } from './pages/AssetPartsPage'
import { DriverDetailPage } from './pages/DriverDetailPage'
import { DriverListPage } from './pages/DriverListPage'
import { EquipmentDetailPage } from './pages/EquipmentDetailPage'
import { EquipmentListPage } from './pages/EquipmentListPage'
import { HomePage } from './pages/HomePage'
import { InspectionDetailPage } from './pages/InspectionDetailPage'
import { InspectionFormPage } from './pages/InspectionFormPage'
import { InspectionHistoryPage } from './pages/InspectionHistoryPage'
import { MyWorkPage } from './pages/MyWorkPage'
import { OpenRepairQueuePage } from './pages/OpenRepairQueuePage'
import { PartDetailPage } from './pages/PartDetailPage'
import { PartInstanceCreatePage } from './pages/PartInstanceCreatePage'
import { PartInstanceDetailPage } from './pages/PartInstanceDetailPage'
import { PartListPage } from './pages/PartListPage'
import { PmStatusPage } from './pages/PmStatusPage'
import { PmWorkOrderDetailPage } from './pages/PmWorkOrderDetailPage'
import { PmWorkOrderHistoryPage } from './pages/PmWorkOrderHistoryPage'
import { RepairCreatePage } from './pages/RepairCreatePage'
import { RepairDetailPage } from './pages/RepairDetailPage'
import { RepairHistoryPage } from './pages/RepairHistoryPage'
import { RepairRequestDetailPage } from './pages/RepairRequestDetailPage'
import { RepairRequestQueuePage } from './pages/RepairRequestQueuePage'
import { SystemStatusPage } from './pages/SystemStatusPage'
import { WaitingAssignmentQueuePage } from './pages/WaitingAssignmentQueuePage'
import { VehicleCertificatesPage } from './pages/VehicleCertificatesPage'
import { VehicleDetailPage } from './pages/VehicleDetailPage'
import { VehicleDriverAssignmentsPage } from './pages/VehicleDriverAssignmentsPage'
import { VehicleListPage } from './pages/VehicleListPage'

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/system-status" element={<SystemStatusPage />} />
        <Route path="/vehicles" element={<VehicleListPage />} />
        {/* Frozen permanent QR route (Phase 2) — never encodes a
            checklist/inspection ID. Inspection/PM/Repair entry points are
            separate nested routes below. */}
        <Route path="/vehicle/:vehicleId" element={<VehicleDetailPage />} />
        <Route path="/vehicle/:vehicleId/inspect" element={<InspectionFormPage />} />
        <Route path="/vehicle/:vehicleId/inspections" element={<InspectionHistoryPage />} />
        <Route path="/vehicle/:vehicleId/pm" element={<PmStatusPage />} />
        <Route path="/vehicle/:vehicleId/pm/history" element={<PmWorkOrderHistoryPage />} />
        <Route path="/vehicle/:vehicleId/repairs/new" element={<RepairCreatePage />} />
        <Route path="/vehicle/:vehicleId/repairs" element={<RepairHistoryPage />} />
        <Route path="/vehicle/:vehicleId/parts" element={<AssetPartsPage />} />
        <Route path="/vehicle/:vehicleId/drivers" element={<VehicleDriverAssignmentsPage />} />
        <Route path="/vehicle/:vehicleId/certificates" element={<VehicleCertificatesPage />} />
        <Route path="/equipment" element={<EquipmentListPage />} />
        <Route path="/equipment/:equipmentId" element={<EquipmentDetailPage />} />
        <Route path="/equipment/:equipmentId/inspect" element={<InspectionFormPage />} />
        <Route path="/equipment/:equipmentId/inspections" element={<InspectionHistoryPage />} />
        <Route path="/equipment/:equipmentId/pm" element={<PmStatusPage />} />
        <Route path="/equipment/:equipmentId/pm/history" element={<PmWorkOrderHistoryPage />} />
        <Route path="/equipment/:equipmentId/repairs/new" element={<RepairCreatePage />} />
        <Route path="/equipment/:equipmentId/repairs" element={<RepairHistoryPage />} />
        <Route path="/equipment/:equipmentId/parts" element={<AssetPartsPage />} />
        <Route path="/inspections/:inspectionId" element={<InspectionDetailPage />} />
        <Route path="/pm/work-orders/:workOrderId" element={<PmWorkOrderDetailPage />} />
        <Route path="/repairs/:repairId" element={<RepairDetailPage />} />
        <Route path="/repair-requests/:repairRequestId" element={<RepairRequestDetailPage />} />
        <Route path="/my-work" element={<MyWorkPage />} />
        <Route path="/open-repair-queue" element={<OpenRepairQueuePage />} />
        <Route path="/repair-request-queue" element={<RepairRequestQueuePage />} />
        <Route path="/waiting-assignment" element={<WaitingAssignmentQueuePage />} />
        <Route path="/parts" element={<PartListPage />} />
        <Route path="/parts/:partId" element={<PartDetailPage />} />
        <Route path="/parts/:partId/instances/new" element={<PartInstanceCreatePage />} />
        <Route path="/part-instances/:instanceId" element={<PartInstanceDetailPage />} />
        <Route path="/drivers" element={<DriverListPage />} />
        <Route path="/drivers/:driverId" element={<DriverDetailPage />} />
      </Routes>
    </AppLayout>
  )
}

export default App
