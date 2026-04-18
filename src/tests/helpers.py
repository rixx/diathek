import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image as PILImage


def make_jpeg_bytes(*, width=200, height=150, color=(200, 120, 30)):
    image = PILImage.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def make_uploaded_jpeg(name, *, width=200, height=150, color=(200, 120, 30)):
    return SimpleUploadedFile(
        name, make_jpeg_bytes(width=width, height=height, color=color), "image/jpeg"
    )
