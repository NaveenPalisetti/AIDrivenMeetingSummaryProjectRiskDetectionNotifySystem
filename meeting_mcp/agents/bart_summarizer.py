from meeting_mcp.tools.nlp_task_extraction import extract_tasks_structured
import logging

logger = logging.getLogger("meeting_mcp.bart_summarizer")


def summarize_with_bart(tokenizer, model, transcript, meeting_id):
    logger.debug("BART summarizer entry: meeting_id=%s, transcript_len=%d", meeting_id, len(transcript or ""))
    # Small, safe previews for debugging (avoid logging full transcript)
    try:
        logger.debug("BART transcript preview: %s", (transcript or "")[:500])
    except Exception:
        logger.debug("BART transcript preview unavailable")

    bart_summary = None
    if not transcript or len(transcript.split()) < 10:
        logger.debug("Transcript too short for BART summarization")
        bart_summary = "Transcript too short for summarization."
    else:
        try:
            # Tokenize (may be expensive) — log token count where possible
            try:
                input_ids = tokenizer.encode(transcript, truncation=True, max_length=1024, return_tensors="pt")
                logger.debug("BART tokenized input_ids shape: %s", getattr(input_ids, 'shape', str(input_ids)))
            except Exception:
                logger.debug("BART tokenizer.encode failed or returned unexpected shape")
                input_ids = None

            summary_ids = model.generate(
                input_ids,
                max_length=130,
                min_length=30,
                do_sample=False,
                num_beams=4,
                early_stopping=True
            )
            bart_summary = tokenizer.decode(summary_ids[0], skip_special_tokens=True)
            logger.debug("BART summarization succeeded: summary_len=%d", len(bart_summary or ""))
        except Exception as e:
            logger.exception("BART summarization error: %s", e)
            bart_summary = f"[BART summarization error: {e}]"
    try:
        raw_items = extract_tasks_structured(transcript, max_tasks=6)
        action_items = []
        for item in raw_items:
            action_items.append({
                "summary": item.get("title", ""),
                "assignee": item.get("owner", None),
                "issue_type": "Task",
                "story_points": None,
                "due_date": item.get("due", None)
            })
        logger.debug("Extracted action items count=%d", len(action_items))
    except Exception:
        logger.exception("Action-item extraction failed")
        action_items = []
    return {
        'meeting_id': meeting_id,
        'summary_text': bart_summary,
        'action_items': action_items
    }
