"""Shared enumerations used across all component contracts."""

from enum import Enum


class ClaimCategory(str, Enum):
    """OPD claim categories, matching `document_requirements` keys in policy terms."""

    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class DocumentType(str, Enum):
    """Medical document types the pipeline can classify and extract."""

    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    PHARMACY_BILL = "PHARMACY_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"


class DocumentQuality(str, Enum):
    """Readability assessment of an uploaded document."""

    GOOD = "GOOD"
    POOR = "POOR"
    UNREADABLE = "UNREADABLE"


class Outcome(str, Enum):
    """Result of a single pipeline check or trace step."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    DEGRADED = "DEGRADED"


class Decision(str, Enum):
    """Final claim decision."""

    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class RejectionReason(str, Enum):
    """Machine-readable rejection reason codes.

    The first four match the codes expected by `test_cases.json`; the rest cover
    intake/eligibility failures.
    """

    WAITING_PERIOD = "WAITING_PERIOD"
    PRE_AUTH_MISSING = "PRE_AUTH_MISSING"
    PER_CLAIM_EXCEEDED = "PER_CLAIM_EXCEEDED"
    EXCLUDED_CONDITION = "EXCLUDED_CONDITION"
    MEMBER_NOT_FOUND = "MEMBER_NOT_FOUND"
    POLICY_INACTIVE = "POLICY_INACTIVE"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    BELOW_MINIMUM_AMOUNT = "BELOW_MINIMUM_AMOUNT"
    CATEGORY_NOT_COVERED = "CATEGORY_NOT_COVERED"
    RELATIONSHIP_NOT_COVERED = "RELATIONSHIP_NOT_COVERED"


class DocumentProblemKind(str, Enum):
    """Why a document failed early verification (TC001–TC003)."""

    WRONG_TYPE = "WRONG_TYPE"
    MISSING_REQUIRED = "MISSING_REQUIRED"
    UNREADABLE = "UNREADABLE"
    PATIENT_MISMATCH = "PATIENT_MISMATCH"
    UNCLASSIFIED = "UNCLASSIFIED"


class FraudSignalCode(str, Enum):
    """Named fraud signals surfaced by the fraud checker."""

    SAME_DAY_LIMIT_EXCEEDED = "SAME_DAY_LIMIT_EXCEEDED"
    MONTHLY_LIMIT_EXCEEDED = "MONTHLY_LIMIT_EXCEEDED"
    HIGH_VALUE_CLAIM = "HIGH_VALUE_CLAIM"
    DOCUMENT_ALTERATION = "DOCUMENT_ALTERATION"
