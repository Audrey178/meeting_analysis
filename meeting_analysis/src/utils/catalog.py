"""Machine-readable catalog for the proposed 20 + 8 module architecture."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EngineKind(StrEnum):
    RULE = "rule"
    HYBRID = "hybrid"
    MODEL = "model"
    LLM = "llm"
    GRAPH = "graph"
    TEMPLATE = "template"


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    code: str
    title: str
    engine_kind: EngineKind
    mvp_implemented: bool
    mvp_notes: str


PIPELINE_MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("1", "Effective Transcript Resolver", EngineKind.RULE, True, "Field-level review overlay; raw item retained."),
    ModuleSpec("2", "Evidence Normalizer", EngineKind.RULE, True, "Unicode/whitespace normalization and stable evidence IDs."),
    ModuleSpec("3", "Speaker Turn Builder", EngineKind.RULE, True, "Same-speaker temporal grouping with a configurable gap."),
    ModuleSpec("4", "Clause / Analysis Atom Builder", EngineKind.HYBRID, True, "One exact atom per clause; rule bootstrap, learned-span port, and weak-data generator."),
    ModuleSpec("5", "Atom Feature Builder", EngineKind.HYBRID, True, "Deterministic TF-IDF/BM25, regex+alias entities, and keyphrases; dense embeddings remain injectable."),
    ModuleSpec("6", "Topic Segmenter", EngineKind.HYBRID, True, "Always runs a paper-inspired token-capped strategy; chunked linear is the default and cosine variants are injectable."),
    ModuleSpec("7", "Topic Labeler", EngineKind.LLM, True, "Structured LLM port after fixed boundaries; offline runs are explicitly marked extractive fallback."),
    ModuleSpec("8", "Topic Recurrence Resolver", EngineKind.HYBRID, True, "Semantic branch runs first, then the LLM branch (its per-pair calls run in parallel); conservative join retains both votes."),
    ModuleSpec("9", "Analysis Window Builder", EngineKind.RULE, True, "Deterministic LEFT/CORE/RIGHT atom windows."),
    ModuleSpec("10", "Conversation Quality Assessor", EngineKind.HYBRID, False, "Planned local recoverability classifier and conservative policy."),
    ModuleSpec("11", "Atomic Event Extractor", EngineKind.LLM, True, "Adapter-backed structured extraction; MVP uses a conservative cue-based fallback."),
    ModuleSpec("12", "Event Guard", EngineKind.HYBRID, True, "Bounded three-round LLM reviewer/checker loop with exact evidence; deterministic checker is authoritative."),
    ModuleSpec("13", "Event Graph Linker", EngineKind.GRAPH, True, "Executable topic subgraphs, sequence edges, optional cross-topic semantic/recurrence links, and deterministic traces."),
    ModuleSpec("14", "Graph Trace & Event Ordering", EngineKind.GRAPH, True, "Executable stable topological traversal; episode patterns remain a future graph extension."),
    ModuleSpec("15", "Atomic Claim Builder", EngineKind.GRAPH, True, "Claims are emitted only from deterministic event-graph traversal."),
    ModuleSpec("16", "Citation Builder", EngineKind.RULE, True, "Graph event/atom trace resolves exact backend evidence fragments."),
    ModuleSpec("17", "Evidence Verifier", EngineKind.HYBRID, True, "MVP exact, actor, and modality checks; production NLI remains adapter-backed."),
    ModuleSpec("18", "Publish Policy", EngineKind.RULE, True, "Risk gates unsupported claims and unknown actors."),
    ModuleSpec("19", "Timeline Composer & Renderer", EngineKind.TEMPLATE, True, "MVP chronological composition with deterministic citation rendering."),
    ModuleSpec("20", "Review & Reprocessing Loop", EngineKind.GRAPH, False, "Planned dependency graph, cache invalidation, and incremental recomputation."),
)


ACTION_MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("A1", "Action Candidate Extractor", EngineKind.HYBRID, False, "Planned high-recall action/dialogue-act extraction."),
    ModuleSpec("A2", "Action Slot Extractor", EngineKind.LLM, False, "Planned task, actor, deadline, deliverable, and condition slots."),
    ModuleSpec("A3", "Participant & Organization Resolver", EngineKind.HYBRID, False, "Planned alias, fuzzy retrieval, and coreference resolution."),
    ModuleSpec("A4", "Action Event Guard", EngineKind.RULE, False, "Planned modality, evidence, and assigner validation."),
    ModuleSpec("A5", "Action Thread Linker", EngineKind.GRAPH, False, "Planned temporal linking and semantic deduplication."),
    ModuleSpec("A6", "Action Lifecycle Builder", EngineKind.GRAPH, False, "Planned event-sourced state machine for current owner/deadline/status."),
    ModuleSpec("A7", "Field-level Verifier", EngineKind.HYBRID, False, "Planned per-field exact/NLI verification and risk gating."),
    ModuleSpec("A8", "Action Item Renderer", EngineKind.TEMPLATE, False, "Planned deterministic action ledger with citations and warnings."),
)


MODULE_CATALOG: tuple[ModuleSpec, ...] = PIPELINE_MODULES + ACTION_MODULES


def get_module(code: str) -> ModuleSpec:
    normalized = code.strip().upper()
    for module in MODULE_CATALOG:
        if module.code.upper() == normalized:
            return module
    raise KeyError(f"unknown module code: {code}")


__all__ = [
    "ACTION_MODULES",
    "EngineKind",
    "MODULE_CATALOG",
    "ModuleSpec",
    "PIPELINE_MODULES",
    "get_module",
]
