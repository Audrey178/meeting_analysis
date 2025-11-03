from typing import List, Dict, Any
import json
import logging
from model_handler import ModelHandler
from utils import _clean_response

class FactsReasoningLayer:
    def __init__(self, client, model):
        self.client = client
        self.model = model
    
    def verify_facts_reasoning_output(self, output: str) -> bool:
        """
        Verify if the facts reasoning output is complete and properly formatted.
        Returns True if output is valid, False otherwise.
        """
        try:
            # Try parsing the output as JSON
            try:
                facts_with_scores = json.loads(output)
            except json.JSONDecodeError:
                logging.error("Failed to parse facts reasoning output as JSON")
                return False
            
            # Ensure it's a list
            if not isinstance(facts_with_scores, list):
                logging.error("Facts reasoning output is not a list")
                return False
            
            # Check each fact
            for fact_entry in facts_with_scores:
                # Check if it's a dictionary with all required fields
                if not isinstance(fact_entry, dict):
                    logging.error(f"Fact entry is not a dictionary: {fact_entry}")
                    return False
                
                # Check required fields
                if 'fact' not in fact_entry or 'certainty_score' not in fact_entry:
                    logging.error(f"Missing required fields in fact entry: {fact_entry}")
                    return False
                
                # Check types
                if not isinstance(fact_entry['fact'], dict):
                    logging.error(f"Fact is not a dictionary: {fact_entry['fact']}")
                    return False
                
                if not isinstance(fact_entry['certainty_score'], (int, float)) or not (0 <= fact_entry['certainty_score'] <= 100):
                    logging.error(f"Invalid certainty score: {fact_entry['certainty_score']}")
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error verifying facts reasoning output: {str(e)}")
            return False

    def apply_reasoning_layer(self, atomic_facts: List[Dict], character_sheet: Dict) -> Dict:
        """
        Apply reasoning layer to filter atomic facts based on persona relevance.
        
        Args:
            atomic_facts: List of atomic facts from AtomicFacts
            character_sheet: Character profile from CharacterSheetGenerator
            
        Returns:
            Dictionary containing both structured facts with scores and the full reasoning
        """
        default_output = {
            "facts_with_scores": [
                {
                    "fact": atomic_facts[0] if atomic_facts else {"fact": "Default fact", "context": "", "verbose_context": ""},
                    "certainty_score": 50
                }
            ],
            "full_reasoning": "No reasoning available"
        }
        
        # Extract character profile
        character_profile = character_sheet
        
        system_prompt_per = """
            You are tasked to embody the following persona. Answer from their perspective. Do not answer as yourself. Do not state that you are playing a role. Just embody the persona and answer the questions as they would. Do avoid phrases such as 'as i am extroverted, i would do this'. Instead, answer as if you are the persona.
            
            **Persona Profile**:
            {character_profile}
        """
        
        user_prompt_per = """
            There was just a meeting and someone has provided you with a list of atomic facts from the meeting transcript. You need to analyze these atomic facts and select the most relevant ones for yourself.
            Like, what are the key takeaways if they would read it?

            **IMPORTANT: Your response must include TWO distinct parts:**
            1. First, a detailed explanation of your thinking process
            2. Then, a structured JSON list of facts with scores

            **Step 1: DETAILED REASONING PROCESS**
            Think out loud throughout your entire analysis. Provide a comprehensive explanation addressing each of the following questions:

            (1) What prior knowledge do you have?
            (2) Which project are you currently working on?
            (3) What are your primary interests and goals?
            (4) Read each fact carefully and think about which information is most relevant to you in your role. Explain why.
            (5) Is there an urgency or priority that aligns particularly closely with your current responsibilities or known concerns?
            (6) Which information might require simplification or additional context to ensure clear comprehension?
            (7) You've selected information that you consider important. Review this selection once more and provide concrete examples explaining why these details are relevant for you.
            (8) Now, go through the list a second time and identify which information you consider irrelevant or unimportant for your role/persona, providing reasons for your decisions.
            (9) Are there any topics you found difficult to classify or about which you felt unsure? If so, what are they?
            
            Describe all your thoughts, reflections, and decisions—even if they seem unimportant. There are no right or wrong answers; it is essential that you continuously share your thought process with me.

            **Step 2: STRUCTURED JSON OUTPUT**
            After completing your detailed reasoning, provide your final selection of facts in the following JSON format:
            
            [
                {
                    "fact": {
                        "fact": "The exact fact text",
                        "context": "The original context text",
                        "verbose_context": "The original verbose context text"
                    },
                    "certainty_score": 0-100 (higher means more certainty of relevance)
                },
                ...
            ]
            
            **CRITICAL: You MUST preserve the EXACT and COMPLETE original "fact", "context", and "verbose_context" fields from the input data.** Do not modify, summarize, or omit any of these three fields. Copy them exactly as they appear in the original atomic facts.
            
            Only include facts with a certainty score of 40 or higher. Sort by certainty score descending.
            
            **VERY IMPORTANT: Make sure your response includes BOTH parts:**
            1. Your complete, detailed reasoning process
            2. The JSON list of selected facts with scores, including ALL original fields
        """
        
        user_prompt_per += f"""
            ---\n
            **Atomic Facts**:
            {json.dumps(atomic_facts, indent=2)}
        """
        
        user_prompt = user_prompt_per
        system_prompt = system_prompt_per
        
        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "regeneration",    
                category="Reasoning Layer", 
                log_base_path="./atomic-facts/data_store/cost_time_logging/Qmsum",
                verbose=True, max_tokens=4000
            )
            
            # Store the full response (contains all the reasoning)
            full_reasoning = response
            
            # Extract just the JSON part from the response
            response_text = _clean_response(response)
            
            # Try to find JSON pattern in the response
            import re
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response_text, re.DOTALL)
            
            facts_with_scores = default_output["facts_with_scores"]
            
            if json_match:
                json_str = json_match.group(0)
                if self.verify_facts_reasoning_output(json_str):
                    facts_with_scores = json.loads(json_str)
                else:
                    logging.warning("Invalid facts reasoning output format")
            else:
                # If no JSON pattern found, try parsing the whole response
                if self.verify_facts_reasoning_output(response_text):
                    facts_with_scores = json.loads(response_text)
                else:
                    logging.warning("Could not extract valid JSON from reasoning layer response")
            
            # Return both the structured facts with scores and the complete reasoning
            return {
                "facts_with_scores": facts_with_scores,
                "full_reasoning": full_reasoning
            }
                
        except Exception as e:
            logging.error(f"Error in reasoning layer: {str(e)}")
            return default_output

    def filter_relevant_facts(self, atomic_facts: List[Dict], character_sheet: Dict, 
                            min_certainty: int = 40) -> Dict:
        """
        Apply reasoning layer and filter facts based on certainty threshold.
        Returns filtered facts with all fields preserved, original facts with scores, and the full reasoning.
        
        Args:
            atomic_facts: List of atomic facts
            character_sheet: Character profile
            min_certainty: Minimum certainty score to include (default: 40)
            
        Returns:
            Dictionary with filtered facts, original facts with scores, and reasoning
        """
        # Get both the facts with scores and the full reasoning
        result = self.apply_reasoning_layer(atomic_facts, character_sheet)
        reasoned_facts = result["facts_with_scores"]
        full_reasoning = result["full_reasoning"]
        
        # Filter by certainty score - ensure we preserve the complete fact objects
        filtered_facts = [
            item["fact"] for item in reasoned_facts 
            if item.get("certainty_score", 0) >= min_certainty
        ]

        logging.info(f'in reasoning layer = Filtered facts = {filtered_facts}, with length = {len(filtered_facts)}')
        
        # If no facts meet the threshold, include top 2 facts to ensure some content
        if not filtered_facts and reasoned_facts:
            sorted_facts = sorted(reasoned_facts, key=lambda x: x.get("certainty_score", 0), reverse=True)
            filtered_facts = [item["fact"] for item in sorted_facts[:2]]
        
        # Validate that filtered facts contain all required fields
        validated_facts = []
        for fact in filtered_facts:
            # Check if all required fields are present
            if isinstance(fact, dict) and "fact" in fact and "context" in fact and "verbose_context" in fact:
                validated_facts.append(fact)
            else:
                logging.warning(f"Filtered fact missing required fields: {fact}")
                # If the fact is missing fields, try to find the original in atomic_facts
                # This is a fallback in case the LLM didn't preserve the structure correctly
                fact_text = fact.get("fact", "") if isinstance(fact, dict) else str(fact)
                for original_fact in atomic_facts:
                    if original_fact.get("fact", "") == fact_text:
                        validated_facts.append(original_fact)
                        logging.info(f"Recovered original fact structure from atomic_facts")
                        break
        
        
        logging.info(f'in reasoning layer = Validated facts = {validated_facts}, with length = {len(validated_facts)}')

        # Return all components in a single JSON-friendly structure
        return {
            "filtered_facts": validated_facts,  # Now contains validated facts with all fields
            "facts_with_scores": reasoned_facts,
            "full_reasoning": full_reasoning
        }