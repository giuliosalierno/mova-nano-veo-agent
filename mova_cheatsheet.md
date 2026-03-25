# Mova Nano Veo Agent - Cheatsheet

Guidelines for building an ADK image+video generation agent that works on Agent Engine and Gemini Enterprise (GE) playground.

## Architecture Decisions

### Single agent, not sub-agents
We started with a multi-agent setup (Nano agent for images, Veo agent for videos). This added complexity with no benefit — a single root agent with both tools (`create_frame`, `animate_frame`) is simpler and works better. The LLM handles tool ordering via prompt instructions.

### GCS-direct storage, not ADK artifacts or state
The GE playground uses an `in_memory_runner` that creates a **new temporary session per request**. This means:
- `tool_context.state` does NOT persist between messages
- `session.id` is a random UUID every request
- `tool_context.load_artifact` may not find artifacts saved in a prior request
- Your `artifact_service_builder` is completely bypassed

**Solution:** Store images/videos directly in GCS using `google.cloud.storage`. Key by `tool_context.session.user_id` (stable) — never by `session.id` (random per request).

### Keep `save_artifact` calls for UI display
Even though GCS is the real persistence layer, still call `tool_context.save_artifact()` after saving to GCS. This lets the ADK playground and GE playground render images/videos inline. It's best-effort — don't depend on it for tool-to-tool data flow.

## Model Configuration

### Location must be regional, not `global`
Image and video generation models (`gemini-2.5-flash-image`, `veo-3.1-*`) are **not available** in the `global` endpoint. You'll get `404 NOT_FOUND: Publisher Model was not found`.

```python
# WRONG
client = genai.Client(vertexai=True, project=project_id, location="global")

# CORRECT
client = genai.Client(vertexai=True, project=project_id, location="us-central1")
```

Set `GOOGLE_CLOUD_LOCATION=us-central1` everywhere: code defaults, deploy env vars, `.env`.

### Model names (as of March 2026)
- Image generation: `gemini-2.5-flash-image` (not `gemini-2.5-flash-image-preview`)
- Video generation: `veo-3.1-fast-generate-preview` or `veo-3.1-generate-preview`
- Agent LLM: `gemini-2.5-flash`

Always verify model availability in your project before using.

## Tool Implementation Patterns

### Image generation (`create_frame`)
- Use `generate_content` (non-streaming) — simpler than streaming when you only need one image
- Set `response_modalities=["IMAGE", "TEXT"]`
- Loop through `response.candidates[0].content.parts` looking for `part.inline_data.data`
- For image editing, load the previous image from GCS and prepend it as an image part before the text prompt

### Video generation (`animate_frame`)
- Use `client.aio.models.generate_videos` (async) — video generation takes 30-120 seconds
- Poll with `await asyncio.sleep(10)` + `client.aio.operations.get(operation)`
- Access result via `operation.response.generated_videos[0].video.video_bytes` (not `operation.result`)
- Always check `operation.response and operation.response.generated_videos` before accessing

### Prompt guardrails
The LLM may try to call `animate_frame` before any image exists. Add explicit rules in the agent instruction:

```
CRITICAL RULES:
- You MUST call create_frame first before ever calling animate_frame.
- NEVER call animate_frame unless create_frame has already been called successfully in this conversation.
```

## Agent Engine Deployment

### `litellm` build failure
`google-adk` pulls `litellm` as a transitive dependency, but it's not available in the Agent Engine build environment. Filter it from requirements:

```makefile
uv export --no-hashes --no-header --no-dev --no-emit-project | grep -v "^litellm" > requirements.txt
```

### `LOGS_BUCKET_NAME` must be read at runtime
Don't capture `os.environ.get("LOGS_BUCKET_NAME")` at module import time in a lambda/closure — the env var may not be set during the build phase. Read it inside the builder function:

```python
# WRONG
bucket = os.environ.get("LOGS_BUCKET_NAME")
artifact_service_builder = lambda: GcsArtifactService(bucket_name=bucket)

# CORRECT
def _build_artifact_service():
    bucket = os.environ.get("LOGS_BUCKET_NAME")
    if bucket:
        return GcsArtifactService(bucket_name=bucket)
    return InMemoryArtifactService()
```

### Artifact `app_name` mismatch bug
`AdkApp._convert_response_events` uses `GOOGLE_CLOUD_AGENT_ENGINE_ID` as `app_name`, but the Runner uses `app.name`. This causes artifact lookup failures in the UI. Workaround:

```python
class AgentEngineApp(AdkApp):
    def set_up(self):
        super().set_up()
        app = self._tmpl_attrs.get("app")
        if app:
            self._tmpl_attrs["app_name"] = app.name
```

## GCS Bucket Setup

Create a regional bucket matching your deploy location:

```bash
gcloud storage buckets create gs://YOUR_PROJECT-mova-artifacts --location=us-central1
```

Grant the Agent Engine service account access:

```bash
gcloud storage buckets add-iam-policy-binding gs://YOUR_PROJECT-mova-artifacts \
  --member="serviceAccount:SERVICE_ACCOUNT" \
  --role="roles/storage.objectAdmin"
```

## Quick Reference: What Works Where

| Feature | ADK Web (local) | Agent Engine REST API | GE Playground |
|---------|-----------------|----------------------|---------------|
| `tool_context.state` | Yes | Yes | **No** |
| `tool_context.save_artifact` | Yes | Yes | Best-effort |
| `tool_context.load_artifact` | Yes | Yes | **Unreliable** |
| `session.id` stable | Yes | Yes | **No** (random per request) |
| `session.user_id` stable | Yes | Yes | Yes (`default-user-id`) |
| GCS direct read/write | Yes | Yes | Yes |
