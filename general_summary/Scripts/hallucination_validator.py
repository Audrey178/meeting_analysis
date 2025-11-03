from typing import List, Dict, Tuple
import json
import logging
from model_handler import ModelHandler
from utils import _clean_response

class HallucinationValidator:
    def __init__(self, client, model,log_base_path):
        """Initialize the HallucinationValidator with model settings."""
        self.client = client
        self.model = model
        self.log_base_path = log_base_path

    def validate_atomic_facts(self, atomic_facts: List[Dict], previous_chunk_context,chunk: str) -> Dict:
        """
        Validate atomic facts against original chunk using LLM.
        Returns dict with overall_score, feedback list, and summary.
        """
        system_prompt = """
        You are an expert at detecting hallucinations in extracted information. Your task is to validate facts against source text.

        Process each fact and its context carefully:
        1. Compare each fact with the source text
        2. Check if the context provided is accurate
        3. Verify if verbose_context contains unsupported information
        4. Flag any information not explicitly present in source

        For each fact, verify:
        - Is the main fact supported by source text?
        - Is the context accurate and present in source?
        - Does verbose_context contain only information from source?
        - Are there any unsupported assumptions or inferences?

        IMPORTANT:
        - Process each fact individually
        - Be specific about hallucinated information
        - Flag ANY information not in source text
        - Check both fact and context fields

        Return a JSON object with:
        {
            "overall_score": float (0-100, lower means less hallucination) like 0 mean no hehallucination and 100 means facts are completly irrelevant to the chunk ,
            "feedback": [specific points about hallucinated information],
            "summary": "Brief summary of validation findings"
        }
        """

        user_prompt = f"""
        ANALYZE THESE ATOMIC FACTS AGAINST SOURCE:

        {previous_chunk_context}

        SOURCE TEXT:
        {chunk}

        ATOMIC FACTS TO VALIDATE:
        {json.dumps(atomic_facts, indent=2)}

        Process each fact, context, and verbose_context carefully.
        - Flag ANY information not present in source
        - Identify specific hallucinated details
        - Note unsupported context or background info
        - Look for exaggerations or assumptions

        Return overall evaluation focusing on hallucination detection.
        """

        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "Fact Verification",    
                category="Fact Verification", 
                log_base_path=self.log_base_path,
                verbose=True,
                max_tokens=4000
                )

            enriched_template = _clean_response(response)

            # Parse validation results
            try:
                validation_results = json.loads(enriched_template)
                return {
                    'overall_score': validation_results.get('overall_score', 100),
                    'feedback': validation_results.get('feedback', ["Validation failed"]),
                    'summary': validation_results.get('summary', "Unable to validate properly")
                }
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing validation results: {str(e)}")
                return {
                    'overall_score': 100,
                    'feedback': ["Error parsing validation results"],
                    'summary': "Validation failed due to parsing error"
                }

        except Exception as e:
            logging.error(f"Error in hallucination validation: {str(e)}")
            return {
                'overall_score': 100,
                'feedback': [f"Validation error: {str(e)}"],
                'summary': "Validation failed due to processing error"
            }