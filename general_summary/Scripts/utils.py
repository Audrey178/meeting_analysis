import re
import json
def _clean_response(response):
    # Remove any markdown code block indicators
    response = re.sub(r'```(?:json)?\s*', '', response)
    response = re.sub(r'\s*```\s*', '', response)

    # Remove any leading/trailing whitespace
    response = response.strip()

    # If the response starts with a single quote and ends with a single quote, remove them
    if response.startswith("'") and response.endswith("'"):
        response = response[1:-1]

    # Some backends (e.g. reasoning models) prepend free-form commentary/thinking
    # before the actual JSON payload. If the string isn't already bare JSON,
    # fall back to slicing out the outermost {...} or [...] block, whichever
    # opens first.
    stripped = response.strip()
    if not (stripped.startswith('[') or stripped.startswith('{')):
        best = None
        for opener, closer in (('[', ']'), ('{', '}')):
            start = response.find(opener)
            if start == -1:
                continue
            if best is None or start < best[0]:
                best = (start, closer)
        if best is not None:
            start, closer = best
            end = response.rfind(closer)
            if end > start:
                response = response[start:end + 1]

    return response

def _clean_response_relevant_facts(response):
    """Clean and format the response for proper JSON parsing."""
    
    # Remove any markdown code block indicators
    response = re.sub(r'```(?:json)?\s*', '', response)
    response = re.sub(r'\s*```\s*', '', response)
    
    # Remove any leading/trailing whitespace
    response = response.strip()
    
    # If the response starts with a single quote and ends with a single quote, remove them
    if response.startswith("'") and response.endswith("'"):
        response = response[1:-1]
        
    # Handle potential JSON formatting issues
    try:
        # Try to detect if it's already a valid JSON
        json.loads(response)
        return response
    except json.JSONDecodeError:
        # Clean up common JSON formatting issues
        
        # Fix unquoted keys
        response = re.sub(r'(?<=\{|\,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'"\1":', response)
        
        # Fix single quotes to double quotes
        response = re.sub(r"'([^']*)':", r'"\1":', response)  # Fix keys
        response = re.sub(r':\s*\'([^\']*?)\'(?=\s*[,}])', r':"\1"', response)  # Fix values
        
        # Fix missing quotes around string values
        response = re.sub(r':\s*([a-zA-Z][a-zA-Z0-9_\s]*?)(?=\s*[,}])', r':"\1"', response)
        
        # Handle potential unterminated strings
        response = re.sub(r'("(?:[^"\\]|\\.)*)"?(?=\s*[,}\]])', r'\1"', response)
        
        # Ensure array brackets if missing
        if not response.startswith('['):
            response = f'[{response}]'
        if not response.endswith(']'):
            response = f'{response}]'
            
        return response

def _normalise_feedback(feedback) -> str:
    """Return feedback as a single string."""
    if isinstance(feedback, list):
        return " ".join(str(item) for item in feedback)
    return str(feedback)
