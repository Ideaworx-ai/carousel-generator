import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_unique_variations(slide_text, num_outputs, existing_variations=None, model="gpt-4"):
    if existing_variations is None:
        existing_variations = []

    variations = []
    attempts = 0
    max_attempts = num_outputs * 3  # safety loop

    while len(variations) < num_outputs and attempts < max_attempts:
        attempts += 1

        prompt = f"""Rewrite the following text in a tone that resonates with Gen Z women on TikTok.
It should be casual, punchy, and authentic — the kind of hook that would appear as text on a TikTok carousel.
The output must be between 60 and 80 characters (not less, not more).
Keep the essence, but remix the phrasing.
Avoid these variations:\n{existing_variations}

Original:
"{slide_text}"
"""

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.75,
            max_tokens=200,
        )

        output = response.choices[0].message.content.strip()

        if output not in existing_variations and output not in variations:
            variations.append(output)

    return variations


# def chat_with_gpt_variations(slide_text: str, n: int, model="gpt-4", temperature=0.7, max_tokens=200):
#     prompt_template = f"""Rewrite the following text in a tone that resonates with Gen Z women on TikTok.
# It should be casual, punchy, and authentic — the kind of hook that would appear as text on a TikTok carousel.
# The output must be between 80 and 190 characters (not less, not more).
# Keep the essence, but remix the phrasing.

# Original:
# "{slide_text}"
# """

#     responses = set()
#     attempts = 0
#     while len(responses) < n and attempts < n * 3:  # retry logic to ensure uniqueness
#         response = client.chat.completions.create(
#             model=model,
#             messages=[{"role": "user", "content": prompt_template}],
#             temperature=temperature,
#             max_tokens=max_tokens
#         )
#         output = response.choices[0].message.content.strip()
#         responses.add(output)
#         attempts += 1

#     return list(responses)

