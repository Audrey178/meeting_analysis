from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List

import pandas as pd

# Re‑use the shared model handler to benefit from unified retry / logging logic
from model_handler import ModelHandler  # NOTE: same import path as MeetingSummarizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class SinglePromptMeetingSummarizer:
    """End‑to‑end meeting summarizer that collapses the full multi‑stage flow
    (atomic facts → feature ranking → outline → self‑critique) into **one** LLM
    call by embedding an extremely explicit instruction‑set inside the system
    prompt. The final model response *must* be a JSON object with three
    top‑level keys: `summary` (str), `confidence_score` (0‑100 int),
    `word_count` (int).
    """

    def __init__(self, client: Any, log_base_path,model: str = "gpt-4o") -> None:
        self.client = client
        self.model = model
        self.log_base_path = log_base_path

    @staticmethod
    def _generate_meeting_id(text: str) -> str:
        """Stable hash so we can skip already‑seen meetings when running in batch."""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _build_prompts(self, transcript: str, word_limit: int) -> Dict[str, str]:
        """Create the system + user prompts.

        The *system prompt* is long and instructive; it walks the model through
        every internal sub‑task. The *user prompt* simply supplies the
        transcript and restates the critical constraints.
        """

        # ——— SYSTEM PROMPT ————————————————————————————————————————————————————
        system_prompt = f"""
        NGÔN NGỮ: Phải trả lời bằng tiếng Việt.

You are an advanced assistant skilled in summarizing meeting transcripts accurately and concisely.

Your task is to analyze the provided transcript and, within this single response, internally apply the following process:

1. **Chunk the transcript** into logical sections if it is very long (no need to display chunks).
2. **Extract key facts and concrete points** from each section. Focus only on information explicitly stated in the transcript.
3. **Identify and rank important features, decisions, and insights** from those facts. Group them in your own reasoning as: Decisions, High Importance, Medium Importance, and Context.
4. **Organize your understanding** into an internal outline with:
   - Brief Overview (1-2 sentences)
   - Key Decisions (highest importance)
   - Main Discussion Points (high/medium importance)
   - Next Steps or Action Items (if present)
5. **Write a professional summary** of 200-250 words that covers all major points in narrative paragraph form (no bullet points, no headings, no enumeration).
6. **Review your own summary** to ensure all critical items are included, it is factually accurate, concise, and within the required word count.

Guidelines:
- Use only content from the transcript.
- Do not add outside knowledge or assumptions.
- The summary should be neutral and easy to read.
- Write in third person, never refer to yourself or the model.
- Avoid all mention of steps or process in your output.
- Do not include any outline, intermediate steps, or internal notes—only the final summary.            """

        # ——— USER PROMPT ————————————————————————————————————————————————————
        user_prompt = f"""
        Below is the full transcript to summarise.

        <TRANSCRIPT>
        {transcript.strip()}
        </TRANSCRIPT>
        """

        return {"system": system_prompt, "user": user_prompt}


    def generate_summary(self, transcript: str, word_limit: int = 200) -> Dict[str, Any]:
        """Run the single LLM call and return the parsed JSON dictionary."""
        prompts = self._build_prompts(transcript, word_limit)

        # Build a chat message list compatible with ModelHandler (system first)
        message = ModelHandler.build_message(prompts["system"], prompts["user"])

        raw_response = ModelHandler.call_model_with_retry(
            self.client,
            message,
            self.model,
            query_type="meeting_summary_one_shot",
            max_tokens=4096,
            category="One Shot summary", 
            log_base_path=self.log_base_path
        )
        return raw_response

    def process_dataframe(self, df: pd.DataFrame, output_csv: str) -> pd.DataFrame:
        """Iterate over a DataFrame with at least `transcript` and `summary` cols,
        run the summarizer, and incrementally save results to `output_csv`.
        Returns the final combined DataFrame (new + existing rows).
        """
        os.makedirs(os.path.dirname(output_csv), exist_ok=True)

        # If an output file exists, load to avoid duplicate work
        aggregated: List[Dict[str, Any]]
        if os.path.exists(output_csv):
            aggregated = pd.read_csv(output_csv).to_dict("records")
            logging.info(f"Loaded {len(aggregated)} pre‑existing rows from {output_csv}")
        else:
            aggregated = []

        df = df[3:13]
        for idx, row in df.iterrows():
            meeting_id = self._generate_meeting_id(str(row["Meeting"]))

            # Skip if already processed
            if any(r["meeting_id"] == meeting_id for r in aggregated):
                logging.info(f"Row {idx} already summarised; skipping.")
                continue

            logging.info(f"Summarising transcript {idx + 1}/{len(df)} (≈{len(row['Meeting'].split())} words)")
            try:
                result_json = self.generate_summary(row["Meeting"])
                aggregated.append({
                    "meeting_id": meeting_id,
                    "row_index": idx,
                    "transcript": row["Meeting"],
                    "gold_summary": row.get("Summary", ""),
                    "generated_summary": result_json
                })
                # Incremental save
                pd.DataFrame(aggregated).to_csv(output_csv, index=False)
                logging.info(f"Saved progress after row {idx}")
            except Exception as exc:
                logging.error(f"Error on row {idx}: {exc}")
                continue

        final_df = pd.DataFrame(aggregated)
        logging.info("Batch summarisation complete → {} rows total".format(len(final_df)))
        return final_df

    def process_all_meetings(self, input_path: str, output_csv: str) -> pd.DataFrame:
        """Load a CSV **or** PKL of meeting transcripts and pipe to
        :py:meth:`process_dataframe`. The file must have `transcript` column. A
        `summary` (gold) column is optional and is propagated if present.
        """
        ext = os.path.splitext(input_path)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(input_path)
        elif ext == ".pkl":
            df = pd.read_pickle(input_path)
        else:
            raise ValueError("Input must be .csv or .pkl – got {}".format(ext))

        missing_cols = [c for c in ("Meeting",) if c not in df.columns]
        if missing_cols:
            raise KeyError(f"Input file missing required column(s): {missing_cols}")

        return self.process_dataframe(df, output_csv)
