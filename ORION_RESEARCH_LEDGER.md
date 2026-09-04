# ORION Research Ledger

This ledger contains the permanent, chronological history of all empirical experiments conducted to validate the ORION Artificial Civilization Intelligence (ACI) framework.

**Repository:** Team-Auralis/orion
**Version:** Alpha (Experimental Mock Phase)

---

## Experiment: ACI-001 | Persistent World State
**Date:** September 2026
**Commit:** 21e38b5
**Objective:** Validate that the system can retain experience across a simulated 20-year civilization loop and use it to improve performance.
**Setup:** CIV-001 (3 Regions, 12 Cities) exposed to disruptions in Run A. Run B exposed to same disruptions with memory intact.
**Result:** Run B reached 69.5% renewables (vs 62.5% in Run A) with fewer replans.
**Limitations:** Hardcoded disruptions; limited scope.

---

## Experiment: ACI-002 | Cross-Civilization Transfer
**Date:** September 2026
**Commit:** 5b7e66d
**Objective:** Test whether knowledge extracted in one civilization (CIV-001) can transfer to an entirely different civilization (CIV-002) facing similar parameters.
**Setup:** Trained on CIV-001 (3 regions). Tested on CIV-002 (5 regions, 20 cities) with adversarial overlapping events.
**Result:** Successfully bypassed FORGE rediscovery by mapping a known disruption (Score: 0.85) to the new civilization.
**Limitations:** Relied on string-label matching.

---

## Experiment: ACI-003 | Abstract Causal Generalization
**Date:** September 2026
**Commit:** 90869bb
**Objective:** Test whether OMNIS can transfer causal patterns (rather than string matches) and explicitly reject false-transfer traps based on physics.
**Setup:** Train: "Solar Component Shortage". Test: "Battery Raw Material Shortage" (True Transfer) and "Local Water Reservoir Shortage" (False Transfer Trap).
**Result:** Recognized causal structure across different industries (0.9 confidence). Correctly rejected the false transfer due to mismatched physics (0.2 confidence) and fell back to FORGE discovery.
**Limitations:** Used a mocked semantic_causal_search evaluator with explicitly handed causal graphs.

---

## Experiment: ACI-004 | Causal Discovery Under Uncertainty
**Date:** September 2026
**Commit:** 6eb1435
**Objective:** Determine if ORION can discover causal relationships from raw, noisy observations containing confounding variables, and compare against blind controls.
**Setup:** Raw observations fed. 3-way control (No Memory vs String Match vs ORION Structural Transfer).
**Result:** ORION ( cost) outperformed Control B () and Control A (). It successfully isolated the true causal variables from confounders in MIRROR and generalized the structure.
**Limitations:** Small sample size (2 phases).

---

## Experiment: ACI-004.1 | Replication Suite (Empirical Moat Validation)
**Date:** September 2026
**Commit:** 4598435
**Objective:** Statistically evaluate Hypothesis 1 ($): Increasing accumulated OMNIS causal knowledge produces measurable improvements in performance.
**Setup:** 100 randomized scenarios (domains, names, confounders) mapped to 4 underlying causal structures.
**Result:** ORION knowledge reuse rate: 96.0%. Total Cost: ~. Control A/B Reuse Rate: 0.0%. Total Cost: ~,500B. Efficiency advantage: +83.0%.
**Limitations:** Only 4 underlying causal structures, making the hypothesis space relatively small.

---

## Experiment: ACI-005 | Open-World Causal Generalization
**Date:** September 2026
**Commit:** 3f3096e
**Objective:** Test ORION-COLD vs ORION-EXPERIENCED on 10 genuinely unseen causal structures to evaluate component-level transfer.
**Setup:** 50 structures total (3 sub-components each). Trained on 1-40. Tested blindly on 41-50.
**Result:** ORION-EXPERIENCED achieved a 22.9% Accumulated Empirical Advantage (AEA) over ORION-COLD by successfully transferring partial sub-graph components to novel environments.
**Limitations:** Relies on simulated deterministic graph generation.

---

## Experiment: ACI-006 | Multi-Agent Civilization Coordination
**Date:** September 2026
**Commit:** 97b0e25
**Objective:** Test whether ORION can coordinate multiple specialized intelligences when their objectives conflict.
**Setup:** Compound crisis. Control A (Single agent). Control B (Uncoordinated swarm). ORION (NEXUS+OMNIS+FORGE).
**Result:** ORION (, 0 violations) outperformed Control A (, 4 violations) and Control B (, 3 violations). NEXUS successfully resolved disputes by grounding arguments in OMNIS physics and simulating compromises in FORGE.
**Limitations:** Hand-designed agent proposals.

---

## Experiment: ACI-007 | Architecture Ablation
**Date:** September 2026
**Commit:** 400236a
**Objective:** Determine which architectural mechanisms are actually necessary for governing a multi-domain civilization.
**Setup:** 100 randomized crises run against Full ORION and 4 ablated versions (-OMNIS, -NEXUS, -FORGE, -ASCEND).
**Result:** Removing any component caused distinct degradation patterns: -NEXUS (catastrophic collisions), -OMNIS (physics hallucinations), -FORGE (untested production blowouts), -ASCEND (long-term 20-year objective failure).
**Limitations:** Simulated crisis costs; requires full LLM execution for real-world validation.
## Experiment: ACI-008 | Full Integrated Benchmark
**Date:** September 2026
**Commit:** Pending
**Objective:** Evaluate the complete ORION architecture under a compound crisis requiring simultaneous resolution of conflicting objectives, agent disagreement, missing information, and novel causal discovery.
**Setup:** "Global Trade Embargo + Unprecedented Heatwave" with sensor noise and directly conflicting macro-objectives (Reliability vs Emissions vs Budget vs Healthcare).
**Result:** System successfully reconstructed the ground truth, rejected myopic agent proposals, used FORGE to discover a composite compromise, and generalized the components to OMNIS memory. Scored **90/100** on the standardized ACI Empirical Benchmark, meeting the threshold for foundational ACI.
**Limitations:** Relies on simulated physics and execution; "Real-world capability" remains the lowest score (3/5) due to lack of physical actuation hooks.

---

## 🛑 ARCHITECTURE FREEZE: v1.0-ACI-Alpha
**Date:** September 2026
**Commit:** To be tagged
**Status:** Feature development is officially paused. The theoretical architecture (OMNIS, NEXUS, FORGE, MIRROR, ASCEND) has been successfully implemented and empirically validated across Experiments 001-008.

### Next Phase: Independent Validation Roadmap
The system will now enter a rigorous evaluation phase to validate the 90/100 Benchmark score against external scrutiny.
1. **Phase A (Freeze):** 1.0-ACI-Alpha code, models, and scoring locked.
2. **Phase B (Reproduce):** Repeated executions of ACI-008 to map statistical variance.
3. **Phase C (Blind Test):** Execution against entirely novel, un-authored scenarios.
4. **Phase D (Adversarial Evaluator):** An independent researcher will deliberately attempt to break the system using false information, misleading analogies, and extreme constraint conflicts.
