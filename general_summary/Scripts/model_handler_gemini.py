import requests
import json
import time
import random
import logging

class ModelHandler():
    @staticmethod
    def call_model_with_retry(client, messages, model,query_type, max_tokens=1000, max_attempts=6, base_delay=3.0, verbose=False):
        """
        Calls Gemini model with retry logic on rate limits and network failures.

        Args:
            client (dict): Contains 'API_PASSWORD' and 'API_ENDPOINT'
            messages (tuple): (system_instruction, contents) formatted for Gemini
            model (str): Name of the Gemini model (not actually used in this wrapper)
            max_tokens (int): Max response tokens
            max_attempts (int): Retry attempts
            base_delay (float): Delay between retries
            verbose (bool): Whether to log the final response

        Returns:
            Mimicked OpenAI-like response: {"choices": [{"message": {"content": <response>}}]}
        """
        for attempt in range(max_attempts):
            try:
                response = ModelHandler.call_gemini(client, model, messages, max_tokens)
                return response
            except Exception as e:
                if "429" in str(e) or "Rate limit" in str(e):
                    sleep_time = (2 ** (attempt + 1)) + (random.randint(0, 1000) / 1000)
                    logging.warning(f"[Gemini] Rate limit hit, backing off for {sleep_time:.2f} seconds.")
                    time.sleep(sleep_time)
                else:
                    logging.error(f"[Gemini] Error encountered: {str(e)}")
                    break
            finally:
                time.sleep(base_delay)

        raise Exception("Max retry attempts reached")

    @staticmethod
    def call_gemini(client, model, messages, max_tokens=1000):
        headers = {
            "Content-Type": "application/json",
            "api-key": client.get("API_PASSWORD"),
        }

        system_instruction, contents = messages

        data = {
            "system_instruction": system_instruction,
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0,
                "top_p": 0.95,
                "frequency_penalty": 0.5,
                "presence_penalty": 0.5,
            }
        }

        try:
            logging.info(f"[Gemini] Sending request to {client.get('API_ENDPOINT')}")
            response = requests.post(client.get("API_ENDPOINT"), headers=headers, json=data)
            logging.info(f"[Gemini] Response status code: {response.status_code}")

            if response.status_code == 200:
                response_data = response.json()
                full_text = ""

                for chunk in response_data:
                    candidates = chunk.get("candidates", [])
                    for candidate in candidates:
                        parts = candidate.get("content", {}).get("parts", [])
                        for part in parts:
                            full_text += part.get("text", "")

                return full_text #ModelHandler.repack_as_gpt_response(full_text)
            else:
                logging.error(f"[Gemini] Error {response.status_code}: {response.text}")
                raise Exception(f"Gemini API error {response.status_code}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"[Gemini] Request failed: {e}")

    @staticmethod
    def repack_as_gpt_response(full_text):
        """
        Converts Gemini response into OpenAI-compatible format.
        """
        return {
            "choices": [
                {
                    "message": {
                        "content": full_text
                    }
                }
            ]
        }

    @staticmethod
    def build_message(system_prompt, user_prompt):
        """
        Build message in Gemini's required structure.

        Returns:
            Tuple of (system_instruction, contents)
        """
        return (
            {
                "parts": [{"text": system_prompt}]
            },
            [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ]
        )

    @staticmethod
    def get_response_text(response, verbose=False):
        """
        Extract content from repacked response.
        """
        response_string = response["choices"][0]["message"]["content"].strip()
        if verbose:
            logging.info(f"[Gemini] Model response: {response_string}")
        return response_string
