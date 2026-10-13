"""
jobs/scoring.py
Deterministic 100-point Job Match Scorer.

Scoring Breakdown:
1. Required skills alignment:       30 points
2. Preferred skills alignment:      10 points
3. Role similarity:                 20 points
4. Project relevance & selection:   20 points
5. Location & work style alignment: 10 points
6. Experience level alignment:      10 points
Total:                             100 points

Includes project recommendation ranking based on verified technical depth,
relevance, engineering complexity, and strict safety blacklists.
"""
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional
from agent.safety import is_blacklisted, can_auto_place_on_resume


@dataclass
class ScoreBreakdown:
    required_skills_score: float      # max 30
    preferred_skills_score: float     # max 10
    role_similarity_score: float      # max 20
    project_relevance_score: float    # max 20
    location_score: float             # max 10
    experience_score: float           # max 10
    total_score: float                # max 100

    matched_required_skills: List[str] = field(default_factory=list)
    missing_required_skills: List[str] = field(default_factory=list)
    matched_preferred_skills: List[str] = field(default_factory=list)
    missing_preferred_skills: List[str] = field(default_factory=list)
    
    selected_project_ids: List[str] = field(default_factory=list)
    project_rankings: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class JobMatchEngine:
    """
    Deterministic evaluation engine comparing structured or raw job requirements
    against candidate verified master profile and project registry.
    """

    def __init__(self, master_profile: Dict[str, Any], project_registry: Dict[str, Any]):
        self.profile = master_profile
        self.project_registry = project_registry
        
        # Flatten verified candidate skills
        self.verified_skills = set()
        self.exposure_skills = set()
        
        skills_dict = self.profile.get("skills", {})
        for category, cat_skills in skills_dict.items():
            if isinstance(cat_skills, dict):
                for skill_name, details in cat_skills.items():
                    if isinstance(details, dict):
                        status = details.get("status", "").lower()
                        if status == "verified":
                            self.verified_skills.add(skill_name.lower())
                        else:
                            self.exposure_skills.add(skill_name.lower())
                    elif isinstance(details, str):
                        if details.lower() == "verified":
                            self.verified_skills.add(skill_name.lower())

        # Candidate's target roles
        self.target_roles = [
            r.lower() for r in self.profile.get("preferences", {}).get("target_roles", [])
        ]
        
        # Available verified projects
        self.projects = []
        for p in self.project_registry.get("projects", []):
            if can_auto_place_on_resume(p.get("status", "")) and not is_blacklisted(p.get("display_name", "")) and not is_blacklisted(p.get("id", "")):
                self.projects.append(p)

    def _normalize_skill(self, skill: str) -> str:
        s = skill.strip().lower()
        # Aliases
        aliases = {
            "python3": "python",
            "py": "python",
            "golang": "go",
            "js": "javascript",
            "ts": "typescript",
            "reactjs": "react",
            "react.js": "react",
            "nodejs": "node.js",
            "node": "node.js",
            "drf": "django rest framework",
            "rest": "rest apis",
            "rest api": "rest apis",
            "restful": "rest apis",
            "aws": "aws (s3, iam)",
            "s3": "aws s3",
            "iam": "aws iam",
            "postgres": "sql",
            "postgresql": "sql",
            "mysql": "sql",
            "sqlite3": "sqlite",
            "cloudflare worker": "cloudflare workers",
            "d1": "cloudflare d1",
            "mediapipe": "google mediapipe",
            "llama": "llama 3.2",
            "llama3": "llama 3.2",
            "jwt": "jwt authentication",
            "github action": "github actions",
        }
        return aliases.get(s, s)

    @staticmethod
    def _skills_overlap(a: str, b: str) -> bool:
        if not a or not b:
            return False
        if a == b:
            return True
        # Boundaries also exclude +/#, so C cannot match C++ or C#.
        # Qualified names such as "Java 17" and "C programming" still match.
        return bool(re.search(r"(?<![\w+#])" + re.escape(a) + r"(?![\w+#])", b)
                    or re.search(r"(?<![\w+#])" + re.escape(b) + r"(?![\w+#])", a))

    def _match_skill(self, skill_name: str) -> Tuple[bool, str]:
        """Check if candidate has this skill (verified or exposure)."""
        norm = self._normalize_skill(skill_name)
        
        # Direct check in verified skills
        for vs in self.verified_skills:
            if self._skills_overlap(norm, self._normalize_skill(vs)):
                return True, "verified"
                
        # Direct check in exposure skills
        for es in self.exposure_skills:
            if self._skills_overlap(norm, self._normalize_skill(es)):
                return True, "exposure"
                
        return False, "missing"

    def score(self, job_analysis: Dict[str, Any]) -> ScoreBreakdown:
        """
        Calculates deterministic score based on job requirements.
        """
        title = (job_analysis.get("job_title") or "").strip()
        description = (job_analysis.get("job_description") or "").strip()
        req_skills_raw = job_analysis.get("required_skills") or []
        pref_skills_raw = job_analysis.get("preferred_skills") or []
        tech_raw = job_analysis.get("technologies") or []

        # If required skills list is empty, extract from text/tech
        if not req_skills_raw and not pref_skills_raw:
            # Fallback heuristic extraction
            all_known = list(self.verified_skills) + list(self.exposure_skills)
            desc_lower = description.lower()
            detected = []
            for k in all_known:
                if re.search(r'\b' + re.escape(k) + r'\b', desc_lower):
                    detected.append(k)
            req_skills_raw = detected[:8]
            pref_skills_raw = detected[8:12]

        # 1. Required Skills Score (max 30 pts)
        matched_req = []
        missing_req = []
        for s in req_skills_raw:
            has_skill, level = self._match_skill(s)
            if has_skill and level == "verified":
                matched_req.append(s)
            else:
                missing_req.append(s)

        if req_skills_raw:
            req_ratio = len(matched_req) / len(req_skills_raw)
            req_score = round(req_ratio * 30.0, 1)
        else:
            req_score = 25.0  # neutral high if none explicitly specified

        # 2. Preferred Skills Score (max 10 pts)
        matched_pref = []
        missing_pref = []
        for s in pref_skills_raw:
            has_skill, level = self._match_skill(s)
            if has_skill:
                matched_pref.append(s)
            else:
                missing_pref.append(s)

        if pref_skills_raw:
            pref_ratio = len(matched_pref) / len(pref_skills_raw)
            pref_score = round(pref_ratio * 10.0, 1)
        else:
            pref_score = 8.0  # neutral high if none specified

        # 3. Role Similarity Score (max 20 pts)
        title_lower = title.lower()
        role_score = 5.0  # baseline
        target_match_found = False
        
        for tr in self.target_roles:
            # Check overlap
            tr_words = set(tr.split())
            title_words = set(title_lower.split())
            overlap = tr_words.intersection(title_words)
            if len(overlap) >= 2:
                role_score = max(role_score, 20.0)
                target_match_found = True
                break
            elif len(overlap) == 1:
                role_score = max(role_score, 14.0)

        if not target_match_found:
            if "software" in title_lower or "developer" in title_lower or "engineer" in title_lower:
                role_score = max(role_score, 15.0)
            if "intern" in title_lower or "co-op" in title_lower or "entry" in title_lower:
                role_score = min(20.0, role_score + 5.0)

        # 4. Project Relevance & Ranking (max 20 pts)
        ranked_projects = self._rank_projects(job_analysis)
        top_projects = ranked_projects[:3]
        selected_project_ids = [p["id"] for p in top_projects]

        # Calculate project score from relevance of top 3
        if top_projects:
            avg_proj_score = sum(p["score"] for p in top_projects) / len(top_projects)
            # Normalize to 20 pts (scores are roughly 0-100)
            project_score = round(min(20.0, (avg_proj_score / 100.0) * 20.0), 1)
        else:
            project_score = 10.0

        # 5. Location & Preferences (max 10 pts)
        loc = (job_analysis.get("location") or "").lower()
        is_remote = "remote" in loc or "remote" in title_lower or "remote" in description.lower()
        is_tx = "tx" in loc or "texas" in loc or "dallas" in loc or "arlington" in loc or "austin" in loc
        
        if is_remote or is_tx:
            location_score = 10.0
        elif "united states" in loc or "us" in loc or not loc:
            location_score = 8.0
        else:
            location_score = 5.0

        # 6. Experience Level Alignment (max 10 pts)
        is_intern = bool(re.search(r"\b(intern|internship|co-op|coop|student|campus|university)\b", title_lower))
        is_entry = bool(re.search(r"\b(entry level|junior|associate|new grad)\b", title_lower))
        
        if is_intern:
            exp_score = 10.0  # Perfect match for current undergrad
        elif is_entry:
            exp_score = 8.0
        else:
            exp_score = 6.0

        # Total Calculation
        total = round(
            req_score + pref_score + role_score + project_score + location_score + exp_score, 1
        )
        total = max(0.0, min(100.0, total))

        return ScoreBreakdown(
            required_skills_score=req_score,
            preferred_skills_score=pref_score,
            role_similarity_score=role_score,
            project_relevance_score=project_score,
            location_score=location_score,
            experience_score=exp_score,
            total_score=total,
            matched_required_skills=matched_req,
            missing_required_skills=missing_req,
            matched_preferred_skills=matched_pref,
            missing_preferred_skills=missing_pref,
            selected_project_ids=selected_project_ids,
            project_rankings=ranked_projects,
        )

    def _rank_projects(self, job_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Rank projects according to non-negotiable quality criteria:
        1. Technical depth (Tier 1 > Tier 2)
        2. Relevance to target job keywords/tech
        3. Engineering complexity
        4. Recency (2026 > 2025 > 2024)
        5. Absolute Hard Blacklist check
        """
        text_context = " ".join([
            job_analysis.get("job_title", ""),
            " ".join(job_analysis.get("required_skills", [])),
            " ".join(job_analysis.get("preferred_skills", [])),
            " ".join(job_analysis.get("technologies", [])),
            job_analysis.get("job_description", "")[:2000]
        ]).lower()

        ranked = []
        for p in self.projects:
            pid = p.get("id", "")
            pname = p.get("display_name", "")
            
            # HARD SAFETY CHECK: Never allow blacklisted project
            if is_blacklisted(pid) or is_blacklisted(pname):
                continue

            tier = p.get("quality_tier", 2)
            tech = [t.lower() for t in p.get("tech_stack", [])]
            keywords = [k.lower() for k in p.get("keywords", [])]
            
            # 1. Base score from Quality Tier (Tier 1 gets massive advantage)
            base_score = 65.0 if tier == 1 else 40.0
            
            # 2. Recency bonus
            years = p.get("years", "")
            if "2026" in years:
                base_score += 10.0
            elif "2025" in years:
                base_score += 6.0
            elif "2024" in years:
                base_score += 3.0

            # 3. Keyword / Tech overlap bonus
            match_count = 0
            for t in tech:
                if t and re.search(r'(?<!\w)' + re.escape(t) + r'(?![\w+#])', text_context):
                    match_count += 1
            for k in keywords:
                if k and re.search(r'(?<!\w)' + re.escape(k) + r'(?![\w+#])', text_context):
                    match_count += 1
            
            overlap_score = min(25.0, match_count * 4.0)
            final_project_score = round(base_score + overlap_score, 1)

            ranked.append({
                "id": pid,
                "display_name": pname,
                "score": final_project_score,
                "tier": tier,
                "tech_stack": p.get("tech_stack", []),
                "matched_keywords_count": match_count
            })

        # Sort descending by score
        ranked.sort(key=lambda x: x["score"], reverse=True)
        return ranked
