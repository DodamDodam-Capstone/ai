import asyncio

from dotenv import load_dotenv

from stt.clova import ClovaSTT


async def main():
    load_dotenv()

    with open("test.wav", "rb") as f:
        audio = f.read()

    stt = ClovaSTT()
    result = await stt.transcribe(audio)

    print("인식 결과:", result.text)
    print("신뢰도:", result.confidence)


if __name__ == "__main__":
    asyncio.run(main())