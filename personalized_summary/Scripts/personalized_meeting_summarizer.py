import logging
import pandas as pd
import os
import json
import hashlib
from typing import List, Dict, Tuple
from chunk_processor import ChunkProcessor
from persona_extractor import PersonaExtractor
from atomic_facts import AtomicFacts
from facts_reasoning_layer import FactsReasoningLayer
from persona_extractor import PersonaExtractor
from character_sheet_generator import CharacterSheetGenerator
from personalized_feature_generator import PersonalizedFeatureGenerator
from personalized_agents import PersonalizedAgents
from post_processing import PostProcessor
from personalized_memory_bank import PersonalizedMemoryBank

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class PersonalizedMeetingSummarizer:
    def __init__(self, client, model="gpt-4o", storage_dir="./atomic-facts/data_store"):
        self.client = client
        self.model = model
        self.chunk_processor = ChunkProcessor()
        self.persona_extractor = PersonaExtractor(client,model)
        self.atomic_facts = AtomicFacts(client, model)
        self.facts_reasoning_layer = FactsReasoningLayer(client,model)
        self.character_sheet_generator = CharacterSheetGenerator(client, model)
        self.feature_generator = PersonalizedFeatureGenerator(client, model)
        self.memory_bank = PersonalizedMemoryBank(storage_dir)
        self.agents = PersonalizedAgents(client, model)
        self.post_processor = PostProcessor(client, model)

    def generate_meeting_id(self, transcript: str) -> str:
        """Generate a unique meeting ID based on transcript content."""
        return hashlib.md5(transcript.encode()).hexdigest()
    
    def reduce_chunk_size(self, current_token_limit: int, all_chunks_processed: bool) -> Tuple[int, bool]:
        """Handle chunk size reduction logic."""
        if current_token_limit > self.chunk_processor.MIN_CHUNK_SIZE:
            current_token_limit = current_token_limit - self.chunk_processor.STEP_SIZE
            logging.info(f"Reducing chunk size to {current_token_limit}")
        else:
            all_chunks_processed = False
            raise Exception("Failed to get complete processing even at minimum size")
        return current_token_limit, all_chunks_processed

    def prepare_enhanced_context(self, unique_features: List[Dict], detailed_contexts: Dict) -> Dict:
        """Prepare enhanced context with persona-aligned features."""
        enhanced_context = {
            'matched_information': [],
            'unmatched_features': []
        }
        
        for feature in unique_features:
            feature_id = feature['feature']
            if feature_id in detailed_contexts:
                feature_info = detailed_contexts[feature_id]
                matched_facts = feature_info['matched_facts']
                
                if matched_facts:
                    for match in matched_facts:
                        enhanced_context['matched_information'].append({
                            'fact': match['fact'],
                            'context': match['context'],
                            'verbose_context': match['verbose_context'],
                            'category': feature_info['feature_metadata']['original_category'],
                            'feature_type': feature_info['feature_metadata']['feature_type'],
                            'importance_score': feature_info['feature_metadata']['importance_score'],
                            'persona_alignment_score': feature_info['feature_metadata'].get('persona_alignment_score', 5),
                            'alignment_explanation': feature_info['feature_metadata'].get('alignment_explanation', ''),
                            'combined_score': feature_info['feature_metadata'].get('combined_score', 0)
                        })
                else:
                    enhanced_context['unmatched_features'].append({
                        'feature': feature['feature'],
                        'category': feature_info['feature_metadata']['original_category'],
                        'feature_type': feature_info['feature_metadata']['feature_type'],
                        'importance_score': feature_info['feature_metadata']['importance_score'],
                        'persona_alignment_score': feature_info['feature_metadata'].get('persona_alignment_score', 5),
                        'alignment_explanation': feature_info['feature_metadata'].get('alignment_explanation', ''),
                        'combined_score': feature_info['feature_metadata'].get('combined_score', 0)
                    })
        
        # Sort by combined score
        enhanced_context['matched_information'].sort(
            key=lambda x: x['combined_score'],
            reverse=True
        )
        
        enhanced_context['unmatched_features'].sort(
            key=lambda x: x['combined_score'],
            reverse=True
        )
        
        logging.info(f"Prepared context with {len(enhanced_context['matched_information'])} matched facts "
                    f"and {len(enhanced_context['unmatched_features'])} unmatched features")
        
        return enhanced_context

    def reset_initial_variables(self):
        self.chunk_processor.reset_position()
        self.memory_bank.atomic_facts_chunks = []
        self.memory_bank.important_facts = {
            'DECISION': [],
            'HIGH_ALIGNMENT': [],
            'MEDIUM_ALIGNMENT': [],
            'CONTEXT': []
        }
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
    
    def load_or_create_atomic_facts(self, transcript: str, meeting_id: str, atomic_facts_dir: str) -> List[Dict]:
        """
        Load existing atomic facts for a meeting or create and store new ones if they don't exist.
        
        Args:
            transcript: Meeting transcript text
            meeting_id: Meeting identifier
            atomic_facts_dir: Directory to store atomic facts
            
        Returns:
            List of atomic facts
        """
        # Define the atomic facts file path
        logging.info(f'Atomic facts = {atomic_facts_dir}')
        atomic_facts_path = os.path.join(atomic_facts_dir, f"atomic_facts_{meeting_id}.json")
        
        # Check if atomic facts already exist for this meeting
        if os.path.exists(atomic_facts_path):
            try:
                with open(atomic_facts_path, 'r') as f:
                    all_atomic_facts = json.load(f)
                logging.info(f"Loaded {len(all_atomic_facts)} existing atomic facts for meeting {meeting_id}")
                return all_atomic_facts
            except Exception as e:
                logging.error(f"Error loading existing atomic facts: {str(e)}")
                # If loading fails, we'll extract them again
        
        # If we get here, we need to extract atomic facts
        logging.info("Extracting new atomic facts from transcript...")
        all_atomic_facts = []
        current_token_limit = self.chunk_processor.INITIAL_CHUNK_SIZE
        all_chunks_processed = True
        
        # Reset for new transcript
        self.reset_initial_variables()
        
        while True:
            chunk_text, tokens_used = self.chunk_processor.chunk_transcript(
                transcript, current_token_limit
            )
            
            if not chunk_text:
                break
                
            logging.info(f"Processing chunk with size: {current_token_limit} tokens for atomic facts extraction")
            
            try:
                # Process chunk to get atomic facts
                pre_processed_chunk = self.chunk_processor.pre_process_chunk(chunk_text)
                atomic_facts, is_valid_facts = self.atomic_facts.Break_into_atomic_facts(pre_processed_chunk)
                
                if is_valid_facts:
                    # Store the atomic facts
                    all_atomic_facts.extend(atomic_facts)
                    print(all_atomic_facts)
                    self.chunk_processor.advance_position(chunk_text)
                    
                    if current_token_limit < self.chunk_processor.MAX_CHUNK_SIZE:
                        current_token_limit += self.chunk_processor.STEP_SIZE
                        logging.info(f"Increasing chunk size to {current_token_limit}")
                    
                    # Store current chunk as previous for next iteration
                    if self.atomic_facts.previous_chunk != chunk_text:
                        self.atomic_facts.previous_chunk = chunk_text
                    
                else:
                    current_token_limit, all_chunks_processed = self.reduce_chunk_size(
                        current_token_limit, all_chunks_processed
                    )
                    continue
                    
            except Exception as e:
                logging.error(f"Error processing chunk for atomic facts: {str(e)}")
                current_token_limit, all_chunks_processed = self.reduce_chunk_size(
                    current_token_limit, all_chunks_processed
                )
                continue
        
        # Save all atomic facts to a JSON file
        try:
            os.makedirs(atomic_facts_dir, exist_ok=True)
            with open(atomic_facts_path, 'w') as f:
                json.dump(all_atomic_facts, f, indent=2)
            logging.info(f"Saved {len(all_atomic_facts)} atomic facts to {atomic_facts_path}")
        except Exception as e:
            logging.error(f"Error saving atomic facts: {str(e)}")
        
        return all_atomic_facts

    def process_facts_with_reasoning_layer(self, all_atomic_facts: List[Dict], character_sheet: Dict) -> List[Dict]:
        """
        Process atomic facts through reasoning layer in small batches.
        
        Args:
            all_atomic_facts: List of all atomic facts from transcript
            character_sheet: Character profile for relevance filtering
            
        Returns:
            List of filtered relevant facts
        """
        batch_size = 10  # Process 10 facts at a time
        all_relevant_facts = []
        full_reasoning = []
        total_facts = len(all_atomic_facts)
        
        logging.info(f"Processing {total_facts} atomic facts through reasoning layer in batches of {batch_size}")
        
        for i in range(0, total_facts, batch_size):
            end_idx = min(i + batch_size, total_facts)
            batch = all_atomic_facts[i:end_idx]
            
            logging.info(f"Applying reasoning layer to batch {i//batch_size + 1}: facts {i+1}-{end_idx} of {total_facts}")
            
            try:
                # Apply reasoning to this batch of facts
                relevant_batch = self.facts_reasoning_layer.filter_relevant_facts(batch, character_sheet)
                logging.info(f"Original Batch:  {batch}")

                logging.info(f"Relevant Batch:  {relevant_batch}")


                all_relevant_facts.extend(relevant_batch['filtered_facts'])
                full_reasoning.append(relevant_batch['full_reasoning'])
                logging.info(f"in meeting summarizer = full reasoning = {all_relevant_facts}")
                logging.info(f"in meeting summarizer = full reasoning = {full_reasoning}")
                
                logging.info(f"Batch {i//batch_size + 1}: filtered {len(batch)} facts to {len(relevant_batch['filtered_facts'])} relevant facts")
                
            except Exception as e:
                logging.error(f"Error processing batch {i//batch_size + 1} through reasoning layer: {str(e)}")
                # In case of error, include the whole batch to avoid losing potentially important information
                all_relevant_facts.extend(batch)
                full_reasoning.extend(relevant_batch['full_reasoning'])
                logging.warning(f"Including all {len(batch)} facts from batch {i//batch_size + 1} due to processing error")
        
        logging.info(f"Reasoning layer complete: filtered {total_facts} facts to {len(all_relevant_facts)} relevant facts")
        return all_relevant_facts,full_reasoning
    
    def process_meeting(self, transcript: str, persona_text: str, character_sheet_path: str, atomic_facts_dir, meeting_id: str) -> Tuple[str, str, List[Dict], List[str]]:
        """
        Process meeting transcript with persona preferences.
        
        Args:
            transcript: Meeting transcript text
            persona_text: Text describing the persona
            character_sheet_path: Path to store/retrieve character sheet JSON
            meeting_id: Optional meeting ID, generated if not provided
            
        Returns:
            Tuple of (final_summary, raw_summary, important_features, outline)
        """
        # Get or create character sheet from JSON
        character_sheet = self.get_or_create_character_sheet(persona_text, character_sheet_path)
        logging.info("Retrieved character sheet")
        logging.info(f'Character sheet = {character_sheet}')
        
        all_atomic_facts = self.load_or_create_atomic_facts(transcript, meeting_id, atomic_facts_dir)

        logging.info(f"Applying reasoning layer to filter {len(all_atomic_facts)} atomic facts in batches...")
        # reasoned_facts_path = os.path.join(atomic_facts_dir, f"reasoned_facts_{meeting_id}.json")
        reasoned_facts_path = f"atomic-facts/reasoning/reasoned_facts_{meeting_id}.json"
        full_reasoning_path = f"atomic-facts/reasoning/full_reasoning_{meeting_id}.json"
        # Check if reasoned facts already exist
        if os.path.exists(reasoned_facts_path):
            try:
                with open(reasoned_facts_path, 'r') as f:
                    relevant_facts = json.load(f)
                logging.info(f"Loaded {len(relevant_facts)} existing relevant facts from reasoning layer")
            except Exception as e:
                logging.error(f"Error loading reasoned facts: {str(e)}")
                # If loading fails, we'll process them in batches
                relevant_facts,full_reasoning = self.process_facts_with_reasoning_layer(all_atomic_facts, character_sheet)
        else:
            # Process atomic facts through reasoning layer in batches
            relevant_facts,full_reasoning = self.process_facts_with_reasoning_layer(all_atomic_facts, character_sheet)
            
            # Save the reasoned facts
            try: 
                with open(reasoned_facts_path, 'w') as f:
                    json.dump(relevant_facts, f, indent=2)
                logging.info(f"Saved {len(relevant_facts)} relevant facts to {reasoned_facts_path}")
            except Exception as e:
                logging.error(f"Error saving reasoned facts: {str(e)}")
            
             # Save the reasoned facts
            try: 
                with open(full_reasoning_path, 'w') as f:
                    json.dump(full_reasoning, f, indent=2)
                logging.info(f"Saved {len(full_reasoning)} relevant facts to {full_reasoning_path}")
            except Exception as e:
                logging.error(f"Error saving reasoned facts: {str(e)}")
        
        logging.info(f"Reasoning layer filtered {len(all_atomic_facts)} facts down to {len(relevant_facts)} relevant facts")
        


        all_atomic_facts = relevant_facts
        # Phase 2: Process atomic facts in smaller batches for ranking with dynamic batch size
        initial_batch_size = 5  # Start with 8 atomic facts at a time
        min_batch_size = 2    # Minimum batch size to try
        all_ranked_features = []
        
        # Reset memory bank for new persona processing
        self.reset_initial_variables()

        i = 0


        while i < len(all_atomic_facts):
            # Start with the initial batch size
            batch_size = initial_batch_size
            processed_successfully = False
            
            # Try processing with decreasing batch sizes until successful or min size reached
            while not processed_successfully and batch_size >= min_batch_size:
                # Make sure we don't go beyond the end of the list
                end_idx = min(i + batch_size, len(all_atomic_facts))
                batch = all_atomic_facts[i:end_idx]
                logging.info(f"batch = {batch}")
                
                logging.info(f"Ranking batch starting at index {i} with {len(batch)} atomic facts (batch size: {batch_size})")
                
                try:
                    # Get ranked features for this batch
                    ranked_features, is_complete = self.feature_generator.identify_salient_features(
                        batch, character_sheet
                    )
                    logging.info(f"Ranked Features: {ranked_features}, Flag = {is_complete}")


                    if is_complete:
                        # Store the ranked features
                        all_ranked_features.extend(ranked_features)
                        # Also process them into the memory bank
                        self.memory_bank.process_features(ranked_features, batch)
                        processed_successfully = True
                        
                        # Move to the next batch
                        i += batch_size
                        
                        logging.info(f"Successfully processed batch with size {batch_size}")
                    else:
                        # Reduce batch size and try again
                        batch_size -= 1
                        logging.warning(f"Incomplete ranking, reducing batch size to {batch_size}")
                
                except Exception as e:
                    # Reduce batch size and try again
                    batch_size -= 1
                    logging.error(f"Error ranking batch: {str(e)}. Reducing batch size to {batch_size}")
            
            # If we couldn't process even with minimum batch size, move forward and skip this part
            if not processed_successfully:
                logging.error(f"Failed to process batch at index {i} even with minimum batch size. Skipping {min_batch_size} facts.")
                i += min_batch_size
        
        # Save the ranked features
        self.memory_bank.save_data(meeting_id)
        logging.info("Saved processed data to files")
        
        # Get personalized features for outline
        outline_features = self.memory_bank.get_features_for_outline()
        outline = self.feature_generator.generate_outline(outline_features)
        logging.info(f"Generated personalized outline with {len(outline)} sections")
        
        # Get features and their detailed context
        unique_features, detailed_contexts = self.memory_bank.get_features_for_summary()
        logging.info(f"Found {len(unique_features)} unique features with matched facts")
        
        # Prepare enhanced context for summary generation
        enhanced_context = self.prepare_enhanced_context(unique_features, detailed_contexts)
        
        # Generate personalized summary using enhanced context and character sheet
        summary, score, feedback = self.agents.process_chunk_with_feedback(
            "Final_Summary",
            enhanced_context,
            outline,
            character_sheet
        )
        
        logging.info(f"Generated personalized summary with confidence score: {score}")
        
        final_summary = self.post_processor.post_process_summary(summary)
        return final_summary, summary, unique_features, outline

    def process_all_meetings(self, input_file_path: str, output_dir_path: str,peronas_dir,character_sheets_base_path: str, atomic_facts_dir) -> dict:
        """
        Process multiple meetings with their respective personas, saving results in separate CSV files for each meeting.
        
        Args:
            input_file_path: Path to input CSV with meetings and personas
            output_dir_path: Directory to save output CSV files (one per meeting)
            character_sheets_base_path: Base path for storing character sheets
        
        Returns:
            dict: Dictionary mapping meeting IDs to their respective result DataFrames
        """
        # Load the meetings data
        df = pd.read_csv(input_file_path)
        df = df[0:1]  # Processing first 10 meetings
        dataset_name = os.path.splitext(os.path.basename(input_file_path))[0]

        # Create result directories if they don't exist
        os.makedirs(output_dir_path, exist_ok=True)
        os.makedirs(character_sheets_base_path, exist_ok=True)
        
        # Dictionary to store results by meeting_id
        meeting_results = {}

        persona_count =0
        
        for i, row in df.iterrows():
            logging.info(f"Processing meeting {i+1} of {len(df)}")
            
            meeting_transcript = row['transcript']
            #check if personas text is available or not
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
                peronas_path = os.path.join(peronas_dir, f"{dataset_name}_persona_text", f"meeting_{i+1}.json")
                personas = self.persona_extractor.extract_and_save_personas(meeting_transcript,peronas_path,self.chunk_processor)
            

            meeting_id = self.generate_meeting_id(meeting_transcript)
            logging.info(f"Meeting ID: {meeting_id}")
            
            meeting_slug = f"Meeting {i+1}"

            # Clean meeting title for file naming
            if 'Title' in df.columns and not pd.isna(row['Title']):
                meeting_title = row.get('Title', f"Meeting_{i}")
                meeting_slug = meeting_title.replace(' ', '_').lower()


            meeting_slug = meeting_slug + f'_{dataset_name}'
            
            # Define the output file path for this specific meeting
            meeting_output_file_path = os.path.join(output_dir_path, f"{meeting_slug}_{meeting_id}.csv")
            meeting_output_json_path = os.path.join(output_dir_path, f"{meeting_slug}_{meeting_id}.json")
            
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
            
            ind=0
            # Process each persona for this meeting
            for persona_idx, persona in enumerate(personas):
                role = persona.get('role', f"Unknown_Role_{persona_idx}")
                logging.info(f"Processing persona: {role} for meeting {i+1}")
                if ind > 3:
                    break
                
                persona_count +=1 
                ind = ind + 1
                
                # Prepare persona text with all details
                persona_text = json.dumps(persona, indent=2)
                logging.info(f'{persona_text}')
                # Create unique character sheet path for this persona
                persona_slug = role.replace(' ', '_').lower()
                character_sheet_path = os.path.join(
                    character_sheets_base_path, 
                    f"{meeting_slug}_{persona_slug}.json"
                )
                
                try:
                    # Process the meeting for this specific persona - passing the meeting_id
                    refined_summary, generated_summary, important_features, outline = self.process_meeting(
                        meeting_transcript, persona_text, character_sheet_path, atomic_facts_dir ,meeting_id
                    )
                    
                    # Store results
                    result = {
                        'meeting_id': meeting_id,
                        'transcript': meeting_transcript,
                        'Gold_summary' : row['summary'],
                        'persona_role': role,
                        'persona_description': persona.get('description', ''),
                        'persona_expertise': persona.get('expertise_area', ''),
                        'persona_perspective': persona.get('perspective', ''),
                        'generated_summary': generated_summary,
                        'refined_summary': refined_summary,
                        'character_sheet_path': character_sheet_path,
                        'full_persona': json.dumps(persona),
                        'important_features': json.dumps(important_features),
                        'outline': json.dumps(outline)
                    }
                    
                    meeting_results_list.append(result)
                    logging.info(f"Successfully processed persona {role} for meeting {i+1}")
                    
                    # Save results after each persona is processed
                    current_results_df = pd.DataFrame(meeting_results_list)
                    current_results_df.to_csv(meeting_output_file_path, index=False)
                    logging.info(f"Incremental results saved to {meeting_output_file_path} after processing persona {role}")
                    
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
        logging.info(f'persona_count = {persona_count}')
        return meeting_results