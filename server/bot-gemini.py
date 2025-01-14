"""
Gemini Bot Implementation.

This module implements a chatbot using Google's Gemini Multimodal Live model.
It includes:
- Real-time audio interaction
- Speech-to-speech using the Gemini Multimodal Live API
- Transcription using Gemini's generate_content API
- RTVI client/server events
"""

import asyncio
from datetime import date
import sys
import os

import aiohttp
from requests import get
from loguru import logger
from runner import configure

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import Frame, EndFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frameworks.rtvi import (
    RTVIBotTranscriptionProcessor,
    RTVIMetricsProcessor,
    RTVISpeakingProcessor,
    RTVIUserTranscriptionProcessor,
)
from pipecat.services.gemini_multimodal_live.gemini import GeminiMultimodalLiveLLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from helper_functions import *
from fuzzywuzzy import fuzz
from dotenv import load_dotenv

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")
load_dotenv()

class UserTranscriptionFrameFilter(FrameProcessor):
    """Filter out UserTranscription frames."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and frame.user_id == "user":
            return

        await self.push_frame(frame, direction)


async def main():
    """Main bot execution function.

    Sets up and runs the bot pipeline including:
    - Daily video transport with specific audio parameters
    - Gemini Live multimodal model integration
    - Voice activity detection
    - Animation processing
    - RTVI event handling
    """
    async with aiohttp.ClientSession() as session:
        (room_url, token, user_id) = await configure(session)
        print("user:", user_id)

        data = get(f"https://dialmateai.vercel.app/api/customer?id={user_id}").json()
        name = data["name"]
        context = data["context"]
        userId = data["userId"]

        async def get_product(function_name, tool_call_id, arguments, llm, context, result_callback):
            """
            Retrieve product details based on the user's query and provide a relevant response.
            
            Parameters:
                arguments (dict): Contains query parameters, including 'product_name'.
            """
            wanted_product = arguments["product"]
            prod = get(f"https://dialmateai.vercel.app/api/product?userId={userId}").json()
            
            for product_data in prod:
                product_name = product_data["name"]
                
                # Use fuzzy matching to compare product names
                similarity_score = fuzz.ratio(product_name.lower(), wanted_product.lower())
                
                if similarity_score >= 60:
                    product_desc = product_data["description"]
                    product_price = product_data["price"]
                    status = "Available"
                    break
            else:
                product_name = "Product"
                product_desc = "N/A"
                product_price = "N/A"
                status = "Not available"
            
            await result_callback(f"{product_name} is {status}. Price: {product_price}. Description: {product_desc}")



        SYSTEM_INSTRUCTION = f"""
        You are DialMate.
        Think you are an expert sales agent.

        Your output will be converted to audio so don't include special characters in your answers.

        Today is {date.today().strftime("%A, %B %d, %Y")} and you are talking with {name} about {context}. If there is a long silence, say 'Hello?'
        Use function tools wherever necessary.
        """
        
        system_prompt = f"""
        You are a helpful sales agent who converses with a user and answers questions. Respond concisely to general questions.
        Your response will be turned into speech so use only simple words and punctuation.
        Today is {date.today().strftime("%A, %B %d, %Y")} and you are talking with {name} about {context}. If there is a long silence, say 'Hello?'
        Use function tools wherever necessary.
        """

        # Set up Daily transport with specific audio/video parameters for Gemini
        transport = DailyTransport(
            room_url,
            token,
            "Chatbot",
            DailyParams(
                audio_in_sample_rate=16000,
                audio_out_sample_rate=24000,
                audio_out_enabled=True,
                camera_out_enabled=True,
                camera_out_width=1024,
                camera_out_height=576,
                vad_enabled=True,
                vad_audio_passthrough=True,
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.5)),
            ),
        )

        tools = [
            {
                "google_search": {}
            },
            {
                "code_execution": {}
            },
            {
                "function_declarations": [
                    {
                        "name": "get_product",
                        "description": "Get products information by giving product name. For example: Tell me about your products.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "product": {
                                    "type": "string",
                                    "description": "The product name. Example: Toothpaste, Smartphone.",
                                },
                            },
                            "required": ["product"],
                        },
                    },
                    {
                        "name": "escalate_to_human",
                        "description": "Escalates the query to a human agent and informs the user about the next steps. For example: I want to talk to a human.",
                    },
                    {
                        "name": "schedule_appointment",
                        "description": "Schedules an appointment on given date time and place. For example: When someone asks to schedule an appointment.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "date_time": {
                                    "type": "string",
                                    "description": "The date and time for the schedule of appointment.",
                                },
                                "place": {
                                    "type": "string",
                                    "description": "The place for the scheduled appointment to happen.",
                                },
                            },
                            "required": ["date_time", "place"],
                        }
                    }
                ]
            }
        ]

        # Initialize the Gemini Multimodal Live model
        llm = GeminiMultimodalLiveLLMService(
            api_key=os.getenv('GEMINI_API_KEY'),
            voice_id="Kore",  # Options: Aoede, Charon, Fenrir, Kore, Puck
            transcribe_user_audio=True,
            transcribe_model_audio=True,
            system_instruction=SYSTEM_INSTRUCTION,
            tools=tools,
        )

        llm.register_function("get_product", get_product)
        llm.register_function("schedule_appointment", schedule_appointment)
        llm.register_function("escalate_to_human", escalate_to_human)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f'Start by saying "Hello, I\'m DialMate. How are you {name}?"'},
        ]

        # Set up conversation context and management
        context = OpenAILLMContext(messages, tools=tools)
        context_aggregator = llm.create_context_aggregator(context)

        # RTVI events for Pipecat client UI
        rtvi_speaking = RTVISpeakingProcessor()
        rtvi_user_transcription = RTVIUserTranscriptionProcessor()
        rtvi_bot_transcription = RTVIBotTranscriptionProcessor()
        rtvi_metrics = RTVIMetricsProcessor()

        pipeline = Pipeline(
            [
                transport.input(),
                context_aggregator.user(),
                llm,
                rtvi_speaking,
                rtvi_user_transcription,
                UserTranscriptionFrameFilter(),
                rtvi_bot_transcription,
                rtvi_metrics,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            PipelineParams(
                allow_interruptions=True,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
        )

        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            await transport.capture_participant_transcription(participant["id"])
            await task.queue_frames([context_aggregator.user().get_context_frame()])

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            print(f"Participant left: {participant}")
            await task.queue_frame(EndFrame())

        runner = PipelineRunner()

        await runner.run(task)


if __name__ == "__main__":
    asyncio.run(main())
