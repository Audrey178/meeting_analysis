from typing import List, Dict
from transformers import GPT2Tokenizer
import re

class ChunkProcessor:
    def __init__(self):
        self.tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
        self.current_position = 0
        self.MIN_CHUNK_SIZE = 500
        self.INITIAL_CHUNK_SIZE=1200
        self.MAX_CHUNK_SIZE = 1800
        self.STEP_SIZE = 100

    def chunk_transcript(self, transcript: str, token_limit: int):
        """
        Returns a single chunk of transcript that fits within token_limit.
        
        Args:
            transcript: Full transcript text
            token_limit: Desired token limit for the chunk
            
        Returns:
            Tuple[str, int]: (chunk_text, actual_tokens_used)
        """
        if self.current_position >= len(transcript):
            return "", 0

        # Ensure token limit is within bounds
        actual_limit = max(min(token_limit, self.MAX_CHUNK_SIZE), self.MIN_CHUNK_SIZE)
        
        remaining_transcript = transcript[self.current_position:]
        lines = remaining_transcript.split('\n')
        
        current_chunk = []
        current_token_count = 0

        for line in lines:
            line_token_count = len(self.tokenizer.encode(line))
            
            if current_token_count + line_token_count <= actual_limit:
                current_chunk.append(line)
                current_token_count += line_token_count
            else:
                if not current_chunk:
                    # Handle long lines by taking partial
                    words = line.split()
                    partial_line = []
                    for word in words:
                        word_token_count = len(self.tokenizer.encode(word + ' '))
                        if current_token_count + word_token_count <= actual_limit:
                            partial_line.append(word)
                            current_token_count += word_token_count
                        else:
                            break
                    if partial_line:
                        current_chunk.append(' '.join(partial_line))
                break

        if not current_chunk:
            return "", 0

        chunk_text = '\n'.join(current_chunk)
        return chunk_text, current_token_count

    def advance_position(self, chunk_text: str):
        """Advance position after successful processing"""
        self.current_position += len(chunk_text)

    def reset_position(self):
        """Reset for new transcript"""
        self.current_position = 0

    def pre_process_chunk(self,chunk: str) -> List[Dict[str, str]]:
        lines = chunk.split('\n')
        atomic_facts = []
        current_speaker = ""
        
        for line in lines:
            if ':' in line:
                current_speaker, content = line.split(':', 1)
                current_speaker = current_speaker.strip()
                content = content.strip()
            else:
                content = line.strip()
            
            # Split content into sentences
            sentences = re.split(r'(?<=[.!?])\s+', content)
            for sentence in sentences:
                if sentence:
                    atomic_facts.append({
                        "speaker": current_speaker,
                        "content": sentence
                    })
            
        
        return atomic_facts