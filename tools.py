import asyncio
import os

import google.auth
import google.genai as genai
from google.adk.tools import ToolContext
from google.cloud import storage
from google.genai import types
from google.genai.types import Image

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

client = genai.Client(
    vertexai=True,
    project=project_id,
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

BUCKET_NAME = os.environ.get(
    "LOGS_BUCKET_NAME", f"{project_id}-mova-artifacts"
)
gcs_client = storage.Client(project=project_id)
bucket = gcs_client.bucket(BUCKET_NAME)


def _gcs_path(user_id: str, filename: str) -> str:
    return f"artifacts/{user_id}/{filename}"


def _save_to_gcs(user_id: str, filename: str, data: bytes, content_type: str) -> str:
    path = _gcs_path(user_id, filename)
    blob = bucket.blob(path)
    blob.upload_from_string(data, content_type=content_type)
    print(f"[gcs] Saved gs://{BUCKET_NAME}/{path} ({len(data)} bytes)", flush=True)
    return path


def _load_from_gcs(user_id: str, filename: str) -> bytes | None:
    path = _gcs_path(user_id, filename)
    blob = bucket.blob(path)
    if not blob.exists():
        print(f"[gcs] Not found: gs://{BUCKET_NAME}/{path}", flush=True)
        return None
    data = blob.download_as_bytes()
    print(f"[gcs] Loaded gs://{BUCKET_NAME}/{path} ({len(data)} bytes)", flush=True)
    return data


async def create_frame(
    tool_context: ToolContext, prompt: str, is_image_edit: bool
):
    """
    Use this tool to create an image or to modify a previously generated image based on a user request.
    Args:
    prompt: the prompt to create or edit an image based on the user requests.
    is_image_edit: Set this to True if the user wants edit a previous generated image, False otherwise (create a brand new image)
    """
    try:
        model = "gemini-2.5-flash-image"
        enhanced_prompt = f"photorealistic, cinematic, high quality, {prompt}"
        print(f"[create_frame] called: is_image_edit={is_image_edit}, prompt='{prompt[:100]}'", flush=True)

        user_id = tool_context.session.user_id

        parts = [types.Part.from_text(text=enhanced_prompt)]

        if is_image_edit:
            prev_bytes = _load_from_gcs(user_id, "latest_frame.png")
            if prev_bytes:
                parts.insert(0, types.Part.from_bytes(data=prev_bytes, mime_type="image/png"))

        contents = [types.Content(role="user", parts=parts)]

        generate_content_config = types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        )

        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if not (
                chunk.candidates
                and chunk.candidates[0].content
                and chunk.candidates[0].content.parts
            ):
                continue

            part = chunk.candidates[0].content.parts[0]

            if part.inline_data and part.inline_data.data:
                img_data = part.inline_data.data
                _save_to_gcs(user_id, "latest_frame.png", img_data, "image/png")

                # Also save as artifact for UI display
                await tool_context.save_artifact("created_frame.png", part)

                return {"status": "success", "message": "Image created successfully."}

            if chunk.text:
                print(f"[create_frame] Text chunk: {chunk.text}", flush=True)

        print("[create_frame] FAILED - no image data in response", flush=True)
        return {"status": "error", "message": "Image generation failed."}
    except Exception as e:
        import traceback
        print(f"[create_frame] EXCEPTION: {traceback.format_exc()}", flush=True)
        return {"status": "error", "message": f"Image generation error: {str(e)}"}


async def animate_frame(prompt: str, tool_context: ToolContext) -> dict:
    """
    Use this tool to animate a previously generated image. Never call this tool if an image has never been generated or if the user asks to generate a new image and the image still need to be generated.
    Args:
    prompt: the prompt to generate the video tailored on the user request
    """

    video_model = "veo-3.1-generate-preview"
    video_model_fast = "veo-3.1-fast-generate-preview"

    is_fast_veo = True
    if is_fast_veo:
        video_model = video_model_fast

    user_id = tool_context.session.user_id

    # Load image directly from GCS
    print(f"[animate_frame] Loading image from GCS (user={user_id})", flush=True)
    img_bytes = _load_from_gcs(user_id, "latest_frame.png")

    if not img_bytes:
        print("[animate_frame] FAILED - no image in GCS", flush=True)
        return {"status": "error", "message": "Could not find any generated image. Please create an image first."}

    print(f"[animate_frame] Image loaded ({len(img_bytes)} bytes), generating video...", flush=True)

    operation = await client.aio.models.generate_videos(
        model=video_model,
        prompt=prompt,
        image=Image(image_bytes=img_bytes, mime_type="image/png"),
        config=types.GenerateVideosConfig(
            aspect_ratio="16:9",
            number_of_videos=1,
            duration_seconds=8,
            person_generation="allow_adult",
            enhance_prompt=True,
            generate_audio=True,
        ),
    )

    while not operation.done:
        await asyncio.sleep(10)
        operation = await client.aio.operations.get(operation)

    if operation.response and operation.response.generated_videos:
        video_bytes = operation.response.generated_videos[0].video.video_bytes
        if not video_bytes:
            return {"status": "error", "message": "Video generation returned empty video data."}

        # Save to GCS
        _save_to_gcs(user_id, "animation.mp4", video_bytes, "video/mp4")

        # Also save as artifact for UI display
        artifact_part = types.Part(
            inline_data=types.Blob(
                mime_type="video/mp4",
                data=video_bytes,
            )
        )
        await tool_context.save_artifact(
            filename="animation.mp4",
            artifact=artifact_part,
        )

        return {"status": "success", "message": "Video generated successfully."}

    error_msg = "Video animation failed."
    if operation.error:
        error_msg += f" Error: {operation.error.message}"
    return {"status": "error", "message": error_msg}
