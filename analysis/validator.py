"""
Post-generation validation for LLM analysis output and email HTML.

Two entry points:
  validate_llm_result()  — brand-bleed check with optional LLM auto-correction.
  validate_email_html()  — lightweight regex check on the full email HTML.

Neither function raises; both always return a ValidationResult.
"""

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Brand-specific terms that must only appear in their make's context.
# Keys are lowercase make names. Terms are matched case-insensitively.
_BRAND_TERMS: dict[str, list[str]] = {
    "honda":  ["Honda Sensing", "e:HEV", "Honda Navigation"],
    "toyota": ["Toyota Safety Sense", "Toyota Safety Sense 2.0", "Toyota Safety Sense 3.0"],
    "kia":    ["Drive Wise"],
    "subaru": ["EyeSight", "Symmetrical AWD", "StarTex"],
}


@dataclass
class ValidationIssue:
    severity: str    # "error" | "warning"
    description: str


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    corrected_text: str | None = None  # LLM-corrected analysis if correction ran


# ── Public entry points ───────────────────────────────────────────────────────

def validate_llm_result(
    analysis_text: str,
    makes_present: list[str],
    anthropic_client=None,
) -> ValidationResult:
    """
    Check the LLM analysis for brand-bleed errors (e.g. "Honda Sensing" in a
    RAV4 paragraph). If issues are found, attempt auto-correction via a secondary
    cheap LLM call when an anthropic_client is provided.
    """
    if not analysis_text:
        return ValidationResult(passed=True)

    issues = _check_brand_bleed(analysis_text, makes_present)

    if not issues:
        log.info("LLM validation: PASS")
        return ValidationResult(passed=True)

    for issue in issues:
        log.warning("LLM validation [%s]: %s", issue.severity, issue.description)

    corrected = None
    if anthropic_client is not None:
        corrected = _attempt_correction(analysis_text, makes_present, issues, anthropic_client)

    return ValidationResult(passed=False, issues=issues, corrected_text=corrected)


def validate_email_html(
    html: str,
    makes_present: list[str],
) -> ValidationResult:
    """
    Validate the full email HTML before sending.
    Strips HTML tags and runs brand-bleed checks on the resulting plain text.
    This is a belt-and-suspenders check after LLM validation in Phase 5.5;
    no LLM call is made here.
    """
    if not html:
        return ValidationResult(passed=True)

    # Strip tags and collapse whitespace for text-level checks
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()

    issues = _check_brand_bleed(text, makes_present)

    if not issues:
        log.info("Email HTML validation: PASS")
        return ValidationResult(passed=True)

    for issue in issues:
        log.warning("Email HTML validation [%s]: %s", issue.severity, issue.description)

    return ValidationResult(passed=False, issues=issues)


def build_warning_banner(issues: list[ValidationIssue]) -> str:
    """
    Return an HTML warning banner listing validation issues for injection into
    the email body when validation does not pass.
    """
    items = "".join(
        f"<li style='margin:2px 0'>{issue.description}</li>"
        for issue in issues
    )
    return (
        "<div style='background:#fff3cd;border:1px solid #ffc107;border-radius:6px;"
        "padding:10px 16px;margin-bottom:18px;font-size:12px'>"
        "<b style='color:#856404'>&#9888; Validation warnings — review before acting on this report:</b>"
        f"<ul style='margin:6px 0 0;padding-left:20px;color:#856404'>{items}</ul>"
        "</div>\n"
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_brand_bleed(text: str, makes_present: list[str]) -> list[ValidationIssue]:
    """
    Return a list of brand-bleed issues in `text`.

    Check 1 — absent-make terms: any term belonging to a make NOT in this
    search should never appear anywhere in the text.

    Check 2 — cross-brand bleed between present makes: for each paragraph that
    explicitly names exactly one make, flag any term belonging to a different
    (but present) make appearing in that same paragraph.
    """
    issues: list[ValidationIssue] = []
    makes_lower = {m.lower() for m in makes_present}

    # Check 1: terms for makes not in this search
    for brand, terms in _BRAND_TERMS.items():
        if brand not in makes_lower:
            for term in terms:
                if re.search(re.escape(term), text, re.IGNORECASE):
                    issues.append(ValidationIssue(
                        severity="error",
                        description=(
                            f'"{term}" is a {brand.title()}-specific term but '
                            f"{brand.title()} is not in this search"
                        ),
                    ))

    # Check 2: cross-brand bleed between present makes
    if len(makes_lower) > 1:
        paragraphs = re.split(r"\n{2,}", text)
        seen: set[str] = set()  # deduplicate identical issues across paragraphs
        for para in paragraphs:
            para_lower = para.lower()
            mentioned = [m for m in makes_lower if m in para_lower]
            if len(mentioned) != 1:
                # Zero or multiple makes mentioned — comparison paragraph, skip
                continue
            primary = mentioned[0]
            for brand, terms in _BRAND_TERMS.items():
                if brand == primary or brand not in makes_lower:
                    continue
                for term in terms:
                    if re.search(re.escape(term), para, re.IGNORECASE):
                        key = f"{term}|{primary}"
                        if key not in seen:
                            seen.add(key)
                            issues.append(ValidationIssue(
                                severity="error",
                                description=(
                                    f'"{term}" ({brand.title()}) appears in a '
                                    f"{primary.title()} paragraph"
                                ),
                            ))

    return issues


def _attempt_correction(
    analysis_text: str,
    makes_present: list[str],
    issues: list[ValidationIssue],
    anthropic_client,
) -> str | None:
    """
    Ask the LLM to fix identified brand-bleed issues in the analysis text.
    Returns corrected text on success, None on failure.
    """
    issues_text = "\n".join(f"- {i.description}" for i in issues)
    vehicles_text = ", ".join(m.title() for m in makes_present)

    brand_guide_lines = []
    for brand, terms in _BRAND_TERMS.items():
        if brand.lower() in {m.lower() for m in makes_present}:
            brand_guide_lines.append(
                f"- {brand.title()}: driver-assist system is called '{terms[0]}'"
            )
    brand_guide = "\n".join(brand_guide_lines)

    correction_prompt = (
        "[SYSTEM CONTEXT]\n"
        "You are a copy-editor correcting brand-specific terminology errors in an "
        "automotive analysis. Fix only the identified errors — do not change prices, "
        "mileage figures, scores, rankings, or any other content.\n\n"
        "[CORRECTION TASK]\n"
        f"This analysis covers: {vehicles_text}.\n\n"
        f"Errors to fix:\n{issues_text}\n\n"
        f"Correct terminology by brand:\n{brand_guide}\n\n"
        "Return only the corrected analysis text with no preamble or commentary.\n\n"
        f"[ANALYSIS TO CORRECT]\n{analysis_text}"
    )

    try:
        corrected_text, _ = anthropic_client.analyze(correction_prompt)
        log.info(
            "LLM validation: auto-correction succeeded (%d → %d chars)",
            len(analysis_text), len(corrected_text),
        )
        return corrected_text
    except Exception as exc:
        log.warning("LLM validation: auto-correction failed: %s", exc)
        return None
