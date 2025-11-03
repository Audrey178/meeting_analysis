import logging
import os
import json
import hashlib
import pandas as pd
from typing import Dict, List, Tuple, Any
from model_handler_gemini import ModelHandler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SimpleDocumentSummarizer:
    """
    A simple document summarizer that uses a single LLM call to generate
    general purpose summaries of text documents.
    """
    
    def __init__(self, client, model="gpt-4o"):
        self.client = client
        self.model = model
        
    def generate_document_id(self, document: str) -> str:
        """Generate a unique document ID based on document content."""
        return hashlib.md5(document.encode()).hexdigest()
            
    def generate_summary(self, document: str, word_limit: int = 200) -> str:
        """
        Generate a general-purpose document summary in a single LLM call.
        
        Args:
            document: Document text to summarize
            word_limit: Maximum word count for the summary (default: 200)
            
        Returns:
            Document summary
        """
        # Create system prompt for general-purpose summarization
        system_prompt = """
        You are an expert summarization agent tasked with creating clear, concise document summaries.
        Your goal is to extract the most important information from the document and present it in a coherent summary.

        CRITICAL CONSTRAINTS:
        - Summary MUST be between 150-200 words
        - Use ONLY provided facts from the document
        - NO hallucination or inference beyond what's explicitly stated
        - Focus on the most important information and key points
        - Present as cohesive paragraphs
        - DO NOT use bullet points, numbered lists, or section headers in your summary

        OUTPUT FORMAT:
        - The summary must be in paragraph format only
        - Use well-structured paragraphs that flow naturally
        - No headers, bullet points, or other structural elements
        - Present as a cohesive narrative that covers key points

        SUMMARY CONSIDERATIONS:
        - Identify and prioritize main ideas and key supporting points
        - Maintain the original meaning and intent of the document
        - Preserve critical details while omitting unnecessary ones
        - Ensure logical flow between ideas
        - Use clear, concise language
        - Stay within word limit
        """
        
        # Create user prompt with document
        user_prompt = f"""
        Generate a {word_limit}-word summary of this document:

        Document Text:
        {document}
        
        Remember:
        - Focus on the most important information and key points
        - Stay within {word_limit} words
        - Only use provided information
        - Format as cohesive paragraphs that flow naturally
        - DO NOT use bullet points, headers, or numbered lists
        - Present as a smooth narrative
        """
        
        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "general", 
                max_tokens=4000
            )
            
            # Return the summarized response
            return response
            
        except Exception as e:
            logging.error(f"Error generating summary: {str(e)}")
            return f"Failed to generate summary: {str(e)}"
    
    def process_document(self, document: str, word_limit: int = 200) -> str:
        """
        Process a document to generate a summary.
        
        Args:
            document: Document text
            word_limit: Maximum word count for the summary
            
        Returns:
            Document summary
        """
        # Generate summary
        summary = self.generate_summary(document, word_limit)
        logging.info("Generated document summary")
        
        return summary

    def process_all_meetings(self, input_file_path: str, output_file_path: str) -> pd.DataFrame:
        """
        Process multiple meetings from either a CSV or PKL file and save
        results incrementally. The input file is assumed to have columns:
          - 'Meeting'
          - 'Gold_Summary'
        
        Args:
            input_file_path: Path to CSV or PKL file
            output_file_path: Where to save the CSV of results
        
        Returns:
            DataFrame of processed results
        """
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
        logging.info(f"total meetings =  {len(df)}")
        # Process each document/meeting
        for i, row in df.iterrows():
            # Generate meeting ID
            meeting_id = self.generate_document_id(row['transcript'])
            
            # Check if this meeting has already been processed
            if any(r['meeting_id'] == meeting_id for r in all_results):
                logging.info(f"Meeting {i+1} already processed. Skipping.")
                continue
            
            logging.info(f"Processing meeting {i+1} of {len(df)}")
            
            try:
                # Generate the summary
                raw_summary = self.process_document(row['transcript'])
                
                # Store results
                result = {
                    'meeting_id': meeting_id,
                    'meeting_index': i,
                    'transcript': row['transcript'],
                    'Gold_summary' : row['summary'],
                    'generated_summary': raw_summary,
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
            logging.info("All results processed successfully.")
            return final_results_df
        else:
            logging.warning("No results were generated.")
            return pd.DataFrame()
