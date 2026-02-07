import re
import json
import torch
import logging

logger = logging.getLogger("meeting_mcp.agents.mistral_summarizer")


def extract_last_json(text, chunk_index=None):
    """Module-level extractor: prefer ```json``` fenced blocks then balanced braces.
    Returns best-effort JSON string or None. Logs debug points for troubleshooting.
    """
    import re
    if chunk_index is None:
        ci = "?"
    else:
        ci = str(chunk_index)
    logger.debug("[Mistral][Chunk %s] extract_last_json called (len=%d)", ci, len(text) if text else 0)
    # 1) Look for ```json``` fenced blocks first — prefer the last one (model may include an example template earlier)
    matches = list(re.finditer(r"```json\s*(\{.*?\})\s*```", text, flags=re.S))
    if matches:
        candidate = matches[-1].group(1)
        logger.debug("[Mistral][Chunk %s] Found %d ```json``` fenced block(s); using last one.", ci, len(matches))
    else:
        # 2) Fall back to finding the last top-level {...} block using brace balancing
        starts = []
        ends = []
        brace_count = 0
        start = None
        for i, c in enumerate(text):
            if c == '{':
                if brace_count == 0:
                    start = i
                brace_count += 1
            elif c == '}':
                brace_count -= 1
                if brace_count == 0 and start is not None:
                    starts.append(start)
                    ends.append(i + 1)
                    start = None
        if starts and ends:
            candidate = text[starts[-1]:ends[-1]]
            logger.debug("[Mistral][Chunk %s] Found last balanced JSON block at %d-%d.", ci, starts[-1], ends[-1])
        else:
            logger.debug("[Mistral][Chunk %s] No JSON block found in model output.", ci)
            return None

    fixed = candidate
    try:
        # 3) Minor auto-fixes
        if fixed.count("'") > fixed.count('"'):
            fixed = fixed.replace("'", '"')
            logger.debug("[Mistral][Chunk %s] Replaced single quotes in candidate JSON.", ci)
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
        # Try parsing
        try:
            json.loads(fixed)
            logger.debug("[Mistral][Chunk %s] Candidate JSON parsed successfully.", ci)
            return fixed
        except Exception as parse_e:
            logger.debug("[Mistral][Chunk %s] Candidate JSON failed to parse: %s", ci, parse_e)
            return fixed
    except Exception as e:
        logger.exception("[Mistral][Chunk %s] Error while fixing candidate JSON: %s", ci, e)
        return fixed

def summarize_with_mistral(mistral_tokenizer, mistral_model, transcript, meeting_id):
    logger.info("[Mistral] summarize_with_mistral called. Meeting ID: %s", meeting_id)
    # Default generation / context settings (tuned for mistral-7B-Instruct-v0.2 with 4096 context)
    model_context_tokens = 4096
    generation_max_new_tokens = 512
    safety_margin = 128
    # Accept either a string (single transcript) or a list (pre-chunked)
    if isinstance(transcript, list):
        transcript_chunks = [t for t in transcript if t and isinstance(t, str) and len(t.split()) >= 10]
        logger.debug("[Mistral] Received transcript as list. %d valid chunks.", len(transcript_chunks))
        if not transcript_chunks:
            logger.warning("[Mistral] No valid transcript chunks for summarization.")
            return {
                'meeting_id': meeting_id,
                'summary_text': "Transcript too short for summarization.",
                'action_items': []
            }
    else:
        if not transcript or not isinstance(transcript, str) or len(transcript.split()) < 10:
            logger.warning("[Mistral] Transcript too short for summarization.")
            return {
                'meeting_id': meeting_id,
                'summary_text': "Transcript too short for summarization.",
                'action_items': []
            }
        def chunk_text_by_tokens(text, tokenizer, model_context_tokens=model_context_tokens, max_new_tokens=generation_max_new_tokens, safety_margin=safety_margin):
            """Chunk by tokenizer tokens using a safe prompt token budget.

            Defaults tuned for mistral-7B-Instruct with a 4096 token context window.
            """
            max_prompt_tokens = model_context_tokens - max_new_tokens - safety_margin
            if max_prompt_tokens <= 0:
                raise ValueError("model_context_tokens too small for requested generation length")
            # Encode to token ids then slice
            try:
                ids = tokenizer.encode(text, add_special_tokens=False)
            except Exception:
                ids = tokenizer(text, add_special_tokens=False)["input_ids"]
            chunks = []
            for i in range(0, len(ids), max_prompt_tokens):
                slice_ids = ids[i:i+max_prompt_tokens]
                chunks.append(tokenizer.decode(slice_ids, skip_special_tokens=True))
            return chunks

        # Use token-aware chunking for reliable context/window handling on a 4096-token model
        transcript_chunks = chunk_text_by_tokens(transcript, mistral_tokenizer, model_context_tokens=model_context_tokens, max_new_tokens=generation_max_new_tokens, safety_margin=safety_margin)
        logger.debug("[Mistral] Transcript split into %d chunk(s) (token-aware chunks for %d-context).", len(transcript_chunks), model_context_tokens)

    all_summaries = []
    all_action_items = []

    for idx, chunk in enumerate(transcript_chunks):
        logger.debug("[Mistral][Chunk %d] Processing chunk of length %d words.", idx+1, len(chunk.split()))
        mistral_prompt = (
            "You are an AI specialized in analyzing meeting transcripts.\n"
            "Your task is to produce:\n"
            "1. A clear and concise SUMMARY of the meeting as a numbered or bulleted list (do not use 'point 1', 'point 2', use real content).\n"
            "2. A list of ACTION ITEMS as an array of objects. Use issue_type: 'Story' for major feature creation and 'Task' or 'Bug' for technical sub-work. Each action item must include: summary, assignee, issue_type, and a logical due_date.\n"
            "3. A list of DECISIONS made during the meeting.\n"
            "4. A list of RISKS, blockers, or concerns raised.\n"
            "5. A list of FOLLOW-UP QUESTIONS that attendees should clarify.\n"
            "\n"
            "INSTRUCTIONS:\n"
            "- Read the provided meeting transcript thoroughly.\n"
            "- Do NOT invent information. Only extract what is explicitly or implicitly present.\n"
            "- If some sections have no information, return an empty list.\n"
            "- Keep summary short but complete (5–8 bullet points or numbers).\n"
            "- Use simple, business-friendly language.\n"
            "- DO NOT use placeholder text like 'point 1', 'point 2', '<summary bullet 1>', '<task>', etc.\n"
            "- DO NOT copy the example below. Fill with real meeting content.\n"
            "\n"
            "RETURN THE OUTPUT IN THIS EXACT JSON FORMAT (as a code block):\n"
            "```json\n"
            "{\n"
            "  \"summary\": [\"<summary bullet 1>\", \"<summary bullet 2>\"],\n"
            "  \"action_items\": [ {\"task\": \"<task>\", \"owner\": \"<owner>\", \"deadline\": \"<deadline>\"} ]\n"
            "}\n"
            "```\n"
            "\n"
            "TRANSCRIPT:\n"
            f"{chunk}\n"
        )
        # print(f"[Mistral][Chunk {idx+1}] Prompt sent to model (first 500 chars):\n", mistral_prompt[:500], "..." if len(mistral_prompt) > 500 else "")
        device = next(mistral_model.parameters()).device
        logger.debug("[Mistral][Chunk %d] Using device: %s", idx+1, device)
        # Use the tokenizer __call__ API instead of deprecated/removed encode_plus
        encoded = mistral_tokenizer(
            mistral_prompt,
            truncation=True,
            max_length=4096,
            return_tensors="pt"
        )
        input_ids = encoded["input_ids"].to(device)
        attention_mask = encoded.get("attention_mask")
        if attention_mask is not None:
            attention_mask = attention_mask.to(device)
        logger.debug("[Mistral][Chunk %d] Input IDs shape: %s", idx+1, input_ids.shape)
        gen_kwargs = dict(
            max_new_tokens=generation_max_new_tokens,
            do_sample=False,
            num_beams=3,
            early_stopping=True,
            pad_token_id=mistral_tokenizer.eos_token_id
        )
        if attention_mask is not None:
            gen_kwargs["attention_mask"] = attention_mask

        summary_ids = mistral_model.generate(
            input_ids,
            **gen_kwargs
        )
        mistral_output = mistral_tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        logger.debug("[Mistral][Chunk %d] Model output (first 500 chars):\n%s", idx+1, (mistral_output[:500] + ('...' if len(mistral_output) > 500 else '')))
        logger.debug("[Mistral][Chunk %d] Full Model output length=%d", idx+1, len(mistral_output))
        logger.debug("[Mistral][Chunk %d] Full Model output sample:\n%s", idx+1, (mistral_output[:2000] + ('...' if len(mistral_output) > 2000 else '')))
        # Use module-level extractor so it can be invoked from notebook for debugging
        json_str = extract_last_json(mistral_output, chunk_index=idx+1)
        # Always initialize these to avoid UnboundLocalError
        summary_text = []
        action_items = []
        decisions = []
        risks = []
        follow_up_questions = []
        logger.debug("[Mistral][Chunk %d] Extracted JSON string: %s", idx+1, json_str)
        if json_str:
            logger.debug("[Mistral][Chunk %d] JSON block found in output.", idx+1)
            try:
                parsed = json.loads(json_str)
                summary_text = parsed.get('summary', [])
                action_items = parsed.get('action_items', [])
                # New fields for decisions, risks, follow_up_questions
                decisions = parsed.get('decisions', [])
                risks = parsed.get('risks', [])
                follow_up_questions = parsed.get('follow_up_questions', [])
                logger.debug("[Mistral][Chunk %d] Parsed summary: %s", idx+1, summary_text)
                logger.debug("[Mistral][Chunk %d] Parsed action_items: %s", idx+1, action_items)
                logger.debug("[Mistral][Chunk %d] Parsed decisions: %s", idx+1, decisions)
                logger.debug("[Mistral][Chunk %d] Parsed risks: %s", idx+1, risks)
                logger.debug("[Mistral][Chunk %d] Parsed follow_up_questions: %s", idx+1, follow_up_questions)
            except Exception as e:
                logger.exception("[Mistral][Chunk %d] JSON parsing error: %s", idx+1, e)
        else:
            logger.debug("[Mistral][Chunk %d] No JSON block found in output.", idx+1)
            summary_text = []
            action_items = []
        # Clean up and filter out empty/placeholder/point items
        def is_valid_summary_item(item):
            if not item or not isinstance(item, str):
                return False
            s = item.strip().lower()
            if s in ("point 1", "point 2", "point1", "point2", "", "-", "<summary bullet 1>", "<summary bullet 2>"):
                return False
            if s.startswith("point ") or s.startswith("<summary"):
                return False
            if '<' in s and '>' in s:
                return False
            return True
        def is_valid_action_item(item):
            if not item:
                return False
            if isinstance(item, dict):
                # Remove if any value is a placeholder like <task> or empty
                for v in item.values():
                    if isinstance(v, str) and (v.strip() == '' or v.strip().startswith('<')):
                        return False
                return any(v for v in item.values())
            if isinstance(item, str):
                s = item.strip()
                if s == '' or s.startswith('<'):
                    return False
                return True
            return False
        logger.debug("[Mistral][Chunk %d] Validating and filtering extracted items.", idx+1)
        logger.debug("[Mistral][Chunk %d] Validating and filtering extracted items.summary_text: %s", idx+1, summary_text)
        filtered_summaries = [s for s in (summary_text if isinstance(summary_text, list) else [summary_text]) if is_valid_summary_item(s)]
        filtered_action_items = [a for a in (action_items if isinstance(action_items, list) else [action_items]) if is_valid_action_item(a)]
        filtered_decisions = [d for d in (decisions if isinstance(decisions, list) else [decisions]) if is_valid_summary_item(d)]
        filtered_risks = [r for r in (risks if isinstance(risks, list) else [risks]) if is_valid_summary_item(r)]
        filtered_follow_ups = [f for f in (follow_up_questions if isinstance(follow_up_questions, list) else [follow_up_questions]) if is_valid_summary_item(f)]
        logger.debug("[Mistral][Chunk %d] Filtered summary: %s", idx+1, filtered_summaries)
        logger.debug("[Mistral][Chunk %d] Filtered action_items: %s", idx+1, filtered_action_items)
        logger.debug("[Mistral][Chunk %d] Filtered decisions: %s", idx+1, filtered_decisions)
        logger.debug("[Mistral][Chunk %d] Filtered risks: %s", idx+1, filtered_risks)
        logger.debug("[Mistral][Chunk %d] Filtered follow_up_questions: %s", idx+1, filtered_follow_ups)
        all_summaries.extend(filtered_summaries)
        all_action_items.extend(filtered_action_items)
        if 'all_decisions' not in locals():
            all_decisions = []
        if 'all_risks' not in locals():
            all_risks = []
        if 'all_follow_ups' not in locals():
            all_follow_ups = []
        all_decisions.extend(filtered_decisions)
        all_risks.extend(filtered_risks)
        all_follow_ups.extend(filtered_follow_ups)
        logger.debug("[Mistral][Chunk %d] all_summaries so far: %s", idx+1, all_summaries)
        logger.debug("[Mistral][Chunk %d] all_action_items so far: %s", idx+1, all_action_items)
        logger.debug("[Mistral][Chunk %d] all_decisions so far: %s", idx+1, all_decisions)
        logger.debug("[Mistral][Chunk %d] all_risks so far: %s", idx+1, all_risks)
        logger.debug("[Mistral][Chunk %d] all_follow_ups so far: %s", idx+1, all_follow_ups)

        # Fallback: if summaries are empty or only placeholders, try extracting plaintext from model output
        def extract_plaintext_summary(text, max_items=5):
            try:
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                # Prefer explicit bullets/numbered lines
                bullets = [l for l in lines if re.match(r"^(?:[-*•]|\d+\.)\s+", l)]
                if bullets:
                    return [re.sub(r"^(?:[-*•]|\d+\.)\s+", "", b).strip() for b in bullets[:max_items]]
                # Otherwise split into sentences (simple heuristic)
                sents = re.split(r'(?<=[.!?])\s+', text)
                sents = [s.strip() for s in sents if s.strip()]
                return sents[:max_items]
            except Exception:
                return []

        if not filtered_summaries:
            logger.debug("[Mistral][Chunk %d] No valid summaries after parsing; attempting plaintext fallback.", idx+1)
            pts = extract_plaintext_summary(mistral_output, max_items=5)
            if pts:
                logger.debug("[Mistral][Chunk %d] Plaintext fallback found %d items.", idx+1, len(pts))
                filtered_summaries = pts
            else:
                logger.debug("[Mistral][Chunk %d] Plaintext fallback found no items.", idx+1)

    # print(f"[Mistral] FINAL all_summaries: {all_summaries}")
    # print(f"[Mistral] FINAL all_action_items: {all_action_items}")
    # Deduplicate summaries and action items
    def dedup_list(items):
        seen = set()
        deduped = []
        for item in items:
            key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item).strip().lower()
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped
    logger.debug("[Mistral] Deduplicating final results... %s", all_summaries)
    deduped_summaries = dedup_list(all_summaries)
    logger.debug("[Mistral] Deduplicating final deduped_summaries ... %s", deduped_summaries)
    deduped_action_items = dedup_list(all_action_items)
    deduped_decisions = dedup_list(all_decisions) if 'all_decisions' in locals() else []
    deduped_risks = dedup_list(all_risks) if 'all_risks' in locals() else []
    deduped_follow_ups = dedup_list(all_follow_ups) if 'all_follow_ups' in locals() else []
    logger.debug("[Mistral] FINAL deduped_summaries: %s", deduped_summaries)
    logger.debug("[Mistral] FINAL deduped_action_items: %s", deduped_action_items)
    logger.debug("[Mistral] FINAL deduped_decisions: %s", deduped_decisions)
    logger.debug("[Mistral] FINAL deduped_risks: %s", deduped_risks)
    logger.debug("[Mistral] FINAL deduped_follow_ups: %s", deduped_follow_ups)
    return {
        'meeting_id': meeting_id,
        'summary_text': deduped_summaries,
        'action_items': deduped_action_items,
        'decisions': deduped_decisions,
        'risks': deduped_risks,
        'follow_up_questions': deduped_follow_ups
    }
