#!/usr/bin/env python3
"""
Main script for running MESA pipeline with persona-specific evaluation.
"""

import json
import logging
import os
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from eval_pipeline_persona import EvalPipelinePersona
from baseline_pipeline_persona import BaselinePipelinePersona
from simple_baseline_pipeline_persona import SimpleBaselinePipelinePersona
from client_handler import create_client

def get_project_root():
    """
    Returns the absolute path of the project's root directory.
    Assumes this file is located in <project_root>/src.
    """
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def load_config():
    load_dotenv()
    project_root = get_project_root()
    default_config_path = os.path.join(project_root, "src", "config.json")
    config_path = os.getenv("CONFIG_PATH", default_config_path)
    if not config_path or not os.path.exists(config_path):
        raise FileNotFoundError(f"CONFIG_PATH not found or invalid: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def init_pipeline(config):
    mode = config.get("MODE", 0)
    single_model = config.get("SINGLE_MODEL", True)
    multi_family = config.get("MULTI_FAMILY", False)

    mode_mapping = {
        0: {"postfix": "_ALL_AT_ONCE", "pipeline": SimpleBaselinePipelinePersona},
        1: {"postfix": "_ONE_BY_ONE", "pipeline": BaselinePipelinePersona},
        2: {"postfix": "_THREE_STEP", "pipeline": EvalPipelinePersona},
    }

    pipeline_cls = mode_mapping[mode]["pipeline"]
    postfix = mode_mapping[mode]["postfix"]
    single_model_str = "SInstance" if single_model else "MInstance"
    multi_family_str = "SFamily" if multi_family else "MFamily"


    # Paths from environment
    project_root = get_project_root()

    paths = {
        "criteria": os.getenv("CRITERIA_PATH", os.path.join(project_root, "criteria")),
        "in_context": os.getenv("IN_CONTEXT_LEARNING_SAMPLES", os.path.join(project_root, "report_generation", "outputs", "reports", "feedback_3step.csv")),
        "logging": os.path.join(os.getenv("LOGGING_DIRECTORY", os.path.join(project_root, "_logs")), postfix),
        "samples": os.getenv("SAMPLES_PATH", os.path.join(project_root, "HumanJudgment", "MistekQMSum.csv"))
    }

     
    client = create_client()
    model_name = os.getenv("MODEL_NAME", "gpt-4")

    logger = logging.getLogger(__name__)
    logger.info("[P-MESA] Using model: %s with mode: %d (%s)", model_name, mode, postfix)

    pipeline_instance = pipeline_cls(
        paths["criteria"],
        paths["in_context"],
        client,
        model_name,
        single_model=single_model,
        multi_family=multi_family,
    )

    return pipeline_instance, paths

def load_persona(persona_file_name, personas_path):
    """Load persona data from JSON file."""
    persona_file = os.path.join(personas_path, f"{persona_file_name}.json")
    with open(persona_file, "r", encoding="utf-8") as f:
        return json.load(f)
    
    
def print_structure(data, indent=0, key_name="[root]"):
    prefix = "  " * indent
    if isinstance(data, dict):
        print(f"{prefix}{key_name} -> dict with keys: {list(data.keys())}")
        for k, v in data.items():
            print_structure(v, indent=indent + 1, key_name=str(k))
    elif isinstance(data, (list, tuple)):
        typ = "list" if isinstance(data, list) else "tuple"
        print(f"{prefix}{key_name} -> {typ} of length {len(data)}")
        for i, item in enumerate(data):
            print_structure(item, indent=indent + 1, key_name=f"element[{i}]")
    else:
        # For scalars, just print the type name
        print(f"{prefix}{key_name} -> {type(data).__name__}")


def extract_error_ratings(data):
    """
    Given data with a structure similar to:
    ([
        {
            "criteria": "coreference",
            "selection": [...],
            "filter": [...],
            "score": {"reasoning": "...", "confidence": 9, "rating": 4},
            "protocol": {...}
        }
    ], 0)
    or just a list of sample dictionaries.
    Extracts and returns a dict mapping each sample index to a dict of {error_type: rating}.
    """
    # Determine if data is a tuple (with the samples as first element)
    if isinstance(data, tuple) and len(data) > 0:
        samples = data[0]
    elif isinstance(data, list):
        samples = data
    else:
        raise ValueError("Data must be either a tuple with samples as the first element or a list of samples.")

    result = {}
    for i, sample in enumerate(samples):
        # Defensive programming: ensure sample is a dict
        if not isinstance(sample, dict):
            print(f"Sample at index {i} is not a dict: {sample} (type: {type(sample)})")
            continue  # Or handle accordingly

        error_type = sample.get("criteria")

        score = sample.get("score", {})
        # If score is a string, try converting it to a dictionary
        if isinstance(score, str):
            try:
                score = json.loads(score)
            except json.JSONDecodeError as e:
                print(f"Skipping element at index {i} because score string could not be parsed as JSON: {score}. Error: {e}")
                continue

        # Now check if score is indeed a dict after conversion attempt
        if not isinstance(score, dict):
            print(f"Skipping element at index {i} because score is not a dict even after parsing: {score} (type: {type(score)}).")
            continue
        
        rating = score.get("rating")
        if error_type is not None and rating is not None:
            result[i] = {error_type: rating}
    return result



def run_pipeline(config, 
                pipeline_instance,
                samples_df,
                iteration_log_dir,
                input_col="Input",
                predicted_col="Predicted",
                iteration_idx=0,
                log_path=None,
                file_name="progressive_scores.json",
                persona_col="Persona"):
    logger = logging.getLogger(__name__)
    start_index = config.get("START_INDEX", 0)
    stop_index = config.get("STOP_INDEX", None)
    do_fitting = config.get("DO_FITTING", False)

    # Slice the dataframe if necessary
    if stop_index is None or stop_index <= 0:
        samples_df = samples_df.iloc[start_index:]
    else:
        samples_df = samples_df.iloc[start_index:stop_index]


    logger.info("[P-MESA] Processing rows from index %d to %d (end-exclusive).",
                start_index, stop_index or samples_df.shape[0])

    scores = {}
    human_scores_all = []
    
     # The single JSON file we update row-by-row:
    progressive_json_path = None
    if log_path:
        os.makedirs(log_path, exist_ok=True)
        progressive_json_path = file_name
        logger.info("[P-MESA] Will log row-by-row results to: %s", progressive_json_path)

    for index, row in samples_df.iterrows():
        sample = {
            "summary": row[predicted_col],
            "transcript": row[input_col],
            "persona": row.get(persona_col, None)
        }

        if isinstance(pipeline_instance, EvalPipelinePersona):
            result, quality_score = pipeline_instance.run(sample)
        else:
            result = pipeline_instance.run(sample)
            quality_score = None

        print_structure(result)
        print()
        # print(result)


        scores[index] = {
            "scores": result,
            "quality_score": quality_score,
            "persona": sample["persona"]
        }

        if do_fitting:
            human_scores_row = {metric: {
                "existence": row.get(f"{metric.title()}_Existence"),
                "impact": row.get(f"{metric.title()}_Impact")
            } for metric in ["action_relevance", "context_customization", 
                           "detail_alignment", "priority_alignment"]}
            human_scores_all.append(human_scores_row)

        output_data = {
            "score": result,
            "quality_score": quality_score,
            "persona": sample["persona"]
        }
        if do_fitting:
            output_data["human_scores"] = human_scores_row


        extracted = extract_error_ratings(result)

        # 4) Append to the single JSON file, if any
        if progressive_json_path:
            # (a) Load the existing dictionary from disk, if it exists
            if os.path.isfile(progressive_json_path):
                with open(progressive_json_path, "r", encoding="utf-8") as f:
                    try:
                        existing_data = json.load(f)  # { iteration_str: { row_str: {...} } }
                    except json.JSONDecodeError:
                        existing_data = {}
            else:
                existing_data = {}

            iteration_str = str(iteration_idx)
            if iteration_str not in existing_data:
                existing_data[iteration_str] = {}

            # (b) Add this row’s ratings under [iteration][row_idx]
            existing_data[iteration_str][str(index)] = extracted
            
        with open(progressive_json_path, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=4)
            
        logger.info("[P-MESA] Processed row %d, appended to single JSON file.", index)

    return scores, human_scores_all

def fitting_stage(config, scores, human_scores, iteration_log_dir):
    if not config.get("DO_FITTING", False):
        return None

    logger = logging.getLogger(__name__)
    logger.info("[P-MESA - FITTING] Processing %d samples", len(scores))

    from fitting import Fitting
    fitter = Fitting(
        create_client(),
        os.getenv("MODEL_NAME", "gpt-4"),
        os.getenv("CRITERIA_PATH")
    )
    
    learning_samples, metrics = fitter.run(scores, human_scores)
    
    with open(os.path.join(iteration_log_dir, "quality_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=4)
        
    return learning_samples

def self_training_stage(config, learning_samples, in_context_samples_path):
    if not config.get("SELF_TRAINING", False) or not learning_samples:
        return

    if not os.path.exists(in_context_samples_path):
        os.makedirs(in_context_samples_path)

    grouped_data = {}
    for entry in learning_samples:
        criteria = entry['criteria']
        grouped_data.setdefault(criteria, []).append(entry)

    for criteria, entries in grouped_data.items():
        output_path = os.path.join(in_context_samples_path, f"{criteria}_examples.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=4)

def call_pmesa(
    samples_path=None,
    input_col="Input",
    predicted_col="Predicted",
    persona_col="Persona",
    log_path=None,
    file_name="p_progressive_scores.json"):
    
    configure_logging()
    logger = logging.getLogger(__name__)
    config = load_config()

    pipeline_instance, paths = init_pipeline(config)
    
    if samples_path is None:
        samples_path = paths["samples"]
    
    samples_df = pd.read_csv(samples_path, sep=",")
    logger.info("[P-MESA] Loaded %d samples", len(samples_df))
    
    os.makedirs(paths["logging"], exist_ok=True)

    for iteration_idx in range(config.get("ITERATIONS", 1)):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        iteration_dir = os.path.join(
            paths["logging"],
            f"iteration_{iteration_idx}_{timestamp}_"
            f"{'SInstance' if config.get('SINGLE_MODEL', True) else 'MInstance'}_"
            f"{'SFamily' if config.get('MULTI_FAMILY', False) else 'MFamily'}"
        )
        os.makedirs(iteration_dir, exist_ok=True)

        scores, human_scores = run_pipeline(
            config,
            pipeline_instance, 
            samples_df, 
            iteration_dir,
            input_col=input_col,
            predicted_col=predicted_col,
            iteration_idx=iteration_idx,
            log_path=log_path,
            file_name=file_name,
            persona_col=persona_col
        )
        # learning_samples = fitting_stage(config, scores, human_scores, iteration_dir)
        # self_training_stage(config, learning_samples, paths["in_context"])

        logger.info("[P-MESA] Completed iteration %d", iteration_idx + 1)

    logger.info("\n\n************************** \n [P-MESA] 🏁 All iterations comlpeted. 🏁 \n**************************\n")
    