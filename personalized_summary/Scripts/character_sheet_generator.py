import json
import logging
from typing import Dict, Any
from model_handler import ModelHandler
from utils import _clean_response

class CharacterSheetGenerator:
    def __init__(self, client, model):
        self.client = client
        self.model = model

    def verify_character_sheet(self, sheet_output: str) -> bool:
        """Verify if the character sheet output is complete and properly formatted."""
        try:
            parsed_sheet = json.loads(sheet_output)
            required_sections = {
                'personal_profile',
                'lifestyle_context',
                'project_interests',
                'information_needs',
                'decision_factors'
            }
            
            if not all(section in parsed_sheet for section in required_sections):
                logging.error("Missing required sections in character sheet")
                return False
                
            return True
            
        except json.JSONDecodeError:
            logging.error("Failed to parse character sheet JSON")
            return False
        except Exception as e:
            logging.error(f"Error verifying character sheet: {str(e)}")
            return False

    def generate_character_sheet(self, persona_text: str) -> Dict[str, Any]:
        """Generate a comprehensive character sheet combining personal and project aspects."""
        default_sheet = {
            "personal_profile": {
                "identity": "Not specified",
                "background": "Not specified"
            }
        }

        system_prompt = """
        You are an expert at creating comprehensive character analyses that combine personal understanding with project-specific needs. Create a detailed character sheet that captures both who they are and how they approach information/decisions.

        OUTPUT FORMAT: Valid JSON with these sections:

        1. personal_profile (Who They Are)
           - Demographics and identity
           - Professional background
           - Education and expertise
           - Family situation
           - Economic status
           - Personal values
           - Key life experiences that shape their perspective

        2. lifestyle_context (Their World)
           - Daily routines and patterns
           - Living situation
           - Work environment
           - Social context
           - Time constraints
           - Resources available
           - Major pain points
           - Regular challenges

        3. project_interests (What They Care About)
           - Primary goals and objectives
           - Specific areas of interest
           - Key priorities in decision-making
           - Must-have features/aspects
           - Deal-breakers
           - Value proposition priorities
           - Quality/performance expectations
           - Budget considerations
           Explain WHY each interest matters to them

        4. information_needs (How They Learn)
           - Preferred information formats
           - Detail level requirements
           - Technical knowledge level
           - Context requirements
           - Learning style preferences
           - Trust signals they look for
           - Documentation needs
           - RANK each aspect 1-5 and explain reasoning

        5. decision_factors (How They Choose)
           - Decision-making process
           - Influence factors
           - Risk tolerance
           - Time sensitivity
           - Budget sensitivity
           - Quality vs. cost balance
           - Brand/prestige importance
           - Environmental considerations
           RANK each factor 1-5 with explanation

        CRUCIAL REQUIREMENTS:
        1. Cover both WHO they are and WHAT they need
        2. Explain relationships between personal context and project interests
        3. Identify how their background influences their needs
        4. Include specific examples from the persona text
        5. Mark unknown aspects as "Not specified"
        6. For rankings/priorities, always explain WHY
        """

        user_prompt = f"""
        Create a comprehensive character analysis using this persona text:

        {persona_text}

        Your analysis should:
        1. Describe who they are as a person
        2. Explain their lifestyle and context
        3. Detail their project-specific interests
        4. Analyze their information needs
        5. Break down their decision factors

        Remember to:
        - Include both personal and project-focused aspects
        - Explain connections between background and needs
        - Use specific examples from the text
        - Include rankings with explanations
        - Keep all analysis within the provided JSON structure

        Return as valid JSON matching the specified format.
        """
        
        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "regeneration",    
                category="Character sheet genration", 
                log_base_path="./atomic-facts/data_store/cost_time_logging/Qmsum",
                verbose=True, max_tokens=4000
            )
            
            cleaned_response = _clean_response(response)
            is_valid = self.verify_character_sheet(cleaned_response)
            
            if is_valid:
                return json.loads(cleaned_response)
            else:
                logging.warning("Invalid character sheet format, using default")
                return default_sheet
                
        except Exception as e:
            logging.error(f"Error generating character sheet: {str(e)}")
            return default_sheet

    def extract_priorities(self, character_sheet: Dict[str, Any]) -> Dict[str, float]:
        """Extract and normalize priority weights from the character sheet."""
        try:
            # Combine decision factors and information needs rankings
            priorities = {}
            
            # Get decision factor rankings
            decision_factors = character_sheet.get('decision_factors', {})
            for key, value in decision_factors.items():
                if isinstance(value, dict) and 'ranking' in value:
                    priorities[f"decision_{key}"] = float(value['ranking'])
            
            # Get information needs rankings
            info_needs = character_sheet.get('information_needs', {})
            for key, value in info_needs.items():
                if isinstance(value, dict) and 'ranking' in value:
                    priorities[f"info_{key}"] = float(value['ranking'])
            
            # Normalize weights
            total = sum(priorities.values())
            if total > 0:
                return {k: v/total for k, v in priorities.items()}
            return priorities
            
        except Exception as e:
            logging.error(f"Error extracting priorities: {str(e)}")
            return {}

    def get_summary_guidelines(self, character_sheet: Dict[str, Any]) -> Dict[str, Any]:
        """Extract guidelines for personalized summary generation."""
        return {
            'priority_weights': self.extract_priorities(character_sheet),
            'personal_context': {
                'background': character_sheet.get('personal_profile', {}),
                'lifestyle': character_sheet.get('lifestyle_context', {})
            },
            'project_focus': character_sheet.get('project_interests', {}),
            'information_preferences': character_sheet.get('information_needs', {}),
            'decision_criteria': character_sheet.get('decision_factors', {})
        }

    # Example usage:
    def analyze_persona_complete(self,persona_text: str) -> Dict[str, Any]:
        """Generate complete persona analysis for personalized summarization."""        
        character_sheet = self.generate_character_sheet(persona_text)
        summary_guidelines = self.get_summary_guidelines(character_sheet)
        
        return {
            'character_sheet': character_sheet,
            # 'summary_guidelines': ""
        }



