import os
from fpdf import FPDF

def create_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    
    # Title
    pdf.set_font("Helvetica", style="B", size=16)
    pdf.multi_cell(0, 10, "Civilizational Intent Conservation: A Proposed Framework for Preserving Collective Intent in Civilization-Scale AI Systems", align="C")
    pdf.ln(5)
    
    # Author and Date
    pdf.set_font("Helvetica", style="I", size=12)
    pdf.cell(0, 8, "Shaurya Sanyal (Team Auralis)", align="C")
    pdf.ln()
    pdf.cell(0, 8, "September 2026", align="C")
    pdf.ln(10)
    
    # Abstract
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "Abstract")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "As AI systems scale toward civilization-level coordination, a critical question emerges: can such systems maintain fidelity to their originally articulated objectives, or will optimization pressure cause unintentional drift? This paper proposes Civilizational Intent Conservation (CIC) - a framework for detecting, auditing, and governing changes to collective societal intent within AI-mediated systems. CIC distinguishes between unintentional intent drift and legitimate, explicitly authorized intent evolution. We define the architecture, threat model, proposed benchmark (CIC-001), and formal metrics. No experimental results are reported; this paper establishes the theoretical foundation.")
    pdf.ln(5)
    
    # 1. Introduction
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "1. Introduction")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- The alignment problem at civilization scale\n- Current alignment research focuses on individual model behavior\n- CIC extends alignment to institutional/societal intent continuity\n- Key question: 'Can a civilization-scale intelligent system become increasingly capable without silently losing the intent it was created to serve?'\n- CIC is a PROPOSED research framework, not a solved problem")
    pdf.ln(5)

    # 2. Definition
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "2. Definition")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- Civilizational Intent Conservation = preserving continuity and provenance of collective societal intent while allowing explicitly authorized evolution\n- Unintentional intent drift vs legitimate authorized intent evolution\n- Example: original intent 'human flourishing + ecological sustainability' gradually optimized to 'economic output' without authorization\n- CIC is NOT value policing - it does not decide what values should be")
    pdf.ln(5)

    # 3. CIC Architecture
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "3. CIC Architecture")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- Intent Repository: versioned objectives, principles, constraints, provenance, authorization history\n- Intent Graph: directed graph of values, objectives, constraints, priorities, institutions\n- Value Auditor: compares intended objectives with observed system behavior\n- Drift Detector: statistical change-point detection on intent metrics (objective drift, priority drift, proxy drift, semantic drift, institutional drift)\n- Intent Evolution Gate: determines if change was accidental/emergent/manipulated/proposed/authorized\n- Intent Provenance Recorder: logs WHO, WHAT, WHEN, WHY, AUTHORIZATION, EVIDENCE, PREVIOUS VERSION, NEW VERSION, SIMULATED CONSEQUENCES")
    pdf.ln(5)

    # 4. CIC Safety Principle
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "4. CIC Safety Principle")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- CIC operates: OBSERVE -> COMPARE -> DETECT -> EXPLAIN -> SIMULATE -> ESCALATE -> RECORD -> REQUEST AUTHORIZATION\n- CIC must NOT: OBSERVE -> DECIDE WHAT HUMANS SHOULD VALUE -> FORCE COMPLIANCE\n- Major intent changes require explicit governance/human/civic authorization\n- Integrates with OPA, HITL, CHRONOS, geofence, kill switch")
    pdf.ln(5)

    # 5. Integration with ORION
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "5. Integration with ORION")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- Flow: SENSE -> OMNIS -> NEXUS -> FORGE -> MIRROR -> ASCEND -> GOVERNANCE -> CIC INTENT AUDIT -> AUTHORIZED ACTION -> OBSERVE -> LEARN -> UPDATE OMNIS -> CIC REASSESSMENT -> REPLAN\n- CIC runs both pre-decision and post-decision")
    pdf.ln(5)

    # 6. Related Concepts
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "6. Related Concepts")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- AICC (AI-Mediated Cultural Continuity): cultural memory preservation - supporting research direction, ties to PHOENIX and OMNIS\n- EGE (Evolutionary Governance Engineering): simulation-based governance exploration - research/simulation capability, NOT autonomous political authority\n- Relationship: AICC = cultural memory, PHOENIX = institutional continuity, OMNIS = world model, CIC = intent continuity")
    pdf.ln(5)
    
    # 7. Proposed Benchmark (CIC-001)
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "7. Proposed Benchmark (CIC-001)")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- Simulated civilization with population, institutions, AI agents, economy, culture, laws, resources, environment\n- Seed INTENT v1.0\n- Expose to: optimization pressure, generational turnover, institutional changes, AI replacement, economic shocks, resource scarcity, technological breakthroughs, misinformation, cultural evolution, conflicting objectives\n- Measure 10 dimensions: intent preservation, drift detection, false positive rate, false negative rate, legitimate evolution recognition, provenance integrity, recovery effectiveness, time-to-detection, intervention cost, governance violations\n- STATUS: SPECIFICATION ONLY - no results yet")
    pdf.ln(5)
    
    # 8. Proposed Metrics
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "8. Proposed Metrics")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- Intent Continuity (IC)\n- Intent Drift Magnitude (IDM)\n- Intent Detection Recall (IDR)\n- False Drift Rate (FDR)\n- Authorized Evolution Integrity (AEI)\n- Intent Provenance Integrity (IPI)\n- Intent Recovery Effectiveness (IRE)\n- STATUS: DEFINITIONS ONLY - no numerical results")
    pdf.ln(5)

    # 9. Threat Model
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "9. Threat Model")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- Optimization drift (proxy alignment failure)\n- Gradual institutional capture\n- Adversarial intent manipulation\n- Model interpretation drift\n- Generational value evolution without explicit authorization\n- Semantic drift in objective definitions")
    pdf.ln(5)

    # 10. Limitations
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "10. Limitations")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- Entirely theoretical - no experiments conducted\n- Benchmark is proposed, not executed\n- Formal metrics lack empirical validation\n- Integration with ORION is architectural, not implemented\n- CIC itself could become a single point of failure if misconfigured")
    pdf.ln(5)

    # 11. Conclusion
    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "11. Conclusion")
    pdf.ln()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, "- CIC addresses a gap between individual-model alignment and civilization-scale intent preservation\n- The framework is proposed as a research direction within the ORION architecture\n- Next step: implement minimal CIC prototype and execute CIC-001 benchmark")
    pdf.ln(10)

    # License and Copyright
    pdf.set_font("Helvetica", style="I", size=10)
    pdf.multi_cell(0, 5, "LICENSE: CC BY 4.0 (Creative Commons Attribution 4.0 International)\nCOPYRIGHT: Copyright 2026 Shaurya Sanyal (Team Auralis). All rights reserved.")

    out_path = "D:/orion/papers/CIC_Civilizational_Intent_Conservation_Technical_Report.pdf"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pdf.output(out_path)
    print(f"Paper generated successfully at {out_path}")

if __name__ == "__main__":
    create_pdf()
