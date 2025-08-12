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

NUM_VARIATIONS = 1 # 3 is max for now as there are 4 folders
NUM_DATA_ROWS = 2 # if 'all' then all rows in google sheet with slide texts are iterated
TEMPERATURE=0.2


# Load config
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)
# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_caption(strings, prompt_template, model="gpt-4", max_tokens=50):
    # Join slides into a single text block
    slides_text = "\n".join(f"Slide {i+1}: {text}" for i, text in enumerate(strings))
    print('inside caption generator')
    print(slides_text)
    
    # Build the prompt
    prompt = prompt_template.replace("{slides_text}", slides_text)

    # Call OpenAI API
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=TEMPERATURE
    )

    # Extract and return the caption text
    return response.choices[0].message.content.strip()

def generate_variations(non_hook_prompt_template, hook_prompt_template, strings, num_variations, model="gpt-4", max_tokens=50):
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
                model=model,
                messages=[{"role": "user", "content": final_prompt}],
                temperature=TEMPERATURE,
                max_tokens=max_tokens
            )

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

# === USAGE ===
# SPREADSHEET_ID = spreadsheet_id

# RANGE_NAME = 'Sheet1'  # Change to match your sheet name

# rows = get_sheet_rows(SPREADSHEET_ID, RANGE_NAME)
# for row in rows:
#     print(row)


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


def add_carousel_to_gsheet(slide_texts, id, caption):
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
    row.append(TEMPERATURE)
    # Append row to the sheet
    worksheet.append_row(row, value_input_option='RAW')

def main():

    test_texts = []

    sheet_id = '1O6lNd7gIEnI_K8GxNFYSUj9WVKtveU1mwWIVgL0g7J8'
    sheet_rows = get_sheet_rows(sheet_id, 'Sheet1')


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

            # CAROUSELS = generate_variations(SLIDE_TEXTS, 3)
            

            sheet_id = '1O6lNd7gIEnI_K8GxNFYSUj9WVKtveU1mwWIVgL0g7J8'
            non_hook_prompt_template = get_prompt_from_sheet(sheet_id, 'Prompts!C2')
            hook_prompt_template = get_prompt_from_sheet(sheet_id, 'Prompts!A2')
            caption_template = get_prompt_from_sheet(sheet_id, 'Prompts!E2')


            CAROUSELS = generate_variations(non_hook_prompt_template, hook_prompt_template, SLIDE_TEXTS, NUM_VARIATIONS, "gpt-4", 100)
            CAPTION = generate_caption(SLIDE_TEXTS, caption_template)
            # print('CAPTION')
            # print(CAPTION)

            # exit()
            # strings, prompt_template, model="gpt-4", max_tokens=50

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
                upload_images_to_drive(destination_folder_id, output_dir)
                add_carousel_to_gsheet(slide_texts, f"{next_id}", CAPTION)

                print(f"✅ Uploading Image: {j+1} to folder: {i+1}")

                # except Exception as e:
                #     print(f"❌ Error processing carousel: {e}")

  
if __name__ == "__main__":
    os.makedirs("temp", exist_ok=True)
    main()
    # get_next_id()
    # slide_texts = ['Three months of regular posting taught me some unexpected lessons...', "Show up, stay true to yourself, and connect with other creators. Don't just swipe by—those thoughtful comments you drop can be a real pick-me-up for someone else, and TikTok pays attention. The more you interact, the more visibility your own posts get.", "Earning money can absolutely happen, but don't plunge into it like a full-time job right away. Keep it light, keep it regular, and before you know it, that fun little sideline might just be paying for your skincare routine.", "No need to fret about your next post, there are supportive tools out there. They can identify what's trending within your niche and give you daily inspiration – it's like having your own personal content advisor always available.", "Don't underestimate your contribution, however little it seems. Continue cheering, continue sharing. Everything you do adds up."]
    # caption = "When life throws a curveball, remember, you have the power to turn things around. Don't let those bumps on the road define you; instead, let them inspire you to grow stronger. Seize the day, ladies!"
    # id = '#1'
    # add_carousel_to_gsheet(slide_texts, id, caption)
    # import shutil
    # shutil.rmtree(raw_dir, ignore_errors=True)

