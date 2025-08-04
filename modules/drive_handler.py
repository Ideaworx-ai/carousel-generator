import os
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive']

def upload_folder_to_drive(folder_path, parent_id):
    creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    service = build('drive', 'v3', credentials=creds)

    # Map file extensions to MIME types
    ext_to_mime = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.tiff': 'image/tiff'
    }

    try:
        # Create a folder in the Shared Drive
        folder_metadata = {
            'name': os.path.basename(folder_path),
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = service.files().create(
            body=folder_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()
        folder_id = folder.get('id')
        print(f"✅ Created folder {folder_id} in Shared Drive")

        # Upload each file in the folder
        for file_name in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file_name)
            if os.path.isfile(file_path):
                # Get MIME type based on file extension
                file_ext = os.path.splitext(file_name)[1].lower()
                mime_type = ext_to_mime.get(file_ext, 'application/octet-stream')
                
                file_metadata = {
                    'name': file_name,
                    'parents': [folder_id]
                }
                media = MediaFileUpload(file_path, mimetype=mime_type)
                service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id',
                    supportsAllDrives=True
                ).execute()
                print(f"✅ Uploaded {file_name} to folder {folder_id}")

        print(f"✅ Uploaded {folder_path} to Google Drive")
        return folder_id

    except Exception as e:
        print(f"❌ Error uploading folder {folder_path}: {str(e)}")
        raise