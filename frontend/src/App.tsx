import { Navigate, Route, Routes, generatePath, useParams } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { AssetPartsPage } from './pages/AssetPartsPage'
import { CertificateExpiryReportPage } from './pages/CertificateExpiryReportPage'
import { DepartmentDetailPage } from './pages/DepartmentDetailPage'
import { DepartmentListPage } from './pages/DepartmentListPage'
import { InspectionFindingReportPage } from './pages/InspectionFindingReportPage'
import { DriverDetailPage } from './pages/DriverDetailPage'
import { DriverListPage } from './pages/DriverListPage'
import { EquipmentDetailPage } from './pages/EquipmentDetailPage'
import { EquipmentListPage } from './pages/EquipmentListPage'
import { FleetStatusPage } from './pages/FleetStatusPage'
import { HomePage } from './pages/HomePage'
import { InspectionDetailPage } from './pages/InspectionDetailPage'
import { InspectionFormPage } from './pages/InspectionFormPage'
import { InspectionHistoryPage } from './pages/InspectionHistoryPage'
import { ModelDocumentsPage } from './pages/ModelDocumentsPage'
import { MyWorkPage } from './pages/MyWorkPage'
import { OpenRepairQueuePage } from './pages/OpenRepairQueuePage'
import { PartDetailPage } from './pages/PartDetailPage'
import { PartInstanceCreatePage } from './pages/PartInstanceCreatePage'
import { PartInstanceDetailPage } from './pages/PartInstanceDetailPage'
import { PartListPage } from './pages/PartListPage'
import { PersonnelDetailPage } from './pages/PersonnelDetailPage'
import { PersonnelListPage } from './pages/PersonnelListPage'
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
import { VehicleAlertsPage } from './pages/VehicleAlertsPage'
import { VehicleCertificatesPage } from './pages/VehicleCertificatesPage'
import { VehicleDailySummaryPage } from './pages/VehicleDailySummaryPage'
import { VehicleDetailPage } from './pages/VehicleDetailPage'
import { VehicleListPage } from './pages/VehicleListPage'
import { VehicleWorkHistoryPage } from './pages/VehicleWorkHistoryPage'

/** Redirects a retired B4 `/v2/...` path to its canonical page, keeping the ids. */
function LegacyV2Redirect({ to }: { to: string }) {
  const params = useParams()
  return <Navigate to={generatePath(to, params)} replace />
}

export function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/dashboard" element={<FleetStatusPage />} />
        <Route path="/reports/certificate-expiry" element={<CertificateExpiryReportPage />} />
        <Route path="/reports/inspection-findings" element={<InspectionFindingReportPage />} />
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
        <Route path="/vehicle/:vehicleId/certificates" element={<VehicleCertificatesPage />} />
        <Route path="/vehicle/:vehicleId/work-history" element={<VehicleWorkHistoryPage />} />
        <Route path="/vehicle/:vehicleId/daily-summary" element={<VehicleDailySummaryPage />} />
        <Route path="/vehicle/:vehicleId/alerts" element={<VehicleAlertsPage />} />
        <Route path="/models/:modelId/documents" element={<ModelDocumentsPage />} />
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
        {/* R2 Batch R2e — personnel / department lifecycle */}
        <Route path="/personnel" element={<PersonnelListPage />} />
        <Route path="/personnel/:personnelId" element={<PersonnelDetailPage />} />
        <Route path="/departments" element={<DepartmentListPage />} />
        <Route path="/departments/:departmentId" element={<DepartmentDetailPage />} />
        <Route path="/parts" element={<PartListPage />} />
        <Route path="/parts/:partId" element={<PartDetailPage />} />
        <Route path="/parts/:partId/instances/new" element={<PartInstanceCreatePage />} />
        <Route path="/part-instances/:instanceId" element={<PartInstanceDetailPage />} />
        <Route path="/drivers" element={<DriverListPage />} />
        <Route path="/drivers/:driverId" element={<DriverDetailPage />} />
        {/* R2 Batch R2f-h4 B5 — navigation cutover: the B4 parallel /v2 paths are
            retired; an old bookmark only REDIRECTS (a plain navigation that never
            creates or changes anything) to the one canonical page. */}
        <Route path="/v2" element={<Navigate to="/" replace />} />
        <Route path="/v2/vehicle/:vehicleId/repairs/new" element={<LegacyV2Redirect to="/vehicle/:vehicleId/repairs/new" />} />
        <Route path="/v2/equipment/:equipmentId/repairs/new" element={<LegacyV2Redirect to="/equipment/:equipmentId/repairs/new" />} />
        <Route path="/v2/vehicle/:vehicleId/pm" element={<LegacyV2Redirect to="/vehicle/:vehicleId/pm" />} />
        <Route path="/v2/equipment/:equipmentId/pm" element={<LegacyV2Redirect to="/equipment/:equipmentId/pm" />} />
        <Route path="/v2/repairs/:repairId" element={<LegacyV2Redirect to="/repairs/:repairId" />} />
        <Route path="/v2/pm/work-orders/:workOrderId" element={<LegacyV2Redirect to="/pm/work-orders/:workOrderId" />} />
        <Route path="/v2/my-work" element={<Navigate to="/my-work" replace />} />
        <Route path="/v2/waiting-assignment" element={<Navigate to="/waiting-assignment" replace />} />
        <Route path="/v2/*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  )
}

export default App
