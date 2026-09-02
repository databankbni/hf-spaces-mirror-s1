import os
import json
import asyncio
import hashlib
from typing import Optional, Dict
from datetime import datetime
import edge_tts
from groq import Groq
from app.services.appwrite_db import get_appwrite_db
from app.config import settings

class AudioService:
    def __init__(self):
        # Use Sync client to avoid 'unknown async library' errors with anyio/Proactor on Windows
        self.groq_client = Groq(api_key=settings.GROQ_API_KEY)
        self.voice = "en-US-AndrewNeural"
        
    def _generate_summary_sync(self, content: str) -> str:
        """Synchronous wrapper for Groq API"""
        try:
            chat_completion = self.groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional news anchor. Summarize the following news article into a short, engaging script for audio broadcast. Keep it under 100 words. Focus on the key facts. Do not use special characters or formatting like markdown. Just plain text spoken naturally."
                    },
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
                model="llama-3.3-70b-versatile",
                temperature=0.5,
                max_tokens=150,
            )
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error in Groq Sync API: {e}")
            raise e

    async def generate_summary(self, content: str) -> str:
        """Generate a concise audio-friendly summary using Groq (Threaded)"""
        try:
            # Run blocking sync IO in a separate thread to keep event loop free
            return await asyncio.to_thread(self._generate_summary_sync, content)
        except Exception as e:
            print(f"Error generating summary: {e}")
            return ""

    def _generate_audio_subprocess(self, text: str, output_path: str) -> bool:
        """Helper to run edge-tts in a separate process for stability"""
        import subprocess
        import sys
        import tempfile
        
        temp_file_path = None
        try:
            # Create temp file with utf-8 encoding
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as f:
                f.write(text)
                temp_file_path = f.name
                
            # Construct command: python -m edge_tts --file <temp> --write-media <out> --voice <voice>
            cmd = [
                sys.executable, "-m", "edge_tts",
                "--file", temp_file_path,
                "--write-media", output_path,
                "--voice", self.voice
            ]
            
            # Run blocking subprocess (safe in thread)
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"Error running edge-tts subprocess: {e.stderr}")
            return False
        except Exception as e:
            print(f"General error in audio subprocess: {e}")
            return False
        finally:
            # Cleanup temp file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except:
                    pass

    async def generate_audio(self, text: str, output_path: str) -> bool:
        """Generate audio file from text using Edge TTS (Subprocess)"""
        try:
            # Run the subprocess wrapper in a thread to keep main loop free
            return await asyncio.to_thread(self._generate_audio_subprocess, text, output_path)
        except Exception as e:
            print(f"Error generating audio: {e}")
            return False

    async def upload_audio(self, file_path: str, file_name: str) -> Optional[str]:
        """Upload audio file to Appwrite Storage and return view URL"""
        try:
            appwrite = get_appwrite_db()
            if not appwrite.initialized or not appwrite.storage:
                print("Appwrite Storage not initialized")
                return None
            
            # Ensure bucket exists (or valid) - we assume user created it as 'audio-summaries'
            bucket_id = settings.APPWRITE_AUDIO_BUCKET_ID
            
            # Use InputFile for file upload
            from appwrite.input_file import InputFile
            
            # Run blocking storage upload in a thread
            result = await asyncio.to_thread(
                appwrite.storage.create_file,
                bucket_id=bucket_id,
                file_id='unique()',
                file=InputFile.from_path(file_path)
            )
            
            # Get View URL
            # The SDK might not return the full URL in result, so we construct it or use get_file_view
            # Usually: endpoint/storage/buckets/{bucketId}/files/{fileId}/view?project={projectId}
            # function: storage.get_file_view(bucket_id, file_id) -> returns bytes? No, returns URL in some SDKs or bytes in others?
            # Actually, get_file_view usually returns the file CONTENT (bytes). 
            # We want the URL. 
            # We can construct it manually to be safe, or check if there is a helper.
            # Manual construction is reliable for public buckets.
            
            file_id = result['$id']
            view_url = f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{bucket_id}/files/{file_id}/view?project={settings.APPWRITE_PROJECT_ID}"
            
            return view_url
            
        except Exception as e:
             print(f"Error uploading audio: {e}")
             return None

# Singleton
audio_service = AudioService()
