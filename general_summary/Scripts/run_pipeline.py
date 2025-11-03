import os
import logging
import json
from dotenv import load_dotenv
from openai import AzureOpenAI
import pandas as pd
from post_processing import PostProcessor
from dataset_processor import DatasetProcessor
from simple_document_summarizer import SimpleDocumentSummarizer
from meeting_summarizer import MeetingSummarizer
from single_prompt_meeting_summarizer import SinglePromptMeetingSummarizer

# Load environment variables
load_dotenv()

def run_pipeline():    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    

    MODEL_CONFIG_PATH = os.getenv('CONFIG_PATH')
    DATASET_PATH = os.getenv('DATASET_PATH', './datasets')
    OUTPUT_PATH = os.getenv('OUTPUT_PATH', './output_summaries')
    LOG_BASE_PATH = os.getenv('LOG_BASE_PATH', './data_store')

    if not DATASET_PATH:
        raise ValueError("DATASET_PATH environment variable not set")

    with open(MODEL_CONFIG_PATH) as config_file:
            config = json.load(config_file)

    API_KEY = config["api_key"]
    API_VERSION = config["api_version"]
    ENDPOINT = config["endpoint"]
    MODEL_NAME = config["model"]

    logging.info(f"Using model: {MODEL_NAME} with endpoint {ENDPOINT}")


    logging.info("Using model: %s with endpoint %s", MODEL_NAME, ENDPOINT)

    CLIENT = AzureOpenAI(
        api_key=API_KEY,
        api_version=API_VERSION,
        azure_endpoint=ENDPOINT
    )    

    SUMMARIZER = SinglePromptMeetingSummarizer(CLIENT,LOG_BASE_PATH,MODEL_NAME)
    if not SUMMARIZER:
        raise ValueError("Application not initialized. Call initialize_app() first.")

    logging.info(f"Processing dataset: {DATASET_PATH}")
    results_df = SUMMARIZER.process_all_meetings(DATASET_PATH,OUTPUT_PATH)
    print(results_df.head())

if __name__ == "__main__":
    # Run the pipeline
    run_pipeline()