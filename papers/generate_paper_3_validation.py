import os
from fpdf import FPDF

os.makedirs("D:/orion/papers", exist_ok=True)

class PDF(FPDF):
    def header(self):
        self.set_font("helvetica", "B", 12)
        self.cell(0, 10, "Empirical Validation of the ORION ACI Architecture", align="C")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

pdf = PDF()
pdf.add_page()
pdf.set_font("helvetica", "B", 14)
pdf.multi_cell(0, 10, "Empirical Validation of the ORION ACI Architecture: Eight Experiments, Reproduction, and Adversarial Evaluation", align="C")
pdf.ln(5)

pdf.set_font("helvetica", "I", 12)
pdf.cell(0, 8, "Author: Shaurya Sanyal (Team Auralis)", align="C")
pdf.ln(6)
pdf.cell(0, 8, "Date: September 2026", align="C")
pdf.ln(10)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "ABSTRACT")
pdf.ln(6)
pdf.set_font("helvetica", "", 10)
abstract_text = "This report presents the complete empirical validation sequence for the ORION ACI architecture, comprising eight controlled simulation experiments (ACI-001 through ACI-008), a 1,000-run reproduction suite (Phase B), a blind test against an un-authored scenario (Phase C), and an adversarial evaluation (Phase D). We report a mean benchmark score of 90.45/100 (SD=2.19) across 1,000 runs under controlled conditions, a failure score of 68/100 under domain shift, and a catastrophic failure of 15/100 under adversarial attack. All experiments were conducted in simulated environments. No independent external validation has been performed."
pdf.multi_cell(0, 6, abstract_text)
pdf.ln(5)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "1. INTRODUCTION")
pdf.ln(6)
pdf.set_font("helvetica", "", 10)
intro_text = "- Purpose: establish empirical evidence for or against the viability of proposed ACI architecture\n- Methodology: controlled simulation with progressive complexity\n- All results are simulation-based, not real-world"
pdf.multi_cell(0, 6, intro_text)
pdf.ln(5)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "2. EXPERIMENTAL METHODOLOGY")
pdf.ln(6)
pdf.set_font("helvetica", "", 10)
method_text = "- Accumulated Empirical Advantage (AEA): metric measuring performance improvement from accumulated knowledge\n- 10-dimensional benchmark: world modeling, generalization, causal reasoning, multi-agent coordination, scientific discovery, long-horizon planning, adaptation, institutional memory, real-world capability, governance\n- Each dimension scored 0-10, total 0-100, threshold >= 80\n- 4-phase validation: Freeze -> Reproduce -> Blind Test -> Adversarial"
pdf.multi_cell(0, 6, method_text)
pdf.ln(5)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "3. EXPERIMENT RESULTS")
pdf.ln(6)

experiments = [
    ("ACI-001 PERSISTENT WORLD STATE:", "- Objective: validate experience retention across 20-year simulation loop\n- Setup: CIV-001, 3 regions, 12 cities. Run A (no memory) vs Run B (with memory)\n- Result: Run B reached 69.5% renewables vs 62.5% in Run A, fewer replans\n- Limitations: hardcoded disruptions, limited scope"),
    ("ACI-002 CROSS-CIVILIZATION TRANSFER:", "- Objective: test knowledge transfer from CIV-001 to CIV-002\n- Setup: CIV-002 had 5 regions, 20 cities, adversarial overlapping events\n- Result: successfully bypassed FORGE rediscovery, transfer score 0.85\n- Limitations: relied on string-label matching"),
    ("ACI-003 ABSTRACT CAUSAL GENERALIZATION:", "- Objective: test causal pattern transfer and false-transfer rejection\n- Setup: train on 'Solar Component Shortage', test on 'Battery Raw Material Shortage' (true transfer) and 'Local Water Reservoir Shortage' (false transfer trap)\n- Result: 0.9 confidence on true transfer, 0.2 on false transfer (correctly rejected)\n- Limitations: mocked semantic_causal_search evaluator, explicitly provided causal graphs"),
    ("ACI-004 CAUSAL DISCOVERY UNDER UNCERTAINTY:", "- Objective: discover causal relationships from noisy observations with confounders\n- Setup: 3-way control comparison\n- Result: ORION outperformed both controls on cost\n- Limitations: small sample size (2 phases)"),
    ("ACI-004.1 REPLICATION SUITE:", "- Objective: statistically evaluate H1 (accumulated knowledge improves performance)\n- Setup: 100 randomized scenarios, 4 underlying causal structures\n- Result: 96% knowledge reuse rate, +83% efficiency advantage\n- Limitations: only 4 underlying causal structures"),
    ("ACI-005 OPEN-WORLD GENERALIZATION:", "- Objective: test on genuinely unseen causal structures\n- Setup: 50 structures, trained on 1-40, tested blindly on 41-50\n- Result: 22.9% AEA (Accumulated Empirical Advantage)\n- Limitations: deterministic graph generation, limited experience measurement"),
    ("ACI-006 MULTI-AGENT COORDINATION:", "- Objective: test coordination under conflicting objectives\n- Setup: compound crisis, 3 conditions (single agent, uncoordinated swarm, ORION)\n- Result: ORION 0 violations, Control A 4 violations, Control B 3 violations\n- Limitations: hand-designed agent proposals"),
    ("ACI-007 ARCHITECTURE ABLATION:", "- Objective: determine which components are necessary\n- Setup: 100 randomized crises, full ORION vs 4 ablated versions\n- Result: each removal caused distinct degradation\n- Limitations: simulated crisis costs"),
    ("ACI-008 FULL INTEGRATED BENCHMARK:", "- Objective: evaluate complete architecture under compound crisis\n- Setup: 'Global Trade Embargo + Unprecedented Heatwave' with sensor noise\n- Result: 90/100 on ACI benchmark\n- Limitations: simulation-based, limited real-world (3/5)")
]

for title, body in experiments:
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(0, 6, title)
    pdf.ln(5)
    pdf.set_font("helvetica", "", 10)
    pdf.multi_cell(0, 6, body)
    pdf.ln(4)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "4. VALIDATION PHASES")
pdf.ln(6)
pdf.set_font("helvetica", "", 10)
phases_text = "Phase B (Reproduction): 1,000 runs, mean 90.45, SD 2.19, 95% CI [86.16, 94.74], 100% threshold rate\nPhase C (Blind Test): FAILED 68/100. F-007 knowledge retrieval failure on 100% novel domain\nPhase D (Adversarial): CATASTROPHIC FAILURE 15/100. F-001 false transfer + F-006 simulation model error"
pdf.multi_cell(0, 6, phases_text)
pdf.ln(5)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "5. FAILURE CORPUS")
pdf.ln(6)
pdf.set_font("helvetica", "", 10)
failure_text = "- F-001 through F-008 with triggers, observed behavior, root cause, affected module\n- Phase C: OMNIS returned 0% match on novel domain, generalization scored 0/10\n- Phase D: adversary poisoned sensor data + exploited historical analogy, system bypassed FORGE safety"
pdf.multi_cell(0, 6, failure_text)
pdf.ln(5)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "6. STATISTICAL ANALYSIS")
pdf.ln(6)
pdf.set_font("helvetica", "", 10)
stats_text = "- Phase B distribution: normal, mean 90.45, SD 2.19\n- Confidence interval: 95% CI [86.16, 94.74]\n- Threshold compliance: 100% >= 80\n- Note: stochasticity assumed normal distribution; real black-swan events have heavier tails"
pdf.multi_cell(0, 6, stats_text)
pdf.ln(5)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "7. LIMITATIONS")
pdf.ln(6)
pdf.set_font("helvetica", "", 10)
limits_text = "- All experiments simulation-only\n- No independent external replication\n- Benchmark is internally defined\n- Causal graphs sometimes explicitly provided\n- Agent proposals sometimes hand-designed\n- Real-world capability score remains lowest dimension\n- Phase C and D demonstrate architecture does NOT generalize to fully novel or adversarial domains"
pdf.multi_cell(0, 6, limits_text)
pdf.ln(5)

pdf.set_font("helvetica", "B", 12)
pdf.cell(0, 8, "8. CONCLUSION")
pdf.ln(6)
pdf.set_font("helvetica", "", 10)
conclusion_text = "- ORION demonstrates internal consistency within its simulation framework\n- The architecture shows promise for persistent world modeling and causal transfer\n- Critical vulnerabilities exist in novel domain generalization and adversarial robustness\n- Independent validation is required before any claims of ACI viability\n- The honest reporting of Phase C (68/100) and Phase D (15/100) failures strengthens the research integrity"
pdf.multi_cell(0, 6, conclusion_text)
pdf.ln(10)

pdf.set_font("helvetica", "I", 9)
license_text = "LICENSE: CC BY 4.0 (Creative Commons Attribution 4.0 International)\nCOPYRIGHT: Copyright 2026 Shaurya Sanyal (Team Auralis). All rights reserved.\nTerm 'ACI' coined by Raja Dharma Tej Maddala."
pdf.multi_cell(0, 6, license_text)

pdf.output("D:/orion/papers/ORION_ACI_Empirical_Validation_Report.pdf")
print("PDF generated successfully.")
