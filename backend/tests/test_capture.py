import os
from PIL import Image
from app.capture import capture_portal_page

def test_capture_dimensions():
    img_path, meta_path = capture_portal_page(
        url="https://example.com",
        portal_name="test_portal",
        page_slug="home",
        save_to_samples=False
    )
    assert os.path.exists(img_path)
    assert os.path.exists(meta_path)
    with Image.open(img_path) as img:
        assert img.size == (1920, 1080)