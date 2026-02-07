"""Transcript preprocessing agent for meeting_mcp.

Provides simple cleaning/chunking for meeting transcripts. This agent
is synchronous and intended to be called from the `TranscriptTool` which
runs blocking work in a thread executor.
"""
from typing import List, Dict, Any, Optional
import logging
import uuid

from ..protocols.a2a import AgentCard, AgentCapability, A2AMessage, PartType

logger = logging.getLogger("meeting_mcp.agents.transcript_preprocessing_agent")


class TranscriptPreprocessingAgent:
    def __init__(self):
        self.agent_id = "transcript-preprocessor"
        self.name = "Transcript Preprocessing Agent"

        # agent metadata for discovery/A2A
        self.agent_card = AgentCard(
            agent_id=self.agent_id,
            name=self.name,
            description="Cleans and chunks meeting transcripts",
            version="0.1.0",
            base_url="",
            capabilities=[
                AgentCapability(name="handle_process_message", description="Process transcripts via A2A message handler", parameters={"transcripts": "List[str]", "chunk_size": "int"})
            ],
        )

    def process(self, transcripts: List[str], chunk_size: int = 1500) -> Dict[str, Any]:
        """Public API: route through the A2A message handler for consistent behavior.

        This method builds an `A2AMessage` and passes it to
        `handle_process_message`, then extracts and returns the results.
        """
        msg = A2AMessage(message_id=str(uuid.uuid4()), role="user")
        # Use the same JSON shape `handle_process_message` expects
        msg.add_json_part({"transcripts": transcripts, "chunk_size": chunk_size})
        resp = self.handle_process_message(msg)

        # Extract the JSON payload from the response message
        for part in getattr(resp, "parts", []):
            if part.content_type == PartType.JSON:
                content = part.content
                if isinstance(content, dict) and content.get("status") == "success":
                    return content.get("results", {})
                return content

        return {}

    def get_agent_card(self) -> Dict[str, Any]:
        return self.agent_card.to_dict()

    def handle_process_message(self, message: A2AMessage) -> A2AMessage:
        transcripts: List[str] = []
        chunk_size: int = 1500
        for part in message.parts:
            if part.content_type == PartType.JSON:
                # allow either full params or direct list
                content = part.content
                if isinstance(content, dict):
                    transcripts = content.get("transcripts") or content.get("data") or []
                    chunk_size = content.get("chunk_size", chunk_size)
                elif isinstance(content, list):
                    transcripts = content
                break

        # Core processing logic moved into a private implementation to avoid
        # recursion when `process()` routes through this handler.
        def _process_impl(transcripts: List[str], chunk_size: int) -> Dict[str, Any]:
            import re
            import unicodedata

            contractions = {
                "can't": "cannot", "won't": "will not", "n't": " not", "'re": " are",
                "'s": " is", "'d": " would", "'ll": " will", "'t": " not",
                "'ve": " have", "'m": " am"
            }
            filler_words = [r'\bum\b', r'\buh\b', r'\byou know\b', r'\blike\b', r'\bokay\b', r'\bso\b', r'\bwell\b']
            speaker_tag_pattern = r'^\s*([A-Za-z]+ ?\d*):'
            timestamp_pattern = r'\[\d{1,2}:\d{2}(:\d{2})?\]'
            special_char_pattern = r'[^\w\s.,?!]'

            def expand_contractions(text: str) -> str:
                for k, v in contractions.items():
                    text = re.sub(k, v, text)
                return text

            def clean_text(text: str) -> str:
                text = unicodedata.normalize('NFKC', text)
                text = text.lower()
                text = expand_contractions(text)
                text = re.sub(timestamp_pattern, '', text)
                text = re.sub(speaker_tag_pattern, '', text, flags=re.MULTILINE)
                for fw in filler_words:
                    text = re.sub(fw, '', text)
                text = re.sub(special_char_pattern, '', text)
                text = re.sub(r'\s+', ' ', text)
                return text.strip()

            processed: List[str] = []
            total_words = 0
            for t in transcripts:
                t = (t or '').strip()
                if not t:
                    continue
                t = clean_text(t)
                words = t.split()
                total_words += len(words)
                for i in range(0, len(words), chunk_size):
                    chunk = ' '.join(words[i:i+chunk_size])
                    if chunk:
                        processed.append(chunk)

            debug_info = {
                "input_transcripts": len(transcripts),
                "total_words": total_words,
                "chunk_size": chunk_size,
                "chunks_produced": len(processed),
                "sample_chunks": processed[:3]
            }
            logger.debug("TranscriptPreprocessing: %s", debug_info)

            return {"processed": processed, "debug": debug_info}

        result = _process_impl(transcripts, chunk_size=chunk_size)
        resp = A2AMessage(message_id=str(uuid.uuid4()), role="agent")
        resp.add_json_part({"status": "success", "results": result})
        return resp


__all__ = ["TranscriptPreprocessingAgent"]
