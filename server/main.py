import asyncio
import logging
import json

from enum import Enum
from dataclasses import dataclass, asdict

from livekit import rtc
from livekit.agents import (
    JobContext,
    WorkerOptions,
    cli,
    stt,
    llm,
)
from livekit.agents.voice.room_io import RoomInputOptions
from livekit.agents.voice import Agent, AgentSession
from livekit.plugins import openai, deepgram, silero, cartesia
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("transcriber")


@dataclass
class Language:
    code: str
    name: str
    flag: str


languages = {
    "en": Language(code="en", name="English", flag="🇺🇸"),
    "es": Language(code="es", name="Spanish", flag="🇪🇸"),
    "fr": Language(code="fr", name="French", flag="🇫🇷"),
    "de": Language(code="de", name="German", flag="🇩🇪"),
    "ja": Language(code="ja", name="Japanese", flag="🇯🇵"),
}

LanguageCode = Enum(
    "LanguageCode",  # Name of the Enum
    {code: lang.name for code, lang in languages.items()},  # Enum entries
)


class Translator:
    """Handles real-time translation of transcribed text to target languages."""
    def __init__(self, session: AgentSession, lang: Enum):
        """Initialize translator for a specific language."""
        self.session = session
        self.lang = lang
        self.context = llm.ChatContext().add_message(
            role="system",
            content=(
                f"You are a translator for language: {lang.value}"
                f"Your only response should be the exact translation of input text in the {lang.value} language ."
            ),
        )
        self.llm = openai.LLM()
        # self.context = llm.ChatContext().append(
        #     role="system",
        #     text=(
        #         f"You are a translator for language: {lang.value}"
        #         f"Your only response should be the exact translation of input text in the {lang.value} language ."
        #     ),
        # )
        # self.llm = openai.LLM()

    async def translate(self, message: str):
        """Translate message to target language and publish transcription."""
        self.context.append(text=message, role="user")
        stream = self.llm.chat(chat_ctx=self.context)

        translated_message = ""
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is None:
                break
            translated_message += content

        await self.session.publish_transcription(
            text=translated_message,
            language=self.lang.name,
            final=True
        )

        logger.info("%s: message: %s, translated to %s: %s", self.session.local_participant.identity, message, self.lang.value, translated_message)


class TranslationAgent(Agent):
    """Main agent that manages audio transcription and multilingual translation."""
    def __init__(self) -> None:
        super().__init__(
            instructions="You are Echo.",
            stt=deepgram.STT(),
            vad=silero.VAD.load(),
            llm=openai.LLM(model="gpt-4o-mini"),
            tts=cartesia.TTS(),
        )
        self.translators = {}

    # def __init__(self):
    #     # super().__init__(
    #     #     stt=deepgram.STT(),
    #     #     vad=silero.VAD.load(),
    #     #     llm=openai.LLM(),
    #     # )
    #     self.translators = {}

    async def on_start(self, session: AgentSession):
        """Initialize agent session with RPC methods and event handlers."""
        # Register RPC method
        @session.local_participant.register_rpc_method("get/languages")
        async def get_languages(data: rtc.RpcInvocationData):
            logger.info("%s: get_languages %s", session.local_participant.identity, data)
            languages_list = [asdict(lang) for lang in languages.values()]
            return json.dumps(languages_list)

        # Handle existing participants
        for participant in session.room.remote_participants.values():
            self._setup_participant(participant)

        # Set up event handlers
        session.room.on("track_subscribed", self._on_track_subscribed)
        session.room.on("participant_attributes_changed", self._on_attributes_changed)

    def _setup_participant(self, participant: rtc.RemoteParticipant):
        if participant.identity == self.session.local_participant.identity:
            return

        # Set up audio track handling
        for pub in participant.tracks.values():
            if pub.track and pub.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(self._transcribe_track(participant, pub.track))

    async def _transcribe_track(self, participant: rtc.RemoteParticipant, track: rtc.Track):
        audio_stream = rtc.AudioStream(track)
        async for frame in audio_stream:
            self.stt.push_frame(frame)

    def _on_track_subscribed(self, track: rtc.Track, publication: rtc.TrackPublication, 
                           participant: rtc.RemoteParticipant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info("%s: Adding transcriber for participant: %s", publication.identity, participant.identity)
            asyncio.create_task(self._transcribe_track(participant, track))

    def _on_attributes_changed(self, changed_attributes: dict[str, str], participant: rtc.Participant):
        lang = changed_attributes.get("captions_language", None)
        if lang and lang != LanguageCode.en.name and lang not in self.translators:
            try:
                target_language = LanguageCode[lang].value
                self.translators[lang] = Translator(self.session, LanguageCode[lang])
                logger.info("%s: Added translator for language: %s", participant.identity, target_language)
            except KeyError:
                logger.warning("%s: Unsupported language requested: %s", participant.identity, lang)

    async def on_stt_event(self, event: stt.SpeechEvent):
        """Handle STT events and forward final transcripts to translators."""
        if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
            message = event.alternatives[0].text
            for translator in self.translators.values():
                asyncio.create_task(translator.translate(message))


async def entrypoint(ctx: JobContext):
    """Main entrypoint for the translation agent service."""
    await ctx.connect()
    
    session = AgentSession()
    await session.start(
        agent=TranslationAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(),
            # auto_subscribe=rtc.AutoSubscribe.AUDIO_ONLY
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
