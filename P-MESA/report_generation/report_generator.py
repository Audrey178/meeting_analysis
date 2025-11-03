import openai
import pandas as pd
import os

from openai import AzureOpenAI

import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from SimpleMAD.scripts.model_handler import ModelHandler

def generate_overall_feedback(feedbacks, client, model_id):
    """
    Send the aggregated individual feedback to GPT-4 and request an overall summary.
    """
    system_prompt = (
        "You are tasked with providing an overall summary based on individual feedback about summaries. "
        "The feedback provided includes assessments of the model's reasoning and differences between the human and model's score for specific summaries."
        "Your goal is to analyze these individual feedbacks."
        "Based on this feedback, provide actionable suggestions on improving both the reasoning and the scoring."
        "You should highlight patterns, common issues, and any major differences. Be concise but thorough."
        "Provide individual feedback blocks for the reasoning and scoring."
    )

    user_prompt = (
        f"Here are the individual feedbacks for multiple summaries:\n"
        f"{feedbacks}\n"
        "Please generate a high-level overall feedback summary based on these individual feedbacks."
        "Tell step by step how the reasoning and scoring differ and state the most common issues."
        "Do not add any comment on chaning an architecture or scoring system as these are perfect, the goal is to tweak the current model and tell it how to rate or reason more closely to human."
    )

    message = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    response_raw = ModelHandler.call_model_with_retry(client, message, model_id, max_tokens=4000)
    response = response_raw.choices[0].message.content.strip()
    # logging.info(f"Response: {response}")
    print(f"Response: {response}")
    return response


# Directory containing the CSV files with individual feedbacks
TYPE= '3step-MAD'
directory = 'MAD-SumEval/report_generation/outputs/pairs/' + TYPE
MODEL_CONFIG_PATH = "config_gpt.json"

# ----------

with open(MODEL_CONFIG_PATH) as config_file:
    config = json.load(config_file)

API_KEY = config["api_key"]
API_VERSION = config["api_version"]
ENDPOINT = config["endpoint"]
MODEL_NAME = config["model"]

print(f"Using model: {MODEL_NAME} with endpoint {ENDPOINT}")

CLIENT = AzureOpenAI(
    api_key=API_KEY,
    api_version= API_VERSION,
    azure_endpoint=ENDPOINT,
)

# ---------

# Dictionary to hold feedback per error type
feedback_dict = {}

# Iterate over each CSV file to collect individual feedback and generate overall suggestions
for file in os.listdir(directory):
    if file.endswith('.csv'):
        filepath = os.path.join(directory, file)
        df = pd.read_csv(filepath)

        # Assuming 'gpt_analysis' and 'difference_category' columns contain the feedbacks
        if 'gpt_analysis' in df.columns and 'difference_category' in df.columns:

            # Collect feedback from all rows into one list
            all_feedbacks = []
            for index, row in df.iterrows():
                feedback = f"Reasoning Feedback: {row['feedback_reasoning']}; Score Difference Category: {row['feedback_likert']}"
                all_feedbacks.append(feedback)

            # Join all the individual feedbacks into one large string
            aggregated_feedback = "\n".join(all_feedbacks)

            # Generate the file-specific feedback using GPT-4
            file_feedback = generate_overall_feedback(aggregated_feedback, CLIENT, MODEL_NAME)

            # Store the feedback in the dictionary using the file name as the key
            feedback_dict[file] = {
                'aggregated_feedback': aggregated_feedback,
                'suggestions': file_feedback
            }

# Save the feedback dictionary into a JSON file
with open("MAD-SumEval/report_generation/outputs/reports/feedback_"+TYPE+".csv", "w") as json_file:
    json.dump(feedback_dict, json_file, indent=4)

print("Feedback generation and suggestions complete. Results saved to 'overall_feedback_suggestions.json'.")
