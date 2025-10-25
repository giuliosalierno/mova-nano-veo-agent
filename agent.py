from google.adk.agents import Agent
from dotenv import load_dotenv
from .prompts import MOVA_INSTRUCTION
from .tools import create_frame, animate_frame
import google.auth
import os

# Load environment variables from .env file
load_dotenv()

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

# --- Nano Agent ---
nano_agent = Agent(
    name="nano_agent",
    model="gemini-2.5-flash",
    instruction="You are Nano, an AI assistant that creates still frames for animations. Use the `create_frame` tool to generate an image based on the user's prompt. The image will be saved with the key 'created_frame.png'.",
    tools=[create_frame],
    description="Creates a still frame for an animation.",
)

# --- Veo Agent ---
veo_agent = Agent(
    name="veo_agent",
    model="gemini-2.5-flash",
    instruction="You are Veo, an AI assistant that animates still frames. Use the `animate_frame` tool to generate a video from the image saved with the key 'created_frame.png'. You will be given a prompt.",
    tools=[animate_frame],
    description="Animates a still frame.",
)

# --- Root Agent ---
root_agent = Agent(
    name="Mova",
    model="gemini-2.5-flash",
    instruction=MOVA_INSTRUCTION,
    sub_agents=[
        nano_agent,
        veo_agent
    ],
    description="This is the root agent that orchestrates the video generation process.",
)
