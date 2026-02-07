import json
import asyncio
import logging
import os
import streamlit as st

logger = logging.getLogger("meeting_mcp.ui.renderers")


_CSS = """
<style>
    .main-header { font-size: 2rem; font-weight:700; color: #1f77b4; }
    .sub-header { font-size: 1rem; color: #666; margin-bottom: 1rem; }
    .badge { display:inline-block; padding:0.2rem .6rem; border-radius:4px; background:#f0f0f0; margin-right:6px; }
    .credentials { background:#fff; padding:0.5rem; border-radius:6px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
    /* Table / DataFrame styling */
    div[role="table"] table, table {
        width: 100% !important;
        border-collapse: collapse;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial;
        font-size: 14px;
        color: #222;
    }
    div[role="table"] table th, table th {
        text-align: left;
        padding: 10px 12px;
        background: linear-gradient(180deg,#fbfdff,#f3f7fb);
        border-bottom: 1px solid #e6eef6;
        font-weight: 600;
        color: #123;
    }
    div[role="table"] table td, table td {
        padding: 10px 12px;
        border-bottom: 1px solid #f3f6f9;
    }
    div[role="table"] tr:hover td, table tr:hover td {
        background: rgba(31,119,180,0.03);
    }

    /* Expander / panels */
    .streamlit-expanderHeader {
        font-weight: 600;
        color: #1f77b4;
    }
    .stDownloadButton>button, button[kind="primary"] {
        background-color: #1f77b4 !important;
        color: #fff !important;
        border-radius: 6px !important;
        padding: 6px 10px !important;
    }

    /* Chat / headers */
    .main-header { margin-bottom: 0.5rem; }
    .sub-header { margin-top: 0; }
</style>
"""


def render_css():
    st.markdown(_CSS, unsafe_allow_html=True)


def _get_run_orchestrate(orchestrator=None, run_orchestrate=None):
    """Return a callable run_orchestrate(prompt, params, session_id=None).

    Preference order:
    - If `run_orchestrate` callable provided, return it.
    - If `orchestrator` provided, wrap its `orchestrate` method with `asyncio.run`.
    - Otherwise return a callable that yields an error-shaped dict.
    """
    if callable(run_orchestrate):
        return run_orchestrate

    if orchestrator is not None:
        def _run(prompt, params, session_id=None):
            try:
                if session_id is None:
                    return asyncio.run(orchestrator.orchestrate(prompt, params))
                return asyncio.run(orchestrator.orchestrate(prompt, params, session_id=session_id))
            except Exception as e:
                logger.exception("Orchestrate wrapper failed: %s", e)
                return {"intent": "error", "results": {"error": str(e)}}
        return _run

    def _no_orch(prompt, params, session_id=None):
        logger.warning("No orchestrator or run_orchestrate callable provided")
        return {"intent": "error", "results": {"error": "No orchestrator available"}}

    return _no_orch


def render_chat_messages(messages):
    for message in messages:
        role = message.get("role", "system")
        with st.chat_message(role):
            st.markdown(message.get("content", ""))


def render_processed_chunks(processed, title, add_message, debug: dict | None = None):
    # Persist full processed chunks into chat history
    full_text = "\n\n".join([f"Chunk {i+1}:\n{chunk}" for i, chunk in enumerate(processed)])
    add_message("assistant", full_text)

    # Cache processed chunks for later summarization (keyed by title)
    try:
        if "processed_cache" not in st.session_state:
            st.session_state["processed_cache"] = {}
        st.session_state["processed_cache"][title] = processed
    except Exception:
        pass

    rows = []
    for i, chunk in enumerate(processed):
        preview = chunk if len(chunk) <= 200 else chunk[:200].rstrip() + '...'
        rows.append({"Chunk": i + 1, "Preview": preview})
    st.table(rows)

    # create a safe_title for unique widget keys (avoid collisions across reruns/pages)
    try:
        safe_title = title.replace(' ', '_').replace('/', '_')
    except Exception:
        safe_title = 'processed_transcript'

    for i, chunk in enumerate(processed):
        with st.expander(f"Chunk {i+1}"):
            safe_key = f"{safe_title}_chunk_{i+1}"
            # use a string label (empty string allowed) to avoid type errors
            st.text_area(label=f"Chunk {i+1}", value=chunk, height=300, key=safe_key)

    joined = "\n\n".join(processed)
    st.download_button(f"Download processed transcript", data=joined, file_name=f"{safe_title}_processed.txt", mime="text/plain")

    # If debug info was provided, show it in an expander for quick inspection
    if debug:
        with st.expander("Preprocess debug", expanded=False):
            try:
                st.json(debug)
            except Exception:
                st.write(debug)
    
def render_jira_result(jira_result, title=None, add_message=None):
        """Render Jira creation results in a rich, user-friendly format."""
        import pandas as pd
        st.header(f"Jira Creation Result{f' — {title}' if title else ''}")
        # Persist a short assistant message to history
        if add_message:
            try:
                results = jira_result.get('results', {}) if isinstance(jira_result, dict) else jira_result
                add_message('assistant', f"Jira creation result: {results}")
            except Exception:
                pass
        # Extract created tasks/issues
        results = jira_result.get('results', {}) if isinstance(jira_result, dict) else jira_result
        tasks = results.get('tasks') or results.get('created') or results.get('task') or results.get('issue')
        if tasks:
            if isinstance(tasks, dict):
                tasks = [tasks]
            if isinstance(tasks, list):
                st.markdown("**Created Jira Tasks:**")
                # Flatten dicts for display
                def flatten(d):
                    return {k: (v if not isinstance(v, dict) else str(v)) for k, v in d.items()}
                df = pd.DataFrame([flatten(t) for t in tasks])
                st.dataframe(df, use_container_width=True)
            else:
                st.markdown(f"**Created Jira Task:** {tasks}")
        else:
            st.info("No Jira tasks were created or returned by the backend.")
        # Always show raw JSON for traceability
        with st.expander("Raw Jira result JSON", expanded=False):
            st.markdown(f"```json\n{json.dumps(jira_result, indent=2)}\n```")

    
def render_summary_result(summary_obj, title, add_message, orchestrator=None, run_orchestrate=None):
    """Render a structured summary result (summary text/list and action items).
    Accepts either a string summary or a dict with keys `summary` and `action_items`.
    """
    # Debug: log what is being passed to render_summary_result
    logger.debug(f"[render_summary_result] summary_obj for '{title}': {json.dumps(summary_obj, default=str)[:1000]}")
    # Persist the summary to chat history
    try:
        summary_text = ""
        action_items = []
        if isinstance(summary_obj, dict):
            summary_val = summary_obj.get('summary')
            if isinstance(summary_val, list):
                summary_text = "\n".join([f"- {s}" for s in summary_val])
            else:
                summary_text = str(summary_val or "")
            action_items = summary_obj.get('action_items') or []
        else:
            summary_text = str(summary_obj)        
    except Exception as e:
        logger.exception(f"[render_summary_result] Exception in summary chat persist: {e}")

    st.header(f"Summary — {title}")
    # create a safe_title for unique widget keys (avoid collisions across reruns/pages)
    try:
        safe_title = str(title).replace(' ', '_').replace('/', '_')
    except Exception:
        safe_title = 'summary'
    if isinstance(summary_obj, dict) and summary_obj.get('summary'):
        s = summary_obj.get('summary')
        if isinstance(s, list):
            for item in s:
                st.markdown(f"- {item}")
        else:
            st.markdown(s)
    else:
        st.markdown(str(summary_obj))

    if isinstance(summary_obj, dict) and summary_obj.get('action_items'):
        logger.debug(f"[render_summary_result] Rendering action items table for '{title}' with {len(summary_obj.get('action_items', []))} items.")
        st.subheader("Action Items")
        ais = summary_obj.get('action_items')
        # persist last action items for chat commands (e.g., 'create jira: <task>')
        try:
            logger.debug(f"[render_summary_result] Persisting last_action_items for '{title}' with {len(ais)} items.") 
            st.session_state['last_action_items'] = ais
        except Exception as e:
            logger.exception(f"[render_summary_result] Exception persisting last_action_items: {e}")

        # Build table rows ensuring required fields: summary, assignee, issue_type, due_date
        rows = []
        for ai in ais:
            if isinstance(ai, dict):
                summary_field = ai.get('summary') or ai.get('task') or ai.get('title') or str(ai)
                assignee = ai.get('assignee') or ai.get('owner') or ai.get('assigned_to') or "Unassigned"
                issue_type = ai.get('issue_type') or ai.get('type') or ai.get('ticket_type') or ai.get('issueType') or ""
                due_date = ai.get('due') or ai.get('due_date') or ai.get('deadline') or ""
            else:
                summary_field = str(ai)
                assignee = "Unassigned"
                issue_type = ""
                due_date = ""

            rows.append({
                "Summary": summary_field,
                "Assignee": assignee,
                "Issue Type": issue_type,
                "Due Date": due_date,
            })

        # Display as a table for clarity
        try:
            import pandas as pd
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)
        except Exception:
            # Fallback to simple table if pandas not available
            st.table(rows)
        logger.debug(f"[render_summary_result] Action items table rendered for '{title}'.")
        if summary_text:
            try:
                md = f"Summary for {title}:\n\n{summary_text}"
                # If we have action items, include a compact markdown table in the assistant message
                if ais:
                    table_lines = ["| Summary | Assignee | Issue Type | Due Date |", "|---|---|---|---|"]
                    def _esc(s):
                        return str(s or "").replace("|", "\\|")
                    for ai in ais:
                        if isinstance(ai, dict):
                            summary_field = ai.get('summary') or ai.get('task') or ai.get('title') or str(ai)
                            assignee = ai.get('assignee') or ai.get('owner') or ai.get('assigned_to') or "Unassigned"
                            issue_type = ai.get('issue_type') or ai.get('type') or ai.get('ticket_type') or ai.get('issueType') or ""
                            due_date = ai.get('due') or ai.get('due_date') or ai.get('deadline') or ""
                        else:
                            summary_field = str(ai)
                            assignee = "Unassigned"
                            issue_type = ""
                            due_date = ""
                        table_lines.append(f"| {_esc(summary_field)} | {_esc(assignee)} | {_esc(issue_type)} | {_esc(due_date)} |")
                    md += "\n\nAction Items:\n\n" + "\n".join(table_lines)
                add_message("assistant", md)
            except Exception:
                # fallback to previous behaviour
                add_message("assistant", f"Summary for {title}:\n\n{summary_text}")
        # For each item, provide an expander with full details and only the Create Jira button
        for idx, ai in enumerate(ais):
            item_title = (ai.get('summary') or ai.get('task') or ai.get('title')) if isinstance(ai, dict) else str(ai)
            with st.expander(f"Details — {item_title[:80]}", expanded=False):
                if isinstance(ai, dict):
                    st.markdown(f"**Summary:** {ai.get('summary') or ai.get('task') or ai.get('title')}")
                    st.markdown(f"**Assignee:** {ai.get('assignee') or ai.get('owner') or ai.get('assigned_to') or 'Unassigned'}")
                    st.markdown(f"**Issue Type:** {ai.get('issue_type') or ai.get('type') or ai.get('ticket_type') or ai.get('issueType') or ''}")
                    if ai.get('due') or ai.get('deadline') or ai.get('due_date'):
                        st.markdown(f"**Due Date:** {ai.get('due') or ai.get('deadline') or ai.get('due_date')}")
                    if ai.get('raw'):
                        st.markdown(f"**Raw:** {ai.get('raw')}")
                else:
                    st.write(ai)

                # Only show the Create Jira button
                jira_key = f"jira_{safe_title}_{idx}"
                logger.debug(f"Rendering Create Jira button with key={jira_key}")
                if st.button("Create Jira", key=jira_key):
                    logger.debug(f"Create Jira button clicked with key={jira_key}")
                    # determine task/owner/due first so we can show immediate feedback
                    if isinstance(ai, dict):
                        task = ai.get('summary') or ai.get('task') or ai.get('title') or ''
                        owner = ai.get('assignee') or ai.get('owner') or ai.get('assigned_to') or None
                        due = ai.get('due') or ai.get('deadline') or ai.get('due_date') or None
                    else:
                        task = str(ai)
                        owner = None
                        due = None

                    logger.info("Create Jira button clicked for action item %d (key=%s)", idx, jira_key)
                    st.info(f"Creating Jira for: {task}")

                    add_message('user', f"Create Jira: {task}")
                    with st.chat_message('user'):
                        st.markdown(f"Create Jira: {task}")

                    params = {"task": task, "owner": owner, "deadline": due}
                    run_func = _get_run_orchestrate(orchestrator, run_orchestrate)
                    try:
                        logger.info("Create Jira clicked: task=%s owner=%s due=%s", task, owner, due)
                        jira_result = run_func(f"create jira for {task}", params)
                        logger.info("Jira result received: %s", str(jira_result)[:1000])
                        st.session_state['last_jira_result'] = (True, jira_result)
                        render_jira_result(jira_result, title=task, add_message=add_message)
                    except Exception as e:
                        logger.exception("Error creating Jira: %s", e)
                        st.session_state['last_jira_result'] = (False, f"Error creating Jira: {e}")
                        try:
                            add_message('system', f"Error creating Jira: {e}")
                        except Exception:
                            pass

        # Show Jira creation result below the table if available
        if 'last_jira_result' in st.session_state:
            success, result = st.session_state['last_jira_result']
            if success:
                st.success("Jira ticket created successfully!")
                # Try to extract created tasks from the result
                created = []
                # Traverse possible nesting to find created_tasks
                try:
                    if isinstance(result, dict):
                        created = (
                            result.get('results', {}).get('jira', {}).get('results', {}).get('created_tasks')
                            or result.get('created_tasks')
                            or []
                        )
                except Exception:
                    created = []
                if created:
                    st.markdown("**Created Jira Tasks:**")
                    for idx, task in enumerate(created):
                        if isinstance(task, dict):
                            st.markdown(f"- **Summary:** {task.get('summary') or task.get('title') or task.get('task') or ''}")
                            st.markdown(f"  - **Key:** {task.get('key') or task.get('id') or ''}")
                            st.markdown(f"  - **Status:** {task.get('status') or ''}")
                            st.markdown(f"  - **Assignee:** {task.get('assignee') or ''}")
                            st.markdown(f"  - **Issue Type:** {task.get('issue_type') or ''}")
                            st.markdown(f"  - **URL:** {task.get('url') or ''}")
                        else:
                            st.markdown(f"- {task}")
                else:
                    st.info("No Jira tasks were created or returned by the backend.")
                with st.expander("Full Jira creation result JSON"):
                    st.markdown(f"```json\n{json.dumps(result, indent=2)}\n```")
            else:
                st.error(result)
    logger.debug(f"[render_summary_result] Completed rendering summary for '{title}'.")


def render_calendar_result(calendar_block, orchestrator, add_message, run_orchestrate=None):
    # If a previous action requested suppression (e.g. summarize/preprocess), skip rendering
    try:
        if st.session_state.pop('suppress_calendar_render', False):
            return
    except Exception:
        pass

    if calendar_block and calendar_block.get("status") == "success":
        events = calendar_block.get("events", [])
        st.session_state['last_events'] = events

        if not events:
            st.info("No calendar events found for the requested range.")
            return

        # Present events as a table and individual expanders
        rows = []
        for ev in events:
            rows.append({
                "Summary": ev.get("summary"),
                "Start": ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date"),
                "End": ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date"),
                "Location": ev.get("location"),
                "Organizer": ev.get("organizer", {}).get("email"),
            })
        st.table(rows)

        for ev in events:
            title = ev.get("summary") or ev.get("id")
            ev_key = ev.get("id") or title
            with st.expander(title, expanded=False):
                cols = st.columns([3, 1])
                with cols[0]:
                    st.markdown(f"**When:** {ev.get('start', {}).get('dateTime') or ev.get('start', {}).get('date')}{' → ' + (ev.get('end', {}).get('dateTime') or ev.get('end', {}).get('date')) if ev.get('end') else ''}")
                    if ev.get("location"):
                        st.markdown(f"**Location:** {ev.get('location')}")
                    if ev.get("description"):
                        st.markdown(f"**Description:**\n\n{ev.get('description')}")
                    if ev.get("htmlLink"):
                        st.markdown(f"[Open in Google Calendar]({ev.get('htmlLink')})")                        

                    preprocess_text = ev.get("description") or ev.get("summary") or ""
                    if preprocess_text:
                        btn_key = f"preprocess_{ev_key}"
                        if st.button("Preprocess this meeting", key=btn_key):
                            user_action = f"Preprocess meeting: {title}"
                            add_message("user", user_action)
                            with st.chat_message("user"):
                                st.markdown(user_action)

                            try:
                                params = {"transcripts": [preprocess_text], "chunk_size": 1500}
                                run_func = _get_run_orchestrate(orchestrator, run_orchestrate)
                                proc_result = run_func(f"preprocess transcripts for {title}", params)
                                proc_summary = proc_result.get("results", {}).get("transcript") or proc_result.get("results")
                                if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                                    processed = proc_summary.get("processed", []) if isinstance(proc_summary, dict) else None
                                    if isinstance(processed, list):
                                        assistant_md = f"Preprocessed {len(processed)} chunk(s) for {title}."
                                    else:
                                        assistant_md = "Preprocessing completed."
                                else:
                                    assistant_md = f"Preprocessing result: {proc_result}"

                                add_message("assistant", assistant_md)
                                with st.chat_message("assistant"):
                                    st.markdown(assistant_md)
                                    if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                                            processed = proc_summary.get("processed")
                                            debug = proc_summary.get("debug") if isinstance(proc_summary, dict) else None
                                            if processed:
                                                # persist and render processed chunks
                                                render_processed_chunks(processed, title, add_message, debug)
                                                # suppress re-rendering of the calendar/result JSON on this run
                                                try:
                                                    st.session_state['suppress_calendar_render'] = True
                                                except Exception:
                                                    pass
                            except Exception as e:
                                add_message("system", f"Error: {e}")
                                with st.chat_message("assistant"):
                                    st.markdown(f"Error: {e}")
                    # Summarize button: uses cached processed chunks or runs preprocess then summarization
                    if preprocess_text:
                        sum_key = f"summarize_{ev_key}"
                        if st.button("Summarize this meeting", key=sum_key):
                            meeting_title = title
                            add_message("user", f"Summarize meeting: {meeting_title}")
                            with st.chat_message("user"):
                                st.markdown(f"Summarize meeting: {meeting_title}")

                            try:
                                # Try to reuse cached processed chunks
                                processed = None
                                try:
                                    processed = st.session_state.get('processed_cache', {}).get(meeting_title)
                                except Exception:
                                    processed = None

                                if not processed:
                                    # Trigger preprocessing first
                                    params = {"transcripts": [preprocess_text], "chunk_size": 1500}
                                    run_func = _get_run_orchestrate(orchestrator, run_orchestrate)
                                    proc_result = run_func(f"preprocess transcripts for {meeting_title}", params)
                                    proc_summary = proc_result.get("results", {}).get("transcript") or proc_result.get("results")
                                    if isinstance(proc_summary, dict) and proc_summary.get("status") == "success":
                                        processed = proc_summary.get("processed")
                                        try:
                                            if "processed_cache" not in st.session_state:
                                                st.session_state["processed_cache"] = {}
                                            st.session_state["processed_cache"][meeting_title] = processed
                                        except Exception:
                                            pass

                                # Call summarization tool via orchestrator
                                mode = st.session_state.get('summarizer_model', 'BART')
                                mode_param = 'bart' if mode.lower().startswith('b') else 'mistral'
                                params = {"processed_transcripts": processed or [], "mode": mode_param}
                                sum_result = run_func(f"summarize meeting {meeting_title}", params)
                                sum_block = sum_result.get('results', {}).get('summarization') or sum_result.get('results')
                                # Always pass the full summary dict to render_summary_result
                                if isinstance(sum_block, dict) and sum_block.get('status') == 'success':
                                    summary_obj = sum_block.get('summary') if not sum_block.get('action_items') else sum_block
                                else:
                                    summary_obj = sum_block

                                add_message("assistant", f"Summary for {meeting_title} ready.")
                                with st.chat_message("assistant"):
                                    try:
                                        render_summary_result(summary_obj, meeting_title, add_message, orchestrator)
                                    except Exception:
                                        st.write(summary_obj)
                                    try:
                                        st.session_state['suppress_calendar_render'] = True
                                    except Exception:
                                        pass
                            except Exception as e:
                                add_message("system", f"Error: {e}")
                                with st.chat_message("assistant"):
                                    st.markdown(f"Error: {e}")
                            # Detect Risks button (calls orchestrator/risk tool)
                            detect_key = f"detect_risks_{ev_key}"
                            if st.button("Detect Risks for this meeting", key=detect_key):
                                add_message("user", f"Detect risks: {title}")
                                with st.chat_message("user"):
                                    st.markdown(f"Detect risks: {title}")
                                try:
                                    params = {"meeting_id": title, "summary": {"summary_text": preprocess_text}, "include_jira": True}
                                    if st.session_state.get('last_action_items'):
                                        params['tasks'] = st.session_state.get('last_action_items')
                                    # delegate to orchestrator for risk detection
                                    run_func = _get_run_orchestrate(orchestrator, run_orchestrate)
                                    risk_result = run_func(f"detect risk for {title}", params)
                                    add_message("assistant", f"Risk detection for {title} completed.")
                                    with st.chat_message("assistant"):
                                        try:
                                            render_risk_result(risk_result, title, add_message)
                                        except Exception:
                                            st.markdown("Risk detection result:\n\n```json\n" + json.dumps(risk_result, indent=2) + "\n```")
                                except Exception as e:
                                    add_message("system", f"Error running risk detection: {e}")
                                    with st.chat_message("assistant"):
                                        st.markdown(f"Error running risk detection: {e}")
                            # Notify button: send summary/tasks/risks to external notification channels
                            notify_key = f"notify_{ev_key}"
                            if st.button("Notify team for this meeting", key=notify_key):
                                add_message("user", f"Notify team for: {title}")
                                with st.chat_message("user"):
                                    st.markdown(f"Notify team for: {title}")
                                try:
                                    params = {"meeting_id": title, "summary": {"summary_text": preprocess_text}}
                                    if st.session_state.get('last_action_items'):
                                        params['tasks'] = st.session_state.get('last_action_items')
                                    # include any last detected risks if present
                                    if st.session_state.get('last_risks'):
                                        params['risks'] = st.session_state.get('last_risks')

                                    run_func = _get_run_orchestrate(orchestrator, run_orchestrate)
                                    notify_result = run_func(f"notify for {title}", params)
                                    add_message("assistant", f"Notification result for {title}: {notify_result.get('results', {})}")
                                    with st.chat_message("assistant"):
                                        try:
                                            render_notification_result(notify_result, title, add_message)
                                        except Exception:
                                            st.write(notify_result)
                                except Exception as e:
                                    add_message("system", f"Error sending notification: {e}")
                                    with st.chat_message("assistant"):
                                        st.markdown(f"Error sending notification: {e}")
                with cols[1]:
                    st.markdown("**Metadata**")
                    st.write({k: ev.get(k) for k in ("id", "status", "iCalUID") if ev.get(k)})

        # Keep the raw JSON available for debugging
        with st.expander("Raw calendar JSON", expanded=False):
            st.code(json.dumps(calendar_block, indent=2), language="json")
    else:
        # Fallback: show full result as formatted JSON
        st.markdown("Result:\n\n" + "```json\n" + json.dumps(calendar_block, indent=2) + "\n```")


def render_risk_result(risk_obj, title: str | None, add_message):
    """Render risk detection results in a friendly table and expanders.

    Accepts either an aggregated orchestrator response (with 'results' mapping)
    or a direct tool response containing 'risks', 'summary_risks', 'jira_risks'.
    """
    # Normalize to tool result
    if isinstance(risk_obj, dict) and 'results' in risk_obj:
        # aggregated orchestrator result -> extract 'risk' tool output
        tool_res = risk_obj.get('results', {}).get('risk') or risk_obj.get('results')
    else:
        tool_res = risk_obj

    # Tool-level result may itself be wrapped: {status: success, risks: [...]}
    if isinstance(tool_res, dict) and tool_res.get('status') in ('success', 'ok') and 'risks' in tool_res:
        risks = tool_res.get('risks', []) or []
        summary_risks = tool_res.get('summary_risks', []) or []
        jira_risks = tool_res.get('jira_risks', []) or []
    else:
        # Try to extract list-like payloads
        if isinstance(tool_res, list):
            risks = tool_res
            summary_risks = []
            jira_risks = []
        else:
            risks = []
            summary_risks = []
            jira_risks = []

    # Persist last risks for later actions (keep a flat list for backwards compatibility
    # and also store structured details for callers that need the separate lists)
    try:
        combined = []
        try:
            combined = list(risks or [])
        except Exception:
            combined = []
        try:
            if summary_risks:
                # avoid duplicates
                combined += [r for r in summary_risks if r not in combined]
        except Exception:
            pass
        try:
            if jira_risks:
                combined += [r for r in jira_risks if r not in combined]
        except Exception:
            pass
        st.session_state['last_risks'] = combined
        st.session_state['last_risks_details'] = {'risks': risks, 'summary_risks': summary_risks, 'jira_risks': jira_risks}
    except Exception:
        pass

    # Also add synthetic 'events' for risks into last_events so notify/matching picks them up
    try:
        if risks:
            existing = list(st.session_state.get('last_events', []))
            synthetic = []
            for i, r in enumerate(risks):
                if not isinstance(r, dict):
                    continue
                ev_id = r.get('key') or r.get('id') or f"risk_{i}"
                ev_summary = (r.get('summary') or r.get('description') or f"Risk: {r.get('type') or ''}").strip()
                ev_desc = r.get('description') or r.get('summary') or ''
                synthetic.append({
                    'id': ev_id,
                    'summary': ev_summary,
                    'description': ev_desc,
                    'is_risk': True,
                })
            # Prepend synthetic risk events so they're found first by fuzzy matching
            if synthetic:
                st.session_state['last_events'] = synthetic + existing
                logger.debug("Persisted %d synthetic risk events into last_events", len(synthetic))
    except Exception:
        pass

    st.header(f"Risks — {title or 'meeting'}")
    if not risks:
        st.info("No risks detected.")
        return

    # Aggregate counts
    by_severity = {}
    by_type = {}
    for r in risks:
        if not isinstance(r, dict):
            continue
        sev = (r.get('severity') or 'unknown').title()
        typ = (r.get('type') or 'general').title()
        by_severity[sev] = by_severity.get(sev, 0) + 1
        by_type[typ] = by_type.get(typ, 0) + 1

    cols = st.columns(max(1, min(4, len(by_severity) + 1)))
    i = 0
    for sev, cnt in sorted(by_severity.items(), key=lambda x: x[0]):
        cols[i].metric(label=f"{sev} risks", value=str(cnt))
        i += 1

    # Quick breakdown by type
    if by_type:
        with st.expander("Risk types breakdown", expanded=False):
            for typ, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
                st.write(f"- **{typ}**: {cnt}")

    # Build table rows for a concise list view
    rows = []
    for r in risks:
        if isinstance(r, dict):
            key = r.get('key') or r.get('id') or ''
            summary = (r.get('summary') or r.get('description') or '')
            summary_short = (summary[:120].rstrip() + '...') if len(summary) > 120 else summary
            rows.append({
                'Severity': (r.get('severity') or '').title(),
                'Key': key,
                'Summary': summary_short,
                'Type': r.get('type') or '',
                'Source': r.get('source') or '',
            })
        else:
            rows.append({'Severity': '', 'Key': '', 'Summary': str(r), 'Type': '', 'Source': ''})

    # Display as dataframe if pandas available, else table
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
    except Exception:
        st.table(rows)

    # Persist a compact assistant message summarizing the top risks for chat history
    try:
        if add_message:
            total = len(risks)
            top_lines = []
            for r in risks:
                if not isinstance(r, dict):
                    continue
                k = r.get('key') or r.get('id') or ''
                s = (r.get('summary') or r.get('description') or '')
                s_short = (s.replace('\n', ' ')[:100].rstrip() + '...') if len(s) > 100 else s.replace('\n', ' ')
                sev = (r.get('severity') or '').title()
                top_lines.append(f"- {k} — {s_short} ({sev})")
            md = f"Risks for {title or 'meeting'}: {total} detected.\n\n" + ("\n".join(top_lines) if top_lines else "No detailed risks to list.")
            try:
                add_message("assistant", md)
            except Exception:
                pass
    except Exception:
        pass

    # Detail expanders with actions
    for idx, r in enumerate(risks):
        title_text = (r.get('summary') or r.get('description') or str(r))[:80] if isinstance(r, dict) else str(r)
        with st.expander(f"Risk {idx+1}: {title_text}"):
            if isinstance(r, dict):
                st.markdown(f"**Key:** {r.get('key') or r.get('id') or ''}")
                st.markdown(f"**Severity:** {r.get('severity')}")
                st.markdown(f"**Type:** {r.get('type')}")
                st.markdown(f"**Source:** {r.get('source')}")
                st.markdown(f"**Summary:** {r.get('summary') or ''}")
                if r.get('description'):
                    st.markdown(f"**Description:** {r.get('description')}")
                # Jira link if key present
                key = r.get('key')
                if key and isinstance(key, str) and key.strip():
                    jira_base = os.environ.get('JIRA_URL') or ''
                    if jira_base:
                        jira_link = jira_base.rstrip('/') + f"/browse/{key}"
                        st.markdown(f"[Open in Jira]({jira_link})")
                    else:
                        st.markdown(f"**Key:** {key}")

                # Derived badges (combined flags)
                badges = []
                if r.get('severity'):
                    badges.append(r.get('severity').upper())
                if r.get('type'):
                    badges.append(str(r.get('type')))
                if badges:
                    st.markdown(f"**Tags:** {' | '.join(badges)}")

                # Quick actions: mark reviewed, copy key (show), suggest assign
                action_cols = st.columns([1, 1, 2])
                reviewed_key = f"reviewed_{r.get('key') or r.get('id') or idx}"
                if reviewed_key not in st.session_state:
                    st.session_state[reviewed_key] = False

                if action_cols[0].button("Mark Reviewed", key=f"mark_{idx}"):
                    st.session_state[reviewed_key] = True
                    st.success("Marked as reviewed")
                    try:
                        add_message('assistant', f"Marked risk {r.get('key') or r.get('id')} as reviewed")
                    except Exception:
                        pass

                if action_cols[1].button("Show Key", key=f"showkey_{idx}"):
                    st.info(f"Key: {r.get('key') or r.get('id') or ''}")

                if action_cols[2].button("Suggest Assign", key=f"assign_{idx}"):
                    # Post a suggest-assign message to chat history that the user can edit/confirm
                    assignee_sugg = "@owner"
                    try:
                        add_message('user', f"Assign {r.get('key') or r.get('id')} to {assignee_sugg}")
                    except Exception:
                        pass
                    st.info("Suggested assign message added to chat history")
            else:
                st.write(r)

    # Show separated lists if present
    if summary_risks:
        with st.expander("Summary-derived risks", expanded=False):
            st.json(summary_risks)
    if jira_risks:
        with st.expander("Jira-derived risks", expanded=False):
            st.json(jira_risks)
    try:
        combined = []
        try:
            combined = list(risks or [])
        except Exception:
            combined = []
        try:
            if summary_risks:
                combined += [r for r in summary_risks if r not in combined]
        except Exception:
            pass
        try:
            if jira_risks:
                combined += [r for r in jira_risks if r not in combined]
        except Exception:
            pass
        st.session_state['last_risks'] = combined
        st.session_state['last_risks_details'] = {'risks': risks, 'summary_risks': summary_risks, 'jira_risks': jira_risks}
    except Exception:
        pass

def render_notification_result(notify_obj, title: str | None, add_message):
    """Render notification tool results in a concise, user-friendly way.

    Accepts either an orchestrator-wrapped response (with 'results') or
    a direct tool response such as {"status":"success","notified":True}.
    """
    # Normalize orchestrator-style wrappers
    if isinstance(notify_obj, dict) and 'results' in notify_obj:
        tool_res = notify_obj.get('results', {}).get('notification') or notify_obj.get('results')
    else:
        tool_res = notify_obj

    st.header(f"Notification — {title or 'meeting'}")

    if isinstance(tool_res, dict):
        status = tool_res.get('status') or tool_res.get('result') or 'unknown'
        notified = tool_res.get('notified')
        msg = tool_res.get('message') or tool_res.get('details') or None

        st.markdown(f"**Status:** {status}")
        if isinstance(notified, bool):
            st.markdown(f"**Notified:** {'Yes' if notified else 'No'}")
        if msg:
            st.markdown(f"**Message:** {msg}")

        # Persist a short assistant message to history
        try:
            add_message('assistant', f"Notification status: {status}")
        except Exception:
            pass
        # Offer full payload for debugging
        with st.expander("Full notification payload", expanded=False):
            try:
                st.json(tool_res)
            except Exception:
                st.write(tool_res)
    else:
        # Unknown shape — display raw
        try:
            st.write(tool_res)
        except Exception:
            st.text(str(tool_res))
