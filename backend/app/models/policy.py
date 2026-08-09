"""Typed mirror of `policy_terms.json` — no policy logic lives here.

Parsing the policy file through these models is what "no hardcoded policy
logic" means in practice: rules are data, the engine interprets them.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PolicyHolder(BaseModel):
    company_name: str
    employee_count: int
    policy_start_date: date
    policy_end_date: date
    renewal_status: str


class FamilyFloater(BaseModel):
    enabled: bool
    combined_limit: Decimal
    covered_relationships: list[str]


class Coverage(BaseModel):
    sum_insured_per_employee: Decimal
    annual_opd_limit: Decimal
    per_claim_limit: Decimal
    family_floater: FamilyFloater


class CategoryTerms(BaseModel):
    """Terms for one OPD category. Optional fields exist only on some categories."""

    model_config = ConfigDict(extra="allow")

    sub_limit: Decimal
    copay_percent: Decimal = Decimal(0)
    network_discount_percent: Decimal = Decimal(0)
    requires_prescription: bool = False
    requires_pre_auth: bool = False
    pre_auth_threshold: Decimal | None = None
    high_value_tests_requiring_pre_auth: list[str] = Field(default_factory=list)
    branded_drug_copay_percent: Decimal | None = None
    generic_mandatory: bool = False
    requires_dental_report: bool = False
    requires_registered_practitioner: bool = False
    max_sessions_per_year: int | None = None
    covered: bool = True
    covered_procedures: list[str] = Field(default_factory=list)
    excluded_procedures: list[str] = Field(default_factory=list)
    covered_items: list[str] = Field(default_factory=list)
    excluded_items: list[str] = Field(default_factory=list)
    covered_systems: list[str] = Field(default_factory=list)


class WaitingPeriods(BaseModel):
    initial_waiting_period_days: int
    pre_existing_conditions_days: int
    specific_conditions: dict[str, int] = Field(
        description="Condition key (e.g. 'diabetes') -> waiting period in days."
    )


class Exclusions(BaseModel):
    conditions: list[str]
    dental_exclusions: list[str] = Field(default_factory=list)
    vision_exclusions: list[str] = Field(default_factory=list)


class PreAuthorization(BaseModel):
    required_for: list[str]
    validity_days: int


class SubmissionRules(BaseModel):
    deadline_days_from_treatment: int
    minimum_claim_amount: Decimal
    currency: str


class DocumentRequirements(BaseModel):
    required: list[str]
    optional: list[str] = Field(default_factory=list)


class FraudThresholds(BaseModel):
    same_day_claims_limit: int
    monthly_claims_limit: int
    high_value_claim_threshold: Decimal
    auto_manual_review_above: Decimal
    fraud_score_manual_review_threshold: float


class Member(BaseModel):
    """A member or dependent from the roster.

    Dependents carry `primary_member_id` and no `join_date`; waiting periods
    for dependents use the primary member's join date.
    """

    member_id: str
    name: str
    date_of_birth: date
    gender: str
    relationship: str
    join_date: date | None = None
    dependents: list[str] = Field(default_factory=list)
    primary_member_id: str | None = None


class PolicyTerms(BaseModel):
    """Root model for `policy_terms.json`."""

    policy_id: str
    policy_name: str
    insurer: str
    policy_holder: PolicyHolder
    coverage: Coverage
    opd_categories: dict[str, CategoryTerms] = Field(
        description="Keyed by lowercase category name (e.g. 'consultation')."
    )
    waiting_periods: WaitingPeriods
    exclusions: Exclusions
    pre_authorization: PreAuthorization
    network_hospitals: list[str]
    submission_rules: SubmissionRules
    document_requirements: dict[str, DocumentRequirements] = Field(
        description="Keyed by uppercase claim category (e.g. 'CONSULTATION')."
    )
    fraud_thresholds: FraudThresholds
    members: list[Member]
