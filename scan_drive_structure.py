import os
import sys
import argparse
from google.oauth2 import service_account
from googleapiclient.discovery import build

def get_credentials():
    """Gets credentials from the environment variable."""
    creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if not creds_path:
        print("Error: GOOGLE_APPLICATION_CREDENTIALS environment variable not set.")
        sys.exit(1)
    
    try:
        return service_account.Credentials.from_service_account_file(
            creds_path, scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
    except Exception as e:
        print(f"Error loading credentials: {e}")
        sys.exit(1)

def list_folders(service, drive_id, parent_id):
    """Lists folders within a specific parent folder."""
    folders = []
    page_token = None
    
    while True:
        try:
            response = service.files().list(
                corpora="drive",
                driveId=drive_id,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageToken=page_token
            ).execute()
            
            folders.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            if not page_token:
                break
        except Exception as e:
            print(f"Error listing folders for parent {parent_id}: {e}")
            break
            
    return folders

def walk_drive_structure(service, drive_id, parent_id, current_path, level, output_file):
    """Recursively walks the drive structure."""
    folders = list_folders(service, drive_id, parent_id)
    
    # Sort folders by name for consistent output
    folders.sort(key=lambda x: x['name'])
    
    for folder in folders:
        folder_name = folder['name']
        folder_id = folder['id']
        
        # Construct path
        new_path = f"{current_path}/{folder_name}" if current_path else folder_name
        
        # Format output line
        indent = "  " * level
        line = f"{indent}{new_path} — {folder_id}"
        
        # Print to console
        print(line)
        
        # Write to file
        output_file.write(line + "\n")
        output_file.flush() # Ensure it's written immediately
        
        # Recurse
        walk_drive_structure(service, drive_id, folder_id, new_path, level + 1, output_file)

def main():
    parser = argparse.ArgumentParser(description="Scan Google Drive shared drive structure.")
    parser.add_argument("--drive-id", help="The ID of the shared drive to scan.")
    args = parser.parse_args()
    
    # Resolve drive_id
    drive_id = args.drive_id or os.environ.get("SHARED_DRIVE_ID")
    
    if not drive_id:
        print("Please provide SHARED_DRIVE_ID via --drive-id or env var.")
        sys.exit(1)
        
    print(f"📁 Scanning shared drive: {drive_id}")
    
    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)
    
    output_filename = "drive_structure.txt"
    
    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            # Start the recursive walk from the drive root (drive_id acts as the root folder id)
            walk_drive_structure(service, drive_id, drive_id, "", 0, f)
            
        print(f"\nScan complete. Output saved to {output_filename}")
        
    except KeyboardInterrupt:
        print("\nScan interrupted by user.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
