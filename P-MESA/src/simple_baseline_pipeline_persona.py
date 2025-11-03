
"""
Simple pipeline: evaluates all criteria "at once" with a single GPT call,
producing a JSON map of {criterion_name: {reasoning, confidence, rating}}.
"""

import os
import json
import logging

from model_handler import ModelHandler

logger = logging.getLogger(__name__)

class SimpleBaselinePipelinePersona:
    def __init__(self, criteria_path, in_context_learning_samples, client, model_id, single_model=True, multi_family=False):
        self.criteria = self._load_criteria(criteria_path)
        self.in_context_learning_samples = self._load_learning_samples(in_context_learning_samples)
        self.client = client
        self.model_id = model_id
        self.single_model = single_model

    def _load_criteria(self, criteria_path):
        definitions_dict = {}
        for file in os.listdir(criteria_path):
            if file.endswith(".json"):
                with open(os.path.join(criteria_path, file), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    filename = file.split(".")[0]
                    definitions_dict[filename] = {
                        "definition": data.get("definition", ""),
                        "scoring_guide": data.get("scoring_guide", {}),
                        "example": data.get("example", {})
                    }
        return definitions_dict

    def run(self, sample):
        logger.info("\n\n**************************\n[MESA - SIMPLE BASELINE] Running _ALL_AT_ONCE Pipeline\n**************************\n")
        score = self.pipeline(sample, self.criteria)
        
        scores = []
        for crit_name, details in score.items():
            assessment = {
                "criteria": crit_name,
                "selection": "",
                "filter": "",
                "score": {
                    "reasoning": details.get("reasoning", ""),
                    "confidence": int(details.get("confidence", 0)),
                    "rating": int(details.get("rating", 0)),
                }
            }
            scores.append(assessment)
        return scores

    def pipeline(self, data, criteria_dict):
        # Build examples section
        examples_text = ""
        for crit_name, criteria_data in criteria_dict.items():
            examples = criteria_data.get('example', {})
            if examples:
                high_example = examples.get('high_score', {}) or examples.get('high', {})
                low_example = examples.get('low_score', {}) or examples.get('low', {})
                examples_text += f"\n{crit_name} Examples:\n"
                examples_text += f"\nTranscript used for both high and low score example: {examples.get('transcript', '')}\n"
                examples_text += f"High Score:\n{json.dumps(high_example, indent=2)}\n"
                examples_text += f"Low Score:\n{json.dumps(low_example, indent=2)}\n"

        system_prompt = (
            "You are an expert in evaluating personalized meeting summaries. "
            "You will evaluate all criteria simultaneously.\n"
            f"Reference Examples:{examples_text}"
        )

        # Combine all criteria definitions
        combined_criteria = ""
        for crit, crit_data in criteria_dict.items():
            combined_criteria += f"{crit}:\nDefinition: {crit_data['definition']}\n"
            if crit_data.get('scoring_guide'):
                combined_criteria += f"Scoring Guide: {json.dumps(crit_data['scoring_guide'], indent=2)}\n\n"

        user_prompt = (
            f"Transcript: <{data['transcript']}>\n"
            f"Summary: <{data['summary']}>\n"
            f"Persona: <{data.get('persona', {})}>\n"
            f"Criteria Definitions:\n{combined_criteria}\n"
            "For each criterion, provide:\n"
            '{\n'
            '   "reasoning": "<evaluation based on examples>",\n'
            '   "confidence": <0-10>,\n'
            '   "rating": <0-5>\n'
            '}\n'
            "Return a JSON object mapping each criterion to these metrics."
        )

        message = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_raw = ModelHandler.call_model_with_retry(self.client, message, self.model_id, max_tokens=4000)
        response_text = response_raw.choices[0].message.content.strip()
        response_text = response_text.strip("```json").strip("```").strip()

        try:
            parsed = json.loads(response_text)
            return parsed
        except json.JSONDecodeError:
            logger.warning("[MESA - SIMPLE BASELINE] Could not parse JSON. Returning empty.")
            return {}