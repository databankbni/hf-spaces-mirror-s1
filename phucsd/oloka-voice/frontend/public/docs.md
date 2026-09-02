# OmniVoice Gateway API Documentation

OmniVoice Gateway is a secure, high-performance RESTful API and user gateway for speech synthesis, voice cloning, automatic speech recognition, and video dubbing. This document serves as a complete reference for bots, coding agents, and developers integrating OmniVoice.

---

## 1. Overview & General Info

* **Protocol**: HTTPS REST API
* **Base URL**: The gateway client resolves the backend URL dynamically. In local development it is typically `http://localhost:8000` or proxied to a Hugging Face Space backend (e.g., `https://voice.oloka.net`).
* **Request & Response Format**: JSON (UTF-8 encoding). Audio files are returned as binary downloads (WAV / MP4).

---

## 2. Authentication

All requests to secured endpoints must include your API Key in the `Authorization` header as a Bearer token:

```http
Authorization: Bearer YOUR_API_KEY
```

Some public endpoints (like reading the public voice library) do not require authentication. Some media preview links support authentication via a query parameter: `?token=YOUR_API_KEY`.

---

## 3. Text-to-Speech (TTS) & Voice Cloning

The TTS pipeline operates asynchronously. You create a job, poll its status, and download the resulting WAV audio once completed.

### 3.1 Create TTS Job
* **Method**: `POST`
* **Path**: `/v1/tts/jobs`
* **Content-Type**: `application/json`

#### Request Body Parameters
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `mode` | string | **Yes** | - | Speech synthesis mode: `clone_voice` (voice cloning), `auto_voice` (pre-defined speaker), or `voice_design` (generated voice). |
| `text` | string | **Yes** | - | The input text to synthesize (recommended max 500 chars). Supports emotional tags and phonetic overrides. |
| `voice_sample_id` | string | Optional | - | The voice ID (`vs_xxxx`) to use for `clone_voice` mode. |
| `ref_text` | string | Optional | - | The reference text corresponding to the voice sample's audio. If omitted, the worker automatically transcribes the sample with Whisper. |
| `speed` | float | Optional | `1.0` | Playback speed multiplier (range: `0.5` to `2.0`). |
| `num_step` | integer | Optional | `32` | Diffusion steps (neural network quality). Range: `16` to `64`. |
| `denoise` | boolean | Optional | `true` | Apply post-inference noise filtering. |
| `guidance_scale` | float | Optional | `2.0` | Classifier-free guidance scale. Higher values follow prompt attributes closely. |
| `t_shift` | float | Optional | `0.1` | Noise schedule time shift. |
| `position_temperature` | float | Optional | `5.0` | Position random temperature. |
| `class_temperature` | float | Optional | `0.0` | Class sample temperature (randomness level). `0.0` is deterministic. |
| `layer_penalty_factor` | float | Optional | `5.0` | Depth codebook penalty factor to boost initial stability. |
| `duration` | float | Optional | - | Fixed output audio length (in seconds). |
| `preprocess_prompt` | boolean | Optional | `true` | Clean and remove silence from the voice sample prompt. |
| `postprocess_output` | boolean | Optional | `true` | Clean and remove trailing silence from output audio. |
| `audio_chunk_duration` | float | Optional | `15.0` | Maximum length of single chunks when processing long text (in seconds). |
| `audio_chunk_threshold` | float | Optional | `30.0` | Text length threshold (in characters/seconds) to trigger multi-chunk division. |
| `with_alignment` | boolean | Optional | `false` | Return word-level timestamps (start and end times) in the job status. |

#### Response (200 OK)
```json
{
  "job_id": "job_1be7696c9157",
  "status": "queued",
  "message": "Job added to queue."
}
```

---

### 3.2 Check Job Status (Polling)
* **Method**: `GET`
* **Path**: `/v1/jobs/{job_id}`

#### Response (200 OK)
```json
{
  "job_id": "job_1be7696c9157",
  "status": "completed",
  "progress": 100,
  "audio_url": "/v1/tts/jobs/job_1be7696c9157/audio",
  "text": "Xin chào, đây là giọng đọc nhân bản.",
  "alignment": [
    { "word": "Xin", "start": 0.12, "end": 0.45 },
    { "word": "chào,", "start": 0.45, "end": 0.78 },
    { "word": "đây", "start": 0.78, "end": 0.98 },
    { "word": "lành", "start": 0.98, "end": 1.25 }
  ],
  "error_message": null,
  "created_at": "2026-07-21T02:00:00.000Z",
  "started_at": "2026-07-21T02:00:01.000Z",
  "completed_at": "2026-07-21T02:00:05.000Z",
  "processing_time": 4.0,
  "queue_time": 1.0,
  "total_time": 5.0
}
```

#### Status States
* `queued`: Job is waiting in the queue.
* `starting_worker`: The assigned GPU worker is initializing.
* `running`: The worker is actively generating audio.
* `completed`: Generation is successful.
* `failed`: Generation failed. The details are in `error_message`.

---

### 3.3 Download Resulting Audio
* **Method**: `GET`
* **Path**: `/v1/tts/jobs/{job_id}/audio`
* **Headers**: `Authorization: Bearer YOUR_API_KEY` (Required!)

Returns a binary stream of the output audio (`audio/wav`).

---

## 4. Word-Level Alignment & Timing

If `with_alignment` was set to `true` during job creation, the successful job status response includes the `alignment` array.
* **Mốc thời gian**: Given as decimal seconds relative to the audio start (`0.0`).
* **Karaoke / Subtitles**: Can be used to sync voiceover words perfectly with on-screen text.

---

## 5. Fine-Grained Speech Controls

You can insert tags directly into the input `text` parameter to manipulate expressions or fix pronunciation.

### 5.1 Non-Verbal Expressions
Inject human sound cues by placing brackets around tags at any point in the text:
* `[laughter]`: Laughter
* `[sigh]`: A sigh of relief or fatigue
* `[sniff]`: Sniffing sound
* `[question-en]`, `[question-ah]`: Confused/inquisitive tone adjustments
* `[surprise-ah]`, `[surprise-oh]`: Surprised reactions

*Example*: `"[laughter] Thật tuyệt vời! [sigh] Nhưng tôi hơi mệt rồi."`

### 5.2 Phonetic Pronunciation Correction (Phonetic Overrides)
Correct spelling overrides when terms, abbreviations, or names are mispronounced:
* **English Phonetics**: Standard CMU capitalization inside brackets:
  * `"read as [B EY1 S]"` (forces pronunciation matching the word "base").
* **Chinese Pinyin & Tones**: Capitalized Pinyin syllables followed by tone numbers (1-4) inside brackets:
  * `"打[ZHE2]出售"` (forces folding tone 2 for 折).

---

## 6. Voice Library & Management

### 6.1 List Public Voice Samples (No Auth Required)
* **Method**: `GET`
* **Path**: `/v1/voice-library`
* **Query Parameters**:
  * `tag` (string, optional): Filter by tags (e.g. `Miền Nam`, `Trẻ`, `Kể chuyện`).
  * `search` (string, optional): Text query to search voice names.
  * `limit` (int, default 50): Page size.
  * `offset` (int, default 0): Pagination offset.

### 6.2 Update Voice Sample Details
* **Method**: `PUT`
* **Path**: `/v1/voice-samples/{voice_sample_id}`
* **Payload Format** (JSON):
  ```json
  {
    "name": "Giọng Nam Bộ Trẻ Đọc Truyện",
    "tags": ["Miền Nam", "Trẻ", "Kể chuyện"],
    "ref_text": "Văn bản tham chiếu mới",
    "is_public": true
  }
  ```

---

## 7. ElevenLabs Compatibility API

You can use standard ElevenLabs SDKs/clients by pointing their base URL to the OmniVoice Gateway endpoint.

### 7.1 List ElevenLabs-compatible Voices
* **Method**: `GET`
* **Path**: `/v1/voices`

Returns a list matching ElevenLabs JSON schema containing combined public and private voice lists.

### 7.2 Get Voice Audio Preview
* **Method**: `GET`
* **Path**: `/v1/voices/{voice_id}/previews`
* **Query Parameter**: `?token=YOUR_API_KEY` (Optional, required only for private voice samples).

Can be directly embedded in standard HTML `<audio>` elements:
```html
<audio src="https://omnivoice-gateway.pages.dev/v1/voices/YOUR_VOICE_ID/previews?token=YOUR_API_KEY" controls />
```

---

## 8. Speech-to-Text (ASR)

Convert uploaded audio files into transcripts.

### 8.1 Create ASR Job
* **Method**: `POST`
* **Path**: `/v1/asr`
* **Content-Type**: `multipart/form-data`
* **Payload**:
  * `file` (Binary file, e.g. WAV, MP3, M4A)

Returns a standard job response containing a `job_id` and initial state.

### 8.2 Poll ASR Job Progress
* **Method**: `GET`
* **Path**: `/v1/jobs/{job_id}`

Upon completion (`status` is `completed`), the transcribed text is available in the `text` attribute of the response.

### 8.3 Get Original ASR Audio
* **Method**: `GET`
* **Path**: `/v1/asr/jobs/{job_id}/audio`

Retrieves the raw audio upload associated with this job.

---

## 9. Video Dubbing API

A multi-stage asynchronous processing pipe to download a video, split audio into dialog vocals and background music (BGM), translate & transcribe segments, generate cloned voices for each speaker, and compile a finalized video.

### 9.1 Upload Local Video File
* **Method**: `POST`
* **Path**: `/v1/video-dubbing/upload`
* **Content-Type**: `multipart/form-data`
* **Payload**:
  * `file`: Binary video file (MP4, MKV, etc.)

Returns a `VideoDubbingJobResponse` containing the `job_id`.

### 9.2 Submit YouTube Video or Update Settings
* **Method**: `POST`
* **Path**: `/v1/video-dubbing`
* **Content-Type**: `application/json`
* **Payload Schema**:
  ```json
  {
    "source_type": "youtube",
    "source_url": "https://www.youtube.com/watch?v=xxxxxx",
    "target_language": "vi"
  }
  ```

---

### 9.3 Get Dubbing Job Status & Subtitles
* **Method**: `GET`
* **Path**: `/v1/video-dubbing/jobs/{job_id}`

Returns the full state machine details including the `subtitles` array of segments:
```json
{
  "id": "dub_xxxx",
  "status": "translated",
  "progress": 70,
  "source_url": "...",
  "target_language": "vi",
  "subtitles": [
    {
      "id": 0,
      "start": 1.25,
      "end": 4.50,
      "text": "Hello, welcome to this video.",
      "translated_text": "Xin chào, chào mừng bạn đến với video này.",
      "speaker": "Speaker 0",
      "voice_sample_id": "vs_default"
    }
  ]
}
```

#### Dubbing Pipeline Status States
1. `downloading`: Fetching video file from source.
2. `separating_audio`: Splitting original vocal path from instruments.
3. `transcribing`: Running Whisper translation & time mapping.
4. `translating`: Translating source transcript to target language.
5. `translated`: Ready for user adjustment. You can now edit the `subtitles` segments.
6. `dubbing`: Running TTS engines to replace voice tracks.
7. `mixing`: Compiling new audio and combining back with BGM and video components.
8. `completed`: Process complete, file ready for output.
9. `failed`: Error encountered.

---

### 9.4 Update Subtitle Segments
Before finalizing, you can correct the translation, alter timing, or assign distinct voices to specific speakers.
* **Method**: `PUT`
* **Path**: `/v1/video-dubbing/jobs/{job_id}/subtitles`
* **Payload**:
  ```json
  {
    "subtitles": [
      {
        "id": 0,
        "translated_text": "Xin chào, rất vui được gặp các bạn!",
        "voice_sample_id": "vs_southern_male",
        "start": 1.25,
        "end": 4.80
      }
    ]
  }
  ```

---

### 9.5 Finalize Dubbing (Trigger Rendering)
* **Method**: `POST`
* **Path**: `/v1/video-dubbing/jobs/{job_id}/finalize`

Triggers the backend worker to dub segments and mix the output channels. Check `/v1/video-dubbing/jobs/{job_id}` for progress (updates status to `dubbing`, `mixing`, then `completed`).

---

### 9.6 Download Pipeline Assets
* **Original Video**: `GET /v1/video-dubbing/jobs/{job_id}/video`
* **Extracted Vocals WAV**: `GET /v1/video-dubbing/jobs/{job_id}/vocals`
* **Extracted BGM WAV**: `GET /v1/video-dubbing/jobs/{job_id}/bgm`
* **Final Dubbed MP4 Video**: `GET /v1/video-dubbing/jobs/{job_id}/output`
* **Real-time Pipeline Logs**: `GET /v1/video-dubbing/jobs/{job_id}/log`

---

## 10. Code Integration Examples

### 10.1 cURL
```bash
# 1. Create TTS Job
curl -X POST "https://voice.oloka.net/v1/tts/jobs" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "clone_voice",
    "voice_sample_id": "vs_xxxx",
    "ref_text": "Văn bản mẫu giọng gốc",
    "text": "Xin chào, đây là cURL request.",
    "speed": 1.0,
    "num_step": 32,
    "with_alignment": true
  }'

# 2. Get Job Status (Repeat every 3-5 seconds)
curl -X GET "https://voice.oloka.net/v1/jobs/YOUR_JOB_ID" \
  -H "Authorization: Bearer YOUR_API_KEY"

# 3. Download WAV Audio File
curl -o output.wav -X GET "https://voice.oloka.net/v1/tts/jobs/YOUR_JOB_ID/audio" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### 10.2 Python
```python
import time
import requests

API_URL = "https://voice.oloka.net"
API_KEY = "YOUR_API_KEY"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

payload = {
    "mode": "clone_voice",
    "voice_sample_id": "vs_xxxx",
    "text": "Xin chào, đây là tích hợp Python.",
    "with_alignment": True
}

# 1. Submit request
response = requests.post(f"{API_URL}/v1/tts/jobs", json=payload, headers=headers)
response.raise_for_status()
job_id = response.json()["job_id"]
print(f"Job created: {job_id}")

# 2. Poll progress
while True:
    status_res = requests.get(f"{API_URL}/v1/jobs/{job_id}", headers=headers)
    status_res.raise_for_status()
    job_data = status_res.json()
    status = job_data["status"]
    print(f"Status: {status} • Progress: {job_data['progress']}%")
    
    if status == "completed":
        break
    elif status == "failed":
        raise Exception(f"Job failed: {job_data['error_message']}")
    time.sleep(3)

# 3. Download output WAV file
audio_res = requests.get(f"{API_URL}/v1/tts/jobs/{job_id}/audio", headers=headers)
audio_res.raise_for_status()
with open("output.wav", "wb") as f:
    f.write(audio_res.content)
print("File downloaded as output.wav")
```

### 10.3 NodeJS
```javascript
const fetch = require('node-fetch'); // Required if running Node < 18
const fs = require('fs');

const API_URL = "https://voice.oloka.net";
const API_KEY = "YOUR_API_KEY";

const headers = {
  'Authorization': `Bearer ${API_KEY}`,
  'Content-Type': 'application/json'
};

async function execute() {
  // 1. Submit job
  const res = await fetch(`${API_URL}/v1/tts/jobs`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      mode: 'clone_voice',
      voice_sample_id: 'vs_xxxx',
      text: 'Xin chào từ NodeJS client.',
      with_alignment: true
    })
  });
  const { job_id } = await res.json();
  console.log(`Job created: ${job_id}`);

  // 2. Poll progress
  while (true) {
    const statusRes = await fetch(`${API_URL}/v1/jobs/${job_id}`, { headers });
    const jobData = await statusRes.json();
    console.log(`Status: ${jobData.status} (${jobData.progress}%)`);
    
    if (jobData.status === 'completed') {
      break;
    } else if (jobData.status === 'failed') {
      throw new Error(`Job failed: ${jobData.error_message}`);
    }
    await new Promise(r => setTimeout(r, 3000));
  }

  // 3. Download WAV Audio
  const audioRes = await fetch(`${API_URL}/v1/tts/jobs/${job_id}/audio`, { headers });
  const buffer = await audioRes.buffer();
  fs.writeFileSync('output.wav', buffer);
  console.log('Audio file saved to output.wav');
}

execute().catch(console.error);
```
