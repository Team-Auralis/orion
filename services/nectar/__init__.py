"""NECTAR.

NECTAR is a specialized computational instrument for ORION: a Drosophila
(whole-brain) connectome simulation subsystem. It executes connectome-faithful
spiking neuron models (Brian2 CPU baseline) under FORGE experiment dispatch,
and reports structured readouts as evidence into OMNIS.

Every action is audited via the safety layer. All shortcut paths are explicitly
labeled MOCK. No fabricated metrics.
"""
