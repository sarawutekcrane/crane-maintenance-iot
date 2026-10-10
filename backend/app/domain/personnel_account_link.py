"""R2 Batch R2f-c — Personnel ↔ User Account link spec (Final Contract C1 §6).

Authority: `personnel_master.user_id` (0..1 ↔ 0..1, exact id only). The linked
`user_id` is the SUBJECT of the relationship; the actor recorded in the
history (`recorded_by`) is always the authenticated user. `user_account`
itself stays READ ONLY (the R2f-a bounded reader: `user_id` only): no account
is created, deleted, activated, re-roled or otherwise changed here — account
provisioning, passwords, MFA and the auth cutover remain R11.

Durable audit: the SEPARATE append-only `personnel_account_link_history` tab
with the frozen header below. It does NOT exist live yet: never auto-created,
a missing tab fails closed (PERSONNEL_ACCOUNT_LINK_HISTORY_SCHEMA_INVALID), not
part of the global readiness schemas. Existing user_id values with no history
are valid baseline state (NO_HISTORY); no migration.

A TEST link may target only an explicitly TEST-scoped account of the same
batch; the live user_account is untagged, so a live TEST link fails closed
(USER_ACCOUNT_SCOPE_UNPROVEN) whatever the id text looks like.
"""
from __future__ import annotations

from app.domain.personnel import PERSONNEL_PUBLIC_COLUMNS
from app.domain.personnel_link import LinkSpec, PersonnelLinkService
from app.repositories.base import PERSONNEL_LINK_ACCOUNT, Repository

PERSONNEL_ACCOUNT_LINK_HISTORY_TAB = "personnel_account_link_history"
PERSONNEL_ACCOUNT_LINK_HISTORY_COLUMNS: tuple[str, ...] = (
    "link_event_id",
    "personnel_id",
    "event_kind",
    "previous_user_id",
    "new_user_id",
    "recorded_at",
    "recorded_by",
    "request_id",
    "request_fingerprint",
    "reason_th",
    "is_test_data",
    "test_batch_id",
    "related_request_id",
)
# The bounded personnel_master columns the account-link write reads: identity
# and the phantom-row display columns, the link cell, and the test scope.
PERSONNEL_ACCOUNT_LINK_MASTER_COLUMNS: tuple[str, ...] = (
    *PERSONNEL_PUBLIC_COLUMNS, "user_id", "is_test_data", "test_batch_id",
)


async def _accounts(repository: Repository):
    return await repository.read_user_account_reference()


PERSONNEL_ACCOUNT_SPEC = LinkSpec(
    link=PERSONNEL_LINK_ACCOUNT,
    label="PERSONNEL_ACCOUNT_LINK",
    link_column="user_id",
    previous_column="previous_user_id",
    new_column="new_user_id",
    record_columns=PERSONNEL_PUBLIC_COLUMNS,
    history_tab=PERSONNEL_ACCOUNT_LINK_HISTORY_TAB,
    history_columns=PERSONNEL_ACCOUNT_LINK_HISTORY_COLUMNS,
    record_id_prefix="PAL",
    target_label="USER_ACCOUNT",
    target_tab="user_account",
    target_read_prefix="USER_ACCOUNT",
    target_id_column="user_id",
    read_targets=_accounts,
    op_link="personnel_account_link",
    op_unlink="personnel_account_unlink",
    op_relink="personnel_account_relink",
    op_reconcile="personnel_account_link_reconcile",
)


def personnel_account_link_service(
    repository: Repository, data_context: str | None, test_batch_id: str
) -> PersonnelLinkService:
    return PersonnelLinkService(PERSONNEL_ACCOUNT_SPEC, repository, data_context, test_batch_id)


__all__ = [
    "PERSONNEL_ACCOUNT_LINK_HISTORY_COLUMNS",
    "PERSONNEL_ACCOUNT_LINK_HISTORY_TAB",
    "PERSONNEL_ACCOUNT_LINK_MASTER_COLUMNS",
    "PERSONNEL_ACCOUNT_SPEC",
    "personnel_account_link_service",
]
