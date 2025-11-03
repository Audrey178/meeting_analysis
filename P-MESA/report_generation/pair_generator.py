import os
import json
import pandas as pd

# Directory containing your JSON files
directory = 'MAD-SumEval/analysis/in-files/data/3step-single-MAD'

# Initialize a dictionary to hold the data for each error type
error_data = {
    'omission': [],
    'irrelevance': [],
    'incoherence': [],
    'coreference': [],
    'hallucination': [],
    'structure': [],
    'repetition': [],
    'language': []
}

# Loop through all files in the directory
for filename in os.listdir(directory):
    if filename.endswith(".json"):
        filepath = os.path.join(directory, filename)

        with open(filepath, 'r') as file:
            data = json.load(file)

            # Extract the "score" section
            for score_entry in data['score']:
                error_type = score_entry['criteria']
                model_score = score_entry['score']['rating']
                model_reason = score_entry['score']['reasoning']
                confidence = score_entry['score']['confidence']

                # Extract the corresponding human score for that error type
                human_score_data = data['human_scores'].get(error_type, None)
                if human_score_data:
                    human_existence = human_score_data['existence']
                    human_impact = human_score_data['impact']
                    # Check if 'reasoning' is NaN or None, replace it with 'n/a'
                    human_reason = human_score_data.get('reasoning')

                    # If human_reason is NaN, replace with 'n/a'
                    if pd.isna(human_reason):
                        human_reason = 'n/a'

                    # Append the model-human score pair to the relevant error type
                    error_data[error_type].append({
                        'file': filename,
                        'model_score': model_score,
                        'model_reason': model_reason,
                        'confidence': confidence,
                        'human_existence': human_existence,
                        'human_impact': human_impact,
                        'human_reason': human_reason,
                    })

# Create output files for each error type
output_directory = 'MAD-SumEval/report_generation/outputs/pairs/3step-MAD'
if not os.path.exists(output_directory):
    os.makedirs(output_directory)

# Save each error type's data into a separate CSV file
for error_type, score_pairs in error_data.items():
    df = pd.DataFrame(score_pairs)
    output_path = os.path.join(output_directory, f'{error_type}_scores.csv')
    df.to_csv(output_path, index=False)

print("Data extraction complete.")
