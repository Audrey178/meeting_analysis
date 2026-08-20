from typing import List, Dict
from transformers import AutoTokenizer
import re
from docx_ingest import parse_transcript_docx, build_labeled_transcript_text
import json

class ChunkProcessor:
    # Default token budget for a dynamic chunk (see chunk_transcript).
    DEFAULT_CHUNK_TOKEN_BUDGET = 1200

    def __init__(self):
        self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3.8-27B", trust_remote_code=True)
        self.current_position = 0
        # Number of leading '\n' characters stripped by the most recent
        # chunk_transcript() call that advance_position() still needs to
        # account for (see chunk_transcript()/advance_position() below).
        self._pending_skip = 0

    def chunk_transcript(self, transcript: str, token_limit: int = None):
        """
        Returns the next chunk as a dynamic run of whole speaker turns.

        `transcript` is expected to be the labeled text produced by
        build_labeled_transcript_text() — exactly one line per turn
        (e.g. "[PRESENTER] Speaker: ..."). Consecutive turns are packed into
        the chunk one at a time until adding the next turn would exceed
        `token_limit`; the number of turns per chunk is therefore dynamic —
        many short turns (e.g. back-and-forth "vâng ạ", "dạ đúng rồi") pack
        into one chunk, while a couple of long turns may fill it alone.

        Turns are never split mid-way: a chunk always starts with the first
        available turn even if that single turn alone already exceeds
        `token_limit`, so it is still returned whole as a one-turn chunk
        rather than being cut off.

        Args:
            transcript: full labeled transcript text
            token_limit: token budget for the chunk (defaults to
                DEFAULT_CHUNK_TOKEN_BUDGET)

        Returns:
            Tuple[str, int]: (chunk_text, token_count)
        """
        if token_limit is None:
            token_limit = self.DEFAULT_CHUNK_TOKEN_BUDGET

        if self.current_position >= len(transcript):
            return "", 0

        # If the position landed exactly on a turn-separator newline (very
        # common, since advance_position() doesn't count the trailing '\n'
        # of the previously consumed chunk), the remaining text would start
        # with '\n' and split() would yield a leading "" line. That earlier
        # made current_chunk = [""] (truthy) but chunk_text = "" once
        # joined, which callers wrongly read as "end of transcript" and
        # stopped processing early, silently dropping the rest of the
        # transcript. Stripping leading blank lines here prevents that.
        #
        # The stripped characters are still real, unconsumed positions in
        # `transcript`, so their count is remembered here and added back in
        # by advance_position() — otherwise the cursor would land `skip`
        # characters short of the true end of this chunk on every call that
        # strips something, corrupting the next chunk with a stray fragment
        # of the tail of this one.
        remaining = transcript[self.current_position:]
        transcript_from_position = remaining.lstrip('\n')
        self._pending_skip = len(remaining) - len(transcript_from_position)
        if not transcript_from_position:
            return "", 0

        lines = transcript_from_position.split('\n')
        chunk_turns = []
        total_tokens = 0

        for line in lines:
            line_tokens = len(self.tokenizer.encode(line))

            if not chunk_turns:
                # Always take at least one full turn, even if it alone
                # exceeds the budget — never split a turn mid-way.
                chunk_turns.append(line)
                total_tokens = line_tokens
                continue

            if total_tokens + line_tokens > token_limit:
                break

            chunk_turns.append(line)
            total_tokens += line_tokens

        # Join with '\n' so chunk_text stays a verbatim substring of
        # `transcript` starting at current_position — advance_position()
        # relies on len(chunk_text) to move the cursor correctly.
        chunk_text = '\n'.join(chunk_turns)
        return chunk_text, total_tokens

    def advance_position(self, chunk_text: str):
        """Advance position after successful processing"""
        self.current_position += self._pending_skip + len(chunk_text)
        self._pending_skip = 0

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
    
def _load_turns(input_path: str):
    """Load {meeting, turns, docs, entities} from either a .docx transcript or a pre-processed JSON."""
    if input_path.lower().endswith(".docx"):
        return parse_transcript_docx(input_path)

    with open(input_path, 'r', encoding='utf-8') as f:
        return json.load(f)
    
if __name__ == "__main__":
    processor = ChunkProcessor()
    transcript_json = _load_turns('Vietnamese_datasets/processed/GHI_AM_CAI_MEP_THI_VAI.meetingrecord.json')
    transcript_text = build_labeled_transcript_text(transcript_json)
    print("Transcript Text:", transcript_text)
    transcript = "Speaker 1: Hello! How are you?\nSpeaker 2: I'm good, thanks! And you?\nSpeaker 1: I'm fine too."
    chunk, token_count = processor.chunk_transcript(transcript_text)
    for i in range(5):
        chunk, token_count = processor.chunk_transcript(transcript_text)
        processor.advance_position(chunk)
        print(f"Chunk {i+1}:", chunk)
        print(f"Token Count {i+1}:", token_count)
        