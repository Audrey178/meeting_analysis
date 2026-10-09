from openai import OpenAI

client = OpenAI(
    base_url="https://rendered-moments-vinyl-obtaining.trycloudflare.com/v1",
    api_key="EMPTY",
)

result = client.chat.completions.create(
    model="google/medgemma-1.5-4b-it",
    messages=[
        {"role": "user", "content": "Explain the symptoms of pneumonia."}
    ],
    max_tokens=512,
)

print(result.choices[0].message.content)