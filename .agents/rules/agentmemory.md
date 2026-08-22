# AgentMemory: Context Restoration at Session Start

When starting a new conversation or when the user asks to resume/continue previous work:

## Mandatory First Steps (call in parallel)

1. **`memory_smart_search`** — query with project name and relevant keywords
   - Filter results where `sessionId = "memory"` → these are **durable Memories** (decisions, preferences, facts saved via `memory_save`)
   - These correspond to the MEMORIES tab in the agentmemory dashboard
2. **`memory_recall`** with `format: "full"` — query about recent work context
   - Returns both saved memories AND session observations
3. **`memory_lesson_recall`** — query about the project to retrieve saved lessons

## Key Distinction

| Layer | sessionId | What it contains | Value |
|---|---|---|---|
| **Memories** (durable) | `"memory"` | Facts, decisions, preferences via `memory_save` | ⭐ HIGH |
| **Observations** (session) | UUID like `c397835c...` | Auto-recorded file reads, searches, commands | LOW (noisy) |

## Do NOT

- Do NOT rely solely on `memory_sessions` — it only returns session metadata (IDs, timestamps), not actual content
- Do NOT use `memory_recall` with overly generic queries — be specific about project context, features, or recent milestones
- Do NOT ignore entries with `sessionId: "memory"` — these are the most curated and valuable
