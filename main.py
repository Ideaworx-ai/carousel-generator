import os
import io
import time
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.service_account import Credentials
from PIL import Image
from modules.image_handler import process_carousel
from modules.llm import generate_unique_variations
import yaml
import random
from dotenv import load_dotenv
import openai
from openai import OpenAI
import os
from itertools import chain
import gspread
from decimal import Decimal
from typing import Optional

NUM_VARIATIONS = 1 # 3 is max for now as there are 4 folders
NUM_DATA_ROWS = 'all' # if 'all' then all rows in google sheet with slide texts are iterated
MODEL="gpt-4"

class CostTracker:

    def __init__(self):
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cached_prompt_tokens = 0  # if prompt caching is used
        self.total_calls = 0
        self.total_usd = Decimal("0")

    def add(self, response, model_name: str):
        self.total_calls += 1
        usage = getattr(response, "usage", None)
        if not usage:
            return  # nothing to add

        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        # Some responses include caching details
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details and hasattr(details, "cached_tokens"):
            cached = int(details.cached_tokens or 0)

        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cached_prompt_tokens += cached

        rates = PRICES_PER_1K.get(model_name, None)
        if not rates:
            return  # unknown model rate, skip cost math to avoid wrong totals

        # Split cached vs non cached prompt tokens when a cached rate exists
        cached_rate: Optional[Decimal] = rates.get("cached_input")
        if cached_rate is not None and cached > 0:
            uncached_prompt = max(prompt_tokens - cached, 0)
            cost_input = (Decimal(uncached_prompt) * rates["input"] +
                          Decimal(cached) * cached_rate) / Decimal(1000)
        else:
            cost_input = (Decimal(prompt_tokens) * rates["input"]) / Decimal(1000)

        cost_output = (Decimal(completion_tokens) * rates["output"]) / Decimal(1000)
        self.total_usd += (cost_input + cost_output)

    def summary(self) -> str:
        return (
            f"API calls: {self.total_calls}\n"
            f"Prompt tokens: {self.total_prompt_tokens} "
            f"(cached: {self.total_cached_prompt_tokens})\n"
            f"Completion tokens: {self.total_completion_tokens}\n"
            f"Total cost: ${self.total_usd.quantize(Decimal('0.0001'))} USD"
        )

COST = CostTracker()

PRICES_PER_1K = {
    "gpt-3.5-turbo": {
        "input":  Decimal("0.0015"),   # $1.50 per 1M tokens
        "output": Decimal("0.0020"),   # $2.00 per 1M tokens
        "cached_input": None
    },
    "gpt-3.5-turbo-16k": {
        "input":  Decimal("0.0030"),   # $3.00 per 1M
        "output": Decimal("0.0040"),   # $4.00 per 1M
        "cached_input": None
    },
    "gpt-3.5-turbo-0613": {
        "input":  Decimal("0.0015"),
        "output": Decimal("0.0020"),
        "cached_input": None
    },
    # For classic davinci, curie, etc. if needed
    "text-davinci-003": {
        "input":  Decimal("0.02"),     # $20 per 1M
        "output": Decimal("0.02"),
        "cached_input": None
    },
    "text-curie-001": {
        "input":  Decimal("0.002"),    # $2 per 1M
        "output": Decimal("0.002"),
        "cached_input": None
    },
    "text-babbage-001": {
        "input":  Decimal("0.0005"),
        "output": Decimal("0.0005"),
        "cached_input": None
    },
    "text-ada-001": {
        "input":  Decimal("0.0004"),
        "output": Decimal("0.0004"),
        "cached_input": None
    },
    # Your existing GPT-4 and GPT-4o entries below
    "gpt-4": {
        "input":  Decimal("0.03"),
        "output": Decimal("0.06"),
        "cached_input": None
    },
    "gpt-4o": {
        "input":  Decimal("0.005"),
        "output": Decimal("0.02"),
        "cached_input": Decimal("0.0025")
    },
    "gpt-4o-mini": {
        "input":  Decimal("0.0006"),
        "output": Decimal("0.0024"),
        "cached_input": Decimal("0.0003")
    },
}




# Load config
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)
# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_caption(temperature, strings, prompt_template, max_tokens=50):
    # Join slides into a single text block

    slides_text = "\n".join(f"Slide {i+1}: {text}" for i, text in enumerate(strings))
    print(f"{slides_text}")

    print('inside caption generator ################### %$')

    # Build the prompt
    prompt = prompt_template.replace("{slides_text}", slides_text)

    # print(prompt)
    # exit()

    # Call OpenAI API
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    # Extract and return the caption text
    COST.add(response, MODEL)  # <-- track cost
    return response.choices[0].message.content.strip()

def generate_variations(temperature, non_hook_prompt_template, hook_prompt_template, strings, num_variations, max_tokens=50):
    variation_buckets = [[] for _ in range(num_variations)]

    for idx, original in enumerate(strings):
        generated = set()

        while len(generated) < num_variations:
            # Choose the right template
            if idx == 0:
                final_prompt = hook_prompt_template.replace("{original}", original)
            else:
                final_prompt = non_hook_prompt_template.replace("{original}", original)

            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": final_prompt}],
                temperature=temperature,
                max_tokens=max_tokens
            )
            COST.add(response, MODEL)  # <-- track cost

            variation = response.choices[0].message.content.strip().replace('"', '')
            generated.add(variation)

        # Assign variations to their respective buckets
        for i, v in enumerate(list(generated)[:num_variations]):
            variation_buckets[i].append(v)
        
        print([strings])
        print(variation_buckets)

    return [strings] + variation_buckets


# === CONFIGURE YOUR FOLDER IDS AND TEXTS HERE ===
FOLDER_IDS = [
    '162y-dHOkPhN5GpMsGjvM4GXR1sYwll1J',
    '1gQPqzd1aqzVmE7nn_c5kFssdLFQBkmkI',
    '1LB8qBizqdzxAVgTanEYItF8k7Xr7-4K7',
    '1q9Cri0P1SOzfJPhPmBgGTCso5biluW74',
    '1BFxuiDJdi2I7c3KlDrDAE2jPXiZtC64f'
]


GDRIVE_TIKTOK_ACCOUNT_FOLDER_IDS = {
    "CommentScout TikTok Account #1": "1JZrBRDFNZGvIjiFT94gPzCowB5HtqGdR",
    "CommentScout TikTok Account #2": "1pBCM4wFO_gf635FEb8JLDwlHtdhr8o6Z",
    "CommentScout TikTok Account #3": "1r4PViNbyoxvgNwCsVFZacxEUlPfW1NAd",
    "CommentScout TikTok Account #4": "1ZIrLBAhn5bKcTw0J6tRWzBCSn9Zrgzw7"
}

def get_prompt_from_sheet(spreadsheet_id, range_name):
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)

    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()

    values = result.get('values', [])
    if values and values[0]:
        return values[0][0]  # First cell
    else:
        raise ValueError("❌ Prompt cell is empty or missing.")

def get_sheet_rows(spreadsheet_id, range_name):
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)

    sheet = service.spreadsheets()
    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()

    values = result.get('values', [])

    # Return all rows except the header
    return values[1:] if values else []

FONT_COLORS = ["#ffffff"]

# LAYOUT = "upper_middle"
LAYOUT = "auto"
FONTS_FOLDER_ID = "1mwenttTQ04TKdd0EMIfotO7CyucQDkuF"

# === Google Drive Setup ===
def get_drive_service():
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# === Fetch First Image from Folder ===
def get_images_from_folder(folder_id, max_images=100):
    drive_service = get_drive_service()
    query = f"'{folder_id}' in parents and (mimeType contains 'image/')"
    response = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name, mimeType)',
        pageSize=max_images,
        supportsAllDrives=True
    ).execute()
    return response.get('files', [])

# === Download File from Drive ===
def download_image_from_drive(file_id, output_dir, index, is_font=False):
    drive_service = get_drive_service()
    try:
        file_metadata = drive_service.files().get(fileId=file_id, fields='mimeType, name', supportsAllDrives=True).execute()
        mime_type = file_metadata.get('mimeType')
        file_name = file_metadata.get('name')

        mime_to_ext = {
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/bmp': '.bmp',
            'image/tiff': '.tiff',
            'application/x-font-ttf': '.ttf',
            'application/font-sfnt': '.ttf',
            'application/vnd.google-apps.font': '.ttf',
            'font/ttf': '.ttf',
        }

        if mime_type not in mime_to_ext:
            print(f"File {file_id} is not a valid image/font (MIME: {mime_type})")
            return None

        ext = mime_to_ext[mime_type] if not is_font else '.ttf'
        # output_path = os.path.join(output_dir, "font.ttf" if is_font else f"slide_{index+1}{ext}")
        output_path = os.path.join(output_dir, "font.ttf" if is_font else f"raw_slide_{index+1}{ext}")


        request = drive_service.files().get_media(fileId=file_id)
        with io.FileIO(output_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        time.sleep(0.2)

        if is_font:
            from PIL import ImageFont
            ImageFont.truetype(output_path, 10)
        else:
            with Image.open(output_path) as img:
                img.verify()
        return output_path

    except Exception as e:
        print(f"❌ Error downloading file {file_id}: {e}")
        return None

# === Download First TTF from Fonts Folder ===
def download_first_font_from_folder(folder_id, output_dir):
    drive_service = get_drive_service()
    query = f"'{folder_id}' in parents and mimeType != 'application/vnd.google-apps.folder'"
    response = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name, mimeType)',
        supportsAllDrives=True
    ).execute()
    for file in response.get('files', []):
        if file['name'].lower().endswith('.ttf'):
            return download_image_from_drive(file['id'], output_dir, 0, is_font=True)
    print("⚠️ No TTF font found in folder")
    return None

def create_drive_folder(folder_name, parent_folder_id):
    drive_service = get_drive_service()
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_folder_id]
    }

    try:
        folder = drive_service.files().create(
            body=folder_metadata,
            fields='id, name',
            supportsAllDrives=True
        ).execute()
        print(f"📁 Created Drive folder: {folder['name']} (ID: {folder['id']})")
        return folder['id']
    except Exception as e:
        print(f"❌ Failed to create folder: {e}")
        return None

def upload_images_to_drive(folder_id, local_dir):
    drive_service = get_drive_service()
    uploaded_files = []

    for filename in sorted(os.listdir(local_dir)):
        if filename.lower().endswith((".jpg", ".jpeg", ".png")):
            file_path = os.path.join(local_dir, filename)
            file_metadata = {
                "name": filename,
                "parents": [folder_id]
            }
            media = MediaIoBaseUpload(io.FileIO(file_path, 'rb'), mimetype="image/jpeg")
            try:
                uploaded_file = drive_service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields="id, name",
                    supportsAllDrives=True  # ✅ Required for Shared Drives
                ).execute()
                uploaded_files.append(uploaded_file["id"])
                print(f"📤 Uploaded {filename} to Drive folder {folder_id}")
            except Exception as e:
                print(f"❌ Failed to upload {filename}: {e}")

    return uploaded_files

def get_next_id():
    gc = gspread.service_account(filename='credentials.json')
    sh = gc.open_by_key('1O6lNd7gIEnI_K8GxNFYSUj9WVKtveU1mwWIVgL0g7J8')
    worksheet = sh.worksheet('Carousel Outputs')

    # Get all values in column A
    col_a_values = worksheet.col_values(1)  # Column A

    # Filter out empty cells
    col_a_values = [v for v in col_a_values if v.strip() != ""]

    if not col_a_values:
        return "#1"  # If no IDs exist yet

    last_id = col_a_values[-1]  # Last non-empty cell value in col A
    numeric_part = int(last_id.strip().lstrip("#"))
    next_id = numeric_part + 1

    print(next_id)

    return f"#{next_id}"


def add_carousel_to_gsheet(slide_texts, id, caption, temperature, cost):
    # Authenticate using your service account file
    gc = gspread.service_account(filename='credentials.json')

    # Open the sheet by ID
    sh = gc.open_by_key('1O6lNd7gIEnI_K8GxNFYSUj9WVKtveU1mwWIVgL0g7J8')

    # Open the "Carousel Outputs" tab
    worksheet = sh.worksheet('Carousel Outputs')

    # Build the row: id in col A, slides in cols B-G, caption in col H
    row = [id] + slide_texts

    # Ensure caption is in column H (index 7 in 0-based Python list)
    while len(row) < 7:  # Fill blanks until before column H
        row.append("")
    row.append(caption)
    row.append(temperature)
    row.append(cost)

    # Append row to the sheet
    worksheet.append_row(row, value_input_option='RAW')

def main():

    test_texts = []
    sheet_id = '1O6lNd7gIEnI_K8GxNFYSUj9WVKtveU1mwWIVgL0g7J8'
    sheet_rows = get_sheet_rows(sheet_id, 'Sheet1')
    temperature = float(get_prompt_from_sheet(sheet_id, 'Prompts!G2'))

    # Skip header row
    data_rows = sheet_rows[1:]

    if NUM_DATA_ROWS == 'all':
        limit = len(sheet_rows)
    else:
        limit = int(NUM_DATA_ROWS)  # ensure it's an integer

    # for index, row in enumerate(sheet_rows):
    for index, row in enumerate(sheet_rows[:limit]):
        if row:  # skip empty rows

             # Continue with rest of the script...
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_dir = f"temp/carousel_{timestamp}"
            os.makedirs(temp_dir, exist_ok=True)
            raw_dir = os.path.join("temp", "raw")
            os.makedirs(raw_dir, exist_ok=True)
            font_path = download_first_font_from_folder(FONTS_FOLDER_ID, temp_dir)

            SLIDE_TEXTS = []
            for array in row:
                slide_text = array.strip()  # get the first column
                SLIDE_TEXTS.append(slide_text)
            print(f"{SLIDE_TEXTS}")


            sheet_id = '1O6lNd7gIEnI_K8GxNFYSUj9WVKtveU1mwWIVgL0g7J8'
            non_hook_prompt_template = get_prompt_from_sheet(sheet_id, 'Prompts!C2')
            hook_prompt_template = get_prompt_from_sheet(sheet_id, 'Prompts!A2')
            caption_template = get_prompt_from_sheet(sheet_id, 'Prompts!E2')


            CAROUSELS = generate_variations(temperature, non_hook_prompt_template, hook_prompt_template, SLIDE_TEXTS, NUM_VARIATIONS, 100)
            CAPTION = generate_caption(temperature, SLIDE_TEXTS, caption_template,150)
      

            test_texts.append(CAROUSELS)
            if len(CAROUSELS) != NUM_VARIATIONS + 1:
                print(f"variations not complete")
                exit()

            for i in range(1, len(CAROUSELS)):
                local_image_paths = []

                print(f"Variation: {i + 1}")
          
                slide_texts = CAROUSELS[i]

                next_id = get_next_id()

                timestamp = datetime.now().strftime("%Y-%m-%d %H.%M.%S")
                subfolder_name = f"ID:{next_id}-carousel-{timestamp}"
                # Convert dict values to a list
                folder_ids = list(GDRIVE_TIKTOK_ACCOUNT_FOLDER_IDS.values())

                # Access value by index, e.g., index 2
                parent_folder_id = folder_ids[i]


                for j, folder_id in enumerate(FOLDER_IDS):
                    print(f"Folder: {j + 1}")


                    if folder_id and folder_id.strip():
                        images = get_images_from_folder(folder_id.strip(), max_images=100)
                        if images:
                            img_file = random.choice(images)
                            img_path = download_image_from_drive(img_file['id'], raw_dir, j)
                            local_image_paths.append(img_path)
                        else:
                            print(f"❌ No image found in folder {folder_id}")
                            local_image_paths.append(None)
                    else:
                        print(f"⚠️ Empty folder ID for slide {j+1}")
                        local_image_paths.append(None)

                # try:
                destination_folder_id = create_drive_folder(subfolder_name, parent_folder_id)
                output_dir = process_carousel(
                    LAYOUT,
                    local_image_paths,
                    font_path,
                    config,
                    FONT_COLORS,
                    slide_texts
                )
                cost = 0
                upload_images_to_drive(destination_folder_id, output_dir)
                add_carousel_to_gsheet(slide_texts, f"{next_id}", CAPTION, temperature, cost)

                print(f"✅ Uploading Image: {j+1} to folder: {i+1}")

                # except Exception as e:
                #     print(f"❌ Error processing carousel: {e}")

  
if __name__ == "__main__":
    os.makedirs("temp", exist_ok=True)
    try:
        main()
    finally:
        print("\n=== OpenAI cost summary ===")
        print(COST.summary())

