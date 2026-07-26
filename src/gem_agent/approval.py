from __future__ import annotations

from dataclasses import dataclass

from .config import get_settings
from .db import Database
from .models import ApprovalStatus


@dataclass
class ApprovalResult:
    bid_number: str
    status: ApprovalStatus
    message: str


class ApprovalGate:
    """Human-in-the-loop gate. Auto-submit is hard-disabled unless explicitly enabled."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        self.settings = get_settings()

    def request_approval(self, bid_number: str, note: str = "") -> ApprovalResult:
        self.db.set_approval(bid_number, ApprovalStatus.PENDING, note or "Awaiting human approval")
        self.db.log_action("approval_requested", bid_number, note)
        return ApprovalResult(
            bid_number=bid_number,
            status=ApprovalStatus.PENDING,
            message="Marked pending. Approve with: gem-agent approve <bid_number>",
        )

    def approve(self, bid_number: str, note: str = "") -> ApprovalResult:
        row = self.db.get_by_bid_number(bid_number)
        if not row:
            raise ValueError(f"Unknown bid: {bid_number}")
        self.db.set_approval(bid_number, ApprovalStatus.APPROVED, note)
        self.db.log_action("approved", bid_number, note)
        return ApprovalResult(
            bid_number=bid_number,
            status=ApprovalStatus.APPROVED,
            message=(
                "Approved for assisted submit preparation. "
                "Run: gem-agent assist-submit <bid_number> "
                "(still will not place a live bid without credentials + confirm)."
            ),
        )

    def reject(self, bid_number: str, note: str = "") -> ApprovalResult:
        self.db.set_approval(bid_number, ApprovalStatus.REJECTED, note)
        self.db.log_action("rejected", bid_number, note)
        return ApprovalResult(bid_number=bid_number, status=ApprovalStatus.REJECTED, message="Rejected")

    def assist_submit(self, bid_number: str, *, confirm: bool = False) -> ApprovalResult:
        """Assisted submit stub.

        Deliberately does NOT automate live GeM participation here.
        Live browser automation can be added later behind this gate.
        """
        row = self.db.get_by_bid_number(bid_number)
        if not row:
            raise ValueError(f"Unknown bid: {bid_number}")

        if row.get("approval_status") != ApprovalStatus.APPROVED.value:
            return ApprovalResult(
                bid_number=bid_number,
                status=ApprovalStatus(row.get("approval_status") or "pending"),
                message="Bid is not approved. Approve first.",
            )

        policy_auto = False
        # Hard safety: never auto-submit from env alone.
        if self.settings.autonomy_mode != "approve_then_assist":
            return ApprovalResult(
                bid_number=bid_number,
                status=ApprovalStatus.APPROVED,
                message=(
                    "AUTONOMY_MODE is draft_only. "
                    "Set AUTONOMY_MODE=approve_then_assist in .env to unlock assisted submit checklist."
                ),
            )

        if not confirm:
            return ApprovalResult(
                bid_number=bid_number,
                status=ApprovalStatus.APPROVED,
                message="Pass --confirm to generate the assisted-submit checklist (no live bid placed).",
            )

        if not self.settings.gem_username or not self.settings.gem_password:
            checklist = (
                "Credentials missing in .env (GEM_USERNAME / GEM_PASSWORD). "
                "Add them locally — never paste into chat. "
                f"Then manually participate on GeM for {bid_number}: {row.get('url')}"
            )
            self.db.log_action("assist_submit_blocked_no_creds", bid_number, checklist)
            return ApprovalResult(
                bid_number=bid_number,
                status=ApprovalStatus.APPROVED,
                message=checklist,
            )

        # Intentionally no Playwright login/bid placement in v1 for safety.
        msg = (
            f"ASSIST CHECKLIST for {bid_number}:\n"
            f"1. Open {row.get('url')}\n"
            "2. Log in to GeM seller account yourself (or future browser assist)\n"
            "3. Upload proposal from outputs/proposals/\n"
            "4. Enter commercials within your margin policy\n"
            "5. Complete OTP / final submit manually\n"
            "Live auto-bid is disabled in this version by design."
        )
        self.db.log_action("assist_submit_checklist", bid_number, msg)
        self.db.set_approval(bid_number, ApprovalStatus.SUBMITTED, "Checklist issued; human completes portal submit")
        return ApprovalResult(
            bid_number=bid_number,
            status=ApprovalStatus.SUBMITTED,
            message=msg,
        )
