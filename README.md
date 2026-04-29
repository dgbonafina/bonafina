# Generador de subtítulos por palabra

Aplicación web para subir un video y generar subtítulos automáticos sincronizados en bloques de 1 o 2 palabras.

## Qué hace

- Transcribe audio de un video con Whisper.
- Usa timestamps por palabra (`word_timestamps=True`).
- Agrupa palabras de a 1 o 2 para lograr subtítulos muy cortos y sincronizados.
- Exporta en múltiples formatos: **SRT**, **VTT**, **ASS** y **JSON**.
- Descarga todo junto en un `.zip`.

## Requisitos

- Python 3.10+
- FFmpeg instalado en el sistema (requerido por Whisper)

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar

```bash
uvicorn main:app --reload
```

Abrir en el navegador: `http://127.0.0.1:8000`

## Notas

- El primer procesamiento puede tardar más porque Whisper descarga el modelo.
- Si querés más precisión para voces difíciles, podés cambiar `MODEL_NAME` en `main.py` a `medium` o `large`.
