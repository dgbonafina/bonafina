from __future__ import annotations

import io
import json
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

import whisper
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

app = FastAPI(title="Generador de subtítulos por palabra")
MODEL_NAME = "small"
model = whisper.load_model(MODEL_NAME)


def _format_timestamp_srt(seconds: float) -> str:
    total_ms = max(int(seconds * 1000), 0)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    total_ms = max(int(seconds * 1000), 0)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _clean_word(word: str) -> str:
    word = word.strip()
    word = re.sub(r"\s+", " ", word)
    return word


def _extract_words(transcript: dict) -> list[dict]:
    words: list[dict] = []
    for segment in transcript.get("segments", []):
        for word in segment.get("words", []):
            start = word.get("start")
            end = word.get("end")
            text = _clean_word(word.get("word", ""))
            if start is None or end is None or not text:
                continue
            words.append({"start": float(start), "end": float(end), "text": text})
    return words


def _group_words(words: list[dict], words_per_cue: int) -> list[dict]:
    cues: list[dict] = []
    for i in range(0, len(words), words_per_cue):
        chunk = words[i : i + words_per_cue]
        if not chunk:
            continue
        text = " ".join(item["text"] for item in chunk)
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        cues.append(
            {
                "index": len(cues) + 1,
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "text": text.strip(),
            }
        )
    return cues


def _to_srt(cues: Iterable[dict]) -> str:
    chunks = []
    for cue in cues:
        chunks.append(
            f"{cue['index']}\n{_format_timestamp_srt(cue['start'])} --> {_format_timestamp_srt(cue['end'])}\n{cue['text']}\n"
        )
    return "\n".join(chunks).strip() + "\n"


def _to_vtt(cues: Iterable[dict]) -> str:
    chunks = ["WEBVTT\n"]
    for cue in cues:
        chunks.append(
            f"{_format_timestamp_vtt(cue['start'])} --> {_format_timestamp_vtt(cue['end'])}\n{cue['text']}\n"
        )
    return "\n".join(chunks).strip() + "\n"


def _to_ass(cues: Iterable[dict]) -> str:
    header = """[Script Info]
Title: Subtitulos auto
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,40,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,20,20,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def ts(seconds: float) -> str:
        centis = max(int(seconds * 100), 0)
        h, rem = divmod(centis, 360_000)
        m, rem = divmod(rem, 6000)
        s, cs = divmod(rem, 100)
        return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

    lines = [header]
    for cue in cues:
        text = cue["text"].replace("\n", " ")
        lines.append(
            f"Dialogue: 0,{ts(cue['start'])},{ts(cue['end'])},Default,,0,0,0,,{text}"
        )
    return "\n".join(lines).strip() + "\n"


@app.get("/")
def read_index() -> FileResponse:
    return FileResponse("index.html")


@app.get("/styles.css")
def read_styles() -> FileResponse:
    return FileResponse("styles.css")


@app.post("/api/generate-subtitles")
async def generate_subtitles(
    video: UploadFile = File(...),
    words_per_cue: int = Form(2),
    formats: list[str] = Form(["srt", "vtt", "ass"]),
    language: str | None = Form(None),
):
    if words_per_cue not in {1, 2}:
        raise HTTPException(status_code=400, detail="words_per_cue solo acepta 1 o 2")

    valid_formats = {"srt", "vtt", "ass", "json"}
    selected = [fmt.lower() for fmt in formats if fmt.lower() in valid_formats]
    if not selected:
        raise HTTPException(status_code=400, detail="No hay formatos válidos seleccionados")

    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        payload = await video.read()
        tmp.write(payload)
        video_path = tmp.name

    options: dict = {"word_timestamps": True, "verbose": False}
    if language:
        options["language"] = language.strip().lower()

    transcript = model.transcribe(video_path, **options)
    words = _extract_words(transcript)
    if not words:
        raise HTTPException(status_code=422, detail="No se detectó voz en el video")

    cues = _group_words(words, words_per_cue)

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zipf:
        if "srt" in selected:
            zipf.writestr("subtitulos.srt", _to_srt(cues))
        if "vtt" in selected:
            zipf.writestr("subtitulos.vtt", _to_vtt(cues))
        if "ass" in selected:
            zipf.writestr("subtitulos.ass", _to_ass(cues))
        if "json" in selected:
            zipf.writestr("subtitulos.json", json.dumps(cues, ensure_ascii=False, indent=2))

    output.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="subtitulos.zip"'}
    return StreamingResponse(output, media_type="application/zip", headers=headers)
