import sys
from pathlib import Path

VENDOR_PATH = Path(__file__).resolve().parents[1] / ".vendor" / "python"
if VENDOR_PATH.exists():
    sys.path.insert(0, str(VENDOR_PATH))

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib import colors

TITLE = "Continuum - Evidence-First Engineering Operations Control Plane"
SUBTITLE = "Deterministic Runs + Audit-Ready Proof for High-Stakes Financial Systems"

ONE_PAGER = [
    (
        "What Continuum is",
        "Continuum turns high-stakes engineering work into deterministic, replayable <b>Runs</b> "
        "that automatically generate audit-ready evidence and enforce policy gates.",
    ),
    (
        "The problem (what banks feel daily)",
        "Critical changes and incidents rely on tribal orchestration across Jira, Git, CI, Postman/Newman, logs, "
        "databases, and environment rituals. The result: slow cycle time, inconsistent verification, and manual proof.",
    ),
    (
        "The insight",
        "The missing primitive is a <b>Run</b>: the unit of execution that captures inputs -> plan -> execution -> verification -> "
        "evidence -> publishable report. Banks don't just ship code; they must <b>prove</b> it.",
    ),
    (
        "How it works (end-to-end)",
        "<b>Ingest</b> (ticket/workflow/CI/alert) -> <b>Plan</b> (deterministic step graph) -> <b>Execute</b> (plugins) -> "
        "<b>Verify</b> (structured checks) -> <b>Prove</b> (tamper-evident evidence bundle) -> <b>Publish</b> (report + Jira/CI).",
    ),
    (
        "What Continuum outputs (the receipt)",
        "Every run produces a consistent evidence bundle: scenario snapshot, per-step inputs/outputs, logs and checks, "
        "hashed manifest, summary with pass/fail and root-cause details, plus a shareable HTML report.",
    ),
    (
        "Why financial companies buy it",
        "Continuum compresses cycle time while reducing risk: standardized verification, policy gates for releases, "
        "repeatable incident playbooks, and audit readiness by default.",
    ),
    (
        "Differentiation",
        "CI/CD runs pipelines. Continuum runs <b>reality</b>: cross-repo workflows, flaky shared environments, approvals, "
        "evidence requirements, deterministic resume/retry/selective execution, and policy enforcement.",
    ),
    (
        "Wedge -> platform",
        "Start with payments-grade workflows (FedNow/RTP regressions, return-of-funds, end-to-end verification). "
        "Expand to fraud/risk, identity/KYC/AML, core banking integration, and regulated change control across the org.",
    ),
]


def build_pdf(path: str) -> None:
    doc = SimpleDocTemplate(
        path,
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="Continuum One Pager",
        author="Continuum",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "h1", parent=styles["Title"], fontSize=20, leading=24, spaceAfter=10
    )
    h2 = ParagraphStyle(
        "h2",
        parent=styles["Heading2"],
        fontSize=12.5,
        leading=15,
        spaceBefore=10,
        spaceAfter=4,
    )
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10.5, leading=14)

    story = []
    story.append(Paragraph(TITLE, h1))
    story.append(
        Paragraph(
            SUBTITLE,
            ParagraphStyle(
                "sub",
                parent=styles["BodyText"],
                fontSize=11.5,
                leading=14,
                textColor=colors.HexColor("#333333"),
            ),
        )
    )
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DDDDDD")))
    story.append(Spacer(1, 10))

    for heading, text in ONE_PAGER:
        story.append(Paragraph(heading, h2))
        story.append(Paragraph(text, body))
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DDDDDD")))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>CTA:</b> Replace manual orchestration with provable runs. One command. One receipt. Zero ambiguity.",
            body,
        )
    )

    doc.build(story)


if __name__ == "__main__":
    build_pdf("Continuum_One_Pager.pdf")
    print("Wrote Continuum_One_Pager.pdf")
