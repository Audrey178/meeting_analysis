from typing import List, Dict
from model_handler import ModelHandler
from utils import _clean_response
import ast
import json
import logging

class FeatureGenerator:
    def __init__(self, client, model,log_base_path):
        self.client = client
        self.model = model
        self.log_base_path = log_base_path

    def verify_feature_completeness(self, features_output: str) -> bool:
        """
        Verify if the model output is complete and properly formatted.
        Returns True if output is complete, False if truncated or malformed.
        """
        logging.info(f"Features = {features_output}")
        try:
            # Try parsing the output as JSON first
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
                
            # Required fields for each feature
            required_fields = {
                'feature',
                'reasoning',
                'importance_score',
                'feature_type',
                'certainty_score'
            }
            
            # Check each feature has all required fields with valid values
            for feature in features:
                # Check all required fields exist
                if not all(field in feature for field in required_fields):
                    logging.error(f"Missing required fields in feature: {feature}")
                    return False
                
                # Check field types and values
                if not isinstance(feature['feature'], str) or not feature['feature'].strip():
                    return False
                    
                if not isinstance(feature['reasoning'], str) or not feature['reasoning'].strip():
                    return False
                    
                if not isinstance(feature['importance_score'], (int, float)) or \
                   not (1 <= feature['importance_score'] <= 10):
                    return False
                    
                if not isinstance(feature['feature_type'], str) or \
                   feature['feature_type'] not in {'DECISION', 'ACTION', 'INSIGHT', 'CONTEXT'}:
                    return False
                    
                if not isinstance(feature['certainty_score'], (int, float)) or \
                   not (0 <= feature['certainty_score'] <= 100):
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error verifying features: {str(e)}")
            return False

    def identify_salient_features(self, atomic_facts: List[Dict[str, str]]):
        """
        Extract and rank salient features from atomic facts.
        Returns tuple of (features, is_complete)
        """
        default_template = [{
            "feature": "Default feature",
            "reasoning": "Fallback reasoning due to parsing error",
            "importance_score": 5,
            "feature_type": "CONTEXT",
            "certainty_score": 50
        }]

        system_prompt = """
        You are an AI tasked with identifying and ranking the most salient features from meeting transcript atomic facts. Your goal is to extract and prioritize key information based on their importance for the final summary.

        Instructions:
        1. Analyze the provided atomic facts carefully
        2. For each identified feature, first reason about its importance by considering:
           - Is this a critical decision point or major outcome?
           - Does it represent an action item or task assignment?
           - Is it a key insight or discussion point?
           - How does it contribute to the overall context?
           - What impact does this have on the meeting's objectives?
        3. Based on your reasoning, then:
           a. Assign an importance score (1-10) where:
              - 10: Critical decisions, major outcomes, key action items
              - 7-9: Important discussions, significant insights
              - 4-6: Supporting information, context
              - 1-3: Background details
           b. Identify the feature type:
              - DECISION: Final choices or agreements
              - ACTION: Tasks, assignments, or next steps
              - INSIGHT: Important realizations or findings
              - CONTEXT: Background or supporting information
        4. Provide a certainty score (0-100%) indicating how confident you are in your assessment

        *Do not hallucinate about any information, use context provided in form of atomic facts*
        *If possible show the highly important features first and then somehow lesser and then least to maintain order*
        
        IMPORTANT: Your response must be a valid JSON object for each feature. Each object must have exactly these fields:
        - "feature": (string) The identified feature text
        - "reasoning": (string) Detailed explanation of importance considering context of that feature, do not hallucinate
        - "importance_score": (number) Score from 1-10
        - "feature_type": (string) One of: DECISION, ACTION, INSIGHT, CONTEXT
        - "certainty_score": (number) Score from 0-100
        """

        user_prompt = f"""
        Please analyze these atomic facts and provide ranked features in strictly valid JSON format:

        {atomic_facts}

        Remember: Response must be a valid list of json objects with exactly these fields:
        - "feature" (string)
        - "reasoning" (string)
        - "importance_score" (number 1-10)
        - "feature_type" (string: DECISION/ACTION/INSIGHT/CONTEXT)
        - "certainty_score" (number 0-100)
        """

        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "Salient Feature generation",    
                category="Salient Feature generation", 
                log_base_path=self.log_base_path
            )             
            # Clean up the response
            enriched_template = _clean_response(response)
            
            # Verify completeness
            is_complete = self.verify_feature_completeness(enriched_template)
            
            if is_complete:
                # Parse the complete output
                try:
                    features = json.loads(enriched_template)
                except json.JSONDecodeError:
                    features = ast.literal_eval(enriched_template)
                return features, True
            else:
                logging.warning("Incomplete or invalid features output")
                return default_template, False
                
        except Exception as e:
            logging.error(f"Unexpected error in identify_salient_features: {str(e)}")
            return default_template, False

    def generate_outline(self, important_features: List[Dict]) -> List[str]:
        """Generate an outline from consolidated important features from memory bank."""
        
    def generate_outline(self, important_features: List[Dict]) -> List[str]:
        """
        Generate a clear, section-based outline from important features.
        Returns a list of outline strings.
        """
        system_prompt = """
        Create an outline that will guide the creation of the final meeting summary.

        The meeting features are marked with:
        1. DECISION (score 8-10): Key decisions and agreements made
        2. HIGH_PRIORITY (score 8-10): Critical discussion points
        3. MEDIUM_PRIORITY (score 6-7): Important supporting points
        4. CONTEXT: Background information

        Structure:
        1. Meeting Overview (2-3 lines)
        - Main topic and key outcomes
        - Critical decisions

        2. Key Decisions
        - List each decision with who made it
        - Why the decision was made
        - Impact of decision

        3. Main Discussion Points
        - Major topics covered
        - Important insights
        - Agreements reached

        4. Next Steps
        - Action items
        - Follow-up tasks
        - Assigned responsibilities

        This outline will be used to generate a coherent summary that captures:
        - The flow of the meeting
        - Key outcomes and decisions
        - Important context and reasoning
        - Next actions and responsibilities
        """

        user_prompt = f"""
        Create an outline for summary generation using these features:

        {important_features}

        Focus on organizing information to tell a clear story of what happened in the meeting.
        """
        
        message = ModelHandler.build_message(system_prompt, user_prompt)
        response = ModelHandler.call_model_with_retry(
            self.client, message, self.model, "Outline Generation",    
            category="Outline Generation", 
            log_base_path=self.log_base_path
            )        
        return response.split('\n')