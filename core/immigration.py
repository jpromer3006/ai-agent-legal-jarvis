"""Immigration procedure engine + the on the spot procedural survey.

Three layers Jarvis researches for every person:
  1. PROCEDURE    where the person is: before filing, USCIS, immigration
                  court (EOIR), decision, appeal.
  2. RULES        the statutes and regulations behind each stage (INA, 8 CFR).
  3. APPLICATION  the actual forms and how they are filed.

The on the spot survey is the security layer. After the spoken intake, Jarvis
asks 7 short multiple choice questions in the person's language. Its answers
(a) place the person on the procedure map and (b) are cross checked against
what Jarvis understood from the voice intake. Any mismatch is shown and
re asked before research runs, so a mistranslation or misunderstanding can't
silently drive the legal research.

Rules are cited for INFORMATION. Each carries verify=True: the StatuteAgent
confirms the current text from .gov sources at research time, because
immigration rules and fees change often.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

# ---------------------------------------------------------------- stages
STAGES: list[dict] = [
    {"key": "pre_filing", "label": "Before anything is filed",
     "desc": "No application filed and no court case yet."},
    {"key": "uscis", "label": "Application with USCIS",
     "desc": "An application is pending with USCIS (affirmative process)."},
    {"key": "court", "label": "Immigration court (EOIR)",
     "desc": "A Notice to Appear was issued; removal proceedings before an immigration judge."},
    {"key": "decision", "label": "Decision issued",
     "desc": "USCIS or a judge has decided; short windows may apply."},
    {"key": "appeal", "label": "Appeal or motion",
     "desc": "Appeal to the Board of Immigration Appeals or a motion to reopen."},
]
STAGE_INDEX = {s["key"]: i for i, s in enumerate(STAGES)}

# ---------------------------------------------------------------- rules
RULES: dict[str, dict] = {
    "asylum_one_year": {
        "title": "Asylum one year filing deadline",
        "cite": "INA § 208(a)(2)(B); 8 U.S.C. § 1158(a)(2)(B); 8 C.F.R. § 208.4(a)",
        "url": "https://www.law.cornell.edu/uscode/text/8/1158",
        "plain": "Asylum generally must be filed within one year of the last arrival in the U.S., with limited exceptions for changed or extraordinary circumstances.",
        "verify": True},
    "nta": {
        "title": "Notice to Appear starts removal proceedings",
        "cite": "INA § 239; 8 U.S.C. § 1229",
        "url": "https://www.law.cornell.edu/uscode/text/8/1229",
        "plain": "A Notice to Appear (NTA) is the charging document that starts a case in immigration court.",
        "verify": True},
    "in_absentia": {
        "title": "Missing a court hearing",
        "cite": "INA § 240(b)(5); 8 U.S.C. § 1229a(b)(5)",
        "url": "https://www.law.cornell.edu/uscode/text/8/1229a",
        "plain": "If a person misses an immigration court hearing, the judge can order removal in their absence. There are limited ways to ask to reopen, some with a 180 day window.",
        "verify": True},
    "bia_appeal": {
        "title": "Appeal to the Board of Immigration Appeals",
        "cite": "8 C.F.R. § 1003.38(b); Form EOIR-26",
        "url": "https://www.ecfr.gov/current/title-8/chapter-V/subchapter-A/part-1003/subpart-A/subject-group-ECFR4c8a9ebfda3c2f5/section-1003.38",
        "plain": "An appeal of an immigration judge's decision is generally due within 30 calendar days of the decision.",
        "verify": True},
    "change_of_address_court": {
        "title": "Tell the court about a new address",
        "cite": "8 C.F.R. § 1003.15(d)(2); Form EOIR-33",
        "url": "https://www.justice.gov/eoir/form-eoir-33-eoir-immigration-court-listing",
        "plain": "People in immigration court must report an address change to the court within 5 days.",
        "verify": True},
    "change_of_address_uscis": {
        "title": "Tell USCIS about a new address",
        "cite": "INA § 265; 8 U.S.C. § 1305; Form AR-11",
        "url": "https://www.uscis.gov/ar-11",
        "plain": "Most noncitizens must report an address change to USCIS within 10 days.",
        "verify": True},
    "asylum_ead": {
        "title": "Work permit based on a pending asylum case",
        "cite": "8 C.F.R. § 208.7; 8 C.F.R. § 274a.12(c)(8); Form I-765",
        "url": "https://www.uscis.gov/i-765",
        "plain": "A person with a pending asylum application may become eligible to request a work permit after a waiting period. Fees and timing have changed recently; confirm on uscis.gov.",
        "verify": True},
    "notario_fraud": {
        "title": "Only lawyers and accredited representatives may give immigration legal help",
        "cite": "8 C.F.R. § 1292.1; NY Gen. Bus. Law Art. 28-C (Immigrant Assistance Services)",
        "url": "https://www.justice.gov/eoir/recognition-and-accreditation-program",
        "plain": "A 'notario' or form preparer is not a lawyer in the U.S. Check that anyone helping is a licensed attorney or a DOJ accredited representative.",
        "verify": True},
}

# ---------------------------------------------------------------- forms
FORMS: dict[str, dict] = {
    "I-589": {"name": "Application for Asylum and for Withholding of Removal",
              "where": "USCIS if not in court; the immigration court if in removal proceedings",
              "url": "https://www.uscis.gov/i-589"},
    "I-765": {"name": "Application for Employment Authorization (work permit)",
              "where": "USCIS", "url": "https://www.uscis.gov/i-765"},
    "EOIR-26": {"name": "Notice of Appeal from a Decision of an Immigration Judge",
                "where": "Board of Immigration Appeals",
                "url": "https://www.justice.gov/eoir/eoir-forms"},
    "EOIR-33": {"name": "Change of Address, Immigration Court (EOIR-33/IC)",
                "where": "The immigration court handling the case; also online at the EOIR Respondent Portal",
                "url": "https://respondentaccess.eoir.justice.gov/en/forms/eoir33ic"},
    "AR-11": {"name": "Alien's Change of Address Card", "where": "USCIS (online)",
              "url": "https://www.uscis.gov/ar-11"},
    "I-130": {"name": "Petition for Alien Relative", "where": "USCIS",
              "url": "https://www.uscis.gov/i-130"},
    "I-485": {"name": "Application to Register Permanent Residence or Adjust Status",
              "where": "USCIS", "url": "https://www.uscis.gov/i-485"},
    "I-821": {"name": "Application for Temporary Protected Status", "where": "USCIS",
              "url": "https://www.uscis.gov/i-821"},
    "I-918": {"name": "Petition for U Nonimmigrant Status (crime victims)", "where": "USCIS",
              "url": "https://www.uscis.gov/i-918"},
    "I-360": {"name": "Petition for Special Immigrant (SIJS, VAWA)", "where": "USCIS",
              "url": "https://www.uscis.gov/i-360"},
    "N-400": {"name": "Application for Naturalization", "where": "USCIS",
              "url": "https://www.uscis.gov/n-400"},
}

LOOKUPS = [
    {"name": "Immigration court case status (EOIR ACIS)", "url": "https://acis.eoir.justice.gov/",
     "note": "Find the next hearing date with the A-number. Also by phone: 1-800-898-7180."},
    {"name": "USCIS case status", "url": "https://egov.uscis.gov/",
     "note": "Uses the 13 character receipt number on the USCIS notice."},
    {"name": "ActionNYC (free, safe immigration legal help)", "url": "https://www.nyc.gov/site/actionnyc/help/get-help.page",
     "note": "Call 1-800-354-0365, or 311 and say 'ActionNYC'. Any immigration status."},
    {"name": "NYS Office for New Americans hotline", "url": "https://www.ny.gov/agencies/office-new-americans",
     "note": "Multilingual hotline for immigration questions and fraud reports."},
    {"name": "DOJ list of recognized organizations and accredited representatives",
     "url": "https://www.justice.gov/eoir/recognition-accreditation-roster-reports",
     "note": "Check that the person helping you is authorized."},
]

# ---------------------------------------------------------------- status concerns
# The five pain points of immigration status, each with official .gov tools.
CONCERNS: dict[str, dict] = {
    "backlog": {
        "label": "Slow, complex process and long backlogs",
        "plain": ("Immigration cases can take months or years. Official tools show the current "
                  "processing time for each form and office, and when you may ask USCIS about a delay."),
        "keywords": ["waiting", "wait", "backlog", "delay", "slow", "years", "no answer", "pending", "taking long"],
        "links": [
            ("USCIS Check Case Processing Times", "https://egov.uscis.gov/processing-times/"),
            ("USCIS Case Status Online", "https://egov.uscis.gov/"),
            ("USCIS case inquiry outside normal processing (e-Request)", "https://egov.uscis.gov/e-request/Intro.do"),
            ("USCIS Contact Center", "https://www.uscis.gov/contactcenter"),
            ("EOIR Immigration Court Case Status (ACIS)", "https://acis.eoir.justice.gov/"),
            ("EOIR Workload and Adjudication Statistics", "https://www.justice.gov/eoir/workload-and-adjudication-statistics"),
            ("State Department Visa Bulletin (family and employment backlogs)", "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html"),
        ],
        "note": "Asylum (I-589) processing times are not shown in the USCIS online tool."},
    "work": {
        "label": "Restricted work authorization",
        "plain": ("Working legally usually needs an Employment Authorization Document (EAD). "
                  "Eligibility categories and waiting periods differ; asylum based work permits "
                  "have a waiting period after the asylum application is filed."),
        "keywords": ["work permit", "work", "job", "employment", "ead", "permiso de trabajo", "trabajar"],
        "links": [
            ("USCIS Form I-765, Application for Employment Authorization", "https://www.uscis.gov/i-765"),
            ("USCIS Employment Authorization Document", "https://www.uscis.gov/green-card/green-card-processes-and-procedures/employment-authorization-document"),
            ("8 C.F.R. § 274a.12 (who may work)", "https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-274a/subpart-B/section-274a.12"),
            ("8 C.F.R. § 208.7 (asylum based work permit)", "https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/part-208/subpart-A/section-208.7"),
        ]},
    "detention": {
        "label": "Detention risk",
        "plain": ("If a family member is detained by ICE, the official locator can find them. "
                  "Missing a court date or not updating an address raises the risk of detention "
                  "and of an order issued without the person present."),
        "keywords": ["detained", "detention", "ice", "arrested", "custody", "la migra", "jail"],
        "links": [
            ("ICE Online Detainee Locator", "https://locator.ice.gov/odls/"),
            ("EOIR Respondent Access Portal (court notices, address change)", "https://respondentaccess.eoir.justice.gov/"),
            ("EOIR List of Pro Bono Legal Service Providers", "https://www.justice.gov/eoir/list-pro-bono-legal-service-providers"),
            ("NYC Know Your Rights with ICE", "https://www.nyc.gov/knowyourrights"),
        ]},
    "deportation": {
        "label": "Fear of deportation",
        "plain": ("Removal (deportation) cases are decided in immigration court. People have the "
                  "right to a hearing, to bring a lawyer at their own expense, and to apply for "
                  "protection such as asylum. Free help exists."),
        "keywords": ["deport", "deported", "deportation", "removal", "afraid", "fear", "sent back", "miedo"],
        "links": [
            ("EOIR Immigration Court Case Status (ACIS)", "https://acis.eoir.justice.gov/"),
            ("EOIR Immigration Court Online Resource", "https://www.justice.gov/eoir/immigration-court-online-resource"),
            ("INA § 240, removal proceedings (8 U.S.C. § 1229a)", "https://www.law.cornell.edu/uscode/text/8/1229a"),
            ("ActionNYC free immigration legal help", "https://www.nyc.gov/site/actionnyc/help/get-help.page"),
            ("DOJ accredited representatives roster", "https://www.justice.gov/eoir/recognition-accreditation-roster-reports"),
        ]},
    "family": {
        "label": "Possible family separation",
        "plain": ("ICE policy covers detained parents and legal guardians of minor children, "
                  "including participation in family court and arranging care for children. "
                  "Family based petitions are filed with USCIS."),
        "keywords": ["family", "children", "child", "kids", "son", "daughter", "wife", "husband", "separated", "hijos", "familia"],
        "links": [
            ("ICE Detained Parents Directive (11064.4)", "https://www.ice.gov/detain/parental-interest"),
            ("ICE Online Detainee Locator", "https://locator.ice.gov/odls/"),
            ("USCIS Form I-130, Petition for Alien Relative", "https://www.uscis.gov/i-130"),
            ("NYS Office for New Americans", "https://www.ny.gov/agencies/office-new-americans"),
        ]},
}


def detect_concerns(text: str, worry_idx: int = -1) -> list[str]:
    """Concerns from the survey's worry question plus words used in the intake."""
    order = ["backlog", "work", "detention", "deportation", "family"]
    found = []
    if 0 <= worry_idx < len(order):
        found.append(order[worry_idx])
    t = text.lower()
    for k, c in CONCERNS.items():
        if k not in found and any(re.search(r"\b" + re.escape(kw) + r"\b", t) for kw in c["keywords"]):
            found.append(k)
    return found


# ---------------------------------------------------------------- say / believe / do
# Hackathon theme: close the gap between what people SAY in public, what they
# BELIEVE in private, and what they actually DO. Each behavior is measured three
# ways in the Flashpoint community survey (synthetic panel per language).
GAP_SURVEY: list[dict] = [
    {"topic": "court",
     "say": "I will go to every immigration court hearing.",
     "believe": "If I go to immigration court, I could be arrested there.",
     "do": "Has anyone you know missed an immigration court hearing?"},
    {"topic": "address",
     "say": "I always tell immigration when I move.",
     "believe": "Giving immigration my address makes it easier for them to find and detain me.",
     "do": "Did you or people you know move without telling the court or USCIS?"},
    {"topic": "notario",
     "say": "I only get help from real lawyers.",
     "believe": "A notario is the same as a lawyer.",
     "do": "Have you or people you know paid a notario or form preparer for immigration help?"},
    {"topic": "deadline",
     "say": "I know the deadlines in my case.",
     "believe": "There is no deadline to ask for asylum.",
     "do": "Did you or people you know file for asylum more than one year after arriving?"},
    {"topic": "work",
     "say": "I only work with a work permit.",
     "believe": "Asking for a work permit could hurt my case.",
     "do": "Do you or people you know work without a work permit?"},
]


# ---------------------------------------------------------------- survey
# English is canonical. The app renders each question and option in the
# person's language through dialect.translate() with Flashpoint calibration.
SURVEY: list[dict] = [
    {"id": "papers", "q": "Have you received any paper from the U.S. government about your immigration case?",
     "options": ["No papers yet",
                 "A letter from USCIS (receipt, appointment, or interview)",
                 "A paper that says 'Notice to Appear' or gives a court date",
                 "A decision from a judge or from USCIS",
                 "I am not sure"]},
    {"id": "filed", "q": "Have you, or someone helping you, sent any immigration application?",
     "options": ["No", "Yes, for asylum", "Yes, for a work permit",
                 "Yes, a different application", "I am not sure"]},
    {"id": "court_date", "q": "Do you have a date to go to immigration court?",
     "options": ["No", "Yes, in the next 30 days", "Yes, more than 30 days from now",
                 "I missed a court date", "I am not sure"]},
    {"id": "arrival", "q": "About how long ago did you most recently enter the United States?",
     "options": ["Less than 6 months ago", "6 to 12 months ago", "More than 1 year ago",
                 "I prefer not to say"]},
    {"id": "decision", "q": "Has a judge or USCIS made a decision in your case?",
     "options": ["No", "Yes, in the last 30 days", "Yes, more than 30 days ago", "I am not sure"]},
    {"id": "helper", "q": "Who is helping you with your case?",
     "options": ["A lawyer", "A legal aid organization",
                 "Someone who is not a lawyer (a notario or form preparer)",
                 "Nobody yet", "I am not sure"]},
    {"id": "worry", "q": "What worries you most right now?",
     "options": ["How long my case is taking", "Being able to work legally",
                 "Being detained", "Being deported", "Being separated from my family",
                 "Something else"]},
    {"id": "confirm", "q": "This is what Jarvis understood about your situation. Is it correct?",
     "options": ["Yes, that is correct", "Partly correct", "No, that is not correct"]},
]


@dataclass
class StageReport:
    stage: str
    stage_label: str
    alerts: list[dict] = field(default_factory=list)      # {level, text, rule}
    forms: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    verified: bool = False

    def as_dict(self) -> dict:
        return {"stage": self.stage, "stage_label": self.stage_label, "alerts": self.alerts,
                "forms": self.forms, "rules": self.rules, "mismatches": self.mismatches,
                "concerns": self.concerns, "verified": self.verified}


def score_survey(ans: dict[str, int], facts_text: str = "") -> StageReport:
    """Place the person on the procedure map from survey answers (option indexes)
    and cross check against what the voice intake recorded."""
    g = lambda k: ans.get(k, -1)
    papers, filed, court, arrival, decision, helper, confirm = (
        g("papers"), g("filed"), g("court_date"), g("arrival"), g("decision"), g("helper"), g("confirm"))

    # ---- stage
    if decision in (1, 2) or papers == 3:
        stage = "appeal" if decision == 2 else "decision"
    elif papers == 2 or court in (1, 2, 3):
        stage = "court"
    elif papers == 1 or filed in (1, 2, 3):
        stage = "uscis"
    else:
        stage = "pre_filing"
    rep = StageReport(stage, STAGES[STAGE_INDEX[stage]]["label"])

    # ---- alerts (information, never advice)
    if court == 3:
        rep.alerts.append({"level": "urgent", "rule": "in_absentia",
                           "text": "A missed court date can lead to an order issued without the person present. Contact a lawyer or ActionNYC today."})
    if court == 1:
        rep.alerts.append({"level": "urgent", "rule": "nta",
                           "text": "A court date is within 30 days. Confirm the date and courtroom on EOIR ACIS."})
    if decision == 1:
        rep.alerts.append({"level": "urgent", "rule": "bia_appeal",
                           "text": "A decision in the last 30 days may still be inside the 30 day appeal window."})
    if arrival == 2 and filed not in (1,):
        rep.alerts.append({"level": "warning", "rule": "asylum_one_year",
                           "text": "More than one year since arrival and no asylum filing reported. The one year rule and its exceptions are explained in the sources."})
    if arrival in (0, 1) and filed not in (1,):
        rep.alerts.append({"level": "info", "rule": "asylum_one_year",
                           "text": "If asylum may apply, the one year filing rule runs from the last arrival."})
    if helper == 2:
        rep.alerts.append({"level": "warning", "rule": "notario_fraud",
                           "text": "Notarios and form preparers are not lawyers in the U.S. Check the DOJ accredited list."})
    if stage == "court":
        rep.alerts.append({"level": "info", "rule": "change_of_address_court",
                           "text": "Address changes must be reported to the court within 5 days (EOIR-33)."})

    # ---- forms + rules for the stage
    stage_forms = {"pre_filing": ["I-589", "I-765", "AR-11"],
                   "uscis": ["I-765", "AR-11", "I-589"],
                   "court": ["I-589", "EOIR-33", "I-765"],
                   "decision": ["EOIR-26"],
                   "appeal": ["EOIR-26", "EOIR-33"]}
    rep.forms = stage_forms[stage]
    rep.rules = sorted({a["rule"] for a in rep.alerts} |
                       {"court": {"nta"}, "appeal": {"bia_appeal"}, "decision": {"bia_appeal"}}.get(stage, set()))

    # ---- security cross check against the voice intake
    t = facts_text.lower()
    said_court = any(w in t for w in ("court", "judge", "hearing", "notice to appear", "nta"))
    import re as _re
    said_asylum = bool(_re.search(r"(filed|applied|sent|submitted|pending)[ ,]+(?:\w+[ ,]+){0,4}asylum"
                                  r"|asylum[ ,]+(?:\w+[ ,]+){0,3}(application|case|pending|interview)", t))
    if said_court and court == 0 and papers != 2:
        rep.mismatches.append("The intake mentioned court or a judge, but the survey says there is no court date.")
    if not said_court and court in (1, 2, 3):
        rep.mismatches.append("The survey reports a court date that did not come up in the intake.")
    if said_asylum and filed == 0:
        rep.mismatches.append("The intake mentioned a filed or pending asylum case, but the survey says nothing has been filed yet.")
    if confirm == 2:
        rep.mismatches.append("The person said Jarvis's summary is NOT correct.")
    elif confirm == 1:
        rep.mismatches.append("The person said Jarvis's summary is only partly correct.")
    rep.concerns = detect_concerns(facts_text, g("worry"))
    if "detention" in rep.concerns or "family" in rep.concerns:
        rep.alerts.append({"level": "info", "rule": "change_of_address_court",
                           "text": "If a family member is detained, the ICE Online Detainee Locator can find them. Keep the court and USCIS updated on your address."})
    rep.verified = confirm == 0 and not rep.mismatches
    return rep


def one_year_deadline(arrival_iso: str) -> tuple[date, int]:
    """Information only: arrival date + 1 year, and days remaining."""
    a = date.fromisoformat(arrival_iso)
    try:
        d = a.replace(year=a.year + 1)
    except ValueError:  # Feb 29
        d = a + timedelta(days=365)
    return d, (d - date.today()).days


# ---------------------------------------------------------------- research
RESEARCH_TRACKS = {
    "ProcedureAgent": ("Explain the step by step PROCEDURE for a person at this stage: which "
                       "agency (USCIS, EOIR immigration court, BIA), what happens next, how "
                       "hearings and interviews work, and the official way to check case status. "
                       "Use the EOIR Policy Manual and USCIS pages."),
    "StatuteAgent": ("Identify the governing RULES: INA sections, 8 C.F.R. regulations, and any "
                     "current policy changes, including filing deadlines and fees. Cite each one. "
                     "State rules only; do not compute dates."),
    "FormsAgent": ("Identify the actual APPLICATION forms that apply (form number, official "
                   "name, current edition, where and how to file, fee or fee waiver, and the "
                   "official instructions page). Only uscis.gov and justice.gov/eoir pages."),
}
IMMIGRATION_DOMAINS = [
    "uscis.gov", "justice.gov", "dhs.gov", "ice.gov", "cbp.gov", "state.gov",
    "travel.state.gov", "ecfr.gov", "govinfo.gov", "congress.gov", "federalregister.gov",
    "uscode.house.gov", "law.cornell.edu", "nyc.gov", "ny.gov", "uscourts.gov",
]
FORMS_DOMAINS = ["uscis.gov", "justice.gov"]
