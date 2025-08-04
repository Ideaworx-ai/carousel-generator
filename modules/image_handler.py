from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import textwrap
import os
from datetime import datetime
import yaml
import requests
from googleapiclient.discovery import build
from google.oauth2 import service_account
import ultralytics
from ultralytics import YOLO

def get_tiktok_safe_area(image_width, image_height):
    # These values are approximate and can be tweaked per device
    margin_top = 200
    margin_bottom = 420
    margin_right = 200
    margin_left = 80

    return (
        margin_left,
        margin_top,
        image_width - margin_right,
        image_height - margin_bottom,
    )

def draw_safe_area_outline(image, safe_box):
    # safe_box = get_tiktok_safe_area(*image.size)
    print('Draw Safe Box')
    draw = ImageDraw.Draw(image)
    draw.rectangle(safe_box, outline="red", width=4)
    return image

def detect_phones(image_path):
    model = YOLO("yolov8n.pt")  # Make sure this model file is downloaded
    results = model(image_path)
    boxes = []
    for r in results:
        for box in r.boxes:
            cls_id = int(box.cls[0])
            label = r.names[cls_id]
            if label.lower() == "cell phone":
                # print(f"📱 Detected phone at: ({x1}, {y1}, {x2}, {y2}) with label: {label}: {image_path}")
                # exit()
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                boxes.append((x1, y1, x2, y2))
    return boxes

def box_overlap(box1, box2):
    x1, y1, x2, y2 = box1
    a1, b1, a2, b2 = box2
    return not (x2 < a1 or x1 > a2 or y2 < b1 or y1 > b2)

def draw_iphone_boxes(image, box, color=(128, 0, 128), width=4):
    """Draw rectangles around given boxes on the image."""
    print('Draw Iphone Box')
    draw = ImageDraw.Draw(image)

    # for box in boxes:
    draw.rectangle(box, outline=color, width=width)
    print('Return Draw Iphone')
    return image

def hex_to_rgb(hex_color):
    """Convert hex color (e.g., '#2ECC71') to RGB tuple with alpha 255."""
    if not hex_color or not isinstance(hex_color, str):
        return (46, 204, 113, 255)  # Default to alien green if invalid
    hex_color = hex_color.lstrip('#')
    try:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4)) + (255,)
    except ValueError:
        print(f"❌ Invalid hex color {hex_color}, defaulting to (46, 204, 113, 255)")
        return (46, 204, 113, 255)

def draw_soft_glow_text(base_img, position, text, font, fill="white", glow_color="#FF4EDB", glow_radius=10, blur_radius=8):
    x, y = position

    # Create a transparent layer to hold the glow
    glow_layer = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)

    # Draw thicker glow text onto glow layer
    for dx in range(-glow_radius, glow_radius + 1):
        for dy in range(-glow_radius, glow_radius + 1):
            glow_draw.text((x + dx, y + dy), text, font=font, fill=glow_color)

    # Apply Gaussian blur to glow layer
    blurred_glow = glow_layer.filter(ImageFilter.GaussianBlur(blur_radius))

    # Composite glow onto original
    base_img = Image.alpha_composite(base_img, blurred_glow)

    # Draw crisp white text on top
    draw = ImageDraw.Draw(base_img)
    draw.text((x, y), text, font=font, fill=fill)

    return base_img

def download_font_from_drive(service, folder_id, temp_dir="temp"):
    """Download the first TTF file found in the given Drive folder."""
    results = service.files().list(
        q=f"'{folder_id}' in parents and mimeType='application/x-font-ttf'",
        fields="files(id, name)",
        pageSize=1
    ).execute()
    items = results.get('files', [])
    if not items:
        print("❌ No font file found in Fonts folder.")
        return None

    file_id = items[0]['id']
    file_name = items[0]['name']
    font_path = os.path.join(temp_dir, file_name)

    os.makedirs(temp_dir, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    response = requests.get(
        f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
        headers={"Authorization": f"Bearer {service._http.credentials.token}"}
    )
    with open(font_path, 'wb') as f:
        f.write(response.content)
    print(f"✅ Font downloaded to {font_path}")
    return font_path

def get_font_size(char_count, base_chars=80, base_size=80, min_size=60):
    ratio = base_chars / char_count if char_count > base_chars else 1
    return max(int(base_size * ratio), min_size)
    
def process_carousel(layout, image_paths, font_path, config, font_colors, slide_texts):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"temp/carousel_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)

    # Load font
    font_size = config.get("font_size", 120)  # Increased size for visibility
    font = None
    if font_path and os.path.exists(font_path):
        try:
            font = ImageFont.truetype(font_path, font_size)
            print(f"✅ Font loaded successfully from {font_path}")
        except Exception as e:
            print(f"❌ Font loading error from {font_path}: {str(e)}")
    if not font:
        print("⚠️ No valid font available, saving images without text")

    for i, image_path in enumerate(image_paths):
        if image_path and os.path.exists(image_path):
            base_img = Image.open(image_path)
            width = config.get("output_width", 1080)
            height = config.get("output_height", 1920)
            base_img = ImageOps.fit(base_img, (width, height), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            base_img = base_img.convert("RGBA")

            img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            img.paste(base_img, (0, 0))

            if i < len(slide_texts) and slide_texts[i]:
                text = slide_texts[i]
                font_size = get_font_size(len(text))
                try:
                    font = ImageFont.truetype(font_path, font_size)
                except Exception as e:
                    print(f"❌ Failed to load font at size {font_size}: {e}")
                    continue

                print(f"📝 Drawing text on slide {i+1} (font size: {font_size}): {text}")
                margin = 50
                safe_box = get_tiktok_safe_area(width, height)
                # img = draw_safe_area_outline(img, safe_box)

                safe_left = safe_box[0]
                safe_top = safe_box[1]
                safe_right = safe_box[2]
                safe_bottom = safe_box[3]
                max_width = safe_right - safe_left
                max_height = safe_bottom - safe_top

                draw = ImageDraw.Draw(img)
                line_spacing = 10

                # Dynamically wrap text by pixel width, adjusting font size down if needed
                min_font_size = 60
                while True:
                    font = ImageFont.truetype(font_path, font_size)
                    lines = []
                    current_line = ""
                    for word in text.split():
                        test_line = current_line + (" " if current_line else "") + word
                        bbox = draw.textbbox((0, 0), test_line, font=font)
                        if bbox[2] - bbox[0] <= max_width:
                            current_line = test_line
                        else:
                            lines.append(current_line)
                            current_line = word
                    if current_line:
                        lines.append(current_line)

                    line_height = font.getbbox("Ay")[3] - font.getbbox("Ay")[1]
                    total_height = len(lines) * (line_height + line_spacing)

                    # 🔒 Enforce minimum font size of 60
                    if total_height <= max_height:
                        break
                    if font_size <= min_font_size:
                        print(f"⚠️ Slide {i+1}: text too tall to fit even at 60px. Rendering anyway at minimum font size.")
                        font_size = min_font_size
                        font = ImageFont.truetype(font_path, font_size)
                        break

                    font_size -= 2

                y_text = max(safe_top, (safe_top + safe_bottom - total_height) // 2)

                fill_color = hex_to_rgb(font_colors[i] if i < len(font_colors) else "#FFFFFF")
                for line in lines:
                    draw = ImageDraw.Draw(img)
                    bbox = draw.textbbox((0, 0), line, font=font)
                    text_width = bbox[2] - bbox[0]
                    # x_text = max(margin, (width - text_width) // 2)
                    max_width = safe_right - safe_left
                    x_text = safe_left + (max_width - text_width) // 2
                    img = draw_soft_glow_text(
                        img,
                        (x_text, y_text),
                        line,
                        font=font,
                        fill=fill_color,
                        glow_color="#FF4EDB"
                    )
                    line_spacing = 20 
                    y_text += line_height + line_spacing

                    # 📌 Add font size reference
                    # debug_font = ImageFont.truetype(font_path, 30)
                    # debug_text = f"Font size: {font_size}px"
                    # img_draw = ImageDraw.Draw(img)
                    # img_draw.text((safe_left, safe_top - 40), debug_text, font=debug_font, fill=(255, 255, 255, 255))


            output_path = os.path.join(output_dir, f"slide{i+1}.jpg")
            img = img.convert("RGB")
            print(f"🔍 About to save: {output_path}")
            img.save(output_path, "JPEG", quality=95)
            print(f"✅ Processed slide {i+1}: {output_path} (size={os.path.getsize(output_path)} bytes)")

    print(f"✅ Carousel ready at {output_dir}")
    return output_dir

if __name__ == "__main__":
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Google Drive Font Setup
    creds = service_account.Credentials.from_service_account_file(
        "credentials.json",
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    drive_service = build("drive", "v3", credentials=creds)

    font_folder_id = "1mwenttTQ04TKdd0EMIfotO7CyucQDkuF"
    font_path = download_font_from_drive(drive_service, font_folder_id)
