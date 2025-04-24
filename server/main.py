import asyncio
import logging
import json
import uuid

from enum import Enum
from dataclasses import dataclass, asdict

from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    JobRequest,
    WorkerOptions,
    cli,
    stt,
    llm,
    transcription,
    utils,
    WorkerPermissions,
    WorkerType
)
from livekit.plugins import azure, silero, openai
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
    "zh-HK": Language(code="zh-HK", name="Cantonese", flag="🇭🇰"),
    "zh-CN": Language(code="zh-CN", name="Chinese Simplified", flag="🇨🇳"),
}

LanguageCode = Enum(
    "LanguageCode",
    {code: lang.name for code, lang in languages.items()},
)


class Translator:
    def __init__(self, room: rtc.Room, lang: Enum):
        self.room = room
        self.lang = lang
        self.context = llm.ChatContext().append(
            role="system",
            text=(
                f"You are a professional translator for language: {lang.value}. "
                f"Your only response should be the exact translation of input text in the {lang.value} language."
            ),
        )
        self.llm = openai.LLM.with_azure(
            model="gpt-4o-mini",
            temperature=0.8
        )

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


@dataclass
class ParticipantState:
    identity: str
    source_lang: str = "en"
    captions_lang: str = "en"
    captions_enabled: str = "false"
    stt_provider: azure.STT = None
    stt_task: asyncio.Task = None
    translator: Translator = None


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(job: JobContext):
    participants: dict[str, ParticipantState] = {}

    async def _forward_transcription(
        stt_stream: stt.SpeechStream,
        stt_forwarder: transcription.STTSegmentsForwarder,
        track: rtc.Track,
        participant: rtc.RemoteParticipant,
    ):
        async for ev in stt_stream:
            stt_forwarder.update(ev)
            if ev.type == stt.SpeechEventType.INTERIM_TRANSCRIPT:
                print(ev.alternatives[0].text, end="")
            elif ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
                print("\n")
                print(ev.alternatives[0].language, end="")
                print(" -> ", ev.alternatives[0].text)

                message = ev.alternatives[0].text
                # 只在有 translator 時才進行翻譯
                state = participants.get(participant.identity)
                if state and state.translator:
                    asyncio.create_task(
                        state.translator.translate(message, track))

    async def transcribe_track(participant: rtc.RemoteParticipant, track: rtc.Track):
        state = participants.get(participant.identity)
        if not state:
            state = ParticipantState(identity=participant.identity)
            participants[participant.identity] = state

        if not state.stt_provider:
            state.stt_provider = azure.STT()
        stt_provider = state.stt_provider

        audio_stream = rtc.AudioStream(track)
        stt_forwarder = transcription.STTSegmentsForwarder(
            room=job.room, participant=participant, track=track
        )
        stt_stream = stt_provider.stream()
        stt_task = asyncio.create_task(
            _forward_transcription(
                stt_stream, stt_forwarder, track, participant)
        )
        state.stt_task = stt_task

        async for ev in audio_stream:
            stt_stream.push_frame(ev.frame)

    @job.room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        # STT 永遠啟動
        state = participants.get(participant.identity)
        if not state:
            state = ParticipantState(identity=participant.identity)
            participants[participant.identity] = state

        if track.kind == rtc.TrackKind.KIND_AUDIO and not state.stt_task:
            logger.info(
                f"Adding transcriber for participant: {participant.identity}")
            stt_task = asyncio.create_task(
                transcribe_track(participant, track))
            state.stt_task = stt_task

    @job.room.on("participant_attributes_changed")
    def on_attributes_changed(
        changed_attributes: dict[str, str], participant: rtc.Participant
    ):
        # 取得舊狀態
        state = participants.get(participant.identity)
        if not state:
            state = ParticipantState(identity=participant.identity)
            participants[participant.identity] = state

        old_captions_enabled = state.captions_enabled
        old_captions_lang = state.captions_lang
        old_source_lang = state.source_lang

        # 取得新屬性
        new_source_lang = participant.attributes.get("source_language", None)
        new_captions_lang = participant.attributes.get(
            "captions_language", None)
        new_captions_enabled = participant.attributes.get(
            "captions_enabled", None)

        # captions_enabled 只控制翻譯，不再控制 STT 啟動/關閉
        if new_captions_enabled != old_captions_enabled:
            if new_captions_enabled is None or new_captions_enabled.lower() != "true":
                if state.translator:
                    logger.info(
                        f"Removed translator for language: {state.captions_lang} (captions disabled)")
                    state.translator = None

        # captions_lang 或 source_lang 變動時，檢查是否需要建立/移除 translator
        if (
            new_captions_enabled
            and new_captions_enabled.lower() == "true"
            and (new_captions_lang != old_captions_lang or new_source_lang != old_source_lang)
        ):
            if new_source_lang == new_captions_lang:
                # 兩者相同，直接移除 translator，不要建立
                if state.translator:
                    logger.info(
                        f"Removed translator for language: {state.captions_lang} (source and captions language are the same)")
                    state.translator = None
            else:
                # 只有在不同時才建立
                if (
                    not state.translator
                    or state.captions_lang != new_captions_lang
                    or state.source_lang != new_source_lang
                ):
                    if new_captions_lang:
                        try:
                            target_language = LanguageCode[new_captions_lang].value
                            state.translator = Translator(
                                job.room, LanguageCode[new_captions_lang])
                            logger.info(
                                f"Added translator for language: {target_language}")
                        except KeyError:
                            logger.warning(
                                f"Unsupported language requested: {new_captions_lang}")

        # STT provider 語言設定只有 source_lang 變動時才切換
        if state.stt_provider and new_source_lang != old_source_lang and new_source_lang:
            try:
                target_language = LanguageCode[new_source_lang].value
                state.stt_provider.update_options(
                    language=new_source_lang,
                )
                logger.info(
                    f"Updated STT for participant {participant.identity} language: {target_language}")
            except KeyError:
                logger.warning(
                    f"Unsupported language requested: {new_source_lang}")

        # 更新狀態
        state.source_lang = new_source_lang
        state.captions_lang = new_captions_lang
        state.captions_enabled = new_captions_enabled

    # connect to the room
    await job.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    @job.room.local_participant.register_rpc_method("get/languages")
    async def get_languages(data: rtc.RpcInvocationData):
        languages_list = [asdict(lang) for lang in languages.values()]
        return json.dumps(languages_list)


async def request_fnc(req: JobRequest):
    await req.accept(
        name="agent",
        identity=f"agent-{uuid.uuid4()}",
    )


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            request_fnc=request_fnc,
            permissions=WorkerPermissions(
                hidden=True
            ),
            worker_type=WorkerType.PUBLISHER,
        )
    )
