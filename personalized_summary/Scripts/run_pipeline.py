import os
import logging
import json
import pandas as pd
from dotenv import load_dotenv
from openai import AzureOpenAI
from personalized_meeting_summarizer import PersonalizedMeetingSummarizer

load_dotenv()

def run_pipeline():    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    

    MODEL_CONFIG_PATH = os.getenv('CONFIG_PATH')
    DATASET_PATH = os.getenv('DATASET_PATH')
    OUTPUT_PATH = os.getenv('OUTPUT_PATH')
    CHARACTERSHEETS_PATH = os.getenv('CHARACTERSHEETS_PATH')
    PERSONA_TEXT_PATH= os.getenv('PERSONA_TEXT_PATH')

    ATOMIC_FACTS_DIR = os.getenv('ATOMIC_FACTS_DIR')
 
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

    SUMMARIZER = PersonalizedMeetingSummarizer(CLIENT, MODEL_NAME)
    #SUMMARIZER = SimpleMeetingSummarizer(CLIENT, MODEL_NAME)

    if not SUMMARIZER:
        raise ValueError("Application not initialized. Call initialize_app() first.")
    
    results_df = SUMMARIZER.process_all_meetings(DATASET_PATH,OUTPUT_PATH,PERSONA_TEXT_PATH,CHARACTERSHEETS_PATH, ATOMIC_FACTS_DIR)
        
    if isinstance(results_df, dict):
        if len(results_df) == 0:
            logging.warning("process_all_meetings returned an empty dict; no rows to display.")
            df = pd.DataFrame()
        else:
            # If values are already DataFrames, concatenate them
            if all(hasattr(v, "columns") for v in results_df.values()):
                df = pd.concat(results_df.values(), ignore_index=True)
            else:
                # Fallback: treat dict entries as rows
                df = pd.DataFrame.from_dict(results_df, orient="index").reset_index(names=["meeting_id"])
        print(df.head())
    else:
        print(results_df.head())


if __name__ == "__main__":
    run_pipeline()