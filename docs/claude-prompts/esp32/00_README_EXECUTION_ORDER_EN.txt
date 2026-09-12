CLAUDE CODE ESP32 CRANE IoT - PHASED IMPLEMENTATION GUIDE
Revision 02

PURPOSE
=======

These prompt files are intentionally split so Claude Code implements the ESP32 system one stable layer at a time.

The user will run one phase only, return Claude Code's result to ChatGPT for review, and start the next phase only after approval.

This sequencing is designed to avoid repeatedly rewriting earlier code.

EXECUTION ORDER
===============

01 - Phase 1: Foundation, Architecture, and Frozen Contracts
02 - Phase 2: Hardware Input Acquisition and Bench Diagnostics
03 - Phase 3: Vehicle State, Counters, Events, and Persistence
04 - Phase 4: Network, Backend API, Telemetry, and Offline Queue
05 - Phase 5: Online Configuration, Device Management, and Normal Remote Commands
06 - Phase 6: GPS/GNSS, Cellular Abstraction, and Field Health
07 - Phase 7: OTA Firmware Update
08 - Phase 8: Model-Specific Emergency Output
09 - Phase 9: Integration Hardening, Long-Run Testing, and ESP32-S3 Readiness

IMPORTANT
=========

Do not send all phase prompts to Claude Code at once.

For each phase:

1. Send only that phase file.
2. Let Claude Code inspect the current repository.
3. Let it implement only the requested phase.
4. Compile and test.
5. Copy the complete Phase Result Report.
6. Return that report to ChatGPT for review.
7. Start the next phase only after approval.

PHASE 8 SPECIAL CONDITION
=========================

Phase 8 must NOT start until the user supplies the authoritative existing code / fixed ON-OFF timing behavior for the crane model being implemented.

Do not guess emergency signal timing.

WHY PHASE 1 IS CRITICAL
=======================

Phase 1 freezes the interfaces that later phases will plug into.

The intention is that:
- Phase 2 does not redesign Phase 1.
- Phase 3 uses Phase 2 input interfaces.
- Phase 4 consumes Phase 3 telemetry/events without changing counter logic.
- Phase 5 uses the communication interfaces already defined.
- Phase 6 adds transports/location through existing abstractions.
- Phase 7 adds OTA independently.
- Phase 8 adds the emergency output through a safety interface reserved from Phase 1.
- Phase 9 hardens and validates rather than redesigning.

If Claude Code says an earlier phase must be changed, it must stop and explain why before editing the frozen interface.
