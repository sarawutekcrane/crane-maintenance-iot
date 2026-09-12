CLAUDE CODE - WEB DESIGN / API DESIGN PHASED IMPLEMENTATION GUIDE
Crane Fleet Maintenance, IoT, Inspection, Repair, Parts, and Equipment Management
Revision 01

PURPOSE
=======

These prompt files split the Web Application and Backend/API implementation into independent phases.

The system must first run against Google Sheets as the prototype data source, while being designed so PostgreSQL can replace Google Sheets later without redesigning the Web application or business logic.

IMPORTANT EXECUTION RULE
========================

Send ONLY ONE phase file to Claude Code at a time.

After each phase:
1. Claude Code must build and test only that phase.
2. Claude Code must produce the required Phase Result Report.
3. Return the complete result to ChatGPT for review.
4. Start the next phase only after approval.

IMPLEMENTATION ORDER
====================

01 - Foundation, Architecture, API Contracts, Repository Layer, Thai UI Shell
02 - Vehicle / Model / Equipment / Asset / QR Detail
03 - Inspection / Checklist / History / Findings
04 - PM / Maintenance / Repair Workflow
05 - Parts / Part Sets / Lifetime / Component Transfer Tracking
06 - Driver / Certificates / Documents / Work History / GPS / Alerts
07 - Dashboard / Search / Fleet Overview / Reporting Views
08 - IoT Device Management / Telemetry / Online Config / Normal Remote Commands
09 - OTA / Safety-Critical Command Framework / Emergency Output Readiness
10 - RBAC / Audit / Security / Integration Testing / PostgreSQL Migration Readiness

CORE ARCHITECTURE
=================

Prototype:

Thai Web Application
    ->
Backend API
    ->
Domain / Service Layer
    ->
Repository Interface
    ->
Google Sheets Repository

Production:

Thai Web Application
    ->
Backend API
    ->
Domain / Service Layer
    ->
Repository Interface
    ->
PostgreSQL Repository

The Web application must NEVER access Google Sheets directly.
The ESP32 device must NEVER access Google Sheets directly.
All user-facing Web pages must be in Thai.
Backend/API/database field names and stable technical codes should remain in English.

QR RULE
=======

One crane = one permanent QR code.

The QR opens the main Vehicle Detail page.

Workshop equipment may also use one permanent QR per machine and open Equipment Detail.

PHASE FREEZE RULE
=================

Once a phase is accepted, its public API contracts, route meanings, service boundaries, shared types, and UI navigation behavior become FROZEN.

If a later phase finds a frozen interface insufficient:

1. STOP.
2. Explain the exact limitation.
3. Propose a backward-compatible extension or versioned contract.
4. Do not silently rewrite the previous phase.
5. Wait for user approval.
