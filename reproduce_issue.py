
import logging
import sys
from unittest.mock import MagicMock
from drive_service import DriveManager

# Setup logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

def test_logging_key_error():
    dm = DriveManager()
    dm.service = MagicMock()
    
    # Mock _find_file_by_name to return None so it hits the "creating_drive_file" path
    dm._find_file_by_name = MagicMock(return_value=None)
    
    # Mock service.files().create().execute()
    dm.service.files().create().execute.return_value = {"id": "new_file_id", "name": "test.json"}

    print("Attempting to write json file...")
    try:
        dm.write_json_file("parent_id", "test.json", {"foo": "bar"})
        print("Success!")
    except KeyError as e:
        print(f"Caught expected KeyError: {e}")
    except Exception as e:
        print(f"Caught unexpected exception: {e}")

if __name__ == "__main__":
    test_logging_key_error()
