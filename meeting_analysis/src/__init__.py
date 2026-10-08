"""API công khai của package meeting-analysis: catalog module, cấu hình, contract dữ liệu và các port (adapter)."""

from .utils.catalog import (
    ACTION_MODULES,
    MODULE_CATALOG,
    PIPELINE_MODULES,
    EngineKind,
    ModuleSpec,
    get_module,
)
from .utils.config import (
    AtomBuilderConfig,
    AtomConfig,
    EventGuardConfig,
    EventExtractorConfig,
    FeatureBuilderConfig,
    InputDomainConfig,
    PipelineConfig,
    PublishConfig,
    PublishPolicyConfig,
    SpeakerTurnConfig,
    TopicLabelerConfig,
    TopicRecurrenceConfig,
    TopicSegmenterConfig,
    TurnBuilderConfig,
    TurnConfig,
    WindowBuilderConfig,
    WindowConfig,
    load_config,
)
from .utils.contracts import (
    AnalysisAtom,
    AnalysisWindow,
    AtomFeatures,
    AtomicClaim,
    BoundaryTiebreakDecision,
    Citation,
    CitationFragment,
    EffectiveTranscriptItem,
    EntityMention,
    EventKind,
    EvidenceItem,
    FieldProvenance,
    GuardStatus,
    InputDomainAssessment,
    InputDomainSignal,
    InputDomainSignalType,
    InputDomainStatus,
    Provenance,
    PublishableClaim,
    RawTranscriptItem,
    ReviewMarker,
    SourceSpan,
    SpeakerTurn,
    TopicLabel,
    TopicMap,
    TopicRecurrenceDecision,
    TopicRecurrenceVote,
    TopicSegment,
    VerificationScope,
    VerificationStatus,
    VerifiedClaim,
    to_jsonable,
)
from .utils.ports import (
    ActionAdapter,
    ClauseBoundaryAdapter,
    CosineSimilarityAdapter,
    EmbeddingAdapter,
    EventAdapter,
    EventGuardReviewer,
    FeatureAdapter,
    LLMAdapter,
    LLMBoundaryTiebreakAdapter,
    SemanticSimilarityAdapter,
    TopicAdapter,
    TopicLabelAdapter,
    TopicRecurrenceLLMAdapter,
    VerifierAdapter,
)

__version__ = "0.2.0"


def __getattr__(name: str):
    """Nạp trễ ``build_atom_features`` (nhánh atoms, không nằm trên đường chạy chính).

    Trước đây tên này được import sẵn ở đầu file, nên import bất cứ thứ gì trong ``src``
    (kể cả ``src.stages.stage03_speaker_turns``) cũng kéo theo cả nhánh stage05.

    Đầu vào: name - tên thuộc tính được truy cập trên package ``src``.
    Đầu ra: hàm ``build_atom_features`` khi ``name`` khớp, lưu vào namespace cho lần sau.
    Lỗi: AttributeError với mọi tên khác (hành vi chuẩn của Python).
    """

    if name == "build_atom_features":
        from .stages.stage05_atom_features import build_atom_features

        globals()[name] = build_atom_features
        return build_atom_features
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ACTION_MODULES",
    "MODULE_CATALOG",
    "PIPELINE_MODULES",
    "ActionAdapter",
    "AnalysisAtom",
    "AnalysisWindow",
    "AtomFeatures",
    "AtomBuilderConfig",
    "AtomConfig",
    "AtomicClaim",
    "BoundaryTiebreakDecision",
    "Citation",
    "CitationFragment",
    "ClauseBoundaryAdapter",
    "CosineSimilarityAdapter",
    "EffectiveTranscriptItem",
    "EmbeddingAdapter",
    "EngineKind",
    "EntityMention",
    "EventGuardConfig",
    "EventGuardReviewer",
    "EventExtractorConfig",
    "EventAdapter",
    "EventKind",
    "EvidenceItem",
    "FeatureAdapter",
    "FeatureBuilderConfig",
    "FieldProvenance",
    "GuardStatus",
    "InputDomainAssessment",
    "InputDomainConfig",
    "InputDomainSignal",
    "InputDomainSignalType",
    "InputDomainStatus",
    "LLMAdapter",
    "LLMBoundaryTiebreakAdapter",
    "ModuleSpec",
    "PipelineConfig",
    "Provenance",
    "PublishConfig",
    "PublishPolicyConfig",
    "PublishableClaim",
    "RawTranscriptItem",
    "ReviewMarker",
    "SemanticSimilarityAdapter",
    "SourceSpan",
    "SpeakerTurn",
    "SpeakerTurnConfig",
    "TopicAdapter",
    "TopicLabel",
    "TopicLabelAdapter",
    "TopicLabelerConfig",
    "TopicMap",
    "TopicRecurrenceConfig",
    "TopicRecurrenceDecision",
    "TopicRecurrenceLLMAdapter",
    "TopicRecurrenceVote",
    "TopicSegment",
    "TopicSegmenterConfig",
    "TurnBuilderConfig",
    "TurnConfig",
    "VerificationScope",
    "VerificationStatus",
    "VerifiedClaim",
    "VerifierAdapter",
    "WindowBuilderConfig",
    "WindowConfig",
    "build_atom_features",
    "get_module",
    "load_config",
    "to_jsonable",
]
