from google.adk.tools import ToolContext
from google.genai import types
import google.genai as genai
from typing import Optional
from dotenv import load_dotenv
from google.genai.types import Image
import time
import os
import google.auth


_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

client = genai.Client(vertexai=True, project=project_id, location="global")

async def create_frame(prompt: str, tool_context: ToolContext, previous_image: Optional[str] = None) -> dict:
    """Generates an image for a character and returns the filename."""
    model = "gemini-2.5-flash-image-preview"
    enhanced_prompt = f"photorealistic, cinematic, high quality, {prompt}"
    
    parts = [types.Part.from_text(text=enhanced_prompt)]
    
    if previous_image:
        try:
            image_part = await tool_context.load_artifact(previous_image)
            parts.insert(0, image_part)
        except Exception as e:
            print(f"Could not load artifact {previous_image}: {e}")

    contents = [types.Content(role="user", parts=parts)]

    generate_content_config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
    )

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=generate_content_config,
    ):
        if (
            chunk.candidates is None
            or chunk.candidates[0].content is None
            or chunk.candidates[0].content.parts is None
        ):
            continue
        if chunk.candidates[0].content.parts[0].inline_data and chunk.candidates[0].content.parts[0].inline_data.data:
            filename = "created_frame.png"
            inline_data = chunk.candidates[0].content.parts[0].inline_data
            image_data = inline_data.data
            await tool_context.save_artifact(
                filename,
                types.Part(
                    inline_data=types.Blob(
                        mime_type=inline_data.mime_type, data=image_data
                    )
                ),
            )
            return {"status": "success", "filename": filename}
        else:
            print(f"Received text chunk from image generation model: {chunk.text}")

    return {"status": "error", "message": "Image generation failed."}


async def animate_frame(prompt: str, tool_context: ToolContext) -> str:
    """
    Generates a video using the Veo model and stores the resulting artifact.
    """
    video_model = "veo-3.0-generate-preview"
    video_model_fast = "veo-3.0-fast-generate-preview"

    is_fast_veo = True
    if is_fast_veo:
        video_model = video_model_fast

    image_part = await tool_context.load_artifact("created_frame.png")
    img_bytes = image_part.inline_data.data

    operation = client.models.generate_videos(
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
        time.sleep(10)
        operation = client.operations.get(operation)
        print(operation)
    if operation.response:
        video_filename = "animation.mp4"
        await tool_context.save_artifact(
            filename=video_filename,
            artifact=types.Part(
                inline_data=types.Blob(
                    mime_type="video/mp4",
                    data=operation.result.generated_videos[0].video.video_bytes,
                )
            ),
        )

    return video_filename
