CLAUDE CODE - WEB / BACKEND API PHASED IMPLEMENTATION
Crane Fleet Maintenance, IoT Monitoring, Inspection, Repair, Parts, and Equipment Management
Revision 02 - Complete Local-Development Edition

PURPOSE
=======

This package is designed so development can begin immediately even when the user does NOT yet own or operate a production server.

Development starts locally on the user's computer.

Local development architecture:

Browser
  -> Local Frontend Development Server
  -> Local Backend API
  -> Repository Layer
  -> Mock Repository OR Google Sheets Repository

Later production architecture:

Browser
  -> Production Web/Backend
  -> Repository Layer
  -> PostgreSQL

The frontend and business/domain layer must not be rewritten when Google Sheets is replaced by PostgreSQL.

FILES
=====

00_README_EXECUTION_ORDER_EN.txt
00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt
00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt
01_PHASE1_FOUNDATION_LOCAL_STACK_EN.txt
02_PHASE2_VEHICLE_MODEL_EQUIPMENT_QR_EN.txt
03_PHASE3_INSPECTION_CHECKLIST_HISTORY_EN.txt
04_PHASE4_PM_REPAIR_WORKFLOW_EN.txt
05_PHASE5_PARTS_LIFETIME_TRANSFER_EN.txt
06_PHASE6_DRIVER_CERT_DOCS_HISTORY_GPS_ALERTS_EN.txt
07_PHASE7_DASHBOARD_SEARCH_REPORTING_EN.txt
08_PHASE8_IOT_DEVICE_TELEMETRY_CONFIG_COMMANDS_EN.txt
09_PHASE9_OTA_SAFETY_EMERGENCY_READINESS_EN.txt
10_PHASE10_RBAC_AUDIT_POSTGRES_PRODUCTION_READINESS_EN.txt

HOW TO USE
==========

1. Put all files in the project repository under a documentation folder such as:
   docs/claude-prompts/

2. Give Claude Code:
   - 00_SYSTEM_REQUIREMENTS_BASELINE_EN.txt
   - 00_LOCAL_DEVELOPMENT_AND_NO_SERVER_SETUP_EN.txt
   - the CURRENT phase file only.

3. Start with:
   01_PHASE1_FOUNDATION_LOCAL_STACK_EN.txt

4. Claude Code must implement only that phase.

5. At the end of the phase, Claude Code must output the Phase Result Report.

6. Return the complete result to ChatGPT for review.

7. Do not start the next phase until the previous phase has been reviewed and accepted.

PHASE ORDER
===========

Phase 1
Foundation, local-development stack, API contracts, repository abstraction, Thai UI shell.

Phase 2
Vehicle, model, workshop equipment, shared asset references, one-QR-per-machine detail pages.

Phase 3
Inspection, checklist revisions, history, findings.

Phase 4
PM and Repair workflows.

Phase 5
Parts, Part Sets, lifetime, transferable components, incremental part tracking.

Phase 6
Drivers/operators, certificates, documents, work history, GPS, alerts.

Phase 7
Dashboard, search, fleet overview, reporting views.

Phase 8
IoT device management, telemetry, online configuration, normal remote commands.

Phase 9
OTA and safety-critical command framework / emergency-output readiness.

Phase 10
RBAC, audit, security, PostgreSQL migration contract test, deployment readiness.

PHASE FREEZE RULE
=================

After a phase is accepted, its public API contract, shared types, repository interface, route meaning, and workflow behavior are considered FROZEN.

If a later phase requires changing an accepted interface:

1. STOP.
2. Explain exactly why.
3. Propose a backward-compatible extension or a versioned replacement.
4. Do not silently refactor the earlier phase.
5. Wait for approval.

SPECIAL EMERGENCY-OUTPUT RULE
=============================

The Web/backend may store approved profile metadata and command state.

The actual model-specific ON/OFF timing belongs to the ESP32 firmware engineering data.

The Web must not provide ordinary users with free editing of individual signal timings.

The actual fixed timings will be supplied later by the user from authoritative existing source code.

DO NOT GUESS THEM.
