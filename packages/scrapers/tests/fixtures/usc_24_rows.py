"""axiom-corpus rows for 26 USC 24, as served on 2026-09-19.

These are the bodies of three `current_provisions` rows, copied verbatim
so the applier is tested against the text corpus actually hands back. Note what the rows do NOT contain: a subsection or paragraph
row usually does not print its own marker: the (d)(1) row opens at "(A)" and
the (h) row opens at "(1)".
"""

# us/statute/26/24/d/1 — the nearest ancestor of 26 USC 24(d)(1)(B)(i).
# Corpus has no row below the paragraph.
ROW_24_D_1 = (
    "The aggregate credits allowed to a taxpayer under subpart C shall be "
    "increased by the lesser of—\n\n"
    "(A) the credit which would be allowed under this section without "
    "regard to this subsection and the limitation under section 26(a) or"
    "\n\n"
    "(B) the amount by which the aggregate amount of credits allowed by "
    "this subpart (determined without regard to this subsection) would "
    "increase if the limitation imposed by section 26(a) were increased "
    "by the greater of— (i) 15 percent of so much of the taxpayer’s "
    "earned income (within the meaning of section 32) which is taken into "
    "account in computing taxable income for the taxable year as exceeds "
    "$3,000, or (ii) in the case of a taxpayer with 3 or more qualifying "
    "children, the excess (if any) of— (I) the taxpayer’s social security "
    "taxes for the taxable year, over (II) the credit allowed under "
    "section 32 for the taxable year.\n\n"
    "The amount of the credit allowed under this subsection shall not be "
    "treated as a credit allowed under this subpart and shall reduce the "
    "amount of credit otherwise allowable under subsection (a) without "
    "regard to section 26(a). For purposes of subparagraph (B), any "
    "amount excluded from gross income by reason of section 112 shall be "
    "treated as earned income which is taken into account in computing "
    "taxable income for the taxable year."
)

# us/statute/26/24/h
ROW_24_H = (
    "(1) In general In the case of a taxable year beginning after "
    "December 31, 2017 , this section shall be applied as provided in "
    "paragraphs (2) through (7).\n\n"
    "(2) Credit amount Subsection (a) shall be applied by substituting "
    "“$2,200” for “$1,000”.\n\n"
    "(3) Limitation In lieu of the amount determined under subsection "
    "(b)(2), the threshold amount shall be $400,000 in the case of a "
    "joint return ($200,000 in any other case).\n\n"
    "(4) Partial credit allowed for certain other dependents (A) In "
    "general The credit determined under subsection (a) (after the "
    "application of paragraph (2)) shall be increased by $500 for each "
    "dependent of the taxpayer (as defined in section 152) other than a "
    "qualifying child described in subsection (c). (B) Exception for "
    "certain noncitizens Subparagraph (A) shall not apply with respect to "
    "any individual who would not be a dependent if subparagraph (A) of "
    "section 152(b)(3) were applied without regard to all that follows "
    "“resident of the United States”. (C) Certain qualifying children In "
    "the case of any qualifying child with respect to whom a credit is "
    "not allowed under this section by reason of paragraph (7), such "
    "child shall be treated as a dependent to whom subparagraph (A) "
    "applies.\n\n"
    "(5) Maximum amount of refundable credit The amount determined under "
    "subsection (d)(1)(A) with respect to any qualifying child shall not "
    "exceed $1,400, and such subsection shall be applied without regard "
    "to paragraph (4) of this subsection.\n\n"
    "(6) Earned income threshold for refundable credit Subsection "
    "(d)(1)(B)(i) shall be applied by substituting “$2,500” for "
    "“$3,000”.\n\n"
    "(7) Social security number required (A) In general No credit shall "
    "be allowed under this section to a taxpayer with respect to any "
    "qualifying child unless the taxpayer includes on the return of tax "
    "for the taxable year— (i) the taxpayer’s social security number (or, "
    "in the case of a joint return, the social security number of at "
    "least 1 spouse), and (ii) the social security number of such "
    "qualifying child. (B) Social security number For purposes of this "
    "paragraph, the term “social security number” means a social security "
    "number issued to an individual by the Social Security "
    "Administration, but only if the social security number is issued— "
    "(i) to a citizen of the United States or pursuant to subclause (I) "
    "(or that portion of subclause (III) that relates to subclause (I)) "
    "of section 205(c)(2)(B)(i) of the Social Security Act, and (ii) "
    "before the due date for such return."
)

# us/statute/26/24/h/6
ROW_24_H_6 = (
    "Subsection (d)(1)(B)(i) shall be applied by substituting “$2,500” "
    "for “$3,000”."
)

# S. 3596 (119th), Stronger Start for Working Families Act, as introduced.
S3596_TEXT = (
    "SEC. 2. EARNED INCOME THRESHOLD FOR REFUNDABLE CHILD TAX CREDIT.\n\n"
    "    (a) In General.--Section 24(d)(1)(B)(i) of the Internal Revenue \n"
    "Code of 1986 is amended by striking ``$3,000'' and inserting ``$1''.\n"
    "    (b) Conforming Amendment.--Section 24(h) of such Code is amended "
    "by \nstriking paragraph (6).\n"
    "    (c) Effective Date.--The amendments made by this section shall \n"
    "apply to taxable years beginning after December 31, 2025.\n"
)
