"""
meeting_metadata.py

Loader for the manually-filled metadata that a meeting transcript itself
does not contain: exact meeting date, presiding chair's name/title,
attendee list, and reference document numbers (Tờ trình, Báo cáo thẩm
định...). Per REQ-06/REQ-07, none of this is inferred or hallucinated —
missing fields become explicit, human-readable placeholders instead.
"""

import json
import logging
import os
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

_EMPTY_METADATA: Dict = {
    "date": "",
    "location": "",
    "chair_name": "",
    "chair_title": "",
    "participants": [],
    "reference_documents": [],
}


def load_meeting_metadata(path: Optional[str]) -> Dict:
    """
    Load meeting metadata from a JSON file. Returns a dict with the full
    schema (all keys present) even if the file is missing or path is None —
    missing fields simply stay empty/[] and get turned into placeholders by
    metadata_to_placeholders().
    """
    metadata = dict(_EMPTY_METADATA)
    metadata["participants"] = []
    metadata["reference_documents"] = []

    if not path:
        logging.info("No meeting_metadata path provided — using empty metadata (placeholders will be used).")
        return metadata

    if not os.path.exists(path):
        logging.warning(f"meeting_metadata file not found at {path} — using empty metadata (placeholders will be used).")
        return metadata

    try:
        with open(path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        for key in metadata:
            if key in loaded and loaded[key]:
                metadata[key] = loaded[key]
        logging.info(f"Loaded meeting metadata from {path}")
    except Exception as e:
        logging.error(f"Error loading meeting metadata from {path}: {e} — falling back to empty metadata.")

    return metadata


def metadata_to_placeholders(metadata: Dict) -> Dict:
    """
    Return a copy of metadata where any empty field is replaced with an
    explicit, human-editable placeholder string. Non-empty fields are kept
    as-is.
    """
    result = dict(metadata)

    result["date"] = metadata.get("date") or "ngày ___ tháng ___ năm ____"
    result["location"] = metadata.get("location") or "[CẦN BỔ SUNG ĐỊA ĐIỂM]"
    result["chair_name"] = metadata.get("chair_name") or "[CẦN BỔ SUNG TÊN CHỦ TRÌ]"
    result["chair_title"] = metadata.get("chair_title") or "[CẦN BỔ SUNG CHỨC DANH CHỦ TRÌ]"

    participants: List = metadata.get("participants") or []
    result["participants"] = participants if participants else ["[CẦN BỔ SUNG THÀNH PHẦN THAM DỰ]"]

    reference_documents: List = metadata.get("reference_documents") or []
    result["reference_documents"] = reference_documents  # empty list is valid: simply omit the references section

    return result
