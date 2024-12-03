import asyncio
import logging

from enum import Enum

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    stt,
    llm,
    transcription,
    utils,
)
from livekit.plugins import openai, silero, deepgram
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("transcriber")


class Language(Enum):
    es = "Spanish"
    en = "English"
    de = "German"
    ja = "Japanese"
    fr = "French"


class Translator:
    def __init__(self, room: rtc.Room, lang: Language):
        self.room = room
        self.lang = lang
        self.context = llm.ChatContext().append(
            role="system",
            text=(
                f"You are a translator for language: {lang.value}"
                f"Your only response should be the exact translation of input text in the {lang.value} language ."
            ),
        )
        self.llm = openai.LLM()

    async def translate(self, message: str, track: rtc.Track):
        self.context.append(text=message, role="user")
        stream = self.llm.chat(chat_ctx=self.context)

        translated_message = ""
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content is None:
                break
            translated_message += content

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

        print(
            f"message: {message}, translated to {self.lang.value}: {translated_message}"
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(job: JobContext):
    stt_provider = deepgram.STT()
    tasks = []
    translators = {}

    async def _forward_transcription(
        stt_stream: stt.SpeechStream,
        stt_forwarder: transcription.STTSegmentsForwarder,
        track: rtc.Track,
    ):
        """Forward the transcription and log the transcript in the console"""
        async for ev in stt_stream:
            stt_forwarder.update(ev)
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
        stt_forwarder = transcription.STTSegmentsForwarder(
            room=job.room, participant=participant, track=track
        )
        stt_stream = stt_provider.stream()
        stt_task = asyncio.create_task(
            _forward_transcription(stt_stream, stt_forwarder, track)
        )
        tasks.append(stt_task)

        async for ev in audio_stream:
            stt_stream.push_frame(ev.frame)

    @job.room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logger.info(f"Adding transcriber for participant: {participant.identity}")
            tasks.append(asyncio.create_task(transcribe_track(participant, track)))

    @job.room.on("participant_attributes_changed")
    def on_attributes_changed(
        changed_attributes: dict[str, str], participant: rtc.Participant
    ):
        """
        When participant attributes change, handle new translation requests.
        """
        lang = changed_attributes.get("captions_language", None)
        if lang and lang != Language.en.name and lang not in translators:
            try:
                # Create a translator for the requested language
                target_language = Language[lang].value
                translators[lang] = Translator(job.room, Language[lang])
                logger.info(f"Added translator for language: {target_language}")
            except KeyError:
                logger.warning(f"Unsupported language requested: {lang}")

    await job.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
