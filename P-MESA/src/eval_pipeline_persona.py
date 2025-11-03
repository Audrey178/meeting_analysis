"""
Evaluation pipeline that runs a multi-step approach (THREE_STEP) to identify errors,
filter them, and rate summary severity. Now only GPT-based (no LLaMA, Gemini, Phi).
"""

import os
import json
import logging

from panel import Panel
from model_handler import ModelHandler

logger = logging.getLogger(__name__)


class EvalPipelinePersona:
    def __init__(self, criteria_path, in_context_learning_samples, client, model_id, agents=None, single_model=True, multi_family=False):
        self.criteria = self._load_criteria(criteria_path)
        # self.in_context_learning_samples = self._load_learning_samples_from_csv(in_context_learning_samples)
        self.client = client
        self.model_id = model_id
        self.agents = agents
        self.single_model = single_model
        self.multi_family = multi_family

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

    def compute_quality_score(self, scores, importance_weights=None):
        if importance_weights is None:
            importance_weights = {
                "action_relevance": 1.2,
                "context_customization": 1.1,
                "detail_alignment": 1.0,
                "priority_alignment": 1.1,
                "omission": 1.0,
                "hallucination": 1.0,
                "irrelevance": 0.9
            }

        numerator = sum(
            entry['score'].get('rating', 0) * 
            (entry['score'].get('confidence', 1.0) * 0.1) * 
            importance_weights.get(entry['criteria'].lower(), 1.0)
            for entry in scores
        )

        denominator = sum(
            (entry['score'].get('confidence', 1.0) * 0.1) * 
            importance_weights.get(entry['criteria'].lower(), 1.0)
            for entry in scores
        )

        impact = numerator / denominator if denominator != 0 else 0
        quality = 1 + ((5 - impact) / 5) * 9
        return round(quality, 2)

    def run(self, sample):
        logger.info("\n\n**************************\n[P-MESA - EVAL PIPELINE] Running _THREE_STEP Pipeline\n**************************\n")
        scores = []
        
        for criteria_name, criteria_data in self.criteria.items():
            score, selection, filter_output, protocol = self.pipeline(sample, criteria_name, criteria_data)
            
            assessment = {
                "criteria": criteria_name,
                "selection": selection,
                "filter": filter_output,
                "score": score,
                "protocol": protocol,
            }
            scores.append(assessment)
        
        # quality_score = self.compute_quality_score(scores)
        quality_score = 0
        logging.info("[P-MESA - EVAL PIPELINE] Quality score: %s", quality_score)
        
        return scores, quality_score

    def pipeline(self, data, criteria_name, criteria_data):
        examples = criteria_data.get('example', {})
        high_example = examples.get('high_score', {}) or examples.get('high', {})
        low_example = examples.get('low_score', {}) or examples.get('low', {})
        
        base_system_prompt = (
            "You are a Judge evaluating personalized meeting summaries using reference examples:\n"
             f"\nTranscript used for both high and low score example: {examples.get('transcript', '')}\n"
            f"High Score Example:\n{json.dumps(high_example, indent=2)}\n"
            f"Low Score Example:\n{json.dumps(low_example, indent=2)}\n"
            "Consider the persona's needs, role, and preferences while evaluating."
        )

        # Step 1: Identify potential issues
        format_step_1 = '[{"instance": "<text>", "reasoning": "<reason considering persona needs>", "certainty": "<0-100>"}, ...]'
        user_prompt_step_1 = (
            f"Step 1: Identify potential issues for the persona.\n"
            f"Criterion: {criteria_name}: {criteria_data['definition']}\n"
            f"Persona: {json.dumps(data.get('persona', {}), indent=2)}\n"
            f"Summary: {data['summary']}\n"
            f"Transcript: {data['transcript']}\n"
            f"List instances where this criterion might not serve the persona's needs. Format:\n{format_step_1}"
        )

        list_of_instances, log_instances = self.task_execution(base_system_prompt, user_prompt_step_1)

        # Step 2: Validate issues
        format_step_2 = '[{"instance": "<text>", "reasoning": "<reason>", "certainty": "<0-100>", "error_exists": true}, ...]'
        user_prompt_step_2 = (
            f"Step 2: Validate issues considering persona context.\n"
            f"Criterion: {criteria_name}: {criteria_data['definition']}\n"
            f"Persona: {json.dumps(data.get('persona', {}), indent=2)}\n"
            f"Potential instances: {list_of_instances}\n"
            f"Decide if each instance truly affects the persona's needs. Format:\n{format_step_2}"
        )

        list_of_instances_filtered, log_filtered = self.task_execution(base_system_prompt, user_prompt_step_2)

        # Step 3: Rate severity
        rating_format = (
            '{\n'
            '  "reasoning": "<impact on persona needs>",\n'
            '  "confidence": <0-10>,\n'
            '  "rating": <0-5>\n'
            '}'
        )
        user_prompt_step_3 = (
            f"Step 3: Rate impact on persona effectiveness.\n"
            f"Criterion: {criteria_name}: {criteria_data['definition']}\n"
            f"Scoring Guide: {json.dumps(criteria_data.get('scoring_guide', {}), indent=2)}\n"
            f"Persona: {json.dumps(data.get('persona', {}), indent=2)}\n"
            f"Summary: {data['summary']}\n"
            f"Transcript: {data['transcript']}\n"
            f"Validated issues: {list_of_instances_filtered}\n"
            f"Rate severity considering persona impact. Format:\n{rating_format}"
        )

        # Add in-context examples if available
        system_prompt = base_system_prompt
        # if self.in_context_learning_samples.get(criteria_name):
        #     system_prompt += f"\nIn-context examples:\n{self.in_context_learning_samples[criteria_name]}"

        final_score, log_final = self.task_execution(system_prompt, user_prompt_step_3)

        protocol = {
            "instances": log_instances,
            "filter": log_filtered,
            "final": log_final,
        }
        return final_score, list_of_instances, list_of_instances_filtered, protocol

    def task_execution(self, system_prompt, user_prompt):
        if self.single_model:
            message = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            response_raw = ModelHandler.call_model_with_retry(
                self.client, message, self.model_id, max_tokens=4000
            )
            response_text = response_raw.choices[0].message.content.strip()
            response_text = response_text.strip("```json").strip("```").strip()

            try:
                parsed = json.loads(response_text)
                return parsed, parsed
            except json.JSONDecodeError:
                logger.warning("[P-MESA - EVAL PIPELINE] Could not parse JSON. Returning raw text.")
                return response_text, response_text
        else:
            panel = Panel(self.client, self.model_id, self.multi_family)
            final_answer, protocol_log = panel.ask("brainstorming", system_prompt, user_prompt)
            return final_answer, protocol_log