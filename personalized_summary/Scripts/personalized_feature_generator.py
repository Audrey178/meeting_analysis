from typing import List, Dict, Tuple
import json
import ast
import logging
from model_handler import ModelHandler
from utils import _clean_response

class PersonalizedFeatureGenerator:
    def __init__(self, client, model):
        self.client = client
        self.model = model

    def verify_feature_completeness(self, features_output: str) -> bool:
        """Verify if the model output is complete and properly formatted."""
        try:
            try:
                features = json.loads(features_output)
            except json.JSONDecodeError:
                try:
                    features = ast.literal_eval(features_output)
                except (ValueError, SyntaxError):
                    logging.error("Failed to parse features output")
                    return False
            
            if not isinstance(features, list):
                logging.error("Features output is not a list")
                return False
                
            required_fields = {
                'feature',
                'reasoning',
                'importance_score',
                'persona_alignment_score',
                'feature_type',
                'certainty_score',
                'alignment_explanation'
            }
            
            for feature in features:
                if not all(field in feature for field in required_fields):
                    logging.error(f"Missing required fields in feature: {feature}")
                    return False
                    
                if not isinstance(feature['feature'], str) or not feature['feature'].strip():
                    return False
                    
                if not isinstance(feature['reasoning'], str) or not feature['reasoning'].strip():
                    return False
                    
                if not isinstance(feature['importance_score'], (int, float)) or \
                   not (1 <= feature['importance_score'] <= 10):
                    return False
                    
                if not isinstance(feature['persona_alignment_score'], (int, float)) or \
                   not (1 <= feature['persona_alignment_score'] <= 10):
                    return False
                    
                if not isinstance(feature['feature_type'], str) or \
                   feature['feature_type'] not in {'DECISION', 'ACTION', 'INSIGHT', 'CONTEXT'}:
                    return False
                    
                if not isinstance(feature['certainty_score'], (int, float)) or \
                   not (0 <= feature['certainty_score'] <= 100):
                    return False
                    
                if not isinstance(feature['alignment_explanation'], str) or not feature['alignment_explanation'].strip():
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error verifying features: {str(e)}")
            return False

    def identify_salient_features(self, atomic_facts: List[Dict], character_sheet: Dict) -> Tuple[List[Dict], bool]:
        """
        Extract and rank salient features considering persona preferences.
        Returns tuple of (features, is_complete)
        """
        default_template = [{
            "feature": "Default feature",
            "reasoning": "Fallback reasoning due to parsing error",
            "importance_score": 5,
            "persona_alignment_score": 5,
            "feature_type": "CONTEXT",
            "certainty_score": 50,
            "alignment_explanation": "Default alignment explanation"
        }]

        system_prompt = """
        You are an expert at identifying and ranking important features from meeting transcripts while 
        considering specific persona preferences. Your goal is to extract and prioritize information 
        that would be most relevant and valuable to the given persona, ESPECIALLY focusing on what 
        OTHERS said that the persona needs to know or act upon.

        CRITICAL PERSPECTIVE SHIFT:
        - Prioritize information spoken by OTHERS that is relevant to the persona
        - De-prioritize information spoken by the persona themselves (they already know this)
        - Think of this as "what would this persona want to know from the meeting?"
        - Focus on insights, actions, requests, and decisions from others that affect their role

        Instructions:
        1. Analyze atomic facts AND persona preferences carefully
        2. For each identified feature, evaluate:
        a. General Importance (1-10):
            - Critical decisions/outcomes affecting the persona (8-10)
            - Important discussions relevant to persona's role (6-7)
            - Supporting details needed by the persona (3-5)
            - Background info useful to the persona (1-2)
        
        b. Persona Alignment (1-10):
            - How well it matches persona's:
                * Project interests
                * Decision factors
                * Information needs
                * Professional background
                * Personal priorities
                * Knowledge gaps (what they DON'T already know)
        
        c. Feature Type:
            DECISION: Final choices/agreements affecting the persona
            ACTION: Tasks/assignments for the persona or relevant to their work
            INSIGHT: Key realizations from others that impact the persona
            CONTEXT: Background info needed by the persona

        d. Certainty Score (0-100%):
            Your confidence in the assessment

        3. Provide detailed reasoning:
        - Why is this feature important to this persona?
        - How does information from OTHERS align with persona's needs?
        - What context makes it actionable for the persona?

        Output Format (JSON list):
        {
            "feature": "Extracted feature text",
            "reasoning": "Why this is important to the persona",
            "importance_score": 1-10,
            "persona_alignment_score": 1-10,
            "feature_type": "DECISION/ACTION/INSIGHT/CONTEXT",
            "certainty_score": 0-100,
            "alignment_explanation": "How/why this aligns with persona's information needs"
        }

        CRITICAL RULES:
        - Use ONLY facts from provided atomic facts
        - Base alignment strictly on provided persona preferences
        - PRIORITIZE information from others that the persona needs to know
        - DE-PRIORITIZE information the persona themselves shared (they already know this)
        - NO hallucination or inference beyond provided data
        - Explain ALL scoring decisions
        - Order by combined importance and alignment scores
        """

        user_prompt = f"""
        Please analyze these atomic facts considering the persona preferences:

        Character Sheet (Persona Preferences):
        {character_sheet}

        Atomic Facts:
        {atomic_facts}

        For each identified feature, provide:
        1. Feature text and reasoning
        2. General importance score (1-10)
        3. Persona alignment score (1-10)
        4. Feature type and certainty
        5. Detailed alignment explanation

        Remember:
        - FOCUS on what OTHERS said that is relevant to this persona
        - DE-EMPHASIZE what the persona themselves said (they already know this)
        - Consider ALL aspects of persona preferences
        - Justify alignment scores with specific preferences
        - Focus on what matters most to THIS persona
        - Provide clear reasoning for all scores
        """

        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "regeneration",    
                category="salient_feature_generation", 
                 log_base_path="./atomic-facts/data_store/cost_time_logging/",
                verbose=True, max_tokens=4000
            )            
            enriched_template = _clean_response(response)
            is_complete = self.verify_feature_completeness(enriched_template)
            
            if is_complete:
                try:
                    features = json.loads(enriched_template)
                except json.JSONDecodeError:
                    features = ast.literal_eval(enriched_template)
                    
                # Calculate combined scores and sort
                for feature in features:
                    feature['combined_score'] = (
                        0.4 * feature['importance_score'] + 
                        0.6 * feature['persona_alignment_score']
                    )
                
                features.sort(key=lambda x: x['combined_score'], reverse=True)
                return features, True
            else:
                logging.warning("Incomplete or invalid features output")
                return default_template, False
                
        except Exception as e:
            logging.error(f"Unexpected error in identify_salient_features: {str(e)}")
            return default_template, False

    def generate_outline(self, important_features: List[Dict]) -> List[str]:
        """Generate an outline from consolidated important features focusing on what others said."""
        system_prompt = """
        Create a personalized outline based on ranked features that considers both 
        importance and persona alignment scores, with a specific focus on what OTHERS
        said that is relevant to the persona.

        CRITICAL PERSPECTIVE SHIFT:
        - Focus on information FROM OTHERS that the persona needs to know
        - De-emphasize information provided by the persona themselves
        - Structure the outline as "notes the persona would take for themselves"
        - Highlight insights, actions, decisions from others that affect the persona

        Structure sections by:
        1. Critical Information for the Persona (combined score 8-10)
        - Key decisions by others that affect the persona
        - Actions required of the persona based on others' input
        - Important insights from others relevant to the persona's role

        2. Important Considerations (combined score 6-7)
        - Relevant discussions initiated by others
        - Context needed to understand key decisions
        - Information that supports the persona's responsibilities

        3. Supporting Information (combined score 4-5)
        - Background details that enhance understanding
        - Additional context that matches persona's information needs
        - Clarifying points relevant to their interests

        4. Additional Context (combined score 1-3)
        - Only if needed to understand higher-priority items
        - Skip if not aligned with persona's information needs

        Guidelines:
        - Prioritize features with high persona alignment
        - Focus on information the persona would WANT TO KNOW from others
        - Group related items by persona interests
        - Match persona's detail level preferences
        """

        user_prompt = f"""
        Create an outline using these persona-aligned features:
        {important_features}

        Consider:
        - Combined importance/alignment scores
        - Feature types and certainty scores
        - Alignment explanations
        - Related groupings based on persona preferences
        - FOCUS on information FROM OTHERS that the persona needs to know
        - DE-EMPHASIZE information the persona themselves provided

        Generate a clear, hierarchical outline focused on what the persona needs to learn from others.
        """
        
        message = ModelHandler.build_message(system_prompt, user_prompt)
        response = ModelHandler.call_model_with_retry(            
                self.client, message, self.model, "regeneration",    
                category="outline_generation", 
                 log_base_path="./atomic-facts/data_store/cost_time_logging/",
                verbose=True, max_tokens=4000)
        return response.split('\n')