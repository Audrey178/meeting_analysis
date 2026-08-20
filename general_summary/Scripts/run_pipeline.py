import argparse
import os
import logging
import json
from dotenv import load_dotenv
from openai import OpenAI

from meeting_summarizer import MeetingSummarizer
from docx_ingest import parse_transcript_docx, build_labeled_transcript_text
from meeting_metadata import load_meeting_metadata, metadata_to_placeholders
from docx_writer import write_thong_bao_docx

# Load environment variables
load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(description="Meeting transcript -> Thông báo kết luận .docx pipeline")
    parser.add_argument("--input", "-i", default=None,
                         help="Path to input transcript (.docx or pre-processed .json). "
                              "Defaults to DATASET_PATH from .env if omitted.")
    parser.add_argument("--metadata", "-m", default=None,
                         help="Path to meeting_metadata JSON (date/chair/participants/reference_documents). "
                              "Missing fields become explicit placeholders.")
    parser.add_argument("--output", "-o", default=None,
                         help="Path to write the output .docx to. "
                              "Defaults to Vietnamese_datasets/output/<input_basename>.docx")
    return parser.parse_args()


def _load_turns(input_path: str):
    """Load {meeting, turns, docs, entities} from either a .docx transcript or a pre-processed JSON."""
    if input_path.lower().endswith(".docx"):
        return parse_transcript_docx(input_path)

    with open(input_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _default_output_path(input_path: str) -> str:
    base = os.path.splitext(os.path.basename(input_path))[0]
    base = base.replace(" ", "_")
    return os.path.join("Vietnamese_datasets", "output", f"{base}.docx")


def split_numbered_sections(text: str, outline: list) -> list:
    """
    Split the model-generated "II. NỘI DUNG" draft into (title, body) tuples,
    one per numbered item ("1. ...", "2. ...", ...). Falls back to pairing
    outline titles with placeholder bodies if the numbering could not be
    parsed cleanly (e.g. model deviated from the requested format), so the
    document still has the right number of sections instead of failing.
    """
    import re
    # (?!\d) after the marker punctuation keeps this from matching a body
    # line that merely starts with a decimal number (e.g. "5.2 tỷ đồng cần
    # bổ sung...", a common Vietnamese admin-text figure) — without it,
    # "5.2 ..." parses as a false new section "5" titled "2 tỷ đồng...",
    # silently corrupting the split.
    marker = re.compile(r'^\s*(\d+)[.)](?!\d)\s*(.*)$')

    blocks = []
    current_title = None
    current_body_lines = []

    for line in (text or "").split('\n'):
        match = marker.match(line)
        if match:
            if current_title is not None:
                blocks.append((current_title, '\n'.join(current_body_lines).strip()))
            current_title = match.group(2).strip()
            current_body_lines = []
        else:
            if current_title is not None and line.strip():
                current_body_lines.append(line.strip())

    if current_title is not None:
        blocks.append((current_title, '\n'.join(current_body_lines).strip()))

    if blocks and len(blocks) == len(outline):
        return blocks

    if blocks:
        logging.warning(
            f"split_numbered_sections: parsed {len(blocks)} numbered blocks but outline has "
            f"{len(outline)} items — using parsed blocks as-is (titles may not exactly match outline)."
        )
        return blocks

    logging.warning("split_numbered_sections: could not parse any numbered block — "
                     "falling back to outline titles with placeholder bodies.")
    return [(title, "[CẦN BỔ SUNG NỘI DUNG]") for title in outline]


def build_document_fields(metadata_placeholders: dict):
    """
    Build the fixed administrative boilerplate slots (title brief, opening
    paragraph, participants block, closing paragraph) from meeting metadata.
    These are templated, not LLM-generated, per the "boilerplate vs
    extracted content" split agreed in the Blueprint (REQ-08).
    """
    chair_name = metadata_placeholders["chair_name"]
    chair_title = metadata_placeholders["chair_title"]
    date = metadata_placeholders["date"]
    location = metadata_placeholders["location"]

    chair_full = f"đồng chí {chair_name}, {chair_title}"

    title_brief = f"Ý kiến kết luận của {chair_full}\ntại cuộc họp"

    opening_paragraph = (
        f"{date}, tại {location}, {chair_full} đã chủ trì cuộc họp."
    )

    participants = {
        "chair": f"Đồng chí {chair_name}, {chair_title}.",
        "attendees": metadata_placeholders["participants"],
    }

    closing_paragraph = (
        f"Trên đây là ý kiến kết luận của {chair_full} tại cuộc họp. "
        "Văn phòng thông báo đến các cơ quan, tổ chức, cá nhân có liên quan biết, "
        "thực hiện và báo cáo kết quả theo quy định./."
    )

    return title_brief, opening_paragraph, participants, closing_paragraph


def run_pipeline():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    args = parse_args()

    MODEL_CONFIG_PATH = os.getenv('CONFIG_PATH')
    DATASET_PATH = args.input or os.getenv('DATASET_PATH', './datasets')
    LOG_BASE_PATH = os.getenv('LOG_BASE_PATH', './data_store')

    if not DATASET_PATH:
        raise ValueError("No input path provided: pass --input or set DATASET_PATH in .env")

    with open(MODEL_CONFIG_PATH) as config_file:
        config = json.load(config_file)

    API_KEY = os.getenv('OPENAI_API_KEY')
    BASE_URL = os.getenv('OPENAI_BASE_URL')  # e.g. vLLM endpoint; unset = default OpenAI API
    MODEL_NAME = config["model"]

    logging.info(f"Using model: {MODEL_NAME} (base_url={BASE_URL or 'default OpenAI'})")

    CLIENT = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    summarizer = MeetingSummarizer(CLIENT, MODEL_NAME, LOG_BASE_PATH)

    transcript_json = _load_turns(DATASET_PATH)
    transcript_text = build_labeled_transcript_text(transcript_json)

    final_summary, raw_summary, unique_features, outline = summarizer.process_meeting(transcript_text, './facts')
    print("Final II. NỘI DUNG draft:\n", final_summary)

    metadata = load_meeting_metadata(args.metadata)
    metadata_placeholders = metadata_to_placeholders(metadata)

    title_brief, opening_paragraph, participants, closing_paragraph = build_document_fields(metadata_placeholders)

    content_sections = split_numbered_sections(final_summary, outline)

    output_path = args.output or _default_output_path(DATASET_PATH)
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    write_thong_bao_docx(
        output_path,
        title_brief,
        opening_paragraph,
        participants,
        content_sections,
        closing_paragraph,
    )

    logging.info(f"Wrote Thông báo kết luận to {output_path}")
    print(f"\nOutput written to: {output_path}")


if __name__ == "__main__":
    run_pipeline()
