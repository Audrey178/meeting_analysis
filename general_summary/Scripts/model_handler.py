import time
import random
import logging
import re
import os
from openai import RateLimitError

# Add cost per 1000 tokens (update these based on your OpenAI pricing)
INPUT_COST_PER_1000_TOKENS = 0.00275  # Cost for input tokens per 1000 tokens
OUTPUT_COST_PER_1000_TOKENS = 0.011  # Cost for output tokens per 1000 tokens

class ModelHandler():
    @staticmethod
    def call_model_with_retry(client, messages, model, query_type, category, log_base_path, max_tokens=1000, max_attempts=6, base_delay=3.0, verbose=False):
        """
        Call OpenAI's model with retries. Logs token counts and costs per category to a file.
        
        Parameters:
        - category: The category of the current API call (e.g., "fact extraction", "summary generation")
        - log_base_path: The base directory path where the log files will be stored
        """        
        # Calculate input tokens from content in messages
        input_tokens = sum(len(msg['content'].split()) for msg in messages)
        
        for attempt in range(max_attempts):
            try:
                start_time = time.time()  # Track the start time
                response = ModelHandler.call_model(client, model, messages, query_type, max_tokens)
                response_text = ModelHandler.get_response_text(response, verbose)
                duration = time.time() - start_time

                # Calculate output tokens
                output_tokens = len(response_text.split())
                
                # Calculate cost
                input_cost = (input_tokens / 1000) * INPUT_COST_PER_1000_TOKENS
                output_cost = (output_tokens / 1000) * OUTPUT_COST_PER_1000_TOKENS
                total_cost = input_cost + output_cost

                # Prepare log message
                log_message = (f"Category: {category}\n"
                               f"Input Tokens: {input_tokens}\n"
                               f"Output Tokens: {output_tokens}\n"
                               f"Duration: {duration:.2f} seconds\n"
                               f"Cost - Input Tokens: ${input_cost:.4f}, Output Tokens: ${output_cost:.4f}, Total Cost: ${total_cost:.4f}\n\n")
                
                # Write to log file
                ModelHandler.write_log_to_file(category, log_message, log_base_path)
                
                return response_text
            except RateLimitError as e:
                retry_after = ModelHandler.extract_retry_time(str(e))
                sleep_time = retry_after / 1000 + random.uniform(0, 1) if retry_after else (2 ** (attempt + 1)) + random.uniform(0, 1)
                
                logging.warning(f"Rate limit hit, backing off for {sleep_time:.2f} seconds.")
                time.sleep(sleep_time)
            except Exception as e:
                logging.error(f"Error encountered: {str(e)}")
                break
            finally:
                time.sleep(base_delay)
        
        raise Exception("Max retry attempts reached")

    @staticmethod
    def extract_retry_time(error_message):
        match = re.search(r"Please retry after (\d+) milliseconds", error_message)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def call_model(cl, model, messages, query_type, max_tokens=1000):
        temperature = ModelHandler.get_temperature(query_type)
        response = cl.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            n=1,
            stop=None,
            temperature=temperature,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )
        return response
    
    @staticmethod
    def get_temperature(query_type):
        if query_type == "idea_generation":
            return 0.8  # High temperature for more creative ideas
        elif query_type == "refinement":
            return 0.4  # Moderate temperature for focused refinement
        else:  # general query
            return 0.1  # Low temperature for more consistent, factual responses


    @staticmethod
    def build_message(system_prompt, user_prompt):
        return [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]
        
    @staticmethod
    def get_response_text(response, verbose=False):
        responste_string = response.choices[0].message.content.strip()
        if verbose:
            logging.info(f"Response: {responste_string}")
        return responste_string

    @staticmethod
    def write_log_to_file(category, log_message, log_base_path):
        """Write the log message to the log file based on the category."""
        # Ensure the directory exists
        os.makedirs(log_base_path, exist_ok=True)
        
        # Generate the log file name based on the category
        log_filename = f"{category.lower().replace(' ', '_')}_logs.txt"
        log_file_path = os.path.join(log_base_path, log_filename)
        
        # Write the log message to the file
        with open(log_file_path, "a") as log_file:
            log_file.write(log_message)
            logging.info(f"Logged information to {log_file_path}")