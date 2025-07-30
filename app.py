from flask import Flask, request, jsonify
import base64
import requests
import re
import fitz  # PyMuPDF

app = Flask(__name__)

def extract_part_number_from_text(text):
    try:
        match = re.search(r'料品號\s*[:：]?\s*\n?\s*(\S+)', text)
        return match.group(1) if match else None
    except Exception as e:
        return f"[Regex error: {str(e)}]"

def ocr_space_api_base64(file_stream, engine=2):
    try:
        file_stream.seek(0)
        base64_data = base64.b64encode(file_stream.read()).decode()
        response = requests.post(
            'https://api.ocr.space/parse/image',
            data={
                'apikey': 'K85762331988957',
                'language': 'cht',
                'isOverlayRequired': False,
                'OCREngine': engine,
                'base64Image': f'data:application/pdf;base64,{base64_data}'
            },
            timeout=30
        )
        response.raise_for_status()
        result = response.json()
        return result.get('ParsedResults', [{}])[0].get('ParsedText', '')
    except Exception as e:
        return f"[OCR API error: {str(e)}]"

def clean_text(text):
    try:
        text = re.sub(r'(衛生福利部\s*藥品不良反應通報表\s*)+', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    except Exception as e:
        return f"[Text cleaning error: {str(e)}]"

def extract_text_from_pdf(file_stream):
    try:
        file_stream.seek(0)
        doc = fitz.open(stream=file_stream.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        cleaned_text = clean_text(text)
        return cleaned_text
    except Exception as e:
        return f"[PDF parsing error: {str(e)}]"

@app.route('/extract-text', methods=['POST'])
def extract_text():
    try:
        files = request.files.getlist('file') or request.files.getlist('files') or request.files.getlist('files[]')
        if not files:
            return jsonify({'error': 'No files uploaded'}), 400

        results = []

        for file in files:
            if not file or file.filename == '':
                continue

            filename = file.filename
            result = {
                'filename': filename,
                'type': None,
                'part_number': None,
                'raw_text': None,
                'field_status': None,
                'error': None
            }

            try:
                if filename.startswith("C"):
                    result['type'] = "C-type"
                    raw_text = ocr_space_api_base64(file.stream)
                    result['raw_text'] = raw_text
                    extracted = extract_part_number_from_text(raw_text)
                    if extracted:
                        result['part_number'] = extracted
                        result['field_status'] = "part_number extracted"
                    else:
                        result['field_status'] = "part_number not found"

                elif filename.startswith("TW-TFDA"):
                    result['type'] = "TW-TFDA"
                    raw_text = extract_text_from_pdf(file.stream)
                    result['raw_text'] = raw_text
                    case_id_match = re.search(r'TW-TFDA-[A-Z0-9\-]+', raw_text)
                    if case_id_match:
                        result['part_number'] = case_id_match.group(0)
                        result['field_status'] = "case_id extracted"
                    else:
                        result['field_status'] = "case_id not found"

                else:
                    result['type'] = "Unsupported"
                    result['raw_text'] = "[Unsupported filename format]"
                    result['part_number'] = None
                    result['field_status'] = "unsupported filename format"

            except Exception as e:
                result['error'] = str(e)
                result['field_status'] = "error during processing"

            results.append(result)

        return jsonify({'results': results})

    except Exception as e:
        return jsonify({'error': 'Internal Server Error', 'details': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(str(os.environ.get("PORT", "10000")).strip())
    app.run(host="0.0.0.0", port=port)
