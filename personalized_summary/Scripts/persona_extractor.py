import json
import logging
import re
import os
from typing import List, Dict, Any
from model_handler import ModelHandler

class PersonaExtractor:
    """
    Extracts persona descriptions from meeting transcripts when explicit persona 
    information isn't already available.
    """
    
    def __init__(self, client, model="gpt-4o"):
        """
        Initialize the persona extractor.
        
        Args:
            client: LLM client for extraction
            model: Model to use for extraction
        """
        self.client = client
        self.model = model
    
    def identify_meeting_participants(self, transcript: str, chunk_processor=None) -> List[str]:
        """
        Extract a list of meeting participants from the transcript.
        
        Args:
            transcript: The meeting transcript text
            chunk_processor: Optional chunk processor with pre_process_chunk method
            
        Returns:
            List of participant names
        """
        # Use the chunk processor if provided
        if chunk_processor and hasattr(chunk_processor, 'pre_process_chunk'):
            processed_facts = chunk_processor.pre_process_chunk(transcript)
            speakers = set()
            for fact in processed_facts:
                if fact.get("speaker") and fact["speaker"].strip():
                    speakers.add(fact["speaker"].strip())
            
            unique_speakers = sorted(list(speakers))
            logging.info(f"Identified {len(unique_speakers)} unique speakers using chunk processor: {unique_speakers}")
            return unique_speakers
        
        # Fallback to regex pattern matching
        speaker_pattern = re.compile(r'^([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*):(?=\s)', re.MULTILINE)
        matches = speaker_pattern.findall(transcript)
        
        # Remove duplicates and sort
        unique_speakers = sorted(list(set(matches)))
        logging.info(f"Identified {len(unique_speakers)} unique speakers: {unique_speakers}")
        
        return unique_speakers
        
    def extract_personas_from_transcript(self, transcript: str, chunk_processor=None) -> List[Dict[str, Any]]:
        """
        Extract persona descriptions from a meeting transcript.
        
        Args:
            transcript: The meeting transcript text
            chunk_processor: Optional chunk processor with pre_process_chunk method
            
        Returns:
            List of persona dictionaries containing roles and descriptions
        """
        # First identify speakers/participants in the meeting
        speakers = self.identify_meeting_participants(transcript, chunk_processor)
        
        # If the chunk processor is available, use it to preprocess the transcript
        if chunk_processor and hasattr(chunk_processor, 'pre_process_chunk'):
            processed_facts = chunk_processor.pre_process_chunk(transcript)
            
            # Group content by speaker for better analysis
            speaker_content = {}
            for fact in processed_facts:
                speaker = fact.get("speaker", "").strip()
                content = fact.get("content", "").strip()
                
                if speaker and content:
                    if speaker not in speaker_content:
                        speaker_content[speaker] = []
                    speaker_content[speaker].append(content)
            
            # Format structured representation of the transcript with speaker turns
            structured_transcript = ""
            for speaker, contents in speaker_content.items():
                structured_transcript += f"Speaker: {speaker}\n"
                structured_transcript += "Content:\n"
                structured_transcript += "\n".join([f"- {content}" for content in contents])
                structured_transcript += "\n\n"
        else:
            structured_transcript = transcript
        
        # Prepare the system prompt for persona extraction
        system_prompt = """
        You are an expert at analyzing meeting transcripts and identifying key information 
        about the participants. Your task is to extract detailed persona descriptions for
        each participant based on what they say and how they interact in the meeting.
        
        Focus on extracting:
        1. Role/title in the organization
        2. Area of expertise or domain knowledge
        3. Perspective or approach they bring to discussions
        4. Decision-making style and priorities
        5. Communication style
        6. Interests and concerns

        **Alert**
        Keep in mind do no add anything not present in the transcript
        Donot assume or hallucinate anything from your end. 
        
        For each participant, create a rich description that captures who they are professionally.
        """
        
        # Prepare the user prompt with the transcript and identified speakers
        user_prompt = f"""
        Below is a meeting transcript with {len(speakers)} identified participants: {', '.join(speakers)}.
        
        Please extract very detailed persona descriptions for each participant. For each persona, provide:
        
        1. role: Their job title or role (if not then assign one unique based on the content)
        2. description: A paragraph describing who they are professionally
        3. expertise_area: Their primary domain of expertise
        4. perspective: Their general approach to problems or discussions
        5. communication_style: How they express themselves
        6. key_priorities: What matters most to them based on their contributions

        **Alert**
        Keep in mind do no add anything not present in the transcript
        Donot assume or hallucinate anything from your end.    
        
        Return the results as a JSON array of persona objects. For any field you cannot determine 
        with reasonable confidence, use the value "Unknown".
        
        Here is the transcript:
        
        {structured_transcript}
        """
        
        try:
            message = ModelHandler.build_message(system_prompt, user_prompt)
            response = ModelHandler.call_model_with_retry(
                self.client, message, self.model, "Fact Verification",    
                category="Persona Extractor", 
                log_base_path="./atomic-facts/data_store/cost_time_logging/",
                verbose=True,
                max_tokens=4000
            )            
            # Parse the JSON response
            personas = self._extract_json_from_response(response)
            print(personas)
            
            # Validate the extracted personas
            validated_personas = self._validate_personas(personas, speakers)
            
            logging.info(f"Successfully extracted {len(validated_personas)} personas")
            return validated_personas
            
        except Exception as e:
            logging.error(f"Error extracting personas: {str(e)}")
            # Fallback: Create basic personas from speaker names
            basic_personas = self._create_basic_personas(speakers)
            logging.info(f"Created {len(basic_personas)} basic personas as fallback")
            return basic_personas
    
    
    def _extract_json_from_response(self, response: str) -> List[Dict[str, Any]]:
        """
        Extract JSON from the model response.
        
        Args:
            response: Model response text
            
        Returns:
            Parsed JSON as a list of persona dictionaries
        """
        try:
            # Look for JSON content in the response
            json_pattern = re.compile(r'```json\s*([\s\S]*?)\s*```|(\[[\s\S]*\])')
            match = json_pattern.search(response)
            
            if match:
                json_str = match.group(1) if match.group(1) else match.group(2)
                return json.loads(json_str)
            
            # Try to load the entire response as JSON if no pattern match
            return json.loads(response)
            
        except json.JSONDecodeError:
            logging.error("Failed to parse JSON from response")
            logging.debug(f"Problematic response: {response}")
            raise
    
    def _validate_personas(self, personas: List[Dict[str, Any]], speakers: List[str]) -> List[Dict[str, Any]]:
        """
        Validate and clean up extracted personas.
        
        Args:
            personas: List of extracted persona dictionaries
            speakers: List of identified speakers
            
        Returns:
            Validated list of persona dictionaries
        """
        validated = []
        required_fields = ["role", "description", "expertise_area", "perspective"]
        
        for persona in personas:
            # Ensure all required fields exist
            for field in required_fields:
                if field not in persona:
                    persona[field] = "Unknown"
            
            # Check if persona can be mapped to a speaker
            has_valid_name = False
            if "name" in persona:
                for speaker in speakers:
                    if speaker.lower() in persona["name"].lower() or persona["name"].lower() in speaker.lower():
                        has_valid_name = True
                        break
            
            # Add only if it has a valid name or if we couldn't match any names
            if has_valid_name or "name" not in persona:
                validated.append(persona)
        
        return validated
    
    def _create_basic_personas(self, speakers: List[str]) -> List[Dict[str, Any]]:
        """
        Create basic personas from speaker names when extraction fails.
        
        Args:
            speakers: List of identified speakers
            
        Returns:
            List of basic persona dictionaries
        """
        basic_personas = []
        
        for speaker in speakers:
            basic_personas.append({
                "name": speaker,
                "role": "Meeting Participant",
                "description": f"Participant identified as {speaker} in the meeting transcript.",
                "expertise_area": "Unknown",
                "perspective": "Unknown",
                "communication_style": "Unknown",
                "key_priorities": "Unknown"
            })
        
        return basic_personas
    
    def save_personas_to_json(self, personas: List[Dict[str, Any]], output_path: str) -> None:
        """
        Save extracted personas to a JSON file.
        
        Args:
            personas: List of persona dictionaries
            output_path: Path to save the JSON file
        """
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w') as f:
                json.dump(personas, f, indent=2)
            logging.info(f"Saved {len(personas)} personas to {output_path}")
        except Exception as e:
            logging.error(f"Error saving personas to JSON: {str(e)}")
            raise
    
    def load_personas_from_json(self, file_path: str) -> List[Dict[str, Any]]:
        """
        Load personas from a JSON file if it exists.
        
        Args:
            file_path: Path to the JSON file
            
        Returns:
            List of persona dictionaries if file exists, empty list otherwise
        """
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    personas = json.load(f)
                logging.info(f"Loaded {len(personas)} personas from {file_path}")
                return personas
            else:
                logging.info(f"Persona file {file_path} does not exist")
                return []
        except Exception as e:
            logging.error(f"Error loading personas from JSON: {str(e)}")
            return []

    def extract_and_save_personas(self, transcript: str, output_path: str, chunk_processor=None, force_extract: bool = False) -> List[Dict[str, Any]]:
        """
        Check if personas exist, otherwise extract from transcript and save to JSON file.
        
        Args:
            transcript: Meeting transcript text
            output_path: Path to save the extracted personas
            chunk_processor: Optional chunk processor for transcript preprocessing
            force_extract: If True, extract personas even if file already exists
            
        Returns:
            List of extracted or loaded persona dictionaries
        """

        normalized_path = os.path.normpath(output_path)

        # Check if personas already exist
        if not force_extract:
            existing_personas = self.load_personas_from_json(normalized_path)
            if existing_personas:
                logging.info(f"Using {len(existing_personas)} existing personas from {normalized_path}")
                return existing_personas
        
        # If no existing personas or force_extract is True, extract new ones
        personas = self.extract_personas_from_transcript(transcript, chunk_processor)
        self.save_personas_to_json(personas, normalized_path)
        return personas

# Example usage:
"""
from personalized_meeting_summarizer import PersonalizedMeetingSummarizer
from persona_extractor import PersonaExtractor
import client_implementation

# Initialize your components
client = client_implementation.Client()  # Your OpenAI client
chunk_processor = PersonalizedMeetingSummarizer(client).chunk_processor

# Create extractor
extractor = PersonaExtractor(client)

# Extract personas from a single meeting transcript
with open("meeting_transcript.txt", "r") as f:
    transcript = f.read()

# Extract and save personas


# Print extracted personas
for persona in personas:
    print(f"Name: {persona.get('name', 'Unknown')}")
    print(f"Role: {persona.get('role', 'Unknown')}")
    print(f"Expertise: {persona.get('expertise_area', 'Unknown')}")
    print("---")
"""