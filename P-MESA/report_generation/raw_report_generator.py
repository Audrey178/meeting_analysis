import pandas as pd
import os
from openai import AzureOpenAI

import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from SimpleMAD.scripts.model_handler import ModelHandler

def likert_score_feedback(metric_score, human_score):
    """
    Categorize the difference between a metric score and a human score
    based on the provided Likert-like scale.
    """
    difference = abs(metric_score - human_score)

    if (metric_score == 0 and human_score >= 1):
        return ("Error Detection Discrepancy",
                f"Metric detects no error (0), while the human assessment detects an error (1-5). (Human score: {human_score}; Metric score: {metric_score})")

    if (metric_score >= 1 and human_score == 0):
        return ("Error Detection Discrepancy",
                f"Human assessment detects no error (0), while the metric detects an error (1-5). (Human score: {human_score}; Metric score: {metric_score})")

    if difference == 0:
        return ("No Difference", f"The metric score matches the human judgment exactly. (Human score: {human_score}; Metric score: {metric_score})")

    elif difference == 1:
        return ("Minor Difference", f"The scores differ by one point, indicating a minor disagreement in severity. (Human score: {human_score}; Metric score: {metric_score})")

    elif difference == 2:
        return ("Moderate Difference", f"The scores differ by two points, indicating a more significant disagreement. (Human score: {human_score}; Metric score: {metric_score})")

    elif difference >= 3:
        return ("Major Difference", f"The scores differ by three or more points, reflecting a drastic disagreement. (Human score: {human_score}; Metric score: {metric_score})")

    return ("Unknown", f"The case does not fit into predefined categories. (Human score: {human_score}; Metric score: {metric_score})")


def reasoning_feedback(model_reasoning, human_reasoning, client, model_id):
    system_prompt = (
        "You are a judge tasked to decide if the candidate reasoning aligns with the human reasoning."
        "It is fine if the reasoning is not exactly the same as the human reasoning."
        "It is fine if the reasoning mentions additional information that is not present in the human reasoning."
        "It is also fine if the reasoning is shorter than the human reasoning and leaves out minor details."
        "At the end, you have to assign a quality score to the reasoning from 0 meaning very bad to 100 meaning perfect."
    )

    user_prompt = (
        f"Judge the quality of the reasoning provided by the candidate.\n"
        f"Candidate reasoning: **{model_reasoning}**\n"
        f"Human reasoning: **{human_reasoning}**\n"
        "Return a chain-of-thought reasoning process and a single-value quality score between 0 (low quality) and 100 (high quality)."
        "Do not add any additional comments or preamble."
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


# Directory containing the extracted scores
directory = 'MAD-SumEval/report_generation/outputs/pairs/3step-MAD'
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

# Iterate over each CSV file (one for each error type)
for file in os.listdir(directory):
    if file.endswith('.csv'):
        print(f"Processing file: {file}")
        filepath = os.path.join(directory, file)
        df = pd.read_csv(filepath)

        print(df.columns)

        # Ensure required columns exist
        required_columns = ['model_reason', 'human_reason', 'model_score', 'human_impact']
        if all(column in df.columns for column in required_columns):

            print("Columns exist")

            # Add new columns for LLM's analysis and difference category if not present
            if 'gpt_analysis' not in df.columns:
                df['gpt_analysis'] = None
            if 'difference_category' not in df.columns:
                df['difference_category'] = None

            for index, row in df.iterrows():
                model_reasoning = row['model_reason']
                human_reasoning = row['human_reason']

                # Handle missing reasoning gracefully
                if pd.isna(model_reasoning) or pd.isna(human_reasoning):
                    reason_feedback = "Missing reasoning"
                else:
                    # Compare the reasoning using the GPT-4 LLM
                    reason_feedback = reasoning_feedback(model_reasoning, human_reasoning, CLIENT, MODEL_NAME)

                model_score = row['model_score']  # Assuming 'model_score' column exists and is numeric
                human_score = row['human_impact']  # Assuming 'human_score' column exists and is numeric

                # Handle missing scores gracefully
                if pd.isna(model_score) or pd.isna(human_score):
                    likert_feedback = "Missing score data"
                else:
                    likert_feedback = likert_score_feedback(int(model_score), int(human_score))

                # Update dataframe with the analysis and category
                df.at[index, 'feedback_reasoning'] = reason_feedback
                df.at[index, 'feedback_likert'] = likert_feedback[0]

            # Save the updated CSV file with the analysis
            df.to_csv(filepath, index=False)

print("Comparison complete and reports generated.")
