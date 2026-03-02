# Voice Reference

## ElevenLabs Voices

ElevenLabs voice names are auto-resolved to UUIDs. Pass the display name (case-insensitive) in the `voice` parameter.

| Voice | UUID | Notes |
|-------|------|-------|
| Rachel | `21m00Tcm4TlvDq8ikWAM` | **Default voice**. Warm, conversational female |
| Drew | `29vD33N1CtxCmqQRPOHJ` | |
| Clyde | `2EiwWnXFnvU5JabPnv8n` | |
| Paul | `5Q0t7uMcjvnagumLfvZi` | |
| Domi | `AZnzlk1XvdvUeBnXmlld` | |
| Dave | `CYw3kZ02Hs0563khs1Fj` | |
| Fin | `D38z5RcWu1voky8WS1ja` | |
| Sarah | `EXAVITQu4vr4xnSDxMaL` | Clear, professional |
| Antoni | `ErXwobaYiN019PkySvjV` | |
| Thomas | `GBv7mTt0atIp3Br8iCZE` | |
| Charlie | `IKne3meq5aSn9XLyUdCD` | |
| George | `JBFqnCBsd6RMkjVDRZzb` | |
| Emily | `LcfcDJNUP1GQjkzn1xUU` | Bright, energetic |
| Elli | `MF3mGyEYCl7XYWbV9V6O` | |
| Patrick | `ODq5zmih8GrVes37Dizd` | |
| Harry | `SOYHLrjzK2X1ezoPC6cr` | |
| Liam | `TX3LPaxmHKxFdv7VOQHJ` | |
| Dorothy | `ThT5KcBeYPX3keUQqHPh` | |
| Josh | `TxGEqnHWrfWFTfGW9XjX` | Friendly male |
| Arnold | `VR6AewLTigWG4xSOukaG` | |
| Charlotte | `XB0fDUnXU5powFXDhCwa` | |
| Alice | `Xb7hH8MSUJpSbSDYk0k2` | |
| Matilda | `XrExE9yKIg1WjnnlVkGX` | |
| James | `ZQe5CZNOzWyzPSCn5a3c` | |
| Michael | `flq6f7yk4E4fJM5XTYuZ` | |
| Ethan | `g5CIjZEefAph4nQFvHAz` | |
| Chris | `iP95p4xoKVk53GoZ742B` | |
| Mimi | `zrHiDhphv9ZnVXBqCLjz` | |
| Brian | `nPczCjzI2devNBz1zQrb` | |
| Sam | `yoZ06aMxZJJ28mfd3POQ` | |
| Lily | `pFZP5JQG7iQjIQuC4Bku` | |
| Bill | `pqHfZKP75CvOlQylNhV4` | |
| Nicole | `piTKgcLEGmPE4e6mEKli` | |
| Daniel | `onwK4e9ZLuTAKqWW03F9` | |
| Adam | `pNInz6obpgDQGcFmaJgB` | Deep, authoritative |
| Glinda | `z9fAnlkpzviPz146aGWa` | |

**Custom voice IDs**: You can also pass a 20-character alphanumeric ElevenLabs UUID directly (e.g., for cloned voices or voices not in this list). Unknown names fall back to Rachel with a warning.

**Model**: Default is `eleven_multilingual_v2`. Can be overridden via the `model` parameter.

## OpenAI Voices

Available voices for OpenAI TTS (`gpt-4o-mini-tts`):

| Voice | Description |
|-------|-------------|
| `alloy` | Neutral, balanced |
| `echo` | Warm, conversational |
| `fable` | Expressive, storytelling |
| `onyx` | Deep, authoritative |
| `nova` | Bright, engaging |
| `shimmer` | Soft, gentle |
| `coral` | Clear, professional |
| `sage` | Calm, measured |

**Style control**: Use the `instructions` parameter to guide speaking style:
```python
generate_media(
    prompt="The quarterly results exceeded expectations.",
    mode="audio",
    voice="coral",
    instructions="confident, upbeat business presentation tone",
    backend_type="openai"
)
```

`instructions` is only supported by OpenAI `gpt-4o-mini-tts`. It has no effect with ElevenLabs.

## Voice Selection Tips

- For narration: Rachel (ElevenLabs) or coral (OpenAI)
- For conversational content: Sarah (ElevenLabs) or echo (OpenAI)
- For authoritative/deep: Adam (ElevenLabs) or onyx (OpenAI)
- For energetic/bright: Emily (ElevenLabs) or nova (OpenAI)
