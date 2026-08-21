# Answer First Rule

**Trigger & Detection:**
Whenever the user's message contains an interrogative intent in ANY language (e.g., asking questions, seeking reasons, clarifications, confirmations, pointing out an issue as a question, or containing question marks/question words).

**Mandatory Behaviors:**
1. **Stop & Prioritize Answering:** You MUST focus on answering the user's question FIRST. 
2. **No Immediate Action:** Do NOT arbitrarily execute any tool calls, modify code, or run terminal commands in response to a question without explicit permission.
3. **Text-Only Response:** Your response must be purely text-based. Address the question, provide an explanation or assessment, or ask a clarifying question.
4. **Wait for Approval:** ALWAYS end your response by waiting for the user's explicit confirmation or instruction before proceeding to take any concrete actions (e.g., "Would you like me to fix this?", "Should I implement this now?").
