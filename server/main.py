import asyncio
import logging
import json

from enum import Enum
from dataclasses import dataclass, asdict

from livekit import rtc
from livekit.agents import (
    JobContext,
    JobProcess,
    JobRequest,
    WorkerOptions,
    cli,
    stt,
    llm,
    utils,
)
from livekit.plugins import openai, deepgram, silero
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("transcriber")


@dataclass
class Language:
    """Represents a language with its code, name, and flag emoji."""
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
    def __init__(self, room: rtc.Room, lang: Enum):
        """Initialize translator for a specific language."""
        self.room = room
        self.lang = lang
        self.context = llm.ChatContext().add_message(
            role="system",
            content=(
                f"You are a translator for language: {lang.value}"
                f"Your only response should be the exact translation of input text in the {lang.value} language ."
            ),
        )
        self.llm = openai.LLM()

    async def translate(self, message: str, track: rtc.Track):
        """Translate message to target language and publish transcription."""
        self.context.append(text=message, role="user")
        stream = self.llm.chat(chat_ctx=self.context)

        translated_message = ""
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is None:
                break
            translated_message += content

        print("======== translate ==========")
        print(translated_message)
        print("======== translate ==========")
        segment = rtc.TranscriptionSegment(
            id=utils.misc.shortuuid("SG_"),
            text=translated_message,
            start_time=0,
            end_time=0,
            language=self.lang.name,
            final=True,
        )
        transcription = rtc.Transcription(
            self.room.local_participant.identity, track.sid, [segment]
        )
        await self.room.local_participant.publish_transcription(transcription)

        logger.info(f"message: {message}, translated to {self.lang.value}: {translated_message}")



def prewarm(proc: JobProcess):
    """Preload VAD model to accelerate agent initialization."""
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    """Main entrypoint for the translation agent service."""
    stt_provider = deepgram.STT()
    tasks = []
    translators = {}

    async def _forward_transcription(
        stt_stream: stt.SpeechStream,
        stt_forwarder: None,
        #stt_forwarder: transcription.STTSegmentsForwarder,
        track: rtc.Track,
    ):
        """Forward the transcription and log the transcript in the console"""
        async for ev in stt_stream:
            print(ev)
            #stt_forwarder.update(ev)
            # log to console
            if ev.type == stt.SpeechEventType.INTERIM_TRANSCRIPT:
                print(ev.alternatives[0].text, end="")
            elif ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
                print("\n")
                print(" -> ", ev.alternatives[0].text)

                message = ev.alternatives[0].text
                for translator in translators.values():
                    asyncio.create_task(translator.translate(message, track))

    async def transcribe_track(participant: rtc.RemoteParticipant, track: rtc.Track):
        audio_stream = rtc.AudioStream(track)
        stt_forwarder = None 
        # stt_forwarder = transcription.STTSegmentsForwarder(
        #     room=ctx.room, participant=participant, track=track
        # )
        stt_stream = stt_provider.stream()
        stt_task = asyncio.create_task(
            _forward_transcription(stt_stream, stt_forwarder, track)
        )
        tasks.append(stt_task)

        async for ev in audio_stream:
            stt_stream.push_frame(ev.frame)

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"Adding transcriber for participant: {participant.identity}")
            tasks.append(asyncio.create_task(transcribe_track(participant, track)))

    @ctx.room.on("participant_attributes_changed")
    def on_attributes_changed(
        changed_attributes: dict[str, str], participant: rtc.Participant
    ):
        """
        When participant attributes change, handle new translation requests.
        """
        lang = changed_attributes.get("captions_language", None)
        if lang and lang != LanguageCode.en.name and lang not in translators:
            try:
                # Create a translator for the requested language
                target_language = LanguageCode[lang].value
                translators[lang] = Translator(ctx.room, LanguageCode[lang])
                logger.info(f"Added translator for language: {target_language}")
            except KeyError:
                logger.warning(f"Unsupported language requested: {lang}")


    await ctx.connect()

    @ctx.room.local_participant.register_rpc_method("get/languages")
    async def get_languages(data: rtc.RpcInvocationData):
        print("======== get_languages ==========")
        languages_list = [asdict(lang) for lang in languages.values()]
        return json.dumps(languages_list)
  
async def request_fnc(req: JobRequest):
    """Handle incoming job requests by accepting them."""
    await req.accept(
        name="agent",
        identity="agent",
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        request_fnc=request_fnc
    ))
