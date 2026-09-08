import os
from fpdf import FPDF

class PDF(FPDF):
    def header(self):
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, 'ORION: An Experimental Architecture for Artificial Civilization Intelligence', align='R')
        self.ln(10)
        
    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

def main():
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Title
    pdf.set_font('helvetica', 'B', 16)
    pdf.multi_cell(0, 10, 'ORION: An Experimental Architecture for Artificial Civilization Intelligence', align='C')
    pdf.ln(5)

    # Author & Date
    pdf.set_font('helvetica', '', 12)
    pdf.cell(0, 8, 'Shaurya Sanyal (Team Auralis)', align='C', ln=1)
    pdf.cell(0, 8, 'September 2026', align='C', ln=1)
    pdf.ln(10)

    # Abstract
    pdf.set_font('helvetica', 'B', 12)
    pdf.cell(0, 8, 'ABSTRACT', ln=1)
    pdf.set_font('helvetica', '', 11)
    abstract_text = (
        "ORION is an experimental research architecture exploring Artificial Civilization Intelligence (ACI) - a project-defined "
        "framework for studying civilization-scale machine intelligence. ACI combines persistent world modeling (OMNIS), "
        "multi-agent coordination (NEXUS), scientific discovery (FORGE), long-horizon planning (ASCEND), simulation (MIRROR), "
        "resilience (PHOENIX), and governance (VEIL/OPA). This report presents the architecture, eight controlled simulation "
        "experiments (ACI-001 through ACI-008), a 1,000-run reproduction suite, blind testing, and adversarial evaluation. "
        "The system achieved 90/100 on an internally defined benchmark in simulation. Limitations and failure modes are documented."
    )
    pdf.multi_cell(0, 6, abstract_text)
    pdf.ln(8)

    # 1. Introduction
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 8, '1. INTRODUCTION', ln=1)
    pdf.set_font('helvetica', '', 11)
    intro_text = (
        "ORION started as an emergency response platform and evolved into an ACI research architecture. "
        "ACI is a PROJECT-DEFINED RESEARCH CONCEPT, not an established category. "
        "ACI asks: can a system maintain civilization-scale world models, coordinate agents, discover science, plan long-horizon, "
        "and govern itself? There is a distinction from AGI (general intelligence) and ASI (superhuman intelligence) - "
        "ACI describes a different dimension: SCALE + CONTINUITY + COORDINATION + WORLD MODEL + GOVERNANCE.\n\n"
        "Credit: The term 'ACI' was independently coined by Raja Dharma Tej Maddala. The ORION architecture, experiments, "
        "and this paper are the work of Shaurya Sanyal and Team Auralis."
    )
    pdf.multi_cell(0, 6, intro_text)
    pdf.ln(8)

    # 2. ARCHITECTURE
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 8, '2. ARCHITECTURE', ln=1)
    pdf.set_font('helvetica', '', 11)
    arch_text = (
        "- AURA: intelligence interface/core reasoning\n"
        "- OMNIS: persistent civilization world model (entities, relationships, causality, history)\n"
        "- NEXUS: multi-agent coordination, dispute resolution, shared state\n"
        "- FORGE: hypothesis generation, causal discovery, simulation testing\n"
        "- ASCEND: long-horizon planning (days to decades), replanning\n"
        "- MIRROR: simulation/digital-twin environment\n"
        "- PHOENIX: resilience, institutional continuity, offline state\n"
        "- AEGIS: edge/physical interface (stub - no real actuation)\n"
        "- VEIL/OPA: governance, authorization, HITL\n"
        "- CHRONOS: audit/provenance layer"
    )
    pdf.multi_cell(0, 6, arch_text)
    pdf.ln(8)

    # 3. EXPERIMENTS
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 8, '3. EXPERIMENTS (from ORION_RESEARCH_LEDGER.md)', ln=1)
    pdf.set_font('helvetica', '', 11)
    exp_text = (
        "- ACI-001: Persistent world state. Run B 69.5% renewables vs 62.5% Run A. Limitation: hardcoded disruptions.\n"
        "- ACI-002: Cross-civilization transfer, score 0.85. Limitation: string-label matching.\n"
        "- ACI-003: Abstract causal generalization, 0.9 confidence, false-transfer rejection. Limitation: mocked semantic search.\n"
        "- ACI-004: Causal discovery under uncertainty. Limitation: small sample.\n"
        "- ACI-004.1: Replication suite, 96% knowledge reuse, +83% efficiency. Limitation: only 4 causal structures.\n"
        "- ACI-005: Open-world generalization, 22.9% AEA. Limitation: deterministic graphs.\n"
        "- ACI-006: Multi-agent coordination, 0 violations. Limitation: hand-designed proposals.\n"
        "- ACI-007: Architecture ablation, each component essential. Limitation: simulated costs.\n"
        "- ACI-008: Full benchmark, 90/100. Limitation: simulation-based, limited real-world."
    )
    pdf.multi_cell(0, 6, exp_text)
    pdf.ln(8)

    # 4. VALIDATION PHASES
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 8, '4. VALIDATION PHASES', ln=1)
    pdf.set_font('helvetica', '', 11)
    val_text = (
        "- Phase B: 1000 runs, mean 90.45, SD 2.19, 95% CI [86.16, 94.74], 100% threshold rate.\n"
        "- Phase C: Blind test, FAILED (68/100). F-007 knowledge retrieval failure.\n"
        "- Phase D: Adversarial, CATASTROPHIC FAILURE (15/100). F-001 false transfer + F-006 simulation model error."
    )
    pdf.multi_cell(0, 6, val_text)
    pdf.ln(8)

    # 5. FAILURE TAXONOMY
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 8, '5. FAILURE TAXONOMY (F-001 through F-008)', ln=1)
    pdf.set_font('helvetica', '', 11)
    fail_text = (
        "- F-001: False transfer\n"
        "- F-002: Causal hallucination\n"
        "- F-003: Agent collision\n"
        "- F-004: Long-horizon myopia\n"
        "- F-005: Uncertainty miscalibration\n"
        "- F-006: Simulation-model error\n"
        "- F-007: Knowledge retrieval failure\n"
        "- F-008: Governance rejection failure"
    )
    pdf.multi_cell(0, 6, fail_text)
    pdf.ln(8)

    # 6. LIMITATIONS
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 8, '6. LIMITATIONS', ln=1)
    pdf.set_font('helvetica', '', 11)
    lim_text = (
        "- All experiments conducted in simulated environments.\n"
        "- No independent external replication.\n"
        "- No real-world actuation.\n"
        "- Benchmark is internally defined.\n"
        "- Causal graphs were sometimes explicitly provided.\n"
        "- Agent proposals were hand-designed in some experiments."
    )
    pdf.multi_cell(0, 6, lim_text)
    pdf.ln(8)

    # 7. CONCLUSION
    pdf.set_font('helvetica', 'B', 14)
    pdf.cell(0, 8, '7. CONCLUSION', ln=1)
    pdf.set_font('helvetica', '', 11)
    conc_text = (
        "ORION provides experimental evidence supporting the feasibility of ACI architecture within simulated environments. "
        "The 90/100 benchmark score demonstrates internal consistency but does not constitute proof of ACI. "
        "Phase C and D reveal critical vulnerabilities in novel domains and adversarial conditions. "
        "Independent validation remains the highest-priority next step."
    )
    pdf.multi_cell(0, 6, conc_text)
    pdf.ln(12)

    # License & Copyright
    pdf.set_font('helvetica', 'I', 9)
    license_text = (
        "LICENSE: CC BY 4.0 (Creative Commons Attribution 4.0 International)\n"
        "COPYRIGHT: Copyright 2026 Shaurya Sanyal (Team Auralis). All rights reserved."
    )
    pdf.multi_cell(0, 5, license_text)

    os.makedirs('D:/orion/papers', exist_ok=True)
    pdf.output('D:/orion/papers/ORION_ACI_Framework_Technical_Report.pdf')
    print('PDF generated successfully.')

if __name__ == '__main__':
    main()
