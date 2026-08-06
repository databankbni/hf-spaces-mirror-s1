"""Predict a Bible verse from voice (or text/file).

Usage:
    python predict.py                 # record from mic (press Enter to stop)
    python predict.py --seconds 6     # record a fixed 6 seconds
    python predict.py --file clip.wav # transcribe an audio file
    python predict.py --text "for god so loved the world"   # skip audio

The pipeline: audio -> Whisper transcript -> hybrid verse retrieval.
"""
import argparse

from matcher import VerseMatcher


def confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def get_transcript(args) -> str:
    if args.text:
        return args.text
    if args.file:
        from transcribe import transcribe_file

        return transcribe_file(args.file, args.model)

    # Microphone path.
    from transcribe import transcribe_array

    if args.seconds:
        from record import record_fixed

        audio = record_fixed(args.seconds)
    else:
        from record import record_until_enter

        audio = record_until_enter()

    if len(audio) == 0:
        return ""
    print("Transcribing...")
    return transcribe_array(audio, args.model)


def main():
    ap = argparse.ArgumentParser(description="Predict a Bible verse from voice.")
    ap.add_argument("--text", help="skip audio, match this text directly")
    ap.add_argument("--file", help="transcribe an audio file instead of mic")
    ap.add_argument("--seconds", type=float, help="record a fixed duration")
    ap.add_argument("--model", default="base.en", help="Whisper model name")
    ap.add_argument("--top", type=int, default=5, help="how many matches to show")
    args = ap.parse_args()

    print("Loading verse index...")
    matcher = VerseMatcher()

    transcript = get_transcript(args)
    if not transcript:
        print("No speech detected. Try again.")
        return

    print(f'\nHeard: "{transcript}"')
    results = matcher.predict(transcript, top_k=args.top)
    if not results:
        print("No match found.")
        return

    best = results[0]
    print("\n" + "=" * 60)
    print(f"  📖  {best['ref']}   [{confidence_label(best['score'])} confidence]")
    print(f"  {best['text']}")
    print("=" * 60)

    if len(results) > 1:
        print("\nOther possibilities:")
        for r in results[1:]:
            print(f"  • {r['ref']:<22} (score {r['score']:.2f})  {r['text'][:60]}...")


if __name__ == "__main__":
    main()
