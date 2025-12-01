#!/usr/bin/env python3
"""
Debug script to inspect the IT Admin folder structure in Google Drive.

This script lists all children (including shortcuts) in the IT Admin folder
to help debug folder listing issues.
"""

from drive_service import DriveManager

# IT Admin folder ID from folder_map.py
IT_ADMIN_ID = "1jjrPUX9_4hOQfRi_65A9EEQtynNXZcT8"


def main():
    """
    Debug the IT Admin folder by listing all children with detailed metadata.
    """
    print("=" * 70)
    print("IT Admin Folder Debug Tool")
    print("=" * 70)
    print(f"Folder ID: {IT_ADMIN_ID}")
    print()

    # Initialize DriveManager
    drive = DriveManager(correlation_id="debug-it-admin")
    
    # Build the query
    query = f"'{IT_ADMIN_ID}' in parents and trashed=false"
    
    print(f"Query: {query}")
    print()
    
    # Call the underlying Google Drive API directly
    try:
        results = drive.service.files().list(
            q=query,
            fields="files(id,name,mimeType,shortcutDetails,parents)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            corpora="allDrives"
        ).execute()
        
        files = results.get("files", [])
        
        print(f"Raw children count: {len(files)}")
        print()
        
        if len(files) == 0:
            print("⚠️  No children found in IT Admin folder!")
            print()
            print("Possible causes:")
            print("  1. Folder is actually empty")
            print("  2. Service account lacks permissions")
            print("  3. Folder ID is incorrect")
            print("  4. Items are in trash")
        else:
            print("-" * 70)
            print(f"{'ID':<40} {'Name':<20} {'Type':<15}")
            print("-" * 70)
            
            for item in files:
                item_id = item.get("id", "N/A")
                item_name = item.get("name", "N/A")
                mime_type = item.get("mimeType", "N/A")
                shortcut_details = item.get("shortcutDetails", None)
                parents = item.get("parents", [])
                
                # Determine if it's a shortcut
                is_shortcut = mime_type == "application/vnd.google-apps.shortcut"
                
                # Truncate long names for display
                display_name = item_name[:18] + "..." if len(item_name) > 20 else item_name
                
                # Determine type display
                if is_shortcut:
                    type_display = "SHORTCUT"
                elif mime_type == "application/vnd.google-apps.folder":
                    type_display = "FOLDER"
                else:
                    type_display = "FILE"
                
                print(f"{item_id:<40} {display_name:<20} {type_display:<15}")
                
                # Print detailed info
                print(f"  Full name: {item_name}")
                print(f"  MIME type: {mime_type}")
                print(f"  Is shortcut: {is_shortcut}")
                
                if shortcut_details:
                    target_id = shortcut_details.get("targetId", "N/A")
                    target_mime = shortcut_details.get("targetMimeType", "N/A")
                    print(f"  Shortcut target ID: {target_id}")
                    print(f"  Shortcut target MIME: {target_mime}")
                
                if parents:
                    print(f"  Parents: {', '.join(parents)}")
                
                print()
            
            print("-" * 70)
            print()
            
            # Summary statistics
            folders = sum(1 for f in files if f.get("mimeType") == "application/vnd.google-apps.folder")
            shortcuts = sum(1 for f in files if f.get("mimeType") == "application/vnd.google-apps.shortcut")
            regular_files = len(files) - folders - shortcuts
            
            print("Summary:")
            print(f"  Total items: {len(files)}")
            print(f"  Folders: {folders}")
            print(f"  Shortcuts: {shortcuts}")
            print(f"  Regular files: {regular_files}")
    
    except Exception as e:
        print(f"❌ Error querying IT Admin folder: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print()
    print("=" * 70)
    print("Debug complete!")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
