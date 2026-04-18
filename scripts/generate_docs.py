import os
import time
from pathlib import Path
from dotenv import load_dotenv
from mistralai import Mistral

load_dotenv()

API_KEY = os.getenv("MISTRAL_API_KEY")
if not API_KEY:
    raise ValueError("MISTRAL_API_KEY not found in .env")

client = Mistral(api_key=API_KEY)
MODEL = "mistral-small-latest"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "raw_docs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = (
    "You are a legal document writer specializing in insurance policy language. "
    "Write in the exact style of ISO HO-3 homeowners policy forms. "
    "Use formal legal language. Use numbered and lettered subsections. "
    "Reference section numbers explicitly. "
    "Never use bullet points — use the lettered/numbered legal format only."
)

DOCUMENTS = [
    # Base policies
    (
        "base_policy_homeowners.txt",
        """Write a homeowners insurance base policy for Nexus Insurance Co. (Policy Form NX-HO-3). Include these sections exactly:

AGREEMENT
DEFINITIONS (define: insured, residence premises, occurrence, vacancy)
SECTION I - PROPERTY COVERAGES (Coverage A Dwelling, Coverage B Other Structures, Coverage C Personal Property)
SECTION I - PERILS INSURED AGAINST
SECTION I - EXCLUSIONS. In Section 7 titled VACANCY EXCLUSION write: We do not insure for loss on the residence premises if the dwelling has been vacant for more than 60 consecutive days immediately before the loss. This exclusion applies to: (a) vandalism and malicious mischief, (b) glass breakage, (c) water damage from frozen pipes. A dwelling under construction is not considered vacant. This is Section 7.3.
SECTION I - CONDITIONS
SECTION II - LIABILITY COVERAGES
Length: 800-1000 words.""",
    ),
    (
        "base_policy_commercial.txt",
        """Write a commercial property insurance base policy for Nexus Insurance Co. (Policy Form NX-CP-1). Include: AGREEMENT, DEFINITIONS, SECTION I BUILDING AND PERSONAL PROPERTY COVERAGE, SECTION II BUSINESS INTERRUPTION COVERAGE, SECTION III EXCLUSIONS (include vacancy exclusion in Section 4.2: coverage suspended if premises vacant more than 60 consecutive days), SECTION IV CONDITIONS. Length: 700-900 words.""",
    ),
    (
        "base_policy_renters.txt",
        """Write a renters insurance base policy for Nexus Insurance Co. (Policy Form NX-HO-4). Include: AGREEMENT, DEFINITIONS, SECTION I PERSONAL PROPERTY COVERAGE, SECTION II LIABILITY, SECTION III EXCLUSIONS, SECTION IV CONDITIONS. Length: 600-800 words.""",
    ),
    # Endorsements
    (
        "endorsement_01_flood_coverage.txt",
        """Write a flood coverage endorsement for Nexus Insurance Co. (Endorsement Form NX-END-01). This endorsement attaches to Policy Form NX-HO-3. Begin with: THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY. State that it adds flood coverage and overrides the water damage exclusion in Section I - Exclusions paragraph A.3. Include specific coverage limits, a $2,500 deductible for flood events, and conditions. Length: 300-400 words.""",
    ),
    (
        "endorsement_02_vacancy_permit.txt",
        """Write a vacancy permit endorsement for Nexus Insurance Co. (Endorsement Form NX-END-02). This endorsement attaches to Policy Form NX-HO-3. Begin with: THIS ENDORSEMENT CHANGES THE POLICY. PLEASE READ IT CAREFULLY. State explicitly: In consideration of the additional premium charged, Section 7.3 VACANCY EXCLUSION of the base policy is hereby modified as follows: The 60-day vacancy period referenced in Section 7.3 is extended to 120 consecutive days. All other terms of Section 7.3 remain unchanged. Coverage is subject to the insured notifying the Company within 10 days of the property becoming vacant. Length: 300-400 words.""",
    ),
    (
        "endorsement_03_water_backup.txt",
        """Write a water backup and sump overflow endorsement for Nexus Insurance Co. (Endorsement Form NX-END-03). Attaches to NX-HO-3. Adds coverage for water backup through sewers or drains and sump pump overflow. $10,000 sublimit. References and partially overrides Section I Exclusion A.3.b of the base policy. Length: 300-400 words.""",
    ),
    (
        "endorsement_04_scheduled_property.txt",
        """Write a scheduled personal property endorsement for Nexus Insurance Co. (Endorsement Form NX-END-04). Lists specific high-value items with individual coverage limits. Overrides the special limits of liability in Coverage C of the base policy for scheduled items only. Include a schedule table format using plain text. Length: 300-400 words.""",
    ),
    (
        "endorsement_05_home_business.txt",
        """Write a home business liability endorsement for Nexus Insurance Co. (Endorsement Form NX-END-05). Extends Coverage E Personal Liability to include home-based business activities. Overrides the business exclusion in Section II Exclusions paragraph E.2 of the base policy. $300,000 liability limit for business activities. Length: 300-400 words.""",
    ),
    (
        "endorsement_06_earthquake.txt",
        """Write an earthquake coverage endorsement for Nexus Insurance Co. (Endorsement Form NX-END-06). Adds earthquake coverage. 10% of Coverage A dwelling limit as deductible. Overrides Section I Exclusion A.2 Earth Movement. Includes coverage for: (a) sudden earth movement, (b) volcanic eruption, (c) land shock waves. Length: 300-400 words.""",
    ),
    # State amendments
    (
        "amendment_CA.txt",
        """Write a California Amendatory Endorsement for Nexus Insurance Co. (Form NX-CA-AMD). Opens with: THIS ENDORSEMENT MODIFIES INSURANCE PROVIDED UNDER POLICY FORM NX-HO-3 AND IS REQUIRED BY THE STATE OF CALIFORNIA. Includes: (a) Cancellation notice extended from 10 to 20 days, (b) Wildfire provisions — coverage for wildfire smoke damage added, (c) Fair Claims Settlement Practices requirements, (d) Mold disclosure requirements. Reference specific California Insurance Code sections. Length: 400-500 words.""",
    ),
    (
        "amendment_TX.txt",
        """Write a Texas Amendatory Endorsement for Nexus Insurance Co. (Form NX-TX-AMD). Required by Texas Department of Insurance. Includes: (a) Wind and hail deductible rules — separate 2% of Coverage A limit deductible applies to wind/hail losses, (b) Flood disclaimer stating flood is excluded and separate NFIP coverage is available, (c) Texas Homeowners Bill of Rights disclosure. Reference Texas Insurance Code. Length: 400-500 words.""",
    ),
    (
        "amendment_NY.txt",
        """Write a New York Amendatory Endorsement for Nexus Insurance Co. (Form NX-NY-AMD). Required by New York Department of Financial Services. Includes: (a) Mold coverage disclosure — insurer must provide written notice of mold exclusions, (b) Tenant protections for renters policies, (c) Extended cancellation notice of 30 days, (d) Anti-arson application requirement. Reference New York Insurance Law. Length: 400-500 words.""",
    ),
    (
        "amendment_FL.txt",
        """Write a Florida Amendatory Endorsement for Nexus Insurance Co. (Form NX-FL-AMD). Required by Florida Office of Insurance Regulation. Includes: (a) Hurricane deductible — separate deductible of 2% of Coverage A applies during named storms, (b) Sinkhole coverage disclosure — basic sinkhole coverage included, catastrophic ground cover collapse separately defined, (c) Citizens Property Insurance Corporation disclosure, (d) 90-day claims reporting requirement for hurricane losses. Reference Florida Statutes. Length: 400-500 words.""",
    ),
    # Declarations pages
    (
        "declarations_john_smith.txt",
        """Write a homeowners insurance declarations page for Nexus Insurance Co. Format it like a formal insurance declarations page with clear fields. Details: Named Insured: John Smith, Address: 142 Maple Street, Sacramento, CA 95814, Policy Number: NX-HO-2024-001, Policy Period: 01/01/2024 to 01/01/2025, Coverage A Dwelling: $500,000, Coverage B Other Structures: $50,000, Coverage C Personal Property: $150,000, Coverage D Loss of Use: $100,000, Coverage E Liability: $300,000, Coverage F Medical Payments: $5,000, Annual Premium: $2,340, Deductible: $1,000, Endorsements Attached: NX-END-01 Flood Coverage, NX-END-03 Water Backup, State Amendment: NX-CA-AMD. Note: California amendatory endorsement applies. Length: 300-400 words.""",
    ),
    (
        "declarations_acme_corp.txt",
        """Write a commercial property insurance declarations page for Nexus Insurance Co. Details: Named Insured: Acme Corporation, Address: 500 Industrial Parkway, Houston, TX 77001, Policy Number: NX-CP-2024-002, Policy Period: 03/01/2024 to 03/01/2025, Building Coverage: $2,000,000, Business Personal Property: $500,000, Business Interruption: $750,000, General Liability: $1,000,000, Annual Premium: $18,500, Deductible: $5,000, Endorsements Attached: NX-END-05 Home Business Liability, State Amendment: NX-TX-AMD. Note: Texas wind/hail deductible applies. Length: 300-400 words.""",
    ),
    (
        "declarations_jane_doe.txt",
        """Write a renters insurance declarations page for Nexus Insurance Co. Details: Named Insured: Jane Doe, Address: Apt 4B, 88 West 23rd Street, New York, NY 10010, Policy Number: NX-HO4-2024-003, Policy Period: 06/01/2024 to 06/01/2025, Coverage C Personal Property: $50,000, Coverage D Loss of Use: $15,000, Coverage E Liability: $100,000, Coverage F Medical Payments: $1,000, Annual Premium: $420, Deductible: $500, Endorsements Attached: NX-END-04 Scheduled Personal Property (diamond ring $8,000, laptop $3,000), State Amendment: NX-NY-AMD. Length: 300-400 words.""",
    ),
    (
        "declarations_vacant_property.txt",
        """Write a homeowners insurance declarations page for Nexus Insurance Co. for a vacant property. Details: Named Insured: Robert Chen, Address: 78 Birchwood Lane, Miami, FL 33101, Policy Number: NX-HO-2024-004, Policy Period: 09/01/2024 to 09/01/2025, Coverage A Dwelling: $300,000, Coverage B Other Structures: $30,000, Coverage C Personal Property: $0 (dwelling vacant, no personal property), Coverage D Loss of Use: $0, Coverage E Liability: $100,000, Annual Premium: $1,890, Deductible: $2,000, Endorsements Attached: NONE — note that NX-END-02 Vacancy Permit Endorsement is NOT attached to this policy, State Amendment: NX-FL-AMD. IMPORTANT: Add a notice section that reads: VACANCY NOTICE: Insured has notified the company that the dwelling is currently unoccupied. Section 7.3 Vacancy Exclusion of Policy Form NX-HO-3 applies in full. Coverage for vandalism, glass breakage, and frozen pipe damage is suspended. Length: 300-400 words.""",
    ),
]


def generate_document(filename: str, user_prompt: str) -> None:
    output_path = OUTPUT_DIR / filename
    try:
        response = client.chat.complete(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        output_path.write_text(content, encoding="utf-8")
        print(f"[OK] {filename}")
    except Exception as e:
        print(f"[ERROR] {filename}: {e}")


def main():
    total = len(DOCUMENTS)
    print(f"Generating {total} documents into {OUTPUT_DIR}\n")
    for i, (filename, prompt) in enumerate(DOCUMENTS, start=1):
        print(f"[{i}/{total}] Generating {filename} ...")
        generate_document(filename, prompt)
        if i < total:
            time.sleep(2)
    print(f"\nDone. Files saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
