#!/usr/bin/env python3
"""Voice to Text transcription using faster-whisper"""

from faster_whisper import WhisperModel
import sys
import os

# Load model once
MODEL = None

def load_model():
    global MODEL
    if MODEL is None:
        print("Loading Whisper model...")
        MODEL = WhisperModel('small', device='cpu', compute_type='int8')
        print("Model ready")
    return MODEL

def transcribe(audio_path):
    """Transcribe audio file to text"""
    model = load_model()
    
    print(f"Transcribing {audio_path}...")
    segments, info = model.transcribe(audio_path, language='en')
    
    text = ""
    for segment in segments:
        text += segment.text.strip() + " "
    
    return text.strip()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 voice_to_text.py <audio_file>")
        sys.exit(1)
    
    audio_file = sys.argv[1]
    if not os.path.exists(audio_file):
        print(f"File not found: {audio_file}")
        sys.exit(1)
    
    result = transcribe(audio_file)
    print(f"Text: {result}")
