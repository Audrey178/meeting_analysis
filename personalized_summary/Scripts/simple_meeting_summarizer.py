import logging
import os
import json
import hashlib
import pandas as pd
from typing import Dict, List, Tuple, Any
from utils import _clean_response
from model_handler import ModelHandler
from chunk_processor import ChunkProcessor
from persona_extractor import PersonaExtractor
from character_sheet_generator import CharacterSheetGenerator


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SimpleMeetingSummarizer:
    """
    A simpler meeting summarizer that uses a single LLM call to generate
    personalized summaries based on a transcript and character sheet.
    This serves as a baseline for comparison against the more sophisticated
    PersonalizedMeetingSummarizer.
    """
    
    def __init__(self, client, model="gpt-4o"):
        self.client = client
        self.model = model
        self.chunk_processor = ChunkProcessor()
        self.persona_extractor = PersonaExtractor(client,model)
        self.character_sheet_generator = CharacterSheetGenerator(client, model)

        
    def generate_meeting_id(self, transcript: str) -> str:
        """Generate a unique meeting ID based on transcript content."""
        return hashlib.md5(transcript.encode()).hexdigest()
    
    def get_or_create_character_sheet(self, persona_text: str, json_path: str) -> Dict:
        """
        Get character sheet from JSON file or create and save if it doesn't exist.
        
        Args:
            persona_text: Text describing the persona
            json_path: Path to store/retrieve the character sheet JSON
            
        Returns:
            Dict containing the character sheet
        """
        try:
            # Check if JSON file exists
            if os.path.exists(json_path):
                logging.info(f"Loading existing character sheet from {json_path}")
                with open(json_path, 'r') as f:
                    return json.load(f)
            
            # Generate new character sheet if file doesn't exist
            logging.info(f"Generating new character sheet and saving to {json_path}")
            character_sheet = self.character_sheet_generator.generate_character_sheet(persona_text)
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(json_path), exist_ok=True)
            
            # Save to JSON file
            with open(json_path, 'w') as f:
                json.dump(character_sheet, f, indent=4)
            
            return character_sheet
            
        except Exception as e:
            logging.error(f"Error handling character sheet: {str(e)}")
            raise
            
    def generate_summary(self, transcript: str, character_sheet: Dict) -> str:
        """
        Generate a meeting summary personalized for the given character sheet in a single LLM call.
        
        Args:
            transcript: Meeting transcript text
            character_sheet: Character profile for personalization
            
        Returns:
            Personalized meeting summary
        """
        # Create system prompt with character details to guide personalization
        system_prompt = """
        You are an expert summarization agent tasked with creating a highly personalized meeting summary.
        Your goal is to create a summary from the PERSPECTIVE OF THE PERSONA, focusing on what OTHERS said 
        that would be relevant and important for this specific persona.

        CRITICAL PERSPECTIVE SHIFT:
        - The summary is NOT about what the persona said or did
        - Instead, focus on what OTHERS said that the persona needs to know or act upon
        - Think of this as "meeting notes" the persona would write for themselves
        - The persona would NOT write down information they already know or presented themselves
        - They WOULD write down insights, actions, decisions, and requests from others that affect their role

        CRITICAL CONSTRAINTS:
        - Summary MUST be between 150-200 words
        - Use ONLY provided facts from the transcript
        - NO hallucination or inference
        - Focus on information most relevant to the persona FROM OTHERS
        - Present as cohesive paragraphs
        - DO NOT use bullet points, numbered lists, or section headers in your summary

        OUTPUT FORMAT:
        - The summary must be in paragraph format only
        - Use well-structured paragraphs that flow naturally
        - No headers, bullet points, or other structural elements
        - Present as a cohesive narrative that covers key points

        PERSONA CONSIDERATIONS:
        1. Information Preferences:
        - Match their preferred detail level
        - Use their preferred information format
        - Focus on their key interests
        - Address their specific needs

        2. Decision Factors:
        - Emphasize aspects they value most
        - Consider their risk tolerance
        - Match their time sensitivity
        - Align with their priorities

        3. Context Requirements:
        - Provide context they need
        - Match their technical level
        - Include background they care about
        - Support their decision-making style

        Style and Format:
        - Present as cohesive paragraphs that flow naturally
        - Ensure logical transitions between paragraphs
        - Maintain narrative coherence throughout
        - Match their communication preferences
        - Use appropriate technical level
        - Provide detail level they prefer
        - Support their decision-making needs
        - Stay within word limit (**150-200** words)
        - Only use explicit information
        - Focus on what's new and actionable for the persona
        """
        
        # Format the character sheet for the prompt
        character_sheet_str = json.dumps(character_sheet, indent=2)
        
        # Create user prompt with character sheet and transcript
        user_prompt = f"""
        Generate a 150-200 (Strictly*) word personalized meeting summary for this persona:

        Character Sheet (Persona Preferences):
        {character_sheet_str}
        
        Meeting Transcript:
        {transcript}
        
        Remember:
        - Focus on what OTHERS said that is relevant to this persona (not what the persona said themselves)
        - Think of this as personal meeting notes the persona would write for themselves
        - Highlight insights, actions, decisions, and requests from others that affect their role
        - Match their preferred style and detail level
        - Stay within 150-200 words
        - Only use provided information
        - Format as cohesive paragraphs that flow naturally
        - DO NOT use bullet points, headers, or numbered lists
        - Present as a smooth narrative
        """
        
        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "Fact Verification",    
                category="Single LLM PersonalisedSummary Generation", 
                log_base_path="./atomic-facts/data_store/cost_time_logging/",
                verbose=True,
                max_tokens=4000
            )
            
            # Return the summarized response
            return response
            
        except Exception as e:
            logging.error(f"Error generating summary: {str(e)}")
            return f"Failed to generate summary: {str(e)}"

    
    def generate_summary_with_reasoning(
        self,
        transcript: str,
        character_sheet: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        Generate a meeting summary with an explicit reasoning layer, then personalized for the given character sheet.
        Returns a dict with two keys:
        - "Full_reasoning_response": the complete chain-of-thought / reasoning
        - "Summary": the 150–200 word personalized summary

        Args:
            transcript: Meeting transcript text
            character_sheet: Character profile for personalization

        Returns:
            Dict[str, str] containing the reasoning and the final summary.
        """
        default_output =    {
        "Full_reasoning_response": "<YOUR DETAILED CHAIN-OF-THOUGHT HERE like complete thinking process for examples answering questions etc..>",
        "Summary": "<YOUR FINAL 150–200 WORD PARAGRAPH SUMMARY HERE>"
        }
        # Build system prompt with JSON output instructions
        system_prompt = """
        You are an expert summarization agent tasked with creating a highly personalized meeting summary.
        Your goal is to create a summary from the PERSPECTIVE OF THE PERSONA, focusing on what OTHERS said 
        that would be relevant and important for this specific persona.

        PROCESS:
        1. First, you will conduct a detailed reasoning process to understand what information would be most relevant to the persona.
        2. Then, based on that reasoning, you will produce a final personalized summary.

        CRITICAL PERSPECTIVE SHIFT:
        - The summary is NOT about what the persona said or did.
        - Instead, focus on what OTHERS said that the persona needs to know or act upon.
        - Think of this as "meeting notes" the persona would write for themselves.
        - The persona would NOT write down information they already know or presented themselves.
        - They WOULD write down insights, actions, decisions, and requests from others that affect their role.

        CRITICAL CONSTRAINTS:
        - Final Summary MUST be between 150–200 words.
        - Use ONLY provided facts from the transcript.
        - NO hallucination or inference.
        - Focus on information most relevant to the persona FROM OTHERS.
        - Present as cohesive paragraphs.
        - DO NOT use bullet points, numbered lists, or section headers in your summary.
        """

        # Prepare the user prompt (including character sheet and transcript)
        character_sheet_str = json.dumps(character_sheet, indent=2)
        # Create user prompt with character sheet, reasoning protocol, and transcript
        user_prompt = f"""
        You will generate a 150-200 word personalized meeting summary for this persona:

        Character Sheet (Persona Preferences):
        {character_sheet_str}
        
        Meeting Transcript:
        {transcript}

        Follow this structured reasoning process first:

        REASONING LAYER:
        Step 1: DETAILED REASONING PROCESS

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

        After completing the reasoning process, provide your:

        Step 2 FINAL SUMMARY:
        A 150-200 word personalized meeting summary based on your reasoning that:
        - Focuses on what OTHERS said that is relevant to this persona (not what the persona said themselves)
        - Highlights insights, actions, decisions, and requests from others that affect their role
        - Matches their preferred style and detail level
        - Is formatted as cohesive paragraphs that flow naturally
        - Contains NO bullet points, headers, or numbered lists

        STRUCTURED JSON OUTPUT**(strict JSON):
        Your **only** output must be a JSON object with exactly two keys:
        {default_output}
        Make sure the JSON is valid (double-quotes only), with no extra keys or commentary.

        **VERY IMPORTANT: Make sure your response includes BOTH parts:**
            1. Your complete, detailed reasoning process
            2. output should be only json list with keys i have mentiond and for every output i want only two keys with json output.
        """

        try:
            # Build and send the message to the model
            message = ModelHandler.build_message(system_prompt, user_prompt)
            raw_response = ModelHandler.call_model_with_retry(
                self.client,
                message,
                self.model,
                "Fact Verification",
                category="Reasoning Layer PersonalisedSummary Generation",
                log_base_path="./atomic-facts/data_store/cost_time_logging/",
                verbose=True,
                max_tokens=4000
            )

            raw_response = _clean_response(raw_response)
            print(raw_response)

            # Attempt to parse the JSON output
            parsed = json.loads(raw_response)
            # Basic validation
            if not ("Full_reasoning_response" in parsed and "Summary" in parsed):
                raise ValueError("Missing required keys in model output JSON")

            return {
                "Full_reasoning_response": parsed["Full_reasoning_response"].strip(),
                "Summary": parsed["Summary"].strip()
            }

        except json.JSONDecodeError as e:
            logging.error(f"JSON parse error: {e}")
            return {
                "Full_reasoning_response": raw_response.strip(),
                "Summary": ""
            }
        except Exception as e:
            logging.error(f"Error generating summary with reasoning: {e}")
            return {
                "Full_reasoning_response": "",
                "Summary": f"Failed to generate summary: {e}"
            }

    def generate_summary_simple_prompt(self, transcript: str, character_sheet: Dict) -> str:
        """
        Generate a meeting summary using a simpler prompt format focused on a specific reader.
        This variation uses a more straightforward prompt structure.
        
        Args:
            transcript: Meeting transcript text
            character_sheet: Character profile for personalization
            
        Returns:
            Personalized meeting summary
        """
        # Create system prompt with simple instructions
        system_prompt = """
        You are an expert summarization agent. Your task is to summarize a meeting transcript
        for a specific reader, focusing on what would be most relevant and important to them.
        """
        
        # Format the character sheet for the prompt
        character_sheet_str = json.dumps(character_sheet, indent=2)
        
        # Create user prompt with character sheet and transcript
        user_prompt = f"""
        You are tasked to summarize the following meeting for a specific reader.

        Reader details:
        {character_sheet_str}
        
        Meeting Transcript:
        {transcript}
        
        Instructions:
        - Summarize the meeting in 150-200 words
        - Focus on what would be most relevant for this specific reader
        - Emphasize what OTHER people said that the reader would find important
        - Use paragraph format (no bullet points or headers)
        - Only include information explicitly mentioned in the transcript
        """
        
        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "Fact Verification",    
                category="Simple Prompt PersonalisedSummary Generation", 
                log_base_path="./atomic-facts/data_store/cost_time_logging/",
                verbose=True,
                max_tokens=4000
            )
            
            # Return the summarized response
            return response
                
        except Exception as e:
            logging.error(f"Error generating summary with simple prompt: {str(e)}")
            return f"Failed to generate summary: {str(e)}"

    def process_meeting_with_reasoning(self, transcript: str, persona_text: str, character_sheet: str) -> str:
        """
        Process a meeting transcript with a persona's preferences using the reasoning layer approach.
        
        Args:
            transcript: Meeting transcript text
            persona_text: Text describing the persona
            character_sheet_path: character sheet JSON
            
        Returns:
            Personalized meeting summary with reasoning
        """
        
        # Generate personalized summary with reasoning
        response = self.generate_summary_with_reasoning(transcript, character_sheet)
        logging.info("Generated personalized summary with reasoning layer")
        
        return response['Summary'],response['Full_reasoning_response']

    def process_meeting_simple_prompt(self, transcript: str, persona_text: str, character_sheet: str) -> str:
        """
        Process a meeting transcript with a persona's preferences using the simple prompt approach.
        
        Args:
            transcript: Meeting transcript text
            persona_text: Text describing the persona
            character_sheet: character sheet JSON
            
        Returns:
            Personalized meeting summary with simple prompt
        """
        
        # Generate personalized summary with simple prompt
        summary = self.generate_summary_simple_prompt(transcript, character_sheet)
        logging.info("Generated personalized summary with simple prompt")
        
        return summary
    
    def process_meeting(self, transcript: str, persona_text: str, character_sheet: str) -> str:
        """
        Process a meeting transcript with a persona's preferences.
        
        Args:
            transcript: Meeting transcript text
            persona_text: Text describing the persona
            character_sheet_path: Path to retrieve character sheet JSON
            
        Returns:
            Personalized meeting summary
        """
        # Generate personalized summary
        summary = self.generate_summary(transcript, character_sheet)
        logging.info("Generated personalized summary")
        
        return summary

    def process_all_meetings_with_variations(self, input_file_path: str, output_dir_path: str, personas_dir: str, character_sheets_base_path: str) -> dict:
        """
        Process multiple meetings with their respective personas using all three summary variations,
        saving results in separate CSV files for each meeting.
        
        Args:
            input_file_path: Path to input CSV with meetings and personas
            output_dir_path: Directory to save output CSV files (one per meeting)
            personas_dir: Directory where personas are stored
            character_sheets_base_path: Base path for storing character sheets
        
        Returns:
            dict: Dictionary mapping meeting IDs to their respective result DataFrames
        """
        # Load the meetings data
        df = pd.read_csv(input_file_path)
        df = df[:5]  # Processing first 10 meetings
        dataset_name = os.path.splitext(os.path.basename(input_file_path))[0]

        # Create result directories if they don't exist
        os.makedirs(output_dir_path, exist_ok=True)
        os.makedirs(character_sheets_base_path, exist_ok=True)
        
        # Dictionary to store results by meeting_id
        meeting_results = {}
        
        for i, row in df.iterrows():
            logging.info(f"Processing meeting {i+1} of {len(df)}")
            
            meeting_transcript = row['transcript']
            
            # Handle personas - either load from file or extract from transcript
            if 'Personas' in df.columns and not pd.isna(row['Personas']):
                personas_text = row['Personas']
                # Parse personas JSON
                try:
                    # Try with json.loads first
                    personas = json.loads(personas_text)
                except json.JSONDecodeError:
                    try:
                        # If that fails, try ast.literal_eval
                        import ast
                        personas = ast.literal_eval(personas_text)
                    except (ValueError, SyntaxError) as e:
                        logging.error(f"Failed to parse personas for meeting {i}: {e}")
                        continue
            else:
                personas_path = os.path.join(personas_dir, f"{dataset_name}_persona_text", f"meeting_{i+1}.json")
                personas = self.persona_extractor.extract_and_save_personas(meeting_transcript, personas_path, self.chunk_processor)
            
            # Generate meeting ID - this will be consistent for the same transcript
            meeting_id = self.generate_meeting_id(meeting_transcript)
            logging.info(f"Meeting ID: {meeting_id}")
            
            meeting_slug = f"Meeting {i+1}"

            # Clean meeting title for file naming
            if 'Title' in df.columns and not pd.isna(row['Title']):
                meeting_title = row.get('Title', f"Meeting_{i}")
                meeting_slug = meeting_title.replace(' ', '_').lower()

            meeting_slug = meeting_slug + f'_{dataset_name}'
            
            # Define the output file path for this specific meeting
            meeting_output_file_path = os.path.join(output_dir_path, f"{meeting_slug}_{meeting_id}_all_variations.csv")
            meeting_output_json_path = os.path.join(output_dir_path, f"{meeting_slug}_{meeting_id}_all_variations.json")
            
            # Initialize or load existing results for this meeting
            meeting_results_list = []
            
            # Check if output file already exists to append to it
            if os.path.exists(meeting_output_file_path):
                try:
                    existing_results = pd.read_csv(meeting_output_file_path)
                    meeting_results_list = existing_results.to_dict('records')
                    logging.info(f"Loaded {len(meeting_results_list)} existing results from {meeting_output_file_path}")
                except Exception as e:
                    logging.warning(f"Could not load existing results for meeting {meeting_id}, starting fresh: {e}")
            
            # Limit personas processing if needed (for testing)
            ind = 0
            
            # Process each persona for this meeting
            for persona_idx, persona in enumerate(personas):
                role = persona.get('role', f"Unknown_Role_{persona_idx}")
                logging.info(f"Processing persona: {role} for meeting {i+1}")
                if ind > 2:  # Process only first 3 personas
                    break

                ind = ind + 1
                
                # Prepare persona text with all details
                persona_text = json.dumps(persona, indent=2)
                
                # Create unique character sheet path for this persona
                persona_slug = role.replace(' ', '_').lower()
                character_sheet_path = os.path.join(
                    character_sheets_base_path, 
                    f"{meeting_slug}_{persona_slug}.json"
                )
                
                try:
                    # Get character sheet (reused across all variations)
                    character_sheet = self.get_or_create_character_sheet(persona_text, character_sheet_path)
                    
                    # Process meeting using all three variations
                    
                    # Variation 1: Original approach
                    summary_original = self.process_meeting(meeting_transcript, persona_text, character_sheet)
                    logging.info(f"Generated original summary for persona {role}")
                    
                    # Variation 2: With reasoning layer
                    summary_with_reasoning, full_reasoning = self.process_meeting_with_reasoning(
                        meeting_transcript, persona_text, character_sheet
                    )
                    logging.info(f"Reposne = {full_reasoning} and summary = {summary_with_reasoning}")

                    logging.info(f"Generated reasoning-based summary for persona {role}")
                    
                    # Variation 3: Simple prompt
                    summary_simple = self.process_meeting_simple_prompt(
                        meeting_transcript, persona_text, character_sheet
                    )
                    logging.info(f"Generated simple prompt summary for persona {role}")
                    
                    # Store results
                    result = {
                        'meeting_id': meeting_id,
                        'transcript': meeting_transcript,
                        'gold_summary': row.get('summary', ''),  # Use empty string if no summary column
                        'persona_role': role,
                        'persona_description': persona.get('description', ''),
                        'persona_expertise': persona.get('expertise_area', ''),
                        'persona_perspective': persona.get('perspective', ''),
                        'summary_simple_prompt': summary_simple,                    # Variation 1
                        'summary_original': summary_original,                       # Variation 2
                        'summary_with_reasoning': summary_with_reasoning,           # Variation 3 (final summary)
                        'full_reasoning_response': full_reasoning,                  # Variation 3 (full reasoning)
                        'character_sheet_path': character_sheet_path
                    }
                    
                    meeting_results_list.append(result)
                    logging.info(f"Successfully processed all variations for persona {role}")
                    
                    # Save results after each persona is processed
                    current_results_df = pd.DataFrame(meeting_results_list)
                    current_results_df.to_csv(meeting_output_file_path, index=False)
                    logging.info(f"Incremental results saved to {meeting_output_file_path}")
                    
                    # Also save as JSON to preserve all details
                    with open(meeting_output_json_path, 'w') as f:
                        json.dump(meeting_results_list, f, indent=2)
                    logging.info(f"Incremental results also saved as JSON to {meeting_output_json_path}")
                    
                except Exception as e:
                    logging.error(f"Error processing persona {role} for meeting {i+1}: {str(e)}")
                    continue
            
            # Store the results for this meeting in the overall dictionary
            if meeting_results_list:
                meeting_results[meeting_id] = pd.DataFrame(meeting_results_list)
            else:
                logging.warning(f"No results were generated for meeting {meeting_id}.")
        
        return meeting_results

    # def process_all_meetings(self, input_file_path: str, output_dir_path: str,peronas_dir,character_sheets_base_path: str) -> dict:
    #     """
    #     Process multiple meetings with their respective personas, saving results in separate CSV files for each meeting.
        
    #     Args:
    #         input_file_path: Path to input CSV with meetings and personas
    #         output_dir_path: Directory to save output CSV files (one per meeting)
    #         character_sheets_base_path: Base path for storing character sheets
        
    #     Returns:
    #         dict: Dictionary mapping meeting IDs to their respective result DataFrames
    #     """
    #     # Load the meetings data
    #     df = pd.read_csv(input_file_path)
    #     df = df[:1]  # Processing first 10 meetings
    #     dataset_name = os.path.splitext(os.path.basename(input_file_path))[0]

    #     # Create result directories if they don't exist
    #     os.makedirs(output_dir_path, exist_ok=True)
    #     os.makedirs(character_sheets_base_path, exist_ok=True)
        
    #     # Dictionary to store results by meeting_id
    #     meeting_results = {}
        
    #     for i, row in df.iterrows():
    #         logging.info(f"Processing meeting {i+1} of {len(df)}")
            
    #         meeting_transcript = row['transcript']
    #         #check if personas text is available or not
    #         if 'Personas' in df.columns and not pd.isna(row['Personas']):
    #             personas_text = row['Personas']
    #                         # Parse personas JSON
    #             try:
    #                 # Try with json.loads first
    #                 personas = json.loads(personas_text)
    #             except json.JSONDecodeError:
    #                 try:
    #                     # If that fails, try ast.literal_eval
    #                     import ast
    #                     personas = ast.literal_eval(personas_text)
    #                 except (ValueError, SyntaxError) as e:
    #                     logging.error(f"Failed to parse personas for meeting {i}: {e}")
    #                     continue
    #         else:
    #             peronas_path = os.path.join(peronas_dir, f"{dataset_name}_persona_text", f"meeting_{i+1}.json")
    #             personas = self.persona_extractor.extract_and_save_personas(meeting_transcript,peronas_path,self.chunk_processor)
            
 
    #         # # Print extracted personas
    #         # for persona in personas:
    #         #     print(f"Name: {persona.get('name', 'Unknown')}")
    #         #     print(f"Role: {persona.get('role', 'Unknown')}")
    #         #     print(f"Expertise: {persona.get('expertise_area', 'Unknown')}")
    #         #     print("---")
    #         # break
    #         # Generate meeting ID - this will be consistent for the same transcript
    #         meeting_id = self.generate_meeting_id(meeting_transcript)
    #         logging.info(f"Meeting ID: {meeting_id}")
            
    #         meeting_slug = f"Meeting {i+1}"

    #         # Clean meeting title for file naming
    #         if 'Title' in df.columns and not pd.isna(row['Title']):
    #             meeting_title = row.get('Title', f"Meeting_{i}")
    #             meeting_slug = meeting_title.replace(' ', '_').lower()


    #         meeting_slug = meeting_slug + f'_{dataset_name}'
            
    #         # Define the output file path for this specific meeting
    #         meeting_output_file_path = os.path.join(output_dir_path, f"{meeting_slug}_{meeting_id}.csv")
    #         meeting_output_json_path = os.path.join(output_dir_path, f"{meeting_slug}_{meeting_id}.json")
            
    #         # Initialize or load existing results for this meeting
    #         meeting_results_list = []
            
    #         # Check if output file already exists to append to it
    #         if os.path.exists(meeting_output_file_path):
    #             try:
    #                 existing_results = pd.read_csv(meeting_output_file_path)
    #                 meeting_results_list = existing_results.to_dict('records')
    #                 logging.info(f"Loaded {len(meeting_results_list)} existing results from {meeting_output_file_path}")
    #             except Exception as e:
    #                 logging.warning(f"Could not load existing results for meeting {meeting_id}, starting fresh: {e}")
            
            
    #         ind=0
    #         # Process each persona for this meeting
    #         for persona_idx, persona in enumerate(personas):
    #             role = persona.get('role', f"Unknown_Role_{persona_idx}")
    #             logging.info(f"Processing persona: {role} for meeting {i+1}")
    #             if ind > 2:
    #                 break

    #             ind = ind + 1
                
    #             # # Check if this persona has already been processed
    #             # already_processed = False
    #             # for result in meeting_results_list:
    #             #     if result.get('persona_role') == role:
    #             #         logging.info(f"Persona {role} for meeting {i+1} already processed. Skipping.")
    #             #         already_processed = True
    #             #         break
                
    #             # if already_processed:
    #             #     continue
                
    #             # Prepare persona text with all details
    #             persona_text = json.dumps(persona, indent=2)
    #             logging.info(f'{persona_text}')
    #             # Create unique character sheet path for this persona
    #             persona_slug = role.replace(' ', '_').lower()
    #             character_sheet_path = os.path.join(
    #                 character_sheets_base_path, 
    #                 f"{meeting_slug}_{persona_slug}.json"
    #             )
                
    #             try:
    #                 # Process the meeting for this specific persona - passing the meeting_id
    #                 summary = self.process_meeting(
    #                     meeting_transcript, persona_text, character_sheet_path
    #                 )
                    
    #                 # Store results
    #                 result = {
    #                     'meeting_id': meeting_id,
    #                     'transcript': meeting_transcript,
    #                     'Gold_summary' : row['summary'],
    #                     'persona_role': role,
    #                     'persona_description': persona.get('description', ''),
    #                     'persona_expertise': persona.get('expertise_area', ''),
    #                     'persona_perspective': persona.get('perspective', ''),
    #                     'generated_summary': summary,
    #                     'character_sheet_path': character_sheet_path
    #                 }
                    
    #                 meeting_results_list.append(result)
    #                 logging.info(f"Successfully processed persona {role} for meeting {i+1}")
                    
    #                 # Save results after each persona is processed
    #                 current_results_df = pd.DataFrame(meeting_results_list)
    #                 current_results_df.to_csv(meeting_output_file_path, index=False)
    #                 logging.info(f"Incremental results saved to {meeting_output_file_path} after processing persona {role}")
                    
    #                 # Also save as JSON to preserve all details
    #                 with open(meeting_output_json_path, 'w') as f:
    #                     json.dump(meeting_results_list, f, indent=2)
    #                 logging.info(f"Incremental results also saved as JSON to {meeting_output_json_path}")
                    
    #             except Exception as e:
    #                 logging.error(f"Error processing persona {role} for meeting {i+1}: {str(e)}")
    #                 continue
            
    #         # Store the results for this meeting in the overall dictionary
    #         if meeting_results_list:
    #             meeting_results[meeting_id] = pd.DataFrame(meeting_results_list)
    #         else:
    #             logging.warning(f"No results were generated for meeting {meeting_id}.")
        
    #     return meeting_results
        
    # def process_all_meetings(self, input_file_path: str, output_dir_path: str, character_sheets_base_path: str) -> dict:
    #     """
    #     Process multiple meetings with their respective personas, saving results in CSV files.
        
    #     Args:
    #         input_file_path: Path to input CSV with meetings and personas
    #         output_dir_path: Directory to save output CSV files
    #         character_sheets_base_path: Base path for character sheets
        
    #     Returns:
    #         dict: Dictionary mapping meeting IDs to their respective result DataFrames
    #     """
    #     # Load the meetings data
    #     df = pd.read_csv(input_file_path)
    #     df = df[:10]
    #     # Create result directories if they don't exist
    #     os.makedirs(output_dir_path, exist_ok=True)
        
    #     # Dictionary to store results by meeting_id
    #     meeting_results = {}
        
    #     for i, row in df.iterrows():
    #         logging.info(f"Processing meeting {i+1} of {len(df)}")
            
    #         # Extract meeting data
    #         meeting_title = row.get('Title', f"Meeting_{i}")
    #         meeting_transcript = row['Meeting']
    #         personas_text = row['Personas']
            
    #         # Generate meeting ID
    #         meeting_id = self.generate_meeting_id(meeting_transcript)
    #         logging.info(f"Meeting ID: {meeting_id}")
            
    #         # Clean meeting title for file naming
    #         meeting_slug = meeting_title.replace(' ', '_').lower()
            
    #         # Define the output file path for this specific meeting
    #         meeting_output_file_path = os.path.join(output_dir_path, f"simple_{meeting_slug}_{meeting_id}.csv")
            
    #         # Initialize or load existing results for this meeting
    #         meeting_results_list = []
            
    #         # Parse personas JSON
    #         try:
    #             # Try with json.loads first
    #             personas = json.loads(personas_text)
    #         except json.JSONDecodeError:
    #             try:
    #                 # If that fails, try ast.literal_eval
    #                 import ast
    #                 personas = ast.literal_eval(personas_text)
    #             except (ValueError, SyntaxError) as e:
    #                 logging.error(f"Failed to parse personas for meeting {i}: {e}")
    #                 continue
            
    #         # Process each persona for this meeting
    #         for persona_idx, persona in enumerate(personas):
    #             role = persona.get('role', f"Unknown_Role_{persona_idx}")
    #             logging.info(f"Processing persona: {role} for meeting: {meeting_title}")
                
    #             # Prepare persona text with all details
    #             persona_text = json.dumps(persona, indent=2)
                
    #             # Get character sheet path for this persona
    #             persona_slug = role.replace(' ', '_').lower()
    #             character_sheet_path = os.path.join(
    #                 character_sheets_base_path, 
    #                 f"{meeting_slug}_{persona_slug}.json"
    #             )
                
    #             try:
    #                 # Process the meeting for this specific persona
    #                 summary = self.process_meeting(
    #                     meeting_transcript, persona_text, character_sheet_path
    #                 )
                    
    #                 # Store results
    #                 result = {
    #                     'meeting_id': meeting_id,
    #                     'meeting_title': meeting_title,
    #                     'persona_role': role,
    #                     'persona_description': persona.get('description', ''),
    #                     'summary': summary,
    #                     'character_sheet_path': character_sheet_path,
    #                     'full_persona': json.dumps(persona)
    #                 }
                    
    #                 meeting_results_list.append(result)
    #                 logging.info(f"Successfully processed persona {role} for meeting {meeting_title}")
                    
    #             except Exception as e:
    #                 logging.error(f"Error processing persona {role} for meeting {meeting_title}: {str(e)}")
    #                 continue
            
    #         # Save results for this meeting
    #         if meeting_results_list:
    #             results_df = pd.DataFrame(meeting_results_list)
    #             results_df.to_csv(meeting_output_file_path, index=False)
    #             logging.info(f"Results saved to {meeting_output_file_path}")
                
    #             # Store in our return dictionary
    #             meeting_results[meeting_id] = results_df
            
    #     return meeting_results