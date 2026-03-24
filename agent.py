import os

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.apps.app import App

from .prompts import MOVA_INSTRUCTION
from .tools import animate_frame, create_frame

# Load environment variables from .env file
load_dotenv()

_, project_id = google.auth.default()
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

# --- Root Agent ---
root_agent = Agent(
    name="Mova",
    model="gemini-2.5-flash",
    instruction=MOVA_INSTRUCTION,
    description="This is the root agent that orchestrates the video generation process.",
    tools=[create_frame, animate_frame],
)

app = App(
    name="app",
    root_agent=root_agent
)
