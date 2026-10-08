"""Debug runner: execute stages 1-8 and print/write output for manual check.

Runs the pipeline's deterministic prefix through topic recurrence --

    stage01 resolve_effective_transcript
    stage02 build_evidence_items
    stage03 build_speaker_turns
    stage04 build_analysis_atoms
    stage10 assess_input_domain      (applicability gate, runs before 5-9)
    stage05 build_atom_features
    stage06 segment_topics
    stage07 label_topics
    stage08 resolve_topic_recurrence

directly (not via ``MeetingAnalysisPipeline.run``), so it stops right after
topic recurrence instead of continuing into windows/events/claims (stage 9+).

``--config`` defaults to ``configs/default.json`` when that file exists (pass
an explicit path to override). As of this default.json,
``topic_segmenter.strategy="hybrid_bm25_semantic_v2"`` -- the config-schema
name (``TopicSegmenterConfig`` only accepts 5 specific strategy strings, see
``utils/config.py``) for the canonical ``dp_penalty`` mode, which is what
actually runs stage 6 (TIP-004's DP-optimal Gram-matrix engine,
``stages/segmentation.py``) at ``segmentation.beta_dense=0`` -- lexical-only
(BM25 syllable + char n-grams), with ``gamma`` empirically grid-searched by
``eval/optimize_segmentation.py`` (see that script's module docstring for why
``beta_dense`` was deliberately kept at 0 rather than taking the grid's raw
winner: the dense channel there is only scored with a placeholder hash
embedding, not a real model). ``beta_dense=0`` means NO ``embedding_adapter``
is required, so this stays runnable with no flags and no network -- pass
``--embed`` to raise ``beta_dense`` back up via a real embedding client (see
below), or pass ``--config`` with a different ``segmentation`` section.
No model adapters are injected by default beyond what ``configs/default.json``
itself configures, so stages 7/8 use their deterministic offline fallbacks
(extractive title, ``LexicalCosineSimilarity``) UNLESS the corresponding flag
below is passed. This runner's default is intentionally offline-only and does
NOT match ``MeetingAnalysisPipeline`` any more: that orchestrator now
defaults stages 7 AND 8 to real OpenAI calls on its own whenever it can reach
them (see ``pipeline._default_topic_label_adapter``,
``_default_embedding_adapter``, ``_default_topic_recurrence_semantic_adapter``,
``_default_topic_recurrence_llm_adapter``), so ``--llm``/``--embed`` here are
only needed to opt this debug script itself into the same behavior.

Passing ``--llm`` swaps stage 7's title generation to
``StructuredLLMTopicLabeler``, AND stage 8's LLM-judge branch to
``StructuredLLMTopicRecurrenceChecker``, both over the SAME
``OpenAIChatJSONAdapter`` instance (real API calls, model defaults to
gpt-4o-mini), reading ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL`` / ``MODEL_NAME``
from the environment -- same as ``.env`` at the repo root. Without ``--llm``,
stage 8's LLM branch is skipped entirely (every gray-zone pair gets reason
``llm_adapter_unavailable``), same as ``resolve_topic_recurrence``'s own
default.

Passing ``--embed`` switches stage 6 to the ``hybrid_bm25_semantic_v2``
strategy (an alias of the ``dp_penalty`` default above -- same DP-optimal
Gram-matrix engine, ``stages/segmentation.py``) and wires a real
``OpenAIEmbeddingClient`` as its ``embedding_adapter`` -- without this flag,
a config with ``segmentation.beta_dense > 0`` would raise ``ValueError`` (no
embedding_adapter). NOTE: with the shipped ``configs/default.json``
(``beta_dense=0``), ``--embed`` alone does NOT change stage 6's output --
embeddings get computed (real API calls) but the dense channel still
contributes zero weight to the cost function. Pair ``--embed`` with
``--config`` pointing at a segmentation section that raises ``beta_dense``
above 0 to actually use it. Any ``topic_segmenter`` section in ``--config``
is overridden when ``--embed`` is passed: the strategy is forced to
``hybrid_bm25_semantic_v2`` so the flag's promise ("switch to v2 and wire the
adapter") always holds. The SAME embedding
client is also reused for stage 8: when ``topic_recurrence.use_gram_similarity``
is on (the default), ``--embed`` builds the Gram matrix
(``build_segment_gram``) so stage 8 scores pairs on it instead of skipping
straight to ``LexicalCosineSimilarity``; when that config flag is off
instead, ``--embed`` wires an ``OpenAISemanticSimilarity`` adapter as stage
8's semantic-branch fallback. Without ``--embed``, stage 8's semantic branch
stays purely lexical, same as ``resolve_topic_recurrence``'s own default.

Usage:
    python scripts/run_to_stage8.py --input inputs/sample_transcript.json
    python scripts/run_to_stage8.py -i inputs/sample_transcript.json -o outputs/stage8.json
    python scripts/run_to_stage8.py -i inputs/sample_transcript.json --dump-all
    python scripts/run_to_stage8.py -i inputs/sample_transcript.json --llm
    python scripts/run_to_stage8.py -i inputs/sample_transcript.json --embed
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.adapters import load_transcript  # noqa: E402
from src.utils.config import load_config  # noqa: E402
from src.utils.contracts import TopicMap, to_jsonable  # noqa: E402
from src.stages.stage01_effective_transcript import resolve_effective_transcript  # noqa: E402
from src.stages.stage02_evidence import build_evidence_items  # noqa: E402
from src.stages.stage03_speaker_turns import build_speaker_turns  # noqa: E402
from src.stages.stage04_analysis_atoms import build_analysis_atoms  # noqa: E402
from src.stages.stage05_atom_features import build_atom_features  # noqa: E402
from src.stages.stage06_topic_segmentation import segment_topics  # noqa: E402
from src.stages.stage07_topic_labeling import StructuredLLMTopicLabeler, label_topics  # noqa: E402
from src.stages.stage08_topic_recurrence import (  # noqa: E402
    StructuredLLMTopicRecurrenceChecker,
    resolve_topic_recurrence,
)
from src.stages.segmentation import build_segment_gram  # noqa: E402
from src.utils.ports import (  # noqa: E402
    EmbeddingAdapter,
    LLMAdapter,
    TopicLabelAdapter,
    TopicRecurrenceLLMAdapter,
)
from experiments.treeseg_turn_level.treeseg import segment_turns_with_treeseg  # noqa: E402

load_dotenv()

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "default.json"


def _parser() -> argparse.ArgumentParser:
    # Defaults to configs/default.json when present, so a plain invocation
    # actually reflects that file's settings (dp_penalty + the gamma/beta
    # eval/optimize_segmentation.py tuned -- see that file's module
    # docstring) instead of the PipelineConfig() dataclass defaults
    # load_config(None) would otherwise fall back to. --config still
    # overrides explicitly, and a missing default.json falls back to None
    # (dataclass defaults) rather than erroring.
    default_config = str(_DEFAULT_CONFIG_PATH) if _DEFAULT_CONFIG_PATH.is_file() else None
    parser = argparse.ArgumentParser(
        description="Run stages 1-8 of the meeting-analysis pipeline and print output to check"
    )
    parser.add_argument("--input", "-i", required=True, help="Native or legacy transcript JSON")
    parser.add_argument(
        "--config",
        "-c",
        default=default_config,
        help=(
            "Pipeline config JSON. Defaults to configs/default.json when it "
            "exists; pass an explicit path to override, or an empty/missing "
            "file falls back to PipelineConfig()'s dataclass defaults."
        ),
    )
    parser.add_argument("--output", "-o", default=None, help="Write full JSON result here; stdout if omitted")
    parser.add_argument(
        "--dump-all",
        action="store_true",
        help="Include every intermediate stage's output in the JSON result, not just stage08",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help=(
            "Use one shared OpenAIChatJSONAdapter for stage 7 titles "
            "(StructuredLLMTopicLabeler) AND stage 8's LLM-judge branch "
            "(StructuredLLMTopicRecurrenceChecker), instead of their deterministic "
            "fallbacks. Requires the 'openai' package and OPENAI_API_KEY / "
            "OPENAI_BASE_URL / MODEL_NAME in the environment."
        ),
    )
    parser.add_argument(
        "--atoms",
        action="store_true",
        help=(
            "Run TreeSeg over stage 4's analysis atoms (build_analysis_atoms) "
            "instead of raw speaker turns -- a turn can cover several "
            "distinct topics (see turn_purity.py), and turn-level TreeSeg can "
            "never place a boundary inside one. Atom boundaries come from "
            "rule-based candidates (item_boundary/sentence_punct/weak_punct/"
            "discourse_marker/pause) scored by a local Vietnamese PhoBERT "
            "SimCSE model (no API call, no --llm needed for this step)."
        ),
    )
    parser.add_argument(
        "--embed",
        action="store_true",
        help=(
            "Force stage 6's topic_segmenter.strategy to 'hybrid_bm25_semantic_v2' and "
            "wire a real OpenAIEmbeddingClient as its embedding_adapter, instead of the "
            "default 'paper_chunked_linear' strategy (no similarity scoring at all). "
            "The same embedding client also backs stage 8: it builds the Gram matrix "
            "for the semantic branch when topic_recurrence.use_gram_similarity is on "
            "(the default), or an OpenAISemanticSimilarity fallback when it's off. "
            "Requires the 'openai' package and OPENAI_API_KEY / OPENAI_EMBEDDING_BASE_URL "
            "in the environment."
        ),
    )
    return parser


def _build_llm_adapter() -> LLMAdapter:
    # Imported lazily -- the 'openai' package is optional (pyproject.toml
    # keeps the core dependency-free) and unneeded unless --llm is passed.
    # ONE client instance backs both stage 7 and stage 8 below: both only
    # need the small LLMAdapter.generate_json() protocol, so there is no
    # reason to open two.
    try:
        from src.utils.openai_adapters import OpenAIChatJSONAdapter
    except ImportError as exc:
        raise SystemExit(
            "--llm requires the 'openai' package (`pip install openai`)."
        ) from exc
    return OpenAIChatJSONAdapter()


def _build_topic_label_adapter(llm: LLMAdapter, max_title_chars: int) -> TopicLabelAdapter:
    model_name = getattr(llm, "model_name", type(llm).__name__)
    return StructuredLLMTopicLabeler(llm, model_name=model_name, max_title_chars=max_title_chars)


def _build_topic_recurrence_llm_adapter(llm: LLMAdapter) -> TopicRecurrenceLLMAdapter:
    model_name = getattr(llm, "model_name", type(llm).__name__)
    return StructuredLLMTopicRecurrenceChecker(llm, model_name=model_name)


def _build_embedding_adapter() -> EmbeddingAdapter:
    # Imported lazily: the backend's own dependencies (``openai`` or
    # ``sentence-transformers``) are optional and unneeded unless --embed is
    # passed. Backend chosen by EMBEDDING_BACKEND (see src/utils/embedding_backend.py).
    try:
        from src.utils.embedding_backend import build_embedding_adapter
    except ImportError as exc:
        raise SystemExit(f"--embed: could not import the embedding backend: {exc}") from exc
    return build_embedding_adapter()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    # Without this, the root logger stays at its default WARNING level with
    # no handler attached, so every logging.info(...) call anywhere in the
    # pipeline is silently dropped -- it never reaches stdout/stderr,
    # regardless of print() calls working fine.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    meeting_id, revision_id, raw_items = load_transcript(args.input)
    config = load_config(args.config)
    # Built before running any stage so a missing 'openai' package or a bad
    # OPENAI_* env var fails fast, not after stages 1-4/10 already ran.
    llm = _build_llm_adapter() if args.llm else None
    topic_label_adapter = (
        _build_topic_label_adapter(llm, config.topic_labeler.max_title_chars)
        if llm is not None
        else None
    )
    topic_recurrence_llm_adapter = (
        _build_topic_recurrence_llm_adapter(llm) if llm is not None else None
    )
    embedding_adapter = _build_embedding_adapter() if args.embed else None
    if args.embed:
        # See module docstring: --embed always forces v2, overriding any
        # topic_segmenter.strategy set via --config.
        config = dataclasses.replace(
            config,
            topic_segmenter=dataclasses.replace(
                config.topic_segmenter, strategy="hybrid_bm25_semantic_v2"
            ),
        )

    print("Starting stage 1")
    effective = resolve_effective_transcript(raw_items)
    print("Starting stage 2")
    evidence = build_evidence_items(meeting_id, effective)
    print("Starting stage 3")
    turns = build_speaker_turns(evidence, config.turn_builder)

    if args.atoms:
        print("Starting stage 4 (atoms)")
        atoms = build_analysis_atoms(turns, evidence, config.atom_builder)
        print(f"  -> {len(atoms)} atoms from {len(turns)} turns")
        treeseg_items = atoms
    else:
        atoms = None
        treeseg_items = turns

    print(f"Starting to TreeSeg (unit: {'atom' if args.atoms else 'turn'}, {len(treeseg_items)} items)")
    segments = segment_turns_with_treeseg(treeseg_items, embed_fn=embedding_adapter.embed if embedding_adapter else None, width=50, min_size=25)

    # )
    print(f"Starting stage 7 (title source: {'llm' if topic_label_adapter else 'extractive_fallback'})")
    labels = label_topics(
        segments, config=config.topic_labeler, adapter=topic_label_adapter
    )

    print(f"meeting_id={meeting_id} revision_id={revision_id}", file=sys.stderr)
    print(f"stage01 effective_transcript items: {len(effective)}", file=sys.stderr)
    print(f"stage02 evidence items:             {len(evidence)}", file=sys.stderr)
    print(f"stage03 speaker turns:               {len(turns)}", file=sys.stderr)
    print(f"stage06 topic segments:              {len(segments)}", file=sys.stderr)
    print(f"stage07 topic labels:                {len(labels)}", file=sys.stderr)

    result: dict[str, object] = {
        "meeting_id": meeting_id,
        "revision_id": revision_id,
        "turns": to_jsonable(turns),
        "atoms": to_jsonable(atoms) if atoms is not None else None,
        "topic_segments": to_jsonable(segments),
        "topic_labels": to_jsonable(labels),
    }
    if args.dump_all:
        result["effective_transcript"] = to_jsonable(effective)
        result["evidence_items"] = to_jsonable(evidence)
        result["speaker_turns"] = to_jsonable(turns)

    rendered = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote stage 1-8 output to {output_path}", file=sys.stderr)
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
