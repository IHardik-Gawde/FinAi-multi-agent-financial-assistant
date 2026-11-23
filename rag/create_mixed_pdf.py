import pymupdf
import PIL.Image
from PIL import Image, ImageDraw, ImageFont

# Create PDF
doc = pymupdf.open()

# Page 1: Normal digital text
page1 = doc.new_page()

page1.insert_text((60, 80), "NORTHSTAR BUSINESS SERVICES", fontsize=20)

page1.insert_text((60, 130), "Digital Financial Statement", fontsize=14)

page1.insert_text((60, 180), "Total Revenue: INR 900000", fontsize=12)

page1.insert_text((60, 210), "Operating Expenses: INR 550000", fontsize=12)

page1.insert_text((60, 240), "Net Operating Profit: INR 350000", fontsize=12)

# Page 2: Scanned image
page2 = doc.new_page()

text = """
NORTHSTAR BUSINESS SERVICES

SCANNED REVENUE BREAKDOWN

Software Services: INR 400000
Consulting Services: INR 300000
Support Contracts: INR 200000
"""

# Render text into an image
pix = page2.get_pixmap(matrix=pymupdf.Matrix(2, 2))
import PIL.Image
from PIL import ImageDraw, ImageFont
from io import BytesIO

image = Image.open(BytesIO(pix.tobytes("png")))
draw = ImageDraw.Draw(image)

font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 35)

draw.multiline_text((100, 100), text, fill="black", font=font, spacing=20)

image_bytes = BytesIO()
image.save(image_bytes, format="PNG")

page2.insert_image(page2.rect, stream=image_bytes.getvalue())

doc.save("data/documents/mixed_ocr_test.pdf")
doc.close()

print("Mixed PDF created successfully!")
