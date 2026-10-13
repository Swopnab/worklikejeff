"""
jobs/eligibility.py
Hard eligibility verification gates before spending time tailoring resumes.
Evaluates:
1. Degree & Academic Level (B.S. in Computer Science)
2. Graduation Window (Expected: Fall 2027 / Dec 2027)
3. Experience Level (Intern / Entry-Level vs Senior/Staff/Principal 5+ yrs)
4. Location & Remote Alignment (US / Remote / TX vs outside US on-site)
5. Security Clearance (Candidate does NOT have active US Security Clearance)
6. Excluded Companies & Excluded Keywords
"""
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class EligibilityResult:
    passed: bool
    status: str = "eligible"  # "eligible", "ineligible", "needs_review"
    reasons: List[str] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    requires_user_review: bool = False
    review_reason: Optional[str] = None

    @property
    def primary_reason(self) -> str:
        if self.status == "needs_review":
            return self.review_reason or "Review required."
        if self.passed:
            return "All basic eligibility criteria passed."
        return "; ".join(self.reasons) or "Ineligible based on job requirements."


class EligibilityChecker:
    """
    Deterministic eligibility verification for US Internships and F-1 candidate work authorization rules.
    """

    def __init__(self, profile: Dict[str, Any]):
        self.profile = profile
        self.education = (profile.get("education") or [{}])[0]
        self.degree = self.education.get("degree", "B.S. in Computer Science")
        graduation = str(self.education.get("graduation_year") or self.education.get("graduation") or "")
        year = re.search(r"\b(20\d{2})\b", graduation)
        self.grad_year = int(year.group(1)) if year else None
        self.grad_semester = str(self.education.get("graduation") or graduation)
        self.preferences = profile.get("preferences") or {}
        self.excluded_companies = [c.lower() for c in self.preferences.get("excluded_companies", [])]
        self.excluded_keywords = [k.lower() for k in self.preferences.get("excluded_keywords", [])]

    def evaluate(self, job_data: Dict[str, Any]) -> EligibilityResult:
        """
        Evaluate hard eligibility criteria against structured or raw job information.
        Order:
        1. Confirm internship (hard filter: internships only).
        2. Confirm U.S. location.
        3. Check graduation/student eligibility (Fall 2027).
        4. Check citizenship/permanent residency requirements (hard skip).
        5. Check clearance requirements (hard skip).
        6. Check explicit work-authorization / no-sponsorship language (NEEDS_REVIEW).
        """
        reasons: List[str] = []
        failed_checks: List[str] = []
        warnings: List[str] = []
        requires_user_review = False
        review_reason = None

        company = (job_data.get("company") or "").strip()
        title = (job_data.get("job_title") or "").strip()
        desc = (job_data.get("job_description") or "").strip().lower()
        title_lower = title.lower()
        location = (job_data.get("location") or "").lower()
        country = (job_data.get("country") or "").lower()
        emp_type = (job_data.get("employment_type") or "").lower()

        # 1. HARD FILTER: Internship Only
        is_intern_title = bool(re.search(
            r"\b(intern|internship|co-op|coop|student trainee|fellow|fellowship|apprentice)\b",
            title_lower
        ))
        is_intern_desc = bool(re.search(r"\b(intern|internship|co-op|coop)\b", desc[:500]))
        is_fulltime_title = bool(re.search(
            r"\b(senior|sr\.?|staff|principal|lead|director|vp|manager|architect|head of)\b",
            title_lower
        ))

        if is_fulltime_title:
            failed_checks.append("seniority_mismatch")
            reasons.append(f"Role title '{title}' indicates senior/lead/manager level, not internship.")
        elif emp_type and "intern" not in emp_type and "co-op" not in emp_type and "student" not in emp_type:
            failed_checks.append("not_an_internship")
            reasons.append(f"Employment type '{emp_type}' is not an internship.")
        elif not (is_intern_title or is_intern_desc):
            failed_checks.append("not_an_internship")
            reasons.append("Job posting does not clearly indicate an internship or student role.")

        # 2. HARD FILTER: United States Only
        non_us_countries = [
            "canada", "united kingdom", "uk", "london", "germany", "berlin", "munich",
            "india", "bangalore", "hyderabad", "nepal", "australia", "sydney", "singapore",
            "france", "paris", "netherlands", "amsterdam", "japan", "tokyo", "china"
        ]
        is_non_us_country = country and country not in ["united states", "usa", "us", "u.s.", "u.s.a.", "remote - us", "united states of america"]
        is_non_us_location = any(re.search(r"\b" + re.escape(c) + r"\b", location) for c in non_us_countries)
        is_us_location = bool(re.search(r"\b(united states|usa|us|u\.s\.|tx|texas|ca|california|ny|new york|wa|washington|remote)\b", f"{location} {country}"))

        if is_non_us_country or (is_non_us_location and not is_us_location):
            failed_checks.append("non_us_location")
            reasons.append(f"Posting is located outside the United States ({job_data.get('location') or country}).")

        # 3. Excluded Company check
        if company and any(exc in company.lower() for exc in self.excluded_companies if exc):
            failed_checks.append("excluded_company")
            reasons.append(f"Company '{company}' is on your excluded companies list.")

        # 4. Excluded Keywords check
        for kw in self.excluded_keywords:
            if kw and (kw in title_lower or re.search(r'\b' + re.escape(kw) + r'\b', desc)):
                failed_checks.append("excluded_keyword")
                reasons.append(f"Job posting matches excluded keyword '{kw}'.")
                break

        # 5. HARD IMMIGRATION SKIP: US Citizenship / Permanent Residency Required
        citizenship_required = bool(re.search(
            r"\b(must be a u\.?s\.?\s*citizen|u\.?s\.?\s*citizenship required|us citizens only|only u\.?s\.?\s*citizens|must possess u\.?s\.?\s*citizenship)\b",
            desc
        ))
        greencard_required = bool(re.search(
            r"\b(u\.?s\.?\s*permanent resident|green card holder|permanent residency required|must have green card)\b",
            desc
        ))

        if citizenship_required:
            failed_checks.append("citizenship_required")
            reasons.append("Posting explicitly requires U.S. citizenship.")
        if greencard_required:
            failed_checks.append("permanent_residency_required")
            reasons.append("Posting explicitly requires U.S. Permanent Residency / Green Card.")

        # 6. HARD IMMIGRATION SKIP: Active Security Clearance
        clearance_explicit = job_data.get("clearance_required") is True
        clearance_in_desc = bool(re.search(
            r"\b(active secret clearance|top secret clearance|ts/sci|polygraph|dod security clearance|active clearance required|must be able to obtain a security clearance requiring u\.?s\.?\s*citizenship)\b",
            desc
        ))
        if clearance_explicit or clearance_in_desc:
            failed_checks.append("security_clearance")
            reasons.append("Requires active U.S. security clearance (TS/SCI, DoD secret).")

        # 7. Degree Level Requirement Check (Ph.D. / Doctorate Only)
        phd_only = bool(re.search(r"\b(must have a ph\.?d|ph\.?d required|phd only|doctorates? required)\b", desc))
        if phd_only:
            failed_checks.append("degree_level")
            reasons.append("Requires Ph.D. / Doctorate degree; candidate is pursuing B.S. in Computer Science.")

        # 7. Graduation window against the candidate's recorded year
        grad_window_m = re.search(r"must (?:graduate|have graduation date) (?P<rule>between|by|in)\s+(?P<window>[a-zA-Z0-9\s,-]+)", desc)
        if grad_window_m:
            window_str = grad_window_m.group("window")
            years_in_window = [int(y) for y in re.findall(r"\b(20\d{2})\b", window_str)]
            if years_in_window and self.grad_year is None:
                requires_user_review = True
                review_reason = "Posting specifies a graduation window; the candidate's graduation year is missing."
            elif years_in_window and self.grad_year is not None and (
                (grad_window_m.group("rule") == "by" and max(years_in_window) < self.grad_year)
                or (grad_window_m.group("rule") == "in" and self.grad_year not in years_in_window)
                or (grad_window_m.group("rule") == "between" and not min(years_in_window) <= self.grad_year <= max(years_in_window))
            ):
                failed_checks.append("graduation_window")
                reasons.append(f"Graduation requirement specifies ({window_str}) which excludes {self.grad_semester}.")

        # 8. NO-SPONSORSHIP / UNRESTRICTED WORK AUTH LANGUAGE -> Flag for NEEDS_REVIEW
        if not failed_checks:
            no_sponsorship_match = re.search(
                r"\b(no sponsorship available|we do not sponsor visas|unable to provide visa sponsorship|candidates requiring sponsorship will not be considered|not sponsoring employment visas)\b",
                desc
            )
            unrestricted_match = re.search(
                r"\b(must have unrestricted u\.?s\.?\s*work authorization|must be authorized to work without restriction|unrestricted employment authorization)\b",
                desc
            )

            if no_sponsorship_match:
                requires_user_review = True
                review_reason = (
                    f"Posting contains no-sponsorship statement: '{no_sponsorship_match.group(0)}'. "
                    "Candidate plans to use CPT for internships and has approved 'No' for sponsorship. User review required."
                )
            elif unrestricted_match:
                requires_user_review = True
                review_reason = (
                    f"Posting contains unrestricted authorization statement: '{unrestricted_match.group(0)}'. "
                    "User review required before proceeding."
                )

        # Status determination
        passed = len(failed_checks) == 0
        if not passed:
            status = "ineligible"
        elif requires_user_review:
            status = "needs_review"
        else:
            status = "eligible"

        return EligibilityResult(
            passed=passed,
            status=status,
            reasons=reasons,
            failed_checks=failed_checks,
            warnings=warnings,
            requires_user_review=requires_user_review,
            review_reason=review_reason,
        )
