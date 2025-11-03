import logging
from typing import List, Dict, Tuple
import pandas as pd
import os
import json
import hashlib
import time
from model_handler import ModelHandler
from chunk_processor import ChunkProcessor
from atomic_facts import AtomicFacts
from feature_generator import FeatureGenerator
from agent_processor import Agents
from post_processing import PostProcessor
from memory_bank import MemoryBank

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MeetingSummarizer:
    def __init__(self, client,model,log_base_path, storage_dir="data_store"):
        self.client = client
        self.model = model
        self.chunk_processor = ChunkProcessor()
        self.atomic_facts = AtomicFacts(client, model,log_base_path)
        self.feature_generator = FeatureGenerator(client, model,log_base_path)
        self.memory_bank = MemoryBank(storage_dir)
        self.agents = Agents(client, model,log_base_path)
        self.post_processor = PostProcessor(client,model,log_base_path)

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
        """Prepare enhanced context for summary generation with focus on matched facts."""
        enhanced_context = {
            'matched_information': [],  # Will contain facts with contexts
            'unmatched_features': []   # Will contain features without matches
        }
        
        # Process each feature
        for feature in unique_features:
            feature_id = feature['feature']
            if feature_id in detailed_contexts:
                feature_info = detailed_contexts[feature_id]
                matched_facts = feature_info['matched_facts']
                
                if matched_facts:  # If we found matches for this feature
                    for match in matched_facts:
                        enhanced_context['matched_information'].append({
                            'fact': match['fact'],
                            'context': match['context'],
                            'verbose_context': match['verbose_context'],
                            'category': feature_info['feature_metadata']['original_category'],
                            'feature_type': feature_info['feature_metadata']['feature_type'],
                            'importance_score': feature_info['feature_metadata']['importance_score'],
                        })
                else:  # No matches found, preserve the feature
                    enhanced_context['unmatched_features'].append({
                        'feature': feature['feature'],
                        'category': feature_info['feature_metadata']['original_category'],
                        'feature_type': feature_info['feature_metadata']['feature_type'],
                        'importance_score': feature_info['feature_metadata']['importance_score']
                    })
        
        # Sort matched information by importance score
        enhanced_context['matched_information'].sort(
            key=lambda x: x['importance_score'], 
            reverse=True
        )
        
        # Sort unmatched features by importance
        enhanced_context['unmatched_features'].sort(
            key=lambda x: x['importance_score'],
            reverse=True
        )
        
        logging.info(f"Prepared context with {len(enhanced_context['matched_information'])} matched facts "
                    f"and {len(enhanced_context['unmatched_features'])} unmatched features")
        
        return enhanced_context

    def reset_initial_variables(self):
        """Reset processing variables for a new transcript."""
        self.chunk_processor.reset_position()
        self.memory_bank.atomic_facts_chunks = []
        self.atomic_facts.regeneration_logs = []
        self.memory_bank.important_facts = {
            'DECISION': [],
            'HIGH_PRIORITY': [],
            'MEDIUM_PRIORITY': [],
            'CONTEXT': []
        }
    def _strip_context(self, facts: List[Dict]) -> List[Dict]:
        """
        Convert atomic facts → molecular facts by blanking out
        'context' and 'verbose_context' fields in‑place.
        """
        molecular_facts = []
        for f in facts:
            logging.info(f'facts = {f}')
            logging.info(f'------------------------')
            f["context"] = ""
            f["verbose_context"] = ""
            molecular_facts.append(f)
        return molecular_facts

    def _convert_listarray_into_array(self, facts_list: List[Dict]) -> List[Dict]:

        if all(isinstance(item, dict) for item in facts_list):
            return list(facts_list)
        
        molecular_facts = []
        for facts in facts_list:
            for f in facts:
                molecular_facts.append(f)
        return molecular_facts


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
        os.makedirs(atomic_facts_dir, exist_ok=True)
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
                atomic_facts, is_valid_facts = self.atomic_facts.Break_into_atomic_facts(chunk_text)
                
                if is_valid_facts:
                    # Store the atomic facts
                    all_atomic_facts.extend(atomic_facts)
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
        
        return all_atomic_facts

    def store_facts_relevance_logs(self, transcript: str,atomic_facts_dir):
        # Generate meeting ID
        meeting_id = self.generate_meeting_id(transcript)
        logging.info(f"Processing meeting with ID: {meeting_id}")
        
        # Reset all variables
        self.reset_initial_variables()
        
        all_atomic_facts = self.load_or_create_atomic_facts(transcript, meeting_id, atomic_facts_dir)
        logging.info(f"Total atomic facts: {len(all_atomic_facts)}")

        try:
            if self.atomic_facts.regeneration_logs:
                # Decide on a file name to store them, e.g.:
                logs_file = os.path.join(atomic_facts_dir, f"regeneration_logs_{meeting_id}.json")
                
                with open(logs_file, 'w') as f:
                    json.dump(self.atomic_facts.regeneration_logs, f, indent=2)
                
                logging.info(f"Saved regeneration logs to {logs_file}")
            else:
                logging.info(f"No regeneration logs to save for {meeting_id}")
        except Exception as e:
            logging.error(f"Error saving regeneration logs for {meeting_id}: {str(e)}")


    def process_meeting(self, transcript: str,atomic_facts_dir) -> Tuple[str, str, List[Dict], List[str]]:
        """
        Process meeting transcript using a two-phase approach.
        
        Phase 1: Extract and store all atomic facts
        Phase 2: Process atomic facts in batches for feature extraction and ranking
        
        Returns: (final_summary, raw_summary, important_features, outline)
        """
        # Generate meeting ID
        meeting_id = self.generate_meeting_id(transcript)
        logging.info(f"Processing meeting with ID: {meeting_id}")
        
        # Reset all variables
        self.reset_initial_variables()
        
        all_atomic_facts = self.load_or_create_atomic_facts(transcript, meeting_id, atomic_facts_dir)
        all_atomic_facts = self._convert_listarray_into_array(all_atomic_facts)
        logging.info(f"Total atomic facts: {len(all_atomic_facts)}")
        logging.info(f" atomic facts: {all_atomic_facts}")

        try:
            if self.atomic_facts.regeneration_logs:
                # Decide on a file name to store them, e.g.:
                logs_file = os.path.join(atomic_facts_dir, f"regeneration_logs_{meeting_id}.json")
                
                with open(logs_file, 'w') as f:
                    json.dump(self.atomic_facts.regeneration_logs, f, indent=2)
                
                logging.info(f"Saved regeneration logs to {logs_file}")
            else:
                logging.info(f"No regeneration logs to save for {meeting_id}")
        except Exception as e:
            logging.error(f"Error saving regeneration logs for {meeting_id}: {str(e)}")
        
        # Phase 2: Process atomic facts in smaller batches for ranking
        initial_batch_size = 10  # Start with 8 atomic facts at a time
        min_batch_size = 3     # Minimum batch size to try
        all_ranked_features = []
        
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
                
                logging.info(f"Ranking batch starting at index {i} with {len(batch)} atomic facts (batch size: {batch_size})")
                
                try:
                    # Get ranked features for this batch
                    ranked_features, is_complete = self.feature_generator.identify_salient_features(batch)
                    
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
        
        # Save the processed data
        self.memory_bank.save_data(meeting_id)
        logging.info("Saved processed data to files")
        
        # Get features for outline
        outline_features = self.memory_bank.get_features_for_outline()
        outline = self.feature_generator.generate_outline(outline_features)
        logging.info(f"Generated outline with {len(outline)} sections")

        logging.info(f'Ranked Features = {ranked_features}')
        logging.info(f"Generated outline = {outline}")

        
        # Get features and their detailed context
        unique_features, detailed_contexts = self.memory_bank.get_features_for_summary()
        logging.info(f"Found {len(unique_features)} unique features with matched facts")
        
        # Prepare enhanced context for summary generation
        enhanced_context = self.prepare_enhanced_context(unique_features, detailed_contexts)
        
        # Generate summary using enhanced context structure
        summary, score, feedback = self.agents.process_chunk_with_feedback(
            "Final_Summary",
            enhanced_context,
            outline
        )
        
        logging.info(f"Generated summary with confidence score: {score}")

        final_summary = self.post_processor.post_process_summary(summary)
        return final_summary, summary,unique_features, outline


    def process_all_meetings(self, input_file_path: str, output_file_path: str,atomic_facts_dir) -> pd.DataFrame:
        """Process multiple meetings from a CSV file and save results incrementally."""
        # Create result directory if it doesn't exist
        os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
        
        # Check if output file already exists to append to it
        all_results = []
        if os.path.exists(output_file_path):
            try:
                existing_results = pd.read_csv(output_file_path)
                all_results = existing_results.to_dict('records')
                logging.info(f"Loaded {len(all_results)} existing results from {output_file_path}")
            except Exception as e:
                logging.warning(f"Could not load existing results, starting fresh: {e}")
        
        # Load the meetings data
        df = pd.read_csv(input_file_path)
        df = df[26:27]
        logging.info(f"total meetings =  {len(df)}")
        # Process each meeting
        for i, row in df.iterrows():
            # self.store_facts_relevance_logs(row['Meeting'],atomic_facts_dir)
            # logging.info("Done")

            # Generate meeting ID
            meeting_id = self.generate_meeting_id(row['transcript'])


            
            # Check if this meeting has already been processed
            already_processed = False
            for result in all_results:
                if result.get('meeting_id') == meeting_id:
                    logging.info(f"Meeting {i+1} already processed. Skipping.")
                    already_processed = True
                    break
            
            if already_processed:
                continue
            
            logging.info(f"Processing meeting {i+1} of {len(df)}")
            
            try:
                # Process the meeting
                refined_summary, raw_summary, important_features, outline = self.process_meeting(
                    row['transcript'],atomic_facts_dir
                )
                
                # Store results
                result = {
                    'meeting_id': meeting_id,
                    'meeting_index': i,
                    'transcript': row['transcript'],
                    'Gold_summary' : row['summary'],
                    'generated_summary': raw_summary,
                    'refined_summary': refined_summary,
                    'important_features': json.dumps(important_features),
                    'outline': json.dumps(outline)
                }
                
                all_results.append(result)
                logging.info(f"Successfully processed meeting {i+1}")
                
                # Save results after each meeting is processed
                current_results_df = pd.DataFrame(all_results)
                current_results_df.to_csv(output_file_path, index=False)
                logging.info(f"Incremental results saved to {output_file_path} after processing meeting {i+1}")
                
            except Exception as e:
                logging.error(f"Error processing meeting {i+1}: {str(e)}")
                continue
        
        # Final save of all results
        if all_results:
            final_results_df = pd.DataFrame(all_results)
            return final_results_df
        else:
            logging.warning("No results were generated.")
            return pd.DataFrame()