from model_handler import ModelHandler
import json
import ast
import logging
from hallucination_validator import HallucinationValidator
from utils import _clean_response

def track_regeneration_step(
    regeneration_logs,
    chunk_text,
    original_facts,
    original_validation,
    regenerated_facts=None,
    regenerated_validation=None
):
    """
    Store/log the before/after results for external analysis. 
    
    Args:
        regeneration_logs (list): Reference to a list storing all regeneration events.
        chunk_text (str): The exact transcript chunk being processed.
        original_facts (list): The atomic facts generated initially.
        original_validation (dict): The hallucination validation result for original_facts.
        regenerated_facts (list): The atomic facts after regeneration (if any).
        regenerated_validation (dict): The validation result for regenerated_facts (if any).
    """
    data_to_log = {
        "chunk_text": chunk_text,
        "original_facts": original_facts,
        "original_overall_score": original_validation.get('overall_score', None),
        "original_feedback": original_validation.get('feedback', None),
        "regenerated_facts": regenerated_facts,
        "regenerated_overall_score": (
            regenerated_validation.get('overall_score', None) if regenerated_validation else None
        ),
        "regenerated_feedback": (
            regenerated_validation.get('feedback', None) if regenerated_validation else None
        )
    }
    # Append to the in-memory log; you can later dump it to a file or DB as needed.
    regeneration_logs.append(data_to_log)


class AtomicFacts:
    def __init__(self, client, model,log_base_path):
        self.client = client
        self.model = model
        self.log_base_path=log_base_path
        self.previous_chunk = None
        self.validator = HallucinationValidator(client, model,log_base_path)
        self.MAX_REGENERATION_ATTEMPTS = 3
        self.HALLUCINATION_THRESHOLD = 30

         # A list to store before/after details for regenerations.
        self.regeneration_logs = []

    def verify_atomic_facts_format(self, output: str) -> bool:
        """
        Verify if the atomic facts output is complete and properly formatted.
        Returns True if output is valid, False otherwise.
        """
        try:
            # Try parsing the output as JSON first
            try:
                facts = json.loads(output)
            except json.JSONDecodeError:
                try:
                    facts = ast.literal_eval(output)
                except (ValueError, SyntaxError):
                    logging.error("Failed to parse atomic facts output")
                    return False
            
            # Ensure it's a list
            if not isinstance(facts, list):
                logging.error("Atomic facts output is not a list")
                return False
            
            # Required fields for each fact
            required_fields = {'fact', 'context', 'verbose_context'}
            
            # Check each fact
            for fact in facts:
                # Check if it's a dictionary with all required fields
                if not isinstance(fact, dict):
                    logging.error(f"Fact is not a dictionary: {fact}")
                    return False
                
                if not all(field in fact for field in required_fields):
                    logging.error(f"Missing required fields in fact: {fact}")
                    return False
                
                # Check if fields are non-empty strings
                if not all(isinstance(fact[field], str) and fact[field].strip() 
                          for field in required_fields):
                    logging.error(f"Invalid field values in fact: {fact}")
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error verifying atomic facts: {str(e)}")
            return False


    def regenerate_atomic_facts(self, chunk, previous_chunk_context,feedback):
        """
        Regenerate atomic facts while addressing validation feedback.
        Uses same rigorous validation as initial extraction plus feedback handling.
        Returns new atomic facts.
        """
        system_prompt = """
        You are an expert at breaking down meeting transcripts into atomic facts.
        Your task is to regenerate facts while fixing specific issues.

        IMPORTANT RULES:
        1. Output must be a valid JSON list of objects
        2. NEVER add information not in the transcript
        3. Skip unclear or ambiguous content
        4. Each fact must be atomic (single piece of information)
        5. NO hallucination or inference
        6. ONLY include information explicitly stated
        7. Address ALL provided feedback points
        8. Must fix previously identified issues

        CONTENT GUIDELINES - STRICTLY FOLLOW:
        1. INCLUDE only:
           - Clear, explicit statements
           - Complete, meaningful information
           - Actionable items or decisions
           - Important discussion points
           - Concrete facts or outcomes

        2. EXCLUDE completely:
           - Filler statements (e.g., "OK", "Right", "Mm-hmm")
           - General acknowledgments
           - Incomplete or unclear statements
           - Transcription artifacts
           - Side conversations
           - Redundant information
           - Ambiguous statements
           - Previously flagged hallucinations

        3. For each fact, provide:
           - "fact": Single, atomic piece of information
           - "context": Current chunk's context
           - "verbose_context": Historical context
           ALL must be explicitly supported by source text

        Output Format:
        Must return a JSON list of objects, each with exactly these fields:
        [
            {
                "fact": "Clear atomic statement",
                "context": "Immediate context and implications",
                "verbose_context": "Comprehensive context with history"
            }
        ]
        """

        user_prompt = f"""
        REGENERATE ATOMIC FACTS FOR THIS TEXT:

        {previous_chunk_context}


        SOURCE TEXT:
        {chunk}


        PREVIOUS FEEDBACK TO ADDRESS:
        {feedback}

        REQUIREMENTS:
        1. Fix ALL issues mentioned in feedback
        2. Follow ALL rules from original extraction:
           - Only explicit information from source
           - Break into atomic facts
           - Provide accurate context
           - No inferences or assumptions
           - Skip unclear content
           - Proper JSON format
           - Include all required fields

        3. Additional regeneration requirements:
           - Address each feedback point specifically
           - Remove any previously identified hallucinations
           - Double-check context accuracy
           - Ensure no new issues are introduced
           - Maintain completeness while fixing issues

        4. Verification steps for each fact:
           - Is it explicitly stated in source?
           - Is context accurate and supported?
           - Are all elements verifiable?
           - Have previous issues been fixed?
           - Is it properly atomic?

        Generate complete, corrected set of atomic facts."""

        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "regeneration",    
                category="Fact Regenration", 
                 log_base_path=self.log_base_path,
                verbose=True, max_tokens=4000
            )

            enriched_template = _clean_response(response)
            if self.verify_atomic_facts_format(enriched_template):
                try:
                    return json.loads(enriched_template)
                except json.JSONDecodeError:
                    return ast.literal_eval(enriched_template)
            return None

        except Exception as e:
            logging.error(f"Error regenerating atomic facts: {str(e)}")
            return None

    def Break_into_atomic_facts(self, chunk,log_base_path):
        """
        Break chunk into atomic facts with context.
        Returns a list of dictionaries, each containing fact, context, and verbose_context.
        """
        default_template = [{
            "fact": "Default fact due to parsing error",
            "context": "Error occurred during processing",
            "verbose_context": "Unable to process chunk properly"
        }]

        system_prompt = """
        You are an expert at breaking down meeting transcripts into atomic facts. Your task is to extract clear, factual statements with proper context.

        IMPORTANT RULES:
        1. Output must be a valid JSON list of objects
        2. NEVER add information not in the transcript
        3. Skip unclear or ambiguous content
        4. Each fact must be atomic (single piece of information)
        5. NO hallucination or inference

        CONTENT GUIDELINES - STRICTLY FOLLOW:
        1. INCLUDE only:
           - Clear, explicit statements
           - Complete, meaningful information
           - Actionable items or decisions
           - Important discussion points
           - Concrete facts or outcomes

        2. EXCLUDE completely:
           - Filler statements (e.g., "OK", "Right", "Mm-hmm")
           - General acknowledgments
           - Incomplete or unclear statements
           - Transcription artifacts like {"disfmarker"} or {"vocalsound"}
           - Side conversations
           - Redundant information
           - Ambiguous statements

        3. For each included fact, provide:
           - "fact": Single, atomic piece of information
           - "context": Current chunk's context
           - "verbose_context": Historical context

        Output Format:
        Must return a JSON list of objects, each with exactly these fields:
        [
            {
                "fact": "Clear atomic statement",
                "context": "Immediate context and implications",
                "verbose_context": "Comprehensive context with history"
            },
            ...
        ]

        Example valid output:
        [
            {
                "fact": "Team agreed to launch product in Q3",
                "context": "Discussion about timeline constraints and market conditions",
                "verbose_context": "Following previous delays and market analysis, Q3 was chosen for optimal impact"
            }
        ]

        Invalid examples to avoid:
        - Facts containing filler words: {"fact": "OK, we'll do that"}
        - Unclear statements: {"fact": "Maybe we should..."}
        - Transcription artifacts: {"fact": "Speaker1 {disfmarker}"}
        - Compound facts: {"fact": "Team discussed timeline and budget and resources"}
        """
        
        previous_chunk_context = ""
        if self.previous_chunk:
            previous_chunk_context = f"\nPrevious chunk for context:\n{self.previous_chunk}\n"

        user_prompt = f"""
        Break down this transcript chunk into atomic facts with context.
        Remember:
        - Must return a valid JSON list
        - Each fact needs all three fields
        - Only include clear, explicit information
        - Skip all filler words, acknowledgments, and artifacts
        - Break compound statements into atomic facts
        - Exclude unclear or ambiguous content

        {previous_chunk_context}
        Current chunk:
        {chunk}

        Provide output as a JSON list where each object has "fact", "context", and "verbose_context".
        """
        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "regeneration",    
                category="Fact Extraction", 
                log_base_path=self.log_base_path,
                verbose=True, max_tokens=4000
            )

            logging.info(f'Output = {response}')

            enriched_template = _clean_response(response)
            
            logging.info(f'Output = {enriched_template}')
            
            # Verify format
            is_valid = self.verify_atomic_facts_format(enriched_template)
            
            if is_valid:
                try:
                    atomic_facts = json.loads(enriched_template)
                except json.JSONDecodeError:
                    atomic_facts = ast.literal_eval(enriched_template)
                
                # Check for hallucinations
                validation_result = self.validator.validate_atomic_facts(atomic_facts,previous_chunk_context, chunk)
                logging.info(f"Validation_results = {json.dumps(validation_result)}")

                # If hallucination score is too high, attempt regeneration
                attempt_count = 1
                current_facts = atomic_facts
                
                while (validation_result['overall_score'] > self.HALLUCINATION_THRESHOLD 
                       and attempt_count < self.MAX_REGENERATION_ATTEMPTS):
                    
                    logging.info(f"Hallucination score too high ({validation_result['overall_score']}), attempting regeneration")
                    
                    # Log the original facts + validation before first regeneration
                    if attempt_count == 1:
                        track_regeneration_step(
                            self.regeneration_logs,
                            chunk,
                            current_facts,
                            validation_result
                        )
                    
                    regenerated_facts = self.regenerate_atomic_facts(chunk, previous_chunk_context,validation_result['feedback'])
                    


                    if regenerated_facts and self.verify_atomic_facts_format(json.dumps(regenerated_facts)):
                        new_validation = self.validator.validate_atomic_facts(regenerated_facts,previous_chunk_context, chunk)

                        
                        # Now log the original + regenerated with new validation
                        track_regeneration_step(
                            self.regeneration_logs,
                            chunk,
                            current_facts,
                            validation_result,
                            regenerated_facts,
                            new_validation
                        )    
                        # Keep better version
                        if new_validation['overall_score'] < validation_result['overall_score']:
                            current_facts = regenerated_facts
                            validation_result = new_validation
                    
                    attempt_count += 1
                
                # Return facts if final hallucination score is acceptable
                if validation_result['overall_score'] <= self.HALLUCINATION_THRESHOLD:
                    return current_facts, True
                else:
                    logging.warning("High hallucination score even after regeneration attempts")
                    return default_template, False
                    
            else:
                logging.warning("Invalid atomic facts format, using default template")
                return default_template, False
                
        except Exception as e:
            logging.error(f"Error in Break_into_atomic_facts: {str(e)}")
            return default_template, False