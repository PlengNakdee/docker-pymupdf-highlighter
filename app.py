import fitz
import os

from fastapi import FastAPI, UploadFile, File, Request, Form
import uvicorn
import json

app = FastAPI()

os.makedirs("/app/output", exist_ok=True)

filename1 = ""
filename2 = ""

def replace_unknown_with_filename(data, file_1_name, file_2_name):
    mismatches = data['mismatches']

    # Check first category to see if Unknown exists
    first_category = next(iter(mismatches.values()))
    if 'Unknown' not in first_category:
        return data  # Already has two filenames, no Unknown to replace
    
    # Determine which filename to use for replacement
    if file_1_name in first_category:
        replacement_filename = file_2_name
    else:
        replacement_filename = file_1_name
    
    # Replace Unknown in all categories
    for category in mismatches.values():
        if 'Unknown' in category:
            category[replacement_filename] = category.pop('Unknown')
    
    return data

def add_freetext(page, highlight_rect, comment_text):
    ds = """font-size: 8pt; font-family: sans-serif; line-height: 1;"""
    formatted_text = f'<p style="margin: 0; padding-left: 2px; text-align: left;">{comment_text}</p>'
    
    offset_x = 10
    offset_y = 15
    
    page_width = page.rect.width
    page_height = page.rect.height
    page_margin = 20  # Minimum margin from edges

    text_length = len(comment_text)
    # Ensure minimum dimensions to prevent shrinking
    MIN_WIDTH = 120
    MIN_HEIGHT = 40
    
    box_width = max(MIN_WIDTH, min(250, text_length * 2))
    box_height = max(MIN_HEIGHT, (text_length // 25) * 12 + 30)

    # Check if highlight spans most of the page width
    highlight_width = highlight_rect.x1 - highlight_rect.x0
    
    if highlight_width > page_width * 0.8:  # Highlight is >80% of page width
        # Position below the highlight
        box_x0 = highlight_rect.x0 + offset_x
        box_y0 = highlight_rect.y1 + offset_y + 20
        
        # Make sure it fits on the page
        if box_x0 + box_width > page_width - page_margin:
            box_x0 = page_width - box_width - page_margin
            
        # If it goes off the bottom, position above
        if box_y0 + box_height > page_height - page_margin:
            box_y0 = highlight_rect.y0 - box_height - offset_y
    else:
        # Normal positioning
        box_x0 = highlight_rect.x1 + offset_x
        box_y0 = highlight_rect.y1 + offset_y
        
        # If box goes off right edge, position it to the left
        if box_x0 + box_width > page_width:
            box_x0 = highlight_rect.x0 - box_width - offset_x
            
            # If left positioning also fails, place below
            if box_x0 < 0:
                box_x0 = max(page_margin, highlight_rect.x0)
                box_y0 = highlight_rect.y1 + offset_y + 20

    # Ensure box stays within page bounds
    box_x0 = max(0, min(box_x0, page_width - box_width))
    box_y0 = max(0, min(box_y0, page_height - box_height))

    box_rect = fitz.Rect(box_x0, box_y0, box_x0 + box_width, box_y0 + box_height)

    # Check for overlapping annotations
    for annot in page.annots():
        if annot.type[0] == 2:
            if box_rect.intersects(annot.rect):
                box_y0 = annot.rect.y1 + 5
                # Recheck bounds after moving
                if box_y0 + box_height > page_height:
                    box_y0 = annot.rect.y0 - box_height - 5
                box_rect = fitz.Rect(box_x0, box_y0, box_x0 + box_width, box_y0 + box_height)
    
    # Adjust callout points based on final box position
    if box_y0 > highlight_rect.y1 + 10:  # Box is below highlight
        highlight_point = fitz.Point(
            min(highlight_rect.x1, box_x0 + box_width / 2),  # Point to middle of box if possible
            highlight_rect.y1
        )
        box_point = fitz.Point(box_x0 + 20, box_y0)
    elif box_y0 + box_height < highlight_rect.y0:  # Box is above highlight
        highlight_point = fitz.Point(
            min(highlight_rect.x1, box_x0 + box_width / 2),
            highlight_rect.y0
        )
        box_point = fitz.Point(box_x0 + 20, box_y0 + box_height)
    else:  # Box is to the side (normal case)
        highlight_point = highlight_rect.br
        box_point = fitz.Point(box_x0, box_y0 + 15)
    
    knee_point = fitz.Point((box_point.x + highlight_point.x) / 2, box_point.y)
    
    text_annot = page.add_freetext_annot(
        box_rect,
        formatted_text,
        fill_color=(1, 1, 0),
        text_color=(0, 0, 0),
        border_color=(0, 1, 0),
        opacity=0.75,
        rotate=0,
        border_width=1,
        richtext=True,
        callout=(box_point, knee_point, highlight_point),
        line_end=fitz.PDF_ANNOT_LE_NONE,
        style=ds,
    )
    
    # Set multiple flags for better compatibility
    text_annot.set_flags(16 | 32)  # NoZoom, NoRotate
    
    # Set additional info to help preserve formatting
    text_annot.set_info({
        "content": comment_text,
    })
    
    text_annot.update()
    
    return text_annot

def highlight_text(pdf_bytes, json_data, current_filename):
    document = fitz.open(stream=pdf_bytes)
    is_file1 = current_filename == filename1
    all_mismatches = {}
    
    if 'item0_metadata' in json_data and 'mismatches' in json_data['item0_metadata']:
        all_mismatches.update(json_data['item0_metadata']['mismatches'])
    
    if 'item1_metadata' in json_data and 'mismatches' in json_data['item1_metadata']:
        all_mismatches.update(json_data['item1_metadata']['mismatches'])

    for page_num in range(document.page_count):
        page = document[page_num]
        
        for mismatch_key, mismatch_data in all_mismatches.items():
            text_to_highlight = None
            bbox_data = None
            
            for filename, file_data in mismatch_data.items():
                if filename == current_filename:
                    text_to_highlight = file_data.get('text', '')
                    bbox_data = file_data.get('bbox', None)
                    break
            
            if not text_to_highlight or text_to_highlight.strip() == "":
                continue
            
            file_page_no = None
            for filename, file_data in mismatch_data.items():
                if filename == current_filename:
                    file_page_no = file_data.get('page_no', 1)
                    break
            
            if file_page_no and file_page_no - 1 != page_num:
                continue
            
            # If we have bbox data, use it directly
            if bbox_data and 'l' in bbox_data and 't' in bbox_data and 'r' in bbox_data and 'b' in bbox_data:
                # Convert bbox coordinates to fitz.Rect
                # Note: PDF coordinates typically have origin at bottom-left, but fitz uses top-left
                # Check coord_origin to determine if we need to flip Y coordinates
                if bbox_data.get('coord_origin') == 'BOTTOMLEFT':
                    # Need to flip Y coordinates
                    page_height = page.rect.height
                    min_x = bbox_data['l']
                    max_x = bbox_data['r']
                    min_y = page_height - bbox_data['t']  # flip top
                    max_y = page_height - bbox_data['b']  # flip bottom
                else:
                    # Already in top-left origin
                    min_x = bbox_data['l']
                    min_y = bbox_data['t']
                    max_x = bbox_data['r']
                    max_y = bbox_data['b']
                
                paddingX = 8
                paddingY = 2
                rect = fitz.Rect(min_x - paddingX, min_y - paddingY, max_x + paddingX, max_y + paddingY)
                highlight = page.add_highlight_annot(rect)
                highlight.set_colors(stroke=[1, 1, 0])
                
                if not is_file1:
                    file1_text = ""
                    
                    if mismatch_key in ['container_number', 'seal', 'tare_weight']:
                        if 'container.json' in mismatch_data:
                            file1_text = mismatch_data['container.json'].get('text', '')
                    else:
                        if filename1 in mismatch_data:
                            file1_text = mismatch_data[filename1].get('text', '')
                        else:
                            for key, value in mismatch_data.items():
                                if key != current_filename and isinstance(value, dict) and 'text' in value:
                                    file1_text = value.get('text', '')
                                    break
                    
                    if file1_text:
                        add_freetext(page, rect, file1_text)
            else:
                # Fallback to text search if no bbox available
                words = text_to_highlight.split()
                if not words:
                    continue
                
                first_word = words[0]
                text_instances = page.search_for(first_word)
                
                for start_rect in text_instances:
                    min_x = start_rect.x0
                    min_y = start_rect.y0
                    max_x = start_rect.x1
                    max_y = start_rect.y1
                    
                    found_all = True
                    for word in words[1:]:
                        word_instances = page.search_for(word)
                        
                        found_nearby = False
                        for rect in word_instances:
                            if abs(rect.y0 - max_y) < 20 or (rect.y0 > max_y and rect.y0 - max_y < 50):
                                min_x = min(min_x, rect.x0)
                                min_y = min(min_y, rect.y0)
                                max_x = max(max_x, rect.x1)
                                max_y = max(max_y, rect.y1)
                                found_nearby = True
                                break
                        
                        if not found_nearby:
                            found_all = False
                            break
          
                    if found_all:
                        paddingX = 8
                        paddingY = 2
                        rect = fitz.Rect(min_x - paddingX, min_y - paddingY, max_x + paddingX, max_y + paddingY)
                        highlight = page.add_highlight_annot(rect)
                        highlight.set_colors(stroke=[1, 1, 0])

                        if not is_file1:
                            file1_text = ""
                            
                            if mismatch_key in ['container_number', 'seal', 'tare_weight']:
                                if 'container.json' in mismatch_data:
                                    file1_text = mismatch_data['container.json'].get('text', '')
                            else:
                                if filename1 in mismatch_data:
                                    file1_text = mismatch_data[filename1].get('text', '')
                                else:
                                    for key, value in mismatch_data.items():
                                        if key != current_filename and isinstance(value, dict) and 'text' in value:
                                            file1_text = value.get('text', '')
                                            break
                            
                            if file1_text:
                                add_freetext(page, rect, file1_text)
                        break   
                
    output_bytes = document.tobytes()
    document.close()
    return output_bytes

@app.post("/highlight")
async def process_pdfs(
    file1: UploadFile = File(...), 
    file2: UploadFile = File(...), 
    json_data: str = Form(...) 
):
    global filename1, filename2

    pdf_bytes1 = await file1.read()
    pdf_bytes2 = await file2.read()

    json_data = json.loads(json_data)

    file_1_name = json_data.get('item2_metadata', {}).get('filename', 'Unknown')
    file_2_name = json_data.get('item3_metadata', {}).get('filename', 'Unknown')

    filename1 = file_1_name
    filename2 = file_2_name
  
    output_bytes1 = highlight_text(pdf_bytes1, json_data, file_1_name)
    output_bytes2 = highlight_text(pdf_bytes2, json_data, file_2_name)

    output_name1 = f"{os.path.splitext(file_1_name)[0]}_output.pdf"
    output_name2 = f"{os.path.splitext(file_2_name)[0]}_output.pdf"
    
    with open(f"/app/output/{output_name1}", 'wb') as f:
        f.write(output_bytes1)
    
    with open(f"/app/output/{output_name2}", 'wb') as f:
        f.write(output_bytes2)
    
    return {
        "status": "success"
    }

@app.post("/debug")
async def debug_request(request: Request):
    form = await request.form()
    files = []
    for key, value in form.items():
        if hasattr(value, 'filename'):
            files.append({
                "field_name": key,
                "filename": value.filename,
                "content_type": value.content_type
            })
    return {"files_received": files, "all_fields": list(form.keys())}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)